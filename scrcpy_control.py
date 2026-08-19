"""สั่งแตะ/ลากมือถือแบบเรียลไทม์ผ่าน scrcpy-server

ต่างจากการเรียก `adb shell input` ตรงที่ไม่ต้องเปิดโปรเซสใหม่ทุก event
(`/system/bin/input` เป็นสคริปต์ที่เรียก `cmd input` ซึ่งวัดได้ ~33 ms/ครั้ง
= เพดานราว 30 event/วินาที ทำให้ลากแล้วกระตุก)

วิธีนี้ push `scrcpy-server` ไปรันค้างไว้บนมือถือ แล้วส่งข้อความไบนารีสั้นๆ
ผ่าน socket เดียว ฝั่งมือถือฉีด MotionEvent เข้า InputManager โดยตรง
จึงส่งได้เร็วกว่าหลายพันเท่า และกำหนด pointer id / pressure ได้ครบ

ข้อแลกเปลี่ยน: พึ่ง hidden API ของ Android ผ่าน scrcpy-server
ถ้า Android รุ่นใหม่ทำพัง ต้องอัปเดตไฟล์ jar — ผู้เรียกจึงควรมีทางถอย
กลับไปใช้ `input` เสมอ (ดู `web_app.py`)

scrcpy-server เป็นของโครงการ scrcpy (Apache License 2.0)
<https://github.com/Genymobile/scrcpy>
"""

from __future__ import annotations

import logging
import secrets
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

# ซ่อนหน้าต่างคอนโซลตอนสั่งโปรแกรมภายนอก — ไม่ให้กะพริบใส่ผู้ใช้
# ประกาศในไฟล์เองแทนการ import studio_shared เพื่อไม่เพิ่มสายพึ่งพาโดยไม่จำเป็น
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


logger = logging.getLogger(__name__)

# ต้องตรงกับไฟล์ jar ที่วางไว้ ไม่งั้นเซิร์ฟเวอร์ฝั่งมือถือจะปฏิเสธตั้งแต่เริ่ม
SCRCPY_SERVER_VERSION = "4.1"
SCRCPY_JAR = Path(__file__).resolve().parent / "tools" / "scrcpy-server-4.1.jar"
# ตั้งชื่อไม่ให้ชนกับ scrcpy ตัวจริงที่ผู้ใช้อาจเปิดเองอยู่
JAR_ON_DEVICE = "/data/local/tmp/scrcpy-server-webapp.jar"
DEVICE_NAME_FIELD_LENGTH = 64
CONNECT_TIMEOUT_SECONDS = 8.0
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ชนิดข้อความและ action ตามสเปกของ scrcpy 4.x
CONTROL_MSG_INJECT_KEYCODE = 0
CONTROL_MSG_INJECT_TEXT = 1
CONTROL_MSG_INJECT_TOUCH_EVENT = 2
# ชนิดข้อความของ scrcpy 4.x — ตั้งคลิปบอร์ดบนมือถือ (ใช้ส่งลิงก์จากคอมไปมือถือ)
CONTROL_MSG_SET_CLIPBOARD = 9
# อ่านคลิปบอร์ดของมือถือกลับมา (ใช้เก็บลิงก์โพสต์หลังกด "คัดลอกลิงก์")
CONTROL_MSG_GET_CLIPBOARD = 8
COPY_KEY_NONE = 0          # อ่านอย่างเดียว ไม่ยิงปุ่ม copy ซ้ำ
# ข้อความที่มือถือส่งกลับมาทาง socket เดียวกัน
DEVICE_MSG_CLIPBOARD = 0
DEVICE_MSG_ACK_CLIPBOARD = 1
DEVICE_MSG_UHID_OUTPUT = 2
MAX_CLIPBOARD_BYTES = 262_144
TOUCH_ACTIONS = {"DOWN": 0, "UP": 1, "MOVE": 2, "CANCEL": 3}
# นิ้วจำลอง (ไม่ใช่เมาส์) เพื่อให้แอปมองเห็นเป็นการแตะจอจริง
POINTER_ID_GENERIC_FINGER = -2
PRESSURE_MAX = 0xFFFF
MAX_TEXT_BYTES = 300           # เพดานของ INJECT_TEXT ฝั่ง scrcpy

# ---- ปุ่มกด: ทางที่แม่นกว่าการลากนิ้วเสมอ ----
# ลากตัวชี้ข้อความให้ตรงตำแหน่งต้องอาศัยภาพที่ทันนิ้ว ซึ่งไม่มีวันเท่าจอจริง
# ส่วนการกดปุ่มเลื่อนทีละตัวอักษร **แม่น 100% ไม่ว่าภาพจะช้าแค่ไหน**
KEY_ACTION_DOWN = 0
KEY_ACTION_UP = 1
META_NONE = 0
META_SHIFT = 0x1
META_CTRL = 0x1000
KEYCODES = {
    "ซ้าย": 21, "ขวา": 22, "ขึ้น": 19, "ลง": 20,
    "ต้นบรรทัด": 122, "ท้ายบรรทัด": 123,
    "ลบ": 67, "ลบหน้า": 112, "enter": 66, "a": 29,
    "back": 4, "home": 3, "แท็บ": 61,
}


class ScrcpyUnavailable(RuntimeError):
    """เปิดช่องทาง scrcpy ไม่ได้ ผู้เรียกควรถอยไปใช้ `adb shell input`"""


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class _Session:
    """หนึ่งเซสชันต่อมือถือหนึ่งเครื่อง: โปรเซสบนมือถือ + socket ควบคุม"""

    def __init__(self, adb_executable: str, serial: str) -> None:
        self.adb_executable = adb_executable
        self.serial = serial
        # ฝั่ง Java อ่าน scid ด้วย Integer.parseInt(..., 16) ซึ่งเป็น signed 32 บิต
        # จึงต้องไม่เกิน 0x7FFFFFFF ไม่งั้นเซิร์ฟเวอร์ตายทันทีด้วย NumberFormatException
        self.scid = f"{secrets.randbelow(0x80000000):08x}"
        self.port = _free_local_port()
        self.process: subprocess.Popen[bytes] | None = None
        self.sock: socket.socket | None = None
        self.device_name = ""
        self.lock = threading.Lock()

    # ---------- ขั้นตอนเปิดเซสชัน ----------

    def _adb(self, *arguments: str, timeout: float = 15.0):
        return subprocess.run(
            [self.adb_executable, "-s", self.serial, *arguments],
            capture_output=True,
            timeout=timeout,
            creationflags=NO_WINDOW,
        )

    def _push_server(self) -> None:
        result = self._adb("push", str(SCRCPY_JAR), JAR_ON_DEVICE, timeout=60.0)
        if result.returncode != 0:
            raise ScrcpyUnavailable(
                "ส่งไฟล์ scrcpy-server ไปมือถือไม่สำเร็จ: "
                + result.stderr.decode("utf-8", errors="replace").strip()
            )

    def _start_server(self) -> None:
        # tunnel_forward=true = ให้มือถือเป็นฝั่งรอรับ แล้วเราต่อออกไป
        # เลือกแบบนี้เพื่อไม่ต้องไปยุ่งกับ `adb reverse` ที่ผู้ใช้ตั้งไว้ใช้งานอื่น
        self.process = subprocess.Popen(
            [
                self.adb_executable, "-s", self.serial, "shell",
                f"CLASSPATH={JAR_ON_DEVICE}",
                "app_process", "/", "com.genymobile.scrcpy.Server",
                SCRCPY_SERVER_VERSION,
                f"scid={self.scid}",
                "log_level=error",
                "video=false",
                "audio=false",
                "control=true",
                "tunnel_forward=true",
                "cleanup=false",
                # ห้ามปลุกจอเอง มือถือควรอยู่สภาพเดิมที่ผู้ใช้วางไว้
                "power_on=false",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW,
        )

    def _forward(self) -> None:
        result = self._adb(
            "forward", f"tcp:{self.port}", f"localabstract:scrcpy_{self.scid}"
        )
        if result.returncode != 0:
            raise ScrcpyUnavailable(
                "ตั้ง adb forward ไม่สำเร็จ: "
                + result.stderr.decode("utf-8", errors="replace").strip()
            )

    def _connect(self) -> None:
        """ต่อ socket แล้วอ่าน handshake: dummy byte 1 ไบต์ + ชื่อเครื่อง 64 ไบต์

        ใน tunnel_forward การต่อจะสำเร็จทันทีแม้เซิร์ฟเวอร์ยังไม่พร้อม
        dummy byte จึงเป็นตัวยืนยันว่าอีกฝั่งมีจริง (ตามที่ scrcpy ออกแบบไว้)
        """
        deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                sock = socket.create_connection(("127.0.0.1", self.port), timeout=2.0)
                sock.settimeout(2.0)
                if sock.recv(1) == b"\x00":
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    self.sock = sock
                    self.device_name = self._read_exactly(
                        sock, DEVICE_NAME_FIELD_LENGTH
                    ).rstrip(b"\x00").decode("utf-8", errors="replace")
                    return
                sock.close()
            except OSError as error:
                last_error = error
            # โปรเซสตายแล้วก็ไม่ต้องรอจนครบเวลา อ่านสาเหตุจากมันตรงๆ ดีกว่า
            if self.process is not None and self.process.poll() is not None:
                raise ScrcpyUnavailable(
                    "scrcpy-server บนมือถือหยุดทำงาน: " + self._server_output()
                )
            time.sleep(0.15)
        raise ScrcpyUnavailable(
            f"ต่อ scrcpy-server ไม่สำเร็จ (หมดเวลา): {last_error or 'ไม่มีใครรออยู่ปลายทาง'}"
        )

    def _server_output(self) -> str:
        """อ่าน log ที่เซิร์ฟเวอร์ฝั่งมือถือพ่นออกมา ไว้บอกสาเหตุตอนพัง"""
        if self.process is None or self.process.stdout is None:
            return "(ไม่มีข้อความ)"
        try:
            raw = self.process.stdout.read() or b""
        except (OSError, ValueError):
            return "(อ่านข้อความไม่ได้)"
        text = raw.decode("utf-8", errors="replace").strip()
        return text.splitlines()[0] if text else "(ไม่มีข้อความ)"

    @staticmethod
    def _read_exactly(sock: socket.socket, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = sock.recv(size - len(chunks))
            if not chunk:
                raise ScrcpyUnavailable("scrcpy-server ปิดการเชื่อมต่อระหว่าง handshake")
            chunks.extend(chunk)
        return bytes(chunks)

    def _clean_stale(self) -> None:
        """ล้าง forward และโปรเซสที่ค้างจากเซสชันก่อนที่ปิดไม่สะอาด

        เกิดได้เมื่อเว็บแอปถูกฆ่าแบบไม่ผ่าน atexit (ปิดหน้าต่างสีดำ / รีสตาร์ตแรง)
        ของค้างพวกนี้ทำให้มือถือทำงานหนักและสตรีมภาพแรกช้าผิดปกติ

        ลบเฉพาะ forward ที่ปลายทางเป็น `localabstract:scrcpy_*` เท่านั้น
        (ห้ามใช้ --remove-all เพราะจะไปโดนอย่างอื่นที่ผู้ใช้ตั้งไว้)
        """
        try:
            listing = subprocess.run(
                [self.adb_executable, "-s", self.serial, "forward", "--list"],
                capture_output=True, timeout=10, creationflags=NO_WINDOW,
            ).stdout.decode("utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError):
            return
        for line in listing.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2].startswith("localabstract:scrcpy_"):
                try:
                    self._adb("forward", "--remove", parts[1], timeout=6)
                except (OSError, subprocess.SubprocessError):
                    pass
        try:
            # ฆ่าเฉพาะ server ที่ push จากเว็บแอปนี้ (ชื่อไฟล์เฉพาะ)
            # ไม่แตะ scrcpy ตัวจริงที่ผู้ใช้อาจเปิดเองอยู่
            self._adb("shell", f"pkill -f {JAR_ON_DEVICE}", timeout=6)
        except (OSError, subprocess.SubprocessError):
            pass

    def open(self) -> None:
        self._clean_stale()
        self._push_server()
        self._forward()
        self._start_server()
        try:
            self._connect()
        except ScrcpyUnavailable:
            self.close()
            raise

    # ---------- ใช้งาน ----------

    def send_touch(
        self, action: str, x: int, y: int, width: int, height: int
    ) -> None:
        sock = self.sock
        if sock is None:
            raise ScrcpyUnavailable("ยังไม่ได้เปิดเซสชัน scrcpy")
        pressure = 0 if action == "UP" else PRESSURE_MAX
        message = struct.pack(
            ">BBqiiHHHii",
            CONTROL_MSG_INJECT_TOUCH_EVENT,
            TOUCH_ACTIONS[action],
            POINTER_ID_GENERIC_FINGER,
            x,
            y,
            width,
            height,
            pressure,
            0,  # action button — นิ้วจริงไม่มีปุ่ม
            0,  # buttons — เช่นกัน
        )
        sock.sendall(message)

    def send_key(self, keycode: int, meta: int = 0, repeat: int = 0) -> None:
        """กดปุ่มหนึ่งครั้ง (กดลง + ปล่อย)

        ส่งทั้ง DOWN และ UP ในนัดเดียว เพราะแอปจำนวนมากรอ UP ถึงจะถือว่ากดจริง
        ส่งแต่ DOWN แล้วค้างไว้ = ปุ่มค้าง แล้วตัวอักษรจะรัวไม่หยุด
        """
        sock = self.sock
        if sock is None:
            raise ScrcpyUnavailable("ยังไม่ได้เปิดเซสชัน scrcpy")
        for action in (KEY_ACTION_DOWN, KEY_ACTION_UP):
            sock.sendall(struct.pack(
                ">BBiii", CONTROL_MSG_INJECT_KEYCODE, action, keycode, repeat, meta))

    def send_text(self, text: str) -> None:
        """พิมพ์ข้อความลงช่องที่โฟกัสอยู่ — **ASCII เท่านั้น**

        ⚠️ ภาษาไทยส่งทางนี้แล้ว **ไม่มีอะไรเกิดขึ้นเลย และไม่มี error ด้วย**
        (วัดกับมือถือจริง 19 ส.ค. 2026: ส่ง "กขค" แล้วช่องยังว่าง ส่ง "X" แล้วโผล่)
        เพราะ scrcpy แปลงตัวอักษรเป็นปุ่มผ่าน KeyCharacterMap ซึ่งไม่มีผังภาษาไทย

        อย่าเรียกตัวนี้ตรงๆ ถ้าไม่มั่นใจว่าข้อความเป็น ASCII — ให้ใช้ `type_text()`
        ที่เลือกทางให้เอง ไม่งั้นจะเจออาการ "สั่งแล้วเงียบ" ซึ่งไล่หายาก
        """
        sock = self.sock
        if sock is None:
            raise ScrcpyUnavailable("ยังไม่ได้เปิดเซสชัน scrcpy")
        if not text.isascii():
            raise ScrcpyUnavailable(
                "INJECT_TEXT รับได้เฉพาะ ASCII — ข้อความไทย/อีโมจิต้องวางผ่านคลิปบอร์ด")
        payload = text.encode("utf-8")
        if len(payload) > MAX_TEXT_BYTES:
            raise ScrcpyUnavailable(
                f"ข้อความยาว {len(payload)} ไบต์ เกินเพดาน {MAX_TEXT_BYTES} — ให้วางผ่านคลิปบอร์ดแทน")
        sock.sendall(struct.pack(">BI", CONTROL_MSG_INJECT_TEXT, len(payload)) + payload)

    def type_text(self, text: str) -> str:
        """พิมพ์ข้อความโดยเลือกทางให้เอง — คืนชื่อทางที่ใช้จริง

        ASCII สั้นๆ ไปทาง INJECT_TEXT (ไม่ไปยุ่งกับคลิปบอร์ดของผู้ใช้)
        นอกนั้นไปทางคลิปบอร์ด ซึ่งรับไทยและอีโมจิได้ครบ
        """
        if text.isascii() and len(text.encode("utf-8")) <= MAX_TEXT_BYTES:
            self.send_text(text)
            return "พิมพ์ตรง"
        self.set_clipboard(text, paste=True)
        return "วางผ่านคลิปบอร์ด"

    def replace_all(self, text: str) -> str:
        """เลือกทั้งหมดแล้วทับด้วยข้อความใหม่ — ทางที่ไม่ต้องลากนิ้วเลย

        CTRL+A แล้ววาง แม่นเสมอไม่ว่าภาพจะช้าแค่ไหน ต่างจากการกดค้าง+ลากตัวชี้
        ซึ่งต้องอาศัยภาพที่ทันนิ้วถึงจะวางตำแหน่งถูก
        """
        self.send_key(KEYCODES["a"], META_CTRL)
        time.sleep(0.25)                  # ให้แอปทันเลือกก่อนวางทับ
        return self.type_text(text)

    def set_clipboard(self, text: str, paste: bool = False) -> None:
        """ตั้งคลิปบอร์ดบนมือถือ (paste=True คือวางลงช่องที่โฟกัสอยู่ให้เลย)

        ข้อความไทย/อีโมจิผ่านได้หมดเพราะส่งเป็น UTF-8 ตรงๆ ไม่ผ่านเชลล์
        ต่างจาก `input text` ที่รับได้แค่ ASCII
        """
        sock = self.sock
        if sock is None:
            raise ScrcpyUnavailable("ยังไม่ได้เปิดเซสชัน scrcpy")
        payload = text.encode("utf-8")
        if len(payload) > MAX_CLIPBOARD_BYTES:
            raise ScrcpyUnavailable("ข้อความยาวเกินกว่าที่คลิปบอร์ดรับได้")
        # >B q B I  = ชนิดข้อความ, sequence (0 = ไม่ต้องตอบกลับ), ธงวาง, ความยาว
        message = struct.pack(
            ">BqBI", CONTROL_MSG_SET_CLIPBOARD, 0, 1 if paste else 0, len(payload)
        )
        sock.sendall(message + payload)

    def _read_message(self) -> tuple[int, str]:
        """อ่านข้อความหนึ่งอันที่มือถือส่งมา คืน (ชนิด, ข้อความ)"""
        sock = self.sock
        kind = self._read_exactly(sock, 1)[0]
        if kind == DEVICE_MSG_CLIPBOARD:
            length = struct.unpack(">I", self._read_exactly(sock, 4))[0]
            if length > MAX_CLIPBOARD_BYTES:
                raise ScrcpyUnavailable("คลิปบอร์ดยาวผิดปกติ")
            text = (
                self._read_exactly(sock, length).decode("utf-8", "replace")
                if length else ""
            )
            return kind, text
        if kind == DEVICE_MSG_ACK_CLIPBOARD:
            self._read_exactly(sock, 8)
        elif kind == DEVICE_MSG_UHID_OUTPUT:
            self._read_exactly(sock, 2)
            size = struct.unpack(">H", self._read_exactly(sock, 2))[0]
            self._read_exactly(sock, size)
        else:
            raise ScrcpyUnavailable(f"ข้อความจากมือถือชนิดที่ไม่รู้จัก ({kind})")
        return kind, ""

    def wait_clipboard(self, timeout: float = 8.0) -> str:
        """รอจนมือถือ**แจ้งเองว่าคลิปบอร์ดเปลี่ยน** แล้วคืนค่าใหม่

        ทำไมต้องรอแบบนี้แทนการถามตรงๆ:
          Android 10 ขึ้นไปห้ามอ่านคลิปบอร์ดจากแอปที่ไม่ได้อยู่หน้าจอ คำสั่งถาม
          (GET_CLIPBOARD) จึงได้แต่ค่าที่ scrcpy จำไว้ล่าสุด ไม่ใช่ของจริงที่เพิ่ง
          เปลี่ยน — ตรวจกับมือถือจริงแล้ว: กด "คัดลอกลิงก์" ในแอป Facebook สำเร็จ
          (เมนูปิดไปเลย) แต่ถามกลับมายังได้ค่าเดิมที่เราตั้งไว้เอง
          ส่วนตัวแจ้งเตือนของระบบยิงมาเองทันทีที่คลิปบอร์ดเปลี่ยน จึงเชื่อได้
        """
        sock = self.sock
        if sock is None:
            raise ScrcpyUnavailable("ยังไม่ได้เปิดเซสชัน scrcpy")
        deadline = time.monotonic() + timeout
        original = sock.gettimeout()
        try:
            while time.monotonic() < deadline:
                sock.settimeout(max(0.2, deadline - time.monotonic()))
                kind, text = self._read_message()
                if kind == DEVICE_MSG_CLIPBOARD:
                    return text
        except socket.timeout:
            return ""
        finally:
            sock.settimeout(original)
        return ""

    def drain(self, timeout: float = 0.4) -> None:
        """ทิ้งข้อความค้างท่อ — ต้องล้างก่อนรอของใหม่ ไม่งั้นได้ของเก่ามาแทน"""
        sock = self.sock
        if sock is None:
            return
        original = sock.gettimeout()
        try:
            while True:
                sock.settimeout(timeout)
                self._read_message()
        except (socket.timeout, ScrcpyUnavailable, OSError):
            pass
        finally:
            sock.settimeout(original)

    def get_clipboard(self, timeout: float = 4.0) -> str:
        """ถามค่าคลิปบอร์ดตรงๆ — ได้ค่าที่ scrcpy รู้ล่าสุด (ดู wait_clipboard)"""
        sock = self.sock
        if sock is None:
            raise ScrcpyUnavailable("ยังไม่ได้เปิดเซสชัน scrcpy")
        sock.sendall(struct.pack(">BB", CONTROL_MSG_GET_CLIPBOARD, COPY_KEY_NONE))
        return self.wait_clipboard(timeout)

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        try:
            # ฆ่าเฉพาะโปรเซสที่มี scid ของเราเอง
            # (ห้ามฆ่าตาม com.genymobile.scrcpy.Server เฉยๆ เพราะผู้ใช้อาจเปิด scrcpy อยู่)
            self._adb("shell", f"pkill -f scid={self.scid}", timeout=6.0)
            self._adb("forward", "--remove", f"tcp:{self.port}", timeout=6.0)
        except (OSError, subprocess.SubprocessError):
            pass


_sessions: dict[str, _Session] = {}
_registry_lock = threading.Lock()


def is_available() -> bool:
    """มีไฟล์ jar ให้ใช้หรือไม่ (ไม่ได้แปลว่ามือถือจะรองรับ)"""
    return SCRCPY_JAR.is_file()


def send_touch(
    adb_executable: str,
    serial: str,
    action: str,
    x: int,
    y: int,
    width: int,
    height: int,
) -> str:
    """ส่ง DOWN/MOVE/UP/CANCEL คืนชื่อรุ่นมือถือที่ handshake ได้

    เปิดเซสชันให้อัตโนมัติเมื่อยังไม่มี และต่อใหม่หนึ่งครั้งถ้า socket ตายไปแล้ว
    """
    if action not in TOUCH_ACTIONS:
        raise ScrcpyUnavailable(f"ไม่รองรับ action {action}")
    if not is_available():
        raise ScrcpyUnavailable("ไม่พบไฟล์ scrcpy-server ในโฟลเดอร์ tools")

    for attempt in range(2):
        session = _get_or_open(adb_executable, serial)
        try:
            with session.lock:
                session.send_touch(action, x, y, width, height)
            return session.device_name
        except (OSError, ScrcpyUnavailable) as error:
            close_session(serial)
            if attempt == 1:
                raise ScrcpyUnavailable(f"ส่งคำสั่งผ่าน scrcpy ไม่สำเร็จ: {error}")
    raise ScrcpyUnavailable("ส่งคำสั่งผ่าน scrcpy ไม่สำเร็จ")


def set_clipboard(
    adb_executable: str, serial: str, text: str, paste: bool = False
) -> None:
    """ส่งข้อความจากคอมไปคลิปบอร์ดของมือถือ"""
    if not is_available():
        raise ScrcpyUnavailable("ไม่พบไฟล์ scrcpy-server")
    session = _get_or_open(adb_executable, serial)
    try:
        session.set_clipboard(text, paste)
    except OSError as error:
        # ท่อขาด (มือถือถอดสาย/เซิร์ฟเวอร์ตาย) — ปิดเซสชันแล้วลองใหม่รอบเดียว
        close_session(serial)
        session = _get_or_open(adb_executable, serial)
        try:
            session.set_clipboard(text, paste)
        except OSError as retry_error:
            raise ScrcpyUnavailable(f"ส่งคลิปบอร์ดไม่สำเร็จ: {retry_error}") from error


def get_clipboard(adb_executable: str, serial: str, timeout: float = 4.0) -> str:
    """อ่านคลิปบอร์ดของมือถือ — ลองใหม่รอบเดียวถ้าท่อขาด"""
    if not is_available():
        raise ScrcpyUnavailable("ไม่พบไฟล์ scrcpy-server")
    for attempt in range(2):
        session = _get_or_open(adb_executable, serial)
        try:
            with session.lock:
                return session.get_clipboard(timeout)
        except OSError as error:
            close_session(serial)
            if attempt == 1:
                raise ScrcpyUnavailable(f"อ่านคลิปบอร์ดไม่สำเร็จ: {error}") from error
    raise ScrcpyUnavailable("อ่านคลิปบอร์ดไม่สำเร็จ")


def drain_clipboard(adb_executable: str, serial: str) -> None:
    """ล้างข้อความค้างก่อนจะรอของใหม่"""
    if not is_available():
        return
    try:
        session = _get_or_open(adb_executable, serial)
        with session.lock:
            session.drain()
    except (OSError, ScrcpyUnavailable):
        pass


def wait_clipboard(adb_executable: str, serial: str, timeout: float = 8.0) -> str:
    """รอให้มือถือแจ้งว่าคลิปบอร์ดเปลี่ยน แล้วคืนค่าใหม่ ("" ถ้าไม่มีอะไรเปลี่ยน)"""
    if not is_available():
        raise ScrcpyUnavailable("ไม่พบไฟล์ scrcpy-server")
    session = _get_or_open(adb_executable, serial)
    try:
        with session.lock:
            return session.wait_clipboard(timeout)
    except OSError as error:
        close_session(serial)
        raise ScrcpyUnavailable(f"รอคลิปบอร์ดไม่สำเร็จ: {error}") from error


def _get_or_open(adb_executable: str, serial: str) -> _Session:
    with _registry_lock:
        session = _sessions.get(serial)
        if session is not None and session.sock is not None:
            return session
        session = _Session(adb_executable, serial)
        session.open()
        _sessions[serial] = session
        logger.info("เปิดเซสชัน scrcpy กับ %s (%s)", serial, session.device_name)
        return session


def ensure_session(adb_executable: str, serial: str) -> str:
    """เปิดเซสชันล่วงหน้าตอนเริ่มแสดงหน้าจอ เพื่อไม่ให้แตะครั้งแรกต้องรอ push jar"""
    if not is_available():
        raise ScrcpyUnavailable("ไม่พบไฟล์ scrcpy-server ในโฟลเดอร์ tools")
    return _get_or_open(adb_executable, serial).device_name


def close_session(serial: str) -> None:
    with _registry_lock:
        session = _sessions.pop(serial, None)
    if session is not None:
        session.close()


def close_all() -> None:
    with _registry_lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    for session in sessions:
        session.close()
