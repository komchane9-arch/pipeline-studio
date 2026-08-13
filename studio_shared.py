"""ของที่เซิร์ฟเวอร์ทั้งสองตัวใช้ร่วมกัน — พาธ โทเคน ตั้งค่า log และล็อกเบราว์เซอร์

โปรเจกต์นี้แยกเป็นสองโปรเซส:
    app.py       พอร์ต 8866  งานมือถือ + โพสต์ Facebook + บอทหลัก
    clip_app.py  พอร์ต 8877  สายเจนคลิป + บอท @ClipAiABot

ทั้งคู่อ่านเขียนไฟล์ชุดเดียวกันใน data/ จึงต้องใช้ตัวอ่านตัวเดียวกัน ไม่ใช่ต่างคน
ต่างเขียนโค้ดของตัวเอง — ไม่งั้นวันหนึ่งจะเพี้ยนคนละแบบแล้วไล่หาสาเหตุไม่เจอ

**เรื่องสำคัญที่สุดในไฟล์นี้คือ `browser_lock()`**
"""

from __future__ import annotations

import ctypes
import json
import msvcrt
import os
import time
from contextlib import contextmanager
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = DATA_DIR / "logs"
WEB_DIR = BASE_DIR / "web"
CONFIG_FILE = DATA_DIR / "config.json"
TELEGRAM_TOKEN_FILE = DATA_DIR / "telegram_token.bin"
CLIP_TOKEN_FILE = DATA_DIR / "telegram_clip_token.bin"
# บอทตัวที่ 3 — สาย TikTok repost (@TikTokAiABot)
# ต้องเป็นคนละโทเคนกับอีกสองตัว เพราะ `getUpdates` ของโทเคนหนึ่งมีตัวอ่านได้ตัวเดียว
# สองตัวอ่านโทเคนเดียวกัน = 409 Conflict แล้วข้อความหายสลับไปมา (เคยเจอจริง)
TIKTOK_TOKEN_FILE = DATA_DIR / "telegram_tiktok_token.bin"
BROWSER_LOCK_FILE = DATA_DIR / "browser.lock"
# ไฟล์บอกว่าใครถืออยู่ — ต้อง **แยกจากไฟล์ล็อก** เพราะไบต์ที่ msvcrt ล็อกไว้
# อ่านจากโปรเซสอื่นไม่ได้ (ได้ PermissionError) ข้อความจะกลายเป็น "ไม่ทราบ" ตลอด
BROWSER_LOCK_INFO = DATA_DIR / "browser.lock.info"

# โปรไฟล์ Chrome ที่ใช้ขับ ChatGPT / Shopee / Google Flow — **มีตัวเดียว**
BROWSER_PROFILE = DATA_DIR / "flow_browser_profile"


class BrowserBusy(RuntimeError):
    """โปรไฟล์เบราว์เซอร์ถูกอีกงานใช้อยู่"""


# ------------------------------------------------------- ล็อกเบราว์เซอร์ข้ามโปรเซส

@contextmanager
def browser_lock(timeout: float = 900.0, poll: float = 2.0, label: str = ""):
    """กันไม่ให้สองโปรเซสเปิดโปรไฟล์ Chrome เดียวกันพร้อมกัน

    **Chrome เปิดโปรไฟล์เดียวกันซ้อนกันไม่ได้** ตัวที่เปิดทีหลังจะไล่ตัวเดิมออก
    ทันที งานที่กำลังทำอยู่พังกลางคัน (เคยทำหน้าต่างล็อกอินของผู้ใช้หาย และเคยทำ
    งานสตอรีบอร์ดล้มด้วย "Target page, context or browser has been closed")

    เดิมกันด้วย threading.Lock ซึ่งกันได้แค่ภายในโปรเซสเดียว — พอแยกเป็นสอง
    เซิร์ฟเวอร์ ล็อกนั้นไม่กันข้ามกันอีกต่อไป ต้องใช้ล็อกระดับไฟล์ของ Windows แทน

    ใช้ `msvcrt.locking` ไม่ใช่ "สร้างไฟล์แล้วลบทิ้ง" เพราะถ้าโปรเซสตายกลางทาง
    ไฟล์ล็อกจะค้างและบล็อกทุกงานตลอดไป ส่วนล็อกของ OS ปล่อยให้เองเมื่อโปรเซสตาย
    """
    BROWSER_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    handle = open(BROWSER_LOCK_FILE, "a+b")
    deadline = time.time() + timeout
    got = False
    try:
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                got = True
                break
            except OSError:
                if time.time() >= deadline:
                    raise BrowserBusy(
                        f"เบราว์เซอร์ถูกงานอื่นใช้อยู่เกิน {int(timeout)} วินาที "
                        f"({who_holds_browser()})"
                    )
                time.sleep(poll)
        # จดว่าใครถืออยู่ ไว้บอกผู้ใช้ตอนงานอื่นต้องรอ — ไม่ใช่กลไกของล็อกเอง
        try:
            BROWSER_LOCK_INFO.write_text(
                f"{label or 'ไม่ระบุงาน'} · PID {os.getpid()} · "
                f"เริ่ม {datetime.now():%H:%M:%S}",
                encoding="utf-8",
            )
        except OSError:
            pass
        yield
    finally:
        if got:
            try:
                BROWSER_LOCK_INFO.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        handle.close()


def who_holds_browser() -> str:
    """ข้อความบอกว่าใครถือล็อกอยู่ — ใช้แจ้งผู้ใช้เท่านั้น เชื่อ 100% ไม่ได้

    เป็นแค่บันทึกประกอบ ไม่ใช่กลไกของล็อก ถ้าไฟล์หายหรืออ่านไม่ได้ก็ไม่กระทบ
    การกันงานชนกัน
    """
    try:
        return BROWSER_LOCK_INFO.read_text(encoding="utf-8").strip() or "ไม่ทราบ"
    except OSError:
        return "ไม่ทราบ"


# ------------------------------------------------------------------- โทเคน

def _windows_dpapi(data: bytes, decrypt: bool = False) -> bytes:
    """เข้ารหัส/ถอดรหัสด้วย DPAPI ผูกกับบัญชี Windows ปัจจุบัน"""
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    buffer = ctypes.create_string_buffer(data, len(data))
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    destination = Blob()
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    if decrypt:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(destination)
        )
    else:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source), "Pipeline Studio Secret", None, None, None, 0,
            ctypes.byref(destination),
        )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(destination.pbData, wintypes.HLOCAL))


def load_key(path: Path) -> str | None:
    if not Path(path).is_file():
        return None
    try:
        return _windows_dpapi(Path(path).read_bytes(), decrypt=True).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def save_key(path: Path, key: str) -> None:
    # เขียนผ่าน .tmp แล้ว replace — โปรเซสดับกลางคันต้องไม่เหลือไฟล์ครึ่งเดียว
    temporary = Path(path).with_suffix(".tmp")
    temporary.write_bytes(_windows_dpapi(key.encode("utf-8")))
    temporary.replace(path)


def load_clip_token() -> str | None:
    return load_key(CLIP_TOKEN_FILE)


def load_telegram_token() -> str | None:
    return load_key(TELEGRAM_TOKEN_FILE)


def load_tiktok_token() -> str | None:
    """โทเคนของ @TikTokAiABot — สาย TikTok repost"""
    return load_key(TIKTOK_TOKEN_FILE)


def save_tiktok_token(token: str) -> None:
    save_key(TIKTOK_TOKEN_FILE, token)


# ------------------------------------------------------------------ ตั้งค่า

def read_config() -> dict:
    """อ่าน config.json ดิบๆ ไม่เติมค่าปริยาย

    ค่าปริยายเป็นเรื่องของแต่ละเซิร์ฟเวอร์ ตัวนี้แค่ให้ทั้งคู่อ่านไฟล์เดียวกัน
    ด้วยวิธีเดียวกัน (โดยเฉพาะ encoding — เผลอเป็น cp1252 แล้วภาษาไทยเพี้ยนทันที)
    """
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# -------------------------------------------------------------------- log

LOG_LIMIT_BYTES = 200 * 1024
LOG_TABS = {"input", "gems", "gen_pic", "gen_video", "judge", "release", "publish", "clip"}


def log_path(tab: str) -> Path:
    return LOG_DIR / f"{tab}.log"


def append_log(tab: str, message: str) -> None:
    """เขียน log บรรทัดเดียวจบ

    เปิดไฟล์แบบ append แล้วเขียนทีเดียว — สองโปรเซสเขียนไฟล์เดียวกันได้โดยบรรทัด
    ไม่ปนกัน ตราบใดที่เขียนครั้งละบรรทัดสั้นๆ (ต่ำกว่าขนาดบัฟเฟอร์ของ OS)
    """
    if tab not in LOG_TABS:
        raise ValueError(f"ไม่รู้จัก log ของแท็บ {tab}")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = log_path(tab)
    try:
        if path.is_file() and path.stat().st_size >= LOG_LIMIT_BYTES * 0.9:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path.replace(LOG_DIR / f"{tab}-{stamp}.log")
    except OSError:
        pass
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now():%H:%M:%S} {message}\n")


def read_log(tab: str, tail: int = 80) -> list[str]:
    path = log_path(tab)
    if not path.is_file():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]
    except OSError:
        return []
