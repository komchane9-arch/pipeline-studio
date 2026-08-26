"""ฟาร์มโปรไฟล์บอท — คัดลอก Chrome profile ออกมาเป็น user-data-dir แยก แล้วรันขนานกันได้

หลักการ: Chrome ล็อกที่ระดับโฟลเดอร์ User Data ทั้งก้อน (ทุกโปรไฟล์ = โปรเซสเดียว)
จะรันบอท 10 ตัวพร้อมกันจึงต้องแยกคนละ user-data-dir — copy ครั้งเดียว
ล็อกอิน/คุกกี้ติดมาด้วย เพราะกุญแจถอดรหัสคุกกี้ (os_crypt) อยู่ใน Local State
ซึ่งผูกกับ DPAPI ของบัญชี Windows เครื่องนี้ ใช้ข้ามโฟลเดอร์ได้แต่ข้ามเครื่องไม่ได้
"""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

import studio_shared

CHROME_USER_DATA = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"

# โฟลเดอร์แคช/เซสชันที่ไม่มีผลกับล็อกอิน — ข้ามตอน copy ให้เร็วและเล็กลงมาก
_SKIP_DIRS = {
    "Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache",
    "DawnWebGPUCache", "ShaderCache", "GrShaderCache", "component_crx_cache",
    "Crashpad", "BrowserMetrics", "Snapshots", "optimization_guide_model_store",
    "segmentation_platform", "MEIPreload", "Sessions",  # แท็บที่เปิดค้าง ไม่ต้องพก
}

# ไฟล์ที่ต้อง copy ให้ได้จริง ไม่งั้นถือว่านำเข้าไม่สำเร็จ (ล็อกอินจะหาย)
_CRITICAL_FILES = ("Cookies", "Login Data", "Web Data")

# ไฟล์ที่ "อุ้มล็อกอิน" ทั้งหมด — ใช้ตอน refresh ก่อนเปิด (แตะแค่ไม่กี่ MB ไม่ใช่ทั้งโปรไฟล์)
# วางเป็น (relative-path, ต้องมีจริงไหม) โดย Cookies เป็นตัวนำร่อง (canary):
# ถ้าก๊อป Cookies ไม่ได้แปลว่าโปรไฟล์ต้นทางถูกล็อก (เปิดค้างอยู่) → ยกเลิก refresh ทั้งชุด
# เพื่อกัน key/cookie ไม่ตรงกัน (ก๊อป Local State ได้แต่ Cookies ไม่ได้ = ถอดรหัสพัง)
_LOGIN_FILES = [
    "Network/Cookies", "Network/Cookies-journal",
    "Login Data", "Login Data-journal",
    "Web Data", "Web Data-journal",
]

_registry_lock = threading.Lock()


def _with_bot_lock(method):
    """ทุกงานที่แตะโฟลเดอร์โปรไฟล์ต้องถือล็อกของบอท **ตัวนั้น** ก่อน

    `_registry_lock` ข้างบนกันได้แค่ในโปรเซสนี้ พอระยะ 3 แยก post_app.py ออกไป
    คนละพอร์ต จะมีสองโปรเซสที่สั่งเปิด/รีเฟรชบอทได้ ล็อกในโปรเซสจะมองไม่เห็นกัน
    — เรื่องเดียวกับที่เคยเจอกับ Chrome จนต้องทำ browser_lock()

    ล็อกแยกรายบอท บอทคนละตัวจึงทำงานขนานกันได้ตามที่ตั้งใจไว้ตั้งแต่แรก
    ขอซ้อนได้ด้วย เพราะเมธอดพวกนี้เรียกกันเองลึกถึง 3 ชั้น
    (delete -> stop -> backup_login  ·  launch -> refresh_from_source)
    """

    @functools.wraps(method)
    def wrapper(self, profile_id, *args, **kwargs):
        with studio_shared.bot_lock(profile_id, label=f"{method.__name__} {profile_id}"):
            return method(self, profile_id, *args, **kwargs)

    return wrapper
# โปรเซส Chrome ที่ฟาร์มเปิดไว้ {profile_id: Popen}
_running: dict[str, subprocess.Popen] = {}


class FarmError(Exception):
    """ข้อผิดพลาดที่ตั้งใจส่งข้อความให้ผู้ใช้อ่านตรงๆ"""


def _find_chrome() -> str:
    for candidate in (
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    raise FarmError("หา chrome.exe ไม่เจอในเครื่อง")


class ProfileFarm:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "bot_profiles"
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry_file = self.root / "registry.json"

    # ------------------------------------------------------------- registry
    def _load(self) -> dict:
        try:
            return json.loads(self.registry_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"profiles": [], "max_concurrent": 3}

    def _save(self, data: dict) -> None:
        self.registry_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------- โปรไฟล์ Chrome ต้นทาง
    @staticmethod
    def chrome_profiles() -> list[dict]:
        """อ่านรายชื่อโปรไฟล์จาก Local State ของ Chrome จริง"""
        try:
            state = json.loads(
                (CHROME_USER_DATA / "Local State").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        cache = state.get("profile", {}).get("info_cache", {})
        return [
            {"folder": folder, "name": info.get("name") or folder,
             "email": info.get("user_name") or ""}
            for folder, info in sorted(cache.items())
        ]

    # ---- สแกน Chrome ครั้งเดียว ใช้ตอบได้ทั้ง "ใครเปิดอยู่" และ "Chrome ผู้ใช้เปิดไหม" ----
    #
    # **ตัดสินจากของจริง ไม่ใช่จากเลขที่จำไว้** (แก้ 26 ส.ค. 2026)
    #
    # ของเดิมดูว่า `entry["pid"]` ที่บันทึกไว้ยังมีชีวิตไหม ซึ่งพังเงียบๆ 2 ทาง
    #   1. เลขนั้นเขียนโดย `launch()` เท่านั้น แต่บอทที่ทำงานจริงถูกเปิดโดย
    #      `fb_posts_collect.py` / `fb_mass_bot.py` ซึ่งไม่ได้ผ่าน `launch()`
    #      → ไม่มีใครเขียนเลข ระบบเลยเห็นเป็น "ไม่ได้รัน" ตลอด
    #   2. เครื่องรีสตาร์ตแล้วเลขเก่าตายหมด แต่ไฟล์ยังจำไว้
    #
    # วัดจริง 26 ส.ค. 08:45 — Bot8/Bot9/Bot10 เปิด Chrome อยู่ 28 หน้าต่างและ
    # เก็บโพสต์ได้จริง แต่ `running_count` ตอบ 0
    #
    # **ที่อันตรายคือมันไม่ได้แค่แสดงผิด** — `running` เป็นตัวคุมด่านกันพลาด 2 ด่าน
    #   · `launch()`  กันไม่ให้เปิด Chrome ซ้อนบนโปรไฟล์เดิม (เสี่ยงโดน Facebook ตีธง)
    #   · `restore_login()` กันไม่ให้ทับไฟล์ล็อกอินตอน Chrome ยังถืออยู่ (โปรไฟล์พัง)
    # พอตัวตรวจตอบ "ไม่ได้รัน" ตลอด ด่านทั้งสองจึงเปิดโล่งมาตลอดโดยไม่มีใครรู้
    #
    # ทางแก้: อ่าน `--user-data-dir` จากคำสั่งของ chrome.exe ที่เปิดอยู่จริง
    # ใครเปิดมันก็เห็น · เครื่องรีสตาร์ตก็ยังถูก · ไม่มีอะไรให้ค้างเก่า
    _SCAN_PS = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "ConvertTo-Json -Compress -Depth 3 -InputObject @("
        "Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" "
        "| Select-Object ProcessId,CommandLine)"
    )

    # เก็บผลไว้สั้นๆ เพราะหน้าเว็บถามซ้ำถี่ และการสแกนใช้เวลาราวครึ่งวินาที
    # ด่านกันพลาดสั่ง fresh=True เสมอ — ที่นั่นข้อมูลเก่า 2 วินาทีก็ปล่อยของผิดได้
    _scan_cache: tuple[float, dict] | None = None
    _scan_lock = threading.Lock()
    SCAN_TTL = 2.5

    @classmethod
    def _chrome_scan(cls, fresh: bool = False) -> dict:
        """คืน {"by_profile": {รหัสโปรไฟล์: {"main": [pid], "all": [pid]}}, "user_chrome": bool}

        `main` = หน้าต่างแม่ (คำสั่งไม่มี `--type=`) ปิดตัวนี้แบบสุภาพแล้วลูกตายตาม
        และ Chrome ได้เขียนคุกกี้ลงดิสก์ก่อนตาย
        """
        with cls._scan_lock:
            cached = cls._scan_cache
            if not fresh and cached and (time.time() - cached[0]) < cls.SCAN_TTL:
                return cached[1]

        rows: list = []
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cls._SCAN_PS],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=25, creationflags=studio_shared.NO_WINDOW)
            raw = (result.stdout or "").strip()
            if raw:
                parsed = json.loads(raw)
                rows = [parsed] if isinstance(parsed, dict) else list(parsed or [])
        except Exception:                                    # noqa: BLE001
            # สแกนไม่ได้ = **ไม่รู้** ไม่ใช่ "ไม่มีใครเปิด" — ตอบว่าไม่มีคือคำตอบที่
            # อันตรายกว่า เพราะด่านกันพลาดจะปล่อยผ่านทันที ปล่อยให้ผลว่างแล้วให้
            # ผู้เรียกเห็นว่าไม่มีข้อมูล ดีกว่าโกหกว่าปลอดภัย
            rows = []

        by_profile: dict[str, dict[str, list[int]]] = {}
        user_chrome = False
        for row in rows:
            if not isinstance(row, dict):
                continue
            cmd = str(row.get("CommandLine") or "")
            if not cmd.strip():
                continue
            pid = row.get("ProcessId")
            if not isinstance(pid, int):
                continue
            if "--user-data-dir" not in cmd:
                # ไม่มี --user-data-dir = Chrome ตัวจริงของผู้ใช้ (กติกาเดิม ไม่เปลี่ยน)
                user_chrome = True
                continue
            found = re.search(r"bot_profiles[/\\]+([0-9A-Za-z_-]+)", cmd)
            if not found:
                continue
            slot = by_profile.setdefault(found.group(1), {"main": [], "all": []})
            slot["all"].append(pid)
            if "--type=" not in cmd:
                slot["main"].append(pid)

        scan = {"by_profile": by_profile, "user_chrome": user_chrome}
        with cls._scan_lock:
            cls._scan_cache = (time.time(), scan)
        return scan

    @classmethod
    def chrome_is_running(cls) -> bool:
        """เช็คเฉพาะ Chrome ตัวจริงของผู้ใช้ (ที่ใช้ User Data หลัก)

        เช็คแบบเหมารวม chrome.exe ไม่ได้ — บอทของ flow_worker และบอทฟาร์มเอง
        ก็เป็น chrome.exe แต่เปิดด้วย --user-data-dir แยก ไม่แตะ User Data หลัก
        จึงกรองเอาเฉพาะโปรเซสที่ *ไม่มี* --user-data-dir ใน command line
        """
        return cls._chrome_scan()["user_chrome"]

    @staticmethod
    def _chrome_is_running_old() -> bool:
        """เช็คเฉพาะ Chrome ตัวจริงของผู้ใช้ (ที่ใช้ User Data หลัก)

        เช็คแบบเหมารวม chrome.exe ไม่ได้ — บอทของ flow_worker และบอทฟาร์มเอง
        ก็เป็น chrome.exe แต่เปิดด้วย --user-data-dir แยก ไม่แตะ User Data หลัก
        จึงกรองเอาเฉพาะโปรเซสที่ *ไม่มี* --user-data-dir ใน command line
        """
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\").CommandLine"],
            capture_output=True, text=True, timeout=20, creationflags=studio_shared.NO_WINDOW)
        for line in (result.stdout or "").splitlines():
            if line.strip() and "--user-data-dir" not in line:
                return True
        return False

    @staticmethod
    def _alive_chrome_pids() -> set[int]:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, creationflags=studio_shared.NO_WINDOW)
        pids = set()
        for line in (result.stdout or "").splitlines():
            parts = line.split('","')
            if len(parts) > 1:
                try:
                    pids.add(int(parts[1].strip('"')))
                except ValueError:
                    pass
        return pids

    # ------------------------------------------------------------- นำเข้า
    def import_profile(self, source_folder: str, name: str = "") -> dict:
        source = CHROME_USER_DATA / source_folder
        if not re.fullmatch(r"Default|Profile ?\d*|Profile", source_folder):
            raise FarmError(f"ชื่อโฟลเดอร์โปรไฟล์ไม่ถูกต้อง: {source_folder}")
        if not source.is_dir():
            raise FarmError(f"ไม่พบโปรไฟล์ {source_folder} ใน Chrome")
        # ไม่บล็อกเหมารวมตอน Chrome เปิด — โปรไฟล์ที่ไม่ได้เปิดค้าง copy ได้ปกติ
        # ปล่อยให้ด่านตรวจ "ไฟล์สำคัญถูกล็อกไหม" ด้านล่างเป็นตัวตัดสินรายโปรไฟล์แทน
        # (เฉพาะโปรไฟล์ที่กำลังเปิดดูอยู่เท่านั้นที่ Cookies จะถูกล็อก)

        profile_id = uuid.uuid4().hex[:8]
        dest = self.root / profile_id
        dest_default = dest / "Default"

        # copy แบบ best-effort ทีละไฟล์ — ไฟล์ LOCK/ล็อกค้างจะถูกข้ามโดยไม่ล้มทั้งก้อน
        # (copytree เดิมล้มทั้งงานถ้าเจอไฟล์ล็อกแม้ไฟล์เดียว) แล้วค่อยตรวจไฟล์สำคัญทีหลัง
        skipped: list[str] = []
        try:
            for src_path in source.rglob("*"):
                rel = src_path.relative_to(source)
                if any(part in _SKIP_DIRS for part in rel.parts):
                    continue
                if src_path.name == "LOCK":  # marker ล็อกของ leveldb — ไร้ค่า
                    continue
                target = dest_default / rel
                if src_path.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, target)
                except OSError:
                    skipped.append(str(rel))
            # Local State พกกุญแจ os_crypt สำหรับถอดรหัสคุกกี้ — ขาดไม่ได้
            shutil.copy2(CHROME_USER_DATA / "Local State", dest / "Local State")
            (dest / "First Run").touch()  # ข้ามหน้าต้อนรับของ Chrome
        except OSError as error:
            shutil.rmtree(dest, ignore_errors=True)
            raise FarmError(f"คัดลอกไม่สำเร็จ: {error}") from error

        chrome_name = next(
            (p["name"] for p in self.chrome_profiles() if p["folder"] == source_folder),
            source_folder)

        # ไฟล์สำคัญพลาดแม้แต่ตัวเดียว = ล็อกอินจะไม่ติดมา ถือว่าล้มเหลว ไม่เก็บโปรไฟล์เสียไว้
        missing = [
            name for name in _CRITICAL_FILES
            if any(name in s for s in skipped)
        ]
        if missing:
            shutil.rmtree(dest, ignore_errors=True)
            label = f"{chrome_name} ({source_folder})" if chrome_name != source_folder else source_folder
            raise FarmError(
                f"โปรไฟล์ \"{label}\" กำลังเปิดใช้อยู่ (ไฟล์ {', '.join(missing)} "
                "ถูกล็อก) — ปิดหน้าต่าง/แท็บของโปรไฟล์นั้นก่อน แล้วลองใหม่")
        entry = {
            "id": profile_id,
            "name": name.strip() or chrome_name,
            "source": source_folder,
            "created": time.strftime("%Y-%m-%d %H:%M"),
            # รีเฟรชล็อกอินจากต้นทางก่อนเปิดทุกครั้ง (ผู้ใช้สั่ง) — ปิดได้ถ้าจะใช้
            # โปรไฟล์นี้เก็บล็อกอินที่กดเองทิ้งไว้ (refresh จะทับของที่กดเอง)
            "auto_refresh": True,
            "refreshed": "",
        }
        with _registry_lock:
            data = self._load()
            data["profiles"].append(entry)
            self._save(data)
        return {**entry, "skipped": skipped}

    # --------------------------------------------- สร้างโปรไฟล์เปล่า (ไม่ก๊อป)
    def create_blank(self, name: str) -> dict:
        """สร้างโปรไฟล์บอทเปล่า ให้ผู้ใช้เปิดขึ้นมาล็อกอินเอง แล้วจำไว้ถาวร

        ทำไมเลิกก๊อปจาก Chrome ของผู้ใช้ (พิสูจน์จากของจริงแล้ว 3 ข้อ)
          1. `Local State` ที่ก๊อปมาพก `info_cache` ของ**ทั้งเครื่องต้นทาง** ทำให้
             สำเนาติดป้ายผิด — โฟลเดอร์ Default ข้างในเป็น "bot 1" แต่ Chrome โชว์
             "Person 1 · ยังไม่ได้ล็อกอิน" เพราะป้ายอ่านจาก Local State ไม่ใช่โฟลเดอร์
          2. คุกกี้ของ Chrome ยุคนี้เข้ารหัสด้วยกุญแจที่ผูกกับที่อยู่เดิม ก๊อปข้าม
             โฟลเดอร์แล้วใช้ต่อไม่ได้เสมอไป
          3. ต้นทางเองอาจไม่เคยล็อกอินเว็บนั้นไว้ — ก๊อปสมบูรณ์แค่ไหนก็ไม่มีอะไรให้ดึง

        โปรไฟล์เปล่าไม่มีปัญหาทั้งสามข้อ: Chrome สร้างกุญแจของตัวเองในโฟลเดอร์ตัวเอง
        ล็อกอินครั้งเดียวอยู่ยาว และคนละโฟลเดอร์ = คนละโปรเซส รันพร้อมกันได้
        """
        clean = (name or "").strip()[:40]
        if not clean:
            raise FarmError("ต้องตั้งชื่อโปรไฟล์")
        with _registry_lock:
            data = self._load()
            if any(e["name"].casefold() == clean.casefold() for e in data["profiles"]):
                raise FarmError(f"มีโปรไฟล์ชื่อ \"{clean}\" อยู่แล้ว")

        profile_id = uuid.uuid4().hex[:8]
        dest = self.root / profile_id
        try:
            (dest / "Default").mkdir(parents=True, exist_ok=True)
            (dest / "First Run").touch()      # ข้ามหน้าต้อนรับของ Chrome
            # เขียน Local State ขั้นต่ำให้ Chrome ติดป้ายชื่อถูกตั้งแต่เปิดครั้งแรก
            # ไม่ใส่ os_crypt — ปล่อยให้ Chrome สร้างกุญแจของตัวเอง ซึ่งเป็นหัวใจ
            # ที่ทำให้คุกกี้ของโปรไฟล์นี้ถอดรหัสได้เสมอ
            (dest / "Local State").write_text(json.dumps({
                "profile": {
                    "info_cache": {
                        "Default": {"name": clean, "is_using_default_name": False},
                    },
                    "last_used": "Default",
                    "profiles_order": ["Default"],
                },
            }, ensure_ascii=False), encoding="utf-8")
        except OSError as error:
            shutil.rmtree(dest, ignore_errors=True)
            raise FarmError(f"สร้างโปรไฟล์ไม่สำเร็จ: {error}") from error

        entry = {
            "id": profile_id,
            "name": clean,
            # ว่าง = ไม่มีต้นทาง ต้องล็อกอินเองในโปรไฟล์นี้
            "source": "",
            "created": time.strftime("%Y-%m-%d %H:%M"),
            # ต้องปิดตาย ไม่งั้นรอบหน้าจะเอาไฟล์ล็อกอินจากที่อื่นมาทับของที่กดเอง
            "auto_refresh": False,
            "refreshed": "",
        }
        with _registry_lock:
            data = self._load()
            data["profiles"].append(entry)
            self._save(data)
        return entry

    def rename(self, profile_id: str, new_name: str) -> dict:
        """เปลี่ยนแค่ชื่อโชว์ (name) — id/source/ตำแหน่งในทะเบียนคงเดิม

        กันชื่อซ้ำ เพราะโค้ดอื่น (fb_mass_finder ฯลฯ) อ้างบอทด้วยชื่อ
        ชื่อชนกันจะทำให้ lookup ได้ตัวผิด
        """
        new_name = (new_name or "").strip()
        if not new_name:
            raise FarmError("ชื่อว่างไม่ได้")
        with _registry_lock:
            data = self._load()
            target = next((e for e in data["profiles"] if e["id"] == profile_id), None)
            if target is None:
                raise FarmError("ไม่พบโปรไฟล์บอทตัวนี้")
            clash = any(
                e["id"] != profile_id and e["name"].casefold() == new_name.casefold()
                for e in data["profiles"])
            if clash:
                raise FarmError(f"มีบอทชื่อ \"{new_name}\" อยู่แล้ว")
            target["name"] = new_name
            self._save(data)
        return {"name": new_name}

    def ensure_bots(self, count: int = 10, prefix: str = "Bot") -> dict:
        """มีโปรไฟล์ชื่อ Bot1..BotN ครบ — ตัวที่มีอยู่แล้วไม่แตะ"""
        count = max(1, min(50, int(count)))
        with _registry_lock:
            existing = {e["name"].casefold() for e in self._load()["profiles"]}
        created = []
        for number in range(1, count + 1):
            name = f"{prefix}{number}"
            if name.casefold() in existing:
                continue
            created.append(self.create_blank(name)["name"])
        return {"created": created, "total": count}

    # ------------------------------------------------------- refresh ล็อกอิน
    @_with_bot_lock
    def refresh_from_source(self, profile_id: str) -> dict:
        """ก๊อปเฉพาะไฟล์ล็อกอินจากโปรไฟล์ Chrome ต้นทางมาทับ (ไม่ก๊อปทั้งโปรไฟล์)

        Cookies เป็นตัวนำร่อง: ถ้าก๊อปไม่ได้ = ต้นทางเปิดค้างอยู่ → ยกเลิกทั้งชุด
        เพื่อไม่ให้ได้ Local State (กุญแจ) ใหม่แต่ Cookies เก่า ซึ่งจะถอดรหัสไม่ออก
        """
        with _registry_lock:
            data = self._load()
            entry = next((e for e in data["profiles"] if e["id"] == profile_id), None)
        if entry is None:
            raise FarmError("ไม่พบโปรไฟล์บอทตัวนี้")
        if not entry.get("source"):
            # โปรไฟล์ที่สร้างเปล่าไม่มีต้นทาง — ถ้าปล่อยผ่านจะไปก๊อป
            # โฟลเดอร์ User Data ทั้งก้อนมาทับ แล้วล็อกอินที่กดเองหายทันที
            raise FarmError(
                f"\"{entry['name']}\" เป็นโปรไฟล์ที่สร้างขึ้นเอง ไม่มีต้นทางให้รีเฟรช "
                "— ล็อกอินในโปรไฟล์นี้โดยตรงแล้วมันจะจำไว้เอง")
        source = CHROME_USER_DATA / entry["source"]
        if not source.is_dir():
            raise FarmError(f"โปรไฟล์ต้นทาง {entry['source']} หายไปจาก Chrome แล้ว")
        dest_default = self._dir_of(profile_id) / "Default"

        # นำร่องด้วย Cookies (รองรับทั้ง path ใหม่ Network/ และเก่า)
        cookie_rel = ("Network/Cookies"
                      if (source / "Network" / "Cookies").is_file() else "Cookies")
        src_cookie = source / cookie_rel
        if not src_cookie.is_file():
            raise FarmError("โปรไฟล์ต้นทางยังไม่มีคุกกี้ให้รีเฟรช")
        try:
            (dest_default / cookie_rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_cookie, dest_default / cookie_rel)
        except OSError:
            return {"refreshed": False, "reason": "locked"}

        # Cookies ผ่านแล้ว = ต้นทางไม่ถูกล็อก → ก๊อปที่เหลือ + Local State (กุญแจ)
        for rel in _LOGIN_FILES:
            src_file = source / rel
            if not src_file.is_file():
                continue
            try:
                (dest_default / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dest_default / rel)
            except OSError:
                pass
        try:
            shutil.copy2(CHROME_USER_DATA / "Local State",
                         self._dir_of(profile_id) / "Local State")
        except OSError:
            pass

        stamp = time.strftime("%H:%M:%S")
        with _registry_lock:
            data = self._load()
            for e in data["profiles"]:
                if e["id"] == profile_id:
                    e["refreshed"] = stamp
            self._save(data)
        return {"refreshed": True, "at": stamp}

    def set_auto_refresh(self, profile_id: str, value: bool) -> None:
        with _registry_lock:
            data = self._load()
            for e in data["profiles"]:
                if e["id"] == profile_id:
                    e["auto_refresh"] = bool(value)
            self._save(data)

    # ------------------------------------------------------------- สถานะ
    def list_profiles(self, fresh: bool = False) -> dict:
        with _registry_lock:
            data = self._load()
        # ดูจาก Chrome ที่เปิดอยู่จริง ไม่ใช่จากเลขโปรเซสที่บันทึกไว้
        # (เหตุผลเต็มอยู่ที่ `_chrome_scan` — ของเดิมมองไม่เห็นบอทที่เปิดโดย
        #  สคริปต์ตัวอื่น และเลขที่จำไว้ตายทุกครั้งที่เครื่องรีสตาร์ต)
        scan = self._chrome_scan(fresh=fresh)
        profiles = []
        for entry in data["profiles"]:
            slot = scan["by_profile"].get(entry["id"]) or {}
            pids = slot.get("all") or []
            running = bool(pids)
            if not running:
                _running.pop(entry["id"], None)
            profiles.append({**entry, "running": running,
                             "windows": len(pids),
                             "pids": slot.get("main") or pids})
        return {
            "profiles": profiles,
            "max_concurrent": data.get("max_concurrent", 3),
            "running_count": sum(1 for p in profiles if p["running"]),
            "chrome_running": scan["user_chrome"],
        }

    def set_max_concurrent(self, value: int) -> None:
        with _registry_lock:
            data = self._load()
            data["max_concurrent"] = max(1, min(20, int(value)))
            self._save(data)

    def _dir_of(self, profile_id: str) -> Path:
        path = self.root / profile_id
        if not path.is_dir():
            raise FarmError("ไม่พบโปรไฟล์บอทตัวนี้")
        return path

    # ------------------------------------------------------------- เปิด/ปิด
    @_with_bot_lock
    def launch(self, profile_id: str, url: str = "") -> dict:
        # fresh=True — ด่านนี้ยอมให้ข้อมูลเก่าไม่ได้ เปิด Chrome ซ้อนบนโปรไฟล์เดียว
        # แปลว่าเสี่ยงโดน Facebook ตีธง และไฟล์โปรไฟล์อาจพังจากการเขียนชนกัน
        state = self.list_profiles(fresh=True)
        if state["running_count"] >= state["max_concurrent"]:
            raise FarmError(
                f"บอทวิ่งอยู่ {state['running_count']} ตัว ถึงเพดาน "
                f"{state['max_concurrent']} แล้ว — ปิดตัวอื่นก่อนหรือเพิ่มเพดาน")
        if any(p["id"] == profile_id and p["running"] for p in state["profiles"]):
            raise FarmError("โปรไฟล์นี้เปิดอยู่แล้ว")

        # รีเฟรชล็อกอินจากต้นทางก่อนเปิด (ถ้าเปิดสวิตช์ไว้) — best-effort ไม่บล็อกการเปิด
        entry = next((p for p in state["profiles"] if p["id"] == profile_id), {})
        refresh_note = ""
        if entry.get("auto_refresh", True):
            try:
                result = self.refresh_from_source(profile_id)
                refresh_note = (f" · รีเฟรชล่าสุด {result['at']}" if result["refreshed"]
                                else " · ใช้ข้อมูลเดิม (ต้นทางเปิดค้างอยู่ รีเฟรชไม่ได้)")
            except FarmError as error:
                refresh_note = f" · รีเฟรชไม่ได้: {error}"

        args = [
            _find_chrome(),
            f"--user-data-dir={self._dir_of(profile_id)}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if url:
            args.append(url)
        proc = subprocess.Popen(args, creationflags=studio_shared.NO_WINDOW)
        _running[profile_id] = proc
        with _registry_lock:
            data = self._load()
            for entry in data["profiles"]:
                if entry["id"] == profile_id:
                    entry["pid"] = proc.pid
            self._save(data)
        return {"message": "เปิด Chrome ของบอทแล้ว" + refresh_note}

    @_with_bot_lock
    def stop(self, profile_id: str) -> dict:
        _running.pop(profile_id, None)
        # หาเลขโปรเซสจาก Chrome ที่เปิดอยู่จริง ไม่ใช่จากเลขที่บันทึกไว้ —
        # บอทที่เปิดโดย fb_posts_collect.py / fb_mass_bot.py ไม่เคยเขียนเลขลงทะเบียน
        # ของเดิมจึงตอบว่า "ไม่ได้เปิดอยู่" แล้วปิดไม่ได้เลยทั้งที่เห็นหน้าต่างอยู่ตรงหน้า
        scan = self._chrome_scan(fresh=True)
        slot = scan["by_profile"].get(profile_id) or {}
        targets = slot.get("main") or slot.get("all") or []
        if not targets:
            return {"message": "โปรไฟล์นี้ไม่ได้เปิดอยู่"}

        def still_open() -> list[int]:
            fresh = self._chrome_scan(fresh=True)["by_profile"].get(profile_id) or {}
            return fresh.get("all") or []

        # ปิดแบบสุภาพก่อน (ไม่ใส่ /F) — Chrome ได้ WM_CLOSE แล้วเขียนคุกกี้/เซสชัน
        # ลงดิสก์ให้ครบก่อนตาย ถ้าฆ่าด้วย /F ทันที ล็อกอินรอบล่าสุดอาจหายไป
        for pid in targets:
            subprocess.run(["taskkill", "/PID", str(pid), "/T"],
                           capture_output=True, creationflags=studio_shared.NO_WINDOW)
        for _ in range(16):  # รอสูงสุด ~8 วิ
            if not still_open():
                break
            time.sleep(0.5)
        else:
            # ดื้อจริง (ค้าง/มี dialog) — จำเป็นต้องบังคับ
            for pid in still_open():
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, creationflags=studio_shared.NO_WINDOW)
            time.sleep(1.0)  # เผื่อคายล็อกไฟล์

        # โปรเซสตายแล้วค่อยสำรอง — ตอนเปิดอยู่ไฟล์ถูกล็อก copy ไปก็ได้ของเสีย
        note = ""
        try:
            saved = self.backup_login(profile_id)
            note = f" · สำรองล็อกอินแล้ว {saved['at']}"
        except FarmError as error:
            note = f" · สำรองไม่สำเร็จ: {error}"
        return {"message": "ปิดแล้ว" + note}

    # ------------------------------------------------------ สำรอง/กู้ ล็อกอิน
    @_with_bot_lock
    def backup_login(self, profile_id: str) -> dict:
        """เก็บสำเนาไฟล์ล็อกอินไว้ที่ _backups/<id>/<เวลา>/ — เก็บ 5 ชุดล่าสุด

        เหตุผล: โปรไฟล์ทั้งก้อนหายได้ (เคยโดนลบยกชุดมาแล้ว) แต่ไฟล์ล็อกอิน
        มีไม่กี่ MB สำรองทุกครั้งที่ปิดจึงถูกและคุ้ม
        """
        src = self._dir_of(profile_id) / "Default"
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = self.root / "_backups" / profile_id / stamp
        copied = []
        for rel in _LOGIN_FILES:
            src_file = src / rel
            if not src_file.is_file():
                continue
            try:
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dest / rel)
                copied.append(rel)
            except OSError:
                pass
        state = self._dir_of(profile_id) / "Local State"
        if state.is_file():
            try:
                shutil.copy2(state, dest / "Local State")
            except OSError:
                pass
        if not any("Cookies" in c for c in copied):
            shutil.rmtree(dest, ignore_errors=True)
            raise FarmError("ยังไม่มีคุกกี้ให้สำรอง (ยังไม่ได้ล็อกอินอะไรไว้)")

        # เก็บแค่ 5 ชุดล่าสุด — ชุดเก่าลบทิ้ง กันกินดิสก์ไม่จบ
        snaps = sorted((self.root / "_backups" / profile_id).iterdir())
        for old in snaps[:-5]:
            shutil.rmtree(old, ignore_errors=True)

        with _registry_lock:
            data = self._load()
            for e in data["profiles"]:
                if e["id"] == profile_id:
                    e["backed_up"] = stamp
            self._save(data)
        return {"at": time.strftime("%H:%M:%S"), "stamp": stamp, "files": len(copied)}

    def list_backups(self, profile_id: str) -> list[str]:
        folder = self.root / "_backups" / profile_id
        if not folder.is_dir():
            return []
        return sorted((d.name for d in folder.iterdir() if d.is_dir()), reverse=True)

    @_with_bot_lock
    def restore_login(self, profile_id: str, stamp: str = "") -> dict:
        """เอาไฟล์ล็อกอินจากชุดสำรองกลับเข้าโปรไฟล์ (ไม่ระบุ = ชุดล่าสุด)"""
        snaps = self.list_backups(profile_id)
        if not snaps:
            raise FarmError("ยังไม่มีชุดสำรองของโปรไฟล์นี้")
        stamp = stamp or snaps[0]
        if stamp not in snaps:
            raise FarmError(f"ไม่พบชุดสำรอง {stamp}")
        if any(p["id"] == profile_id and p["running"]
               for p in self.list_profiles(fresh=True)["profiles"]):
            raise FarmError("ปิดโปรไฟล์นี้ก่อน แล้วค่อยกู้คืน")
        src = self.root / "_backups" / profile_id / stamp
        dest = self._dir_of(profile_id) / "Default"
        for path in src.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(src)
            target = (self._dir_of(profile_id) / rel if rel.name == "Local State"
                      else dest / rel)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            except OSError as error:
                raise FarmError(f"กู้คืนไม่สำเร็จ: {error}") from error
        return {"stamp": stamp}

    @_with_bot_lock
    def delete(self, profile_id: str) -> dict:
        """ย้ายลงถังขยะ ไม่ลบถาวร — ล็อกอินที่สะสมไว้มีค่าเกินกว่าจะลบทิ้งกู้ไม่ได้

        เคยเกิดจริง: สคริปต์ล้างข้อมูลลบ Bot1..Bot10 ทั้งชุดด้วย rmtree
        ไม่ลง Recycle Bin ไม่มี shadow copy = ล็อกอินหายถาวร (ส.ค. 2026)
        ถังขยะอยู่ที่ data/bot_profiles/_trash/ ลบเองได้เมื่อแน่ใจแล้ว
        """
        self.stop(profile_id)
        target = self.root / profile_id
        trash = self.root / "_trash"
        trash.mkdir(parents=True, exist_ok=True)
        moved_to = trash / f"{profile_id}_{time.strftime('%Y%m%d-%H%M%S')}"
        # Chrome เพิ่งถูกฆ่า อาจคายล็อกไฟล์ไม่ทัน — ลองซ้ำสั้นๆ ก่อนยอมแพ้
        for _ in range(5):
            try:
                shutil.move(str(target), str(moved_to))
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise FarmError("ย้ายโฟลเดอร์ไม่สำเร็จ (ไฟล์ยังถูกล็อก) — ลองใหม่อีกครั้ง")
        with _registry_lock:
            data = self._load()
            data["profiles"] = [p for p in data["profiles"] if p["id"] != profile_id]
            self._save(data)
        return {"message": "ย้ายโปรไฟล์บอทลงถังขยะแล้ว (กู้คืนได้ที่ data/bot_profiles/_trash)"}

    def user_data_dir(self, profile_id: str) -> Path:
        """จุดต่อสำหรับ flow_worker/Playwright — เอา path ไปใช้เป็น user_data_dir ได้เลย"""
        return self._dir_of(profile_id)
