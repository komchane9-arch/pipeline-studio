"""ADB MCP server — ให้ Claude บน cloud เห็นและกดมือถือที่ต่ออยู่กับคอมเครื่องนี้

    python adb-mcp/adb_mcp_server.py          # เปิดที่ 127.0.0.1:8765
    แล้วเปิด tunnel ตาม README (start_adb_mcp.bat ทำให้ทั้งสองอย่าง)

**ความปลอดภัย — อ่านก่อนใช้**
- server ตัวนี้แตะ กด พิมพ์ และลงแอปบนมือถือได้ทั้งเครื่อง
  ใครรู้ URL เต็ม (ที่มีรหัสลับอยู่ในนั้น) ก็สั่งมือถือได้ อย่าส่ง URL ให้ใคร
- ฟังแค่ 127.0.0.1 ทางเข้าจากข้างนอกทางเดียวคือ tunnel — ปิด tunnel เมื่อไม่ใช้
- รหัสลับอยู่ในพาธ (`/<รหัส>/mcp`) เพราะ custom connector ของ claude.ai ต่อแบบไม่มี
  header พิเศษได้ พาธที่ไม่ตรงได้ 404 เหมือนไม่มีอะไรอยู่ตรงนั้น
- ตั้ง `ADB_MCP_DEVICES` ให้ใช้ได้เฉพาะมือถือทดสอบ แยกจากมือถือที่ Studio ใช้โพสต์จริง
- คำสั่ง shell ตรงๆ ปิดไว้ เปิดด้วย `ADB_MCP_ALLOW_SHELL=1` เมื่อจำเป็นเท่านั้น
- ทุกคำสั่งถูกบันทึกลง `adb-mcp/data/audit.log`
"""

from __future__ import annotations

import base64
import hmac
import io
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree

from mcp.server.fastmcp import FastMCP, Image
from mcp.server.transport_security import TransportSecuritySettings

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("ADB_MCP_DATA") or HERE / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
SECRET_FILE = DATA_DIR / "secret.txt"
AUDIT_FILE = DATA_DIR / "audit.log"

PORT = int(os.environ.get("ADB_MCP_PORT", "8765"))
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
KEY_NAMES = {
    "BACK": 4, "HOME": 3, "ENTER": 66, "DEL": 67, "TAB": 61, "MENU": 82,
    "APP_SWITCH": 187, "POWER": 26, "WAKEUP": 224, "VOLUME_UP": 24, "VOLUME_DOWN": 25,
}
SERIAL_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")
PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")
ACTIVITY_RE = re.compile(r"^[A-Za-z0-9_.$]+$")
UPLOAD_NAME_RE = re.compile(r"^[A-Za-z0-9._\-]{1,80}$")
ADB_KEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"


class AdbError(RuntimeError):
    """ข้อความในนี้ Claude อ่านตรงๆ จึงบอกเหตุผลและทางแก้ให้ชัด"""


def find_adb() -> str:
    for candidate in (os.environ.get("ADB_PATH", ""), HERE / "tools" / "adb.exe",
                      HERE.parent / "tools" / "adb.exe"):
        if candidate and Path(candidate).exists():
            return str(candidate)
    return shutil.which("adb") or "adb"


class Adb:
    """ห่อ adb ไว้ที่เดียว — ตรวจเครื่องที่อนุญาต + บันทึกทุกคำสั่ง"""

    def __init__(self, adb: str | None = None, allowed: set[str] | None = None,
                 allow_shell: bool = False,
                 runner: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
        self.adb = adb or find_adb()
        self.allowed = allowed or set()
        self.allow_shell = allow_shell
        self.runner = runner or subprocess.run
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- ล่าง

    def audit(self, line: str) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with AUDIT_FILE.open("a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
        except OSError:
            pass

    def run(self, args: list[str], timeout: float = 30, binary: bool = False):
        self.audit("adb " + " ".join(shlex.quote(a) for a in args)[:300])
        try:
            done = self.runner(
                [self.adb, *args], capture_output=True, timeout=timeout,
                text=not binary,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError as error:
            raise AdbError(f"ไม่พบ adb ({self.adb}) — ติดตั้ง platform-tools หรือตั้ง ADB_PATH") from error
        except subprocess.TimeoutExpired as error:
            raise AdbError(f"adb ไม่ตอบภายใน {timeout:.0f} วินาที") from error
        if done.returncode != 0:
            err = done.stderr if isinstance(done.stderr, str) else (done.stderr or b"").decode("utf-8", "replace")
            raise AdbError(f"adb ล้ม (code {done.returncode}): {err.strip()[:400]}")
        return done.stdout

    def check_serial(self, serial: str) -> str:
        serial = str(serial or "").strip()
        if not SERIAL_RE.match(serial):
            raise AdbError("serial ไม่ถูกต้อง — เรียก devices ก่อนเพื่อดู serial")
        if self.allowed and serial not in self.allowed:
            raise AdbError(f"เครื่อง {serial} ไม่อยู่ในรายการที่อนุญาต (ADB_MCP_DEVICES)")
        return serial

    def dev(self, serial: str, *args: str, timeout: float = 30, binary: bool = False):
        return self.run(["-s", self.check_serial(serial), *args], timeout=timeout, binary=binary)

    def shell(self, serial: str, *args: str, timeout: float = 30) -> str:
        return self.dev(serial, "shell", *args, timeout=timeout)

    # ---------------------------------------------------------------- สูง

    def devices(self) -> list[dict]:
        out = self.run(["devices", "-l"], timeout=15)
        found = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 2:
                continue
            info = {"serial": parts[0], "state": parts[1]}
            for part in parts[2:]:
                if ":" in part:
                    key, value = part.split(":", 1)
                    info[key] = value
            info["allowed"] = not self.allowed or parts[0] in self.allowed
            found.append(info)
        return found

    def screenshot_png(self, serial: str) -> bytes:
        data = self.dev(serial, "exec-out", "screencap", "-p", timeout=30, binary=True)
        if not data or not data.startswith(b"\x89PNG"):
            raise AdbError("แคปหน้าจอไม่ได้ — จออาจดับอยู่ ลอง key WAKEUP ก่อน")
        return data

    def ui_xml(self, serial: str) -> str:
        # dump ลงไฟล์ในเครื่องแล้วค่อยอ่าน — `uiautomator dump /dev/tty` ใช้ไม่ได้ในบางรุ่น
        self.shell(serial, "uiautomator", "dump", "/sdcard/adb_mcp_ui.xml", timeout=40)
        return self.shell(serial, "cat", "/sdcard/adb_mcp_ui.xml", timeout=20)


def parse_bounds(text: str) -> tuple[int, int, int, int] | None:
    found = re.findall(r"\d+", text or "")
    if len(found) != 4:
        return None
    return tuple(int(v) for v in found)  # type: ignore[return-value]


def summarize_ui(xml: str, limit: int = 250) -> str:
    """ผังจอแบบย่อให้ Claude อ่านง่าย — เฉพาะ node ที่มีข้อความหรือกดได้ พร้อมพิกัดกึ่งกลาง"""
    start = xml.find("<?xml")
    start = start if start >= 0 else xml.find("<hierarchy")
    try:
        root = ElementTree.fromstring(xml[start:] if start >= 0 else xml)
    except ElementTree.ParseError as error:
        raise AdbError(f"อ่านผังจอไม่ออก: {error}") from error
    lines = []
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        rid = (node.get("resource-id") or "").split("/")[-1]
        clickable = node.get("clickable") == "true" or node.get("long-clickable") == "true"
        editable = "EditText" in (node.get("class") or "")
        if not (text or desc or clickable or editable):
            continue
        box = parse_bounds(node.get("bounds", ""))
        if not box or box[2] <= box[0] or box[3] <= box[1]:
            continue
        cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        flags = "".join([
            "C" if clickable else "", "E" if editable else "",
            "S" if node.get("selected") == "true" or node.get("checked") == "true" else "",
            "-" if node.get("enabled") == "false" else "",
        ])
        label = " | ".join(p for p in (text, desc and f"desc={desc}", rid and f"id={rid}") if p)
        cls = (node.get("class") or "").split(".")[-1]
        lines.append(f"({cx},{cy}) [{flags or '.'}] {cls}: {label}"[:200])
        if len(lines) >= limit:
            lines.append(f"... ตัดที่ {limit} รายการ")
            break
    package = next((n.get("package") for n in root.iter("node") if n.get("package")), "")
    head = f"แอปบนจอ: {package}\nรูปแบบ: (x,y กึ่งกลาง) [C=กดได้ E=ช่องพิมพ์ S=เลือกอยู่ -=ปิดใช้] ชนิด: ข้อความ"
    return head + "\n" + ("\n".join(lines) if lines else "(ไม่พบ element ที่มีข้อความหรือกดได้)")


def shrink_png(data: bytes, max_side: int) -> tuple[bytes, str]:
    """ย่อรูปให้ส่งเร็วและกิน context น้อยลง — ไม่มี Pillow ก็ส่งรูปเต็ม"""
    try:
        from PIL import Image as PILImage
    except ImportError:
        return data, "png"
    image = PILImage.open(io.BytesIO(data))
    scale = max_side / max(image.size)
    if scale < 1:
        image = image.resize((round(image.width * scale), round(image.height * scale)))
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=80)
    return out.getvalue(), "jpeg"


def load_secret() -> str:
    env = os.environ.get("ADB_MCP_SECRET", "").strip()
    if env:
        return env
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SECRET_FILE.exists():
        value = SECRET_FILE.read_text(encoding="utf-8").strip()
        if len(value) >= 24:
            return value
    value = secrets.token_urlsafe(32)
    SECRET_FILE.write_text(value + "\n", encoding="utf-8")
    try:
        os.chmod(SECRET_FILE, 0o600)
    except OSError:
        pass
    return value


def build_server(adb: Adb) -> FastMCP:
    mcp = FastMCP(
        "adb-phone",
        instructions=(
            "คุมมือถือ Android ที่ต่อกับคอมของเจ้าของผ่าน adb. "
            "เริ่มจาก devices เพื่อดู serial. ก่อนแตะให้ดู ui_tree (ได้พิกัดกึ่งกลางของปุ่ม) "
            "หรือ screenshot. พิกัดเป็นพิกเซลจริงของจอ ไม่ใช่ของรูปที่ย่อแล้ว — "
            "screenshot จะบอกขนาดจอจริงไว้ให้แปลง. ห้ามแตะแอป Facebook/Shopee/ธนาคาร "
            "ของเจ้าของ เว้นแต่เจ้าของสั่งเอง"
        ),
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    def devices() -> list[dict]:
        """รายการมือถือที่ต่ออยู่ (serial, สถานะ, รุ่น, อนุญาตให้ใช้ไหม)"""
        return adb.devices()

    @mcp.tool()
    def screenshot(serial: str, max_side: int = 1280) -> list:
        """แคปหน้าจอ ย่อด้านยาวสุดเหลือ max_side พิกเซล (ตั้ง 0 = รูปเต็ม)"""
        raw = adb.screenshot_png(serial)
        width = int.from_bytes(raw[16:20], "big")
        height = int.from_bytes(raw[20:24], "big")
        data, fmt = (raw, "png") if max_side <= 0 else shrink_png(raw, max_side)
        return [f"ขนาดจอจริง {width}x{height} — tap ใช้พิกัดของขนาดนี้",
                Image(data=data, format=fmt)]

    @mcp.tool()
    def ui_tree(serial: str, raw_xml: bool = False) -> str:
        """ผังปุ่มและข้อความบนจอพร้อมพิกัดกึ่งกลาง (raw_xml=True ได้ XML ดิบ)"""
        xml = adb.ui_xml(serial)
        return xml if raw_xml else summarize_ui(xml)

    @mcp.tool()
    def tap(serial: str, x: int, y: int) -> str:
        """แตะจอที่พิกัด x,y (พิกเซลจริงของจอ)"""
        adb.shell(serial, "input", "tap", str(int(x)), str(int(y)))
        return f"แตะ ({x},{y}) แล้ว"

    @mcp.tool()
    def long_press(serial: str, x: int, y: int, ms: int = 800) -> str:
        """กดค้างที่ x,y"""
        adb.shell(serial, "input", "swipe", *map(str, (int(x), int(y), int(x), int(y), int(ms))))
        return f"กดค้าง ({x},{y}) {ms} ms แล้ว"

    @mcp.tool()
    def swipe(serial: str, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> str:
        """ปัดจาก (x1,y1) ไป (x2,y2) — เลื่อนลงให้ปัดจาก y มากไป y น้อย"""
        adb.shell(serial, "input", "swipe", *map(str, (int(x1), int(y1), int(x2), int(y2), int(ms))))
        return "ปัดแล้ว"

    @mcp.tool()
    def key(serial: str, name: str) -> str:
        """กดปุ่ม: BACK HOME ENTER DEL TAB MENU APP_SWITCH POWER WAKEUP VOLUME_UP VOLUME_DOWN หรือเลข keycode"""
        code = KEY_NAMES.get(name.upper()) if not name.isdigit() else int(name)
        if code is None:
            raise AdbError(f"ไม่รู้จักปุ่ม {name} (มี: {', '.join(KEY_NAMES)})")
        adb.shell(serial, "input", "keyevent", str(code))
        return f"กด {name} แล้ว"

    @mcp.tool()
    def type_text(serial: str, text: str) -> str:
        """พิมพ์ข้อความลงช่องที่โฟกัสอยู่ (แตะช่องก่อน) ภาษาไทยต้องมี ADBKeyboard ในเครื่อง"""
        if not text:
            return "ไม่มีข้อความ"
        if text.isascii():
            escaped = re.sub(r"([\\\"'`$&|;<>()*?!#~ ])", r"\\\1", text).replace("%", "\\%")
            adb.shell(serial, "input", "text", escaped.replace("\\ ", "%s"))
            return f"พิมพ์ {len(text)} ตัวอักษรแล้ว"
        ime = adb.shell(serial, "settings", "get", "secure", "default_input_method").strip()
        if ime != ADB_KEYBOARD_IME:
            raise AdbError(
                "ข้อความมีภาษาไทย/อีโมจิ ต้องสลับคีย์บอร์ดเป็น ADBKeyboard ก่อน "
                f"(ตอนนี้ใช้ {ime or 'ไม่ทราบ'}) — เรียก set_adb_keyboard(serial, true)")
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        adb.shell(serial, "am", "broadcast", "-a", "ADB_INPUT_B64", "--es", "msg", payload)
        return f"พิมพ์ {len(text)} ตัวอักษรผ่าน ADBKeyboard แล้ว"

    @mcp.tool()
    def set_adb_keyboard(serial: str, enable: bool) -> str:
        """สลับเป็น ADBKeyboard (enable=true) หรือกลับไปคีย์บอร์ดเดิม (false) — เสร็จงานแล้วต้องคืนเสมอ"""
        state = DATA_DIR / f"ime-{adb.check_serial(serial)}.txt"
        if enable:
            current = adb.shell(serial, "settings", "get", "secure", "default_input_method").strip()
            if current and current != ADB_KEYBOARD_IME:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                state.write_text(current, encoding="utf-8")
            adb.shell(serial, "ime", "enable", ADB_KEYBOARD_IME)
            adb.shell(serial, "ime", "set", ADB_KEYBOARD_IME)
            return "สลับเป็น ADBKeyboard แล้ว"
        previous = state.read_text(encoding="utf-8").strip() if state.exists() else ""
        if not previous:
            return "ไม่มีคีย์บอร์ดเดิมที่จำไว้ — ไม่ได้เปลี่ยนอะไร"
        adb.shell(serial, "ime", "set", previous)
        state.unlink(missing_ok=True)
        return f"คืนคีย์บอร์ดเป็น {previous} แล้ว"

    @mcp.tool()
    def upload_chunk(name: str, data_b64: str, append: bool = False) -> str:
        """อัปโหลดไฟล์ (เช่น .apk) มาไว้บนคอมทีละก้อน — ก้อนแรก append=false ก้อนถัดไป true"""
        if not UPLOAD_NAME_RE.match(name):
            raise AdbError("ชื่อไฟล์ใช้ได้เฉพาะ A-Z a-z 0-9 . _ -")
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        path = UPLOAD_DIR / name
        data = base64.b64decode(data_b64, validate=True)
        size = (path.stat().st_size if append and path.exists() else 0) + len(data)
        if size > MAX_UPLOAD_BYTES:
            raise AdbError("ไฟล์ใหญ่เกิน 200 MB")
        with path.open("ab" if append else "wb") as handle:
            handle.write(data)
        adb.audit(f"upload {name} +{len(data)} = {size}")
        return f"{name}: {size} ไบต์"

    @mcp.tool()
    def install_apk(serial: str, uploaded_name: str = "", url: str = "") -> str:
        """ลง/อัปเดตแอป จากไฟล์ที่ upload_chunk ไว้ หรือจาก URL (https เท่านั้น)"""
        if bool(uploaded_name) == bool(url):
            raise AdbError("ระบุอย่างใดอย่างหนึ่ง: uploaded_name หรือ url")
        if url:
            if not url.startswith("https://"):
                raise AdbError("รับเฉพาะ URL https")
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            path = UPLOAD_DIR / f"download-{secrets.token_hex(4)}.apk"
            adb.audit(f"download {url[:200]}")
            with urllib.request.urlopen(url, timeout=120) as response, path.open("wb") as handle:
                shutil.copyfileobj(response, handle, length=1024 * 1024)
        else:
            if not UPLOAD_NAME_RE.match(uploaded_name):
                raise AdbError("ชื่อไฟล์ไม่ถูกต้อง")
            path = UPLOAD_DIR / uploaded_name
            if not path.exists():
                raise AdbError(f"ยังไม่มีไฟล์ {uploaded_name} — อัปโหลดด้วย upload_chunk ก่อน")
        with path.open("rb") as handle:
            if handle.read(2) != b"PK":
                raise AdbError("ไฟล์นี้ไม่ใช่ .apk")
        out = adb.dev(serial, "install", "-r", "-d", str(path), timeout=300)
        return out.strip()[-500:] or "ลงแอปแล้ว"

    @mcp.tool()
    def launch_app(serial: str, package: str, activity: str = "") -> str:
        """เปิดแอป — ไม่ใส่ activity จะเปิดหน้าแรกของแอป"""
        if not PACKAGE_RE.match(package) or (activity and not ACTIVITY_RE.match(activity)):
            raise AdbError("ชื่อแพ็กเกจหรือ activity ไม่ถูกต้อง")
        if activity:
            component = f"{package}/{activity}"
            out = adb.shell(serial, "am", "start", "-W", "-n", component, timeout=40)
        else:
            out = adb.shell(serial, "monkey", "-p", package,
                            "-c", "android.intent.category.LAUNCHER", "1", timeout=40)
        return out.strip()[-500:]

    @mcp.tool()
    def stop_app(serial: str, package: str) -> str:
        """ปิดแอป (force-stop)"""
        if not PACKAGE_RE.match(package):
            raise AdbError("ชื่อแพ็กเกจไม่ถูกต้อง")
        adb.shell(serial, "am", "force-stop", package)
        return f"ปิด {package} แล้ว"

    @mcp.tool()
    def list_packages(serial: str, contains: str = "", third_party_only: bool = True) -> list[str]:
        """รายชื่อแอปในเครื่อง (ค่าเริ่มต้น: เฉพาะแอปที่ลงเอง)"""
        args = ["pm", "list", "packages"] + (["-3"] if third_party_only else [])
        out = adb.shell(serial, *args)
        names = sorted(line.split(":", 1)[1].strip() for line in out.splitlines() if ":" in line)
        return [n for n in names if contains.lower() in n.lower()]

    @mcp.tool()
    def logcat(serial: str, lines: int = 200, contains: str = "", errors_only: bool = False,
               clear: bool = False) -> str:
        """log ของเครื่อง — ใช้หาสาเหตุแอปเด้ง (errors_only=true ดูเฉพาะ error)"""
        if clear:
            adb.dev(serial, "logcat", "-c")
            return "ล้าง log แล้ว"
        args = ["logcat", "-d", "-t", str(max(1, min(int(lines) * (5 if contains else 1), 5000)))]
        if errors_only:
            args.append("*:E")
        out = adb.dev(serial, *args, timeout=40)
        rows = out.splitlines()
        if contains:
            rows = [r for r in rows if contains.lower() in r.lower()]
        return "\n".join(rows[-int(lines):]) or "(ไม่มี log ที่ตรง)"

    @mcp.tool()
    def shell(serial: str, command: str) -> str:
        """รันคำสั่ง shell บนมือถือ — ปิดไว้เป็นค่าเริ่มต้น (เปิดด้วย ADB_MCP_ALLOW_SHELL=1)"""
        if not adb.allow_shell:
            raise AdbError("คำสั่ง shell ปิดอยู่ — เจ้าของต้องเปิดด้วย ADB_MCP_ALLOW_SHELL=1")
        return adb.shell(serial, command, timeout=60)[-8000:]

    return mcp


class SecretPathGuard:
    """ASGI ชั้นนอกสุด — พาธที่ไม่ขึ้นต้นด้วยรหัสลับได้ 404 ทันที (เทียบแบบกันจับเวลา)"""

    def __init__(self, app, secret: str) -> None:
        self.app = app
        self.prefix = f"/{secret}"

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        head = path[: len(self.prefix)]
        rest = path[len(self.prefix):]
        if not (hmac.compare_digest(head, self.prefix) and rest.startswith("/")):
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"not found"})
            return
        scope = dict(scope, path=rest, raw_path=rest.encode())
        return await self.app(scope, receive, send)


def create_app(adb: Adb | None = None, secret: str | None = None):
    adb = adb or Adb(
        allowed={s.strip() for s in os.environ.get("ADB_MCP_DEVICES", "").split(",") if s.strip()},
        allow_shell=os.environ.get("ADB_MCP_ALLOW_SHELL") == "1",
    )
    server = build_server(adb)
    return SecretPathGuard(server.streamable_http_app(), secret or load_secret()), server


def main() -> None:
    import uvicorn

    secret = load_secret()
    app, _ = create_app(secret=secret)
    allowed = os.environ.get("ADB_MCP_DEVICES", "") or "ทุกเครื่อง (ตั้ง ADB_MCP_DEVICES เพื่อจำกัด)"
    print("ADB MCP server")
    print(f"  ในเครื่อง : http://127.0.0.1:{PORT}/{secret}/mcp")
    print(f"  URL ใส่ connector: https://<โดเมนจาก tunnel>/{secret}/mcp")
    print(f"  มือถือที่อนุญาต: {allowed}")
    print("  ห้ามส่ง URL ที่มีรหัสนี้ให้ใคร — เปลี่ยนรหัสได้โดยลบ adb-mcp/data/secret.txt")
    sys.stdout.flush()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
