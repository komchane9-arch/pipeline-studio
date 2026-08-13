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
import re
import threading
import time
from contextlib import contextmanager
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# ต้องรับ STUDIO_DATA_DIR เหมือน app.py ไม่งั้น "แยก data ตอนทดสอบ" ไม่จริง
#
# เจอตอนระยะ 4: app.py ย้าย data/ ตามตัวแปรนี้ แต่ไฟล์นี้ยังชี้ data/ ของจริงเสมอ
# ผลคือสำเนาที่ตั้งใจให้แยก (git worktree) จะเปิด clip_app ที่อ่าน **โทเคนบอทตัวจริง**
# แล้วไปแย่ง getUpdates กับบอทที่ผู้ใช้ใช้อยู่ — โทเคนหนึ่งมีตัวอ่านได้ตัวเดียว
# อีกตัวจะได้ 409 แล้วข้อความหายสลับไปมา (เคยเจอมาแล้วตอนทำบอทตัวที่สาม)
_data_name = os.environ.get("STUDIO_DATA_DIR", "data").strip() or "data"
DATA_DIR = Path(_data_name) if Path(_data_name).is_absolute() else BASE_DIR / _data_name
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

# ล็อกที่แยกต่อทรัพยากร (มือถือรายเครื่อง / โปรไฟล์บอทรายตัว) อยู่ในโฟลเดอร์นี้
# ของเดิม browser.lock / phone.lock อยู่ที่ data/ ตรงๆ — ปล่อยไว้ที่เดิมไม่ย้าย
LOCK_DIR = DATA_DIR / "locks"


class BrowserBusy(RuntimeError):
    """โปรไฟล์เบราว์เซอร์ถูกอีกงานใช้อยู่"""


class BotBusy(RuntimeError):
    """โปรไฟล์บอทตัวนั้นถูกอีกงานใช้อยู่"""


# ------------------------------------------------------ เครื่องล็อกกลาง (ระยะ 2.1)
#
# เดิมมีล็อกรวมตัวเดียวต่อชนิด: browser.lock กับ phone.lock
# ล็อกรวมแปลว่า **งานคนละเครื่องก็ยังต้องรอกัน** — มือถือ A โพสต์อยู่ มือถือ B
# ว่างเปล่าแต่เริ่มไม่ได้ ยิ่งเพิ่มมือถือยิ่งไม่ได้ความเร็วเพิ่ม
# ตรงนี้จึงทำเป็น "ล็อกต่อทรัพยากร" — คนละเครื่อง/คนละโปรไฟล์บอท = คนละไฟล์ล็อก

_local_guard = threading.Lock()
_local_locks: dict[str, threading.RLock] = {}
_local_depth: dict[tuple[int, str], int] = {}


def _lock_key(text: str) -> str:
    """แปลงชื่อทรัพยากรให้เป็นชื่อไฟล์ที่ Windows รับได้

    serial ที่ต่อผ่าน Wi-Fi หน้าตาเป็น `192.168.1.5:5555` ซึ่งมี ":" ที่ Windows
    ห้ามใช้ในชื่อไฟล์ ถ้าไม่แปลงก่อน open จะพังตั้งแต่สร้างไฟล์ แล้วล็อกไม่ทำงานเลย
    """
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(text).strip())[:60]


def _read_info(info_file: Path) -> str:
    try:
        return info_file.read_text(encoding="utf-8").strip() or "ไม่ทราบ"
    except OSError:
        return "ไม่ทราบ"


@contextmanager
def _resource_lock(lock_file: Path, info_file: Path, *, timeout: float, poll: float,
                   label: str, busy: type[RuntimeError], what: str):
    """ล็อกทรัพยากรหนึ่งชิ้น — กันทั้งข้ามโปรเซสและข้ามเธรด และ "ขอซ้อนได้"

    สองชั้นที่ต้องมีทั้งคู่:
      1. `threading.RLock` ต่อไฟล์ — กันเธรดอื่นในโปรเซสเดียวกัน และยอมให้
         **เธรดเดิม**ขอซ้อนได้
      2. `msvcrt.locking` บนไฟล์ — กันข้ามโปรเซส ขอเฉพาะครั้งนอกสุดเท่านั้น

    ทำไมต้องขอซ้อนได้: `bot_profiles` เรียกกันเองลึกถึง 3 ชั้น
        delete() -> stop() -> backup_login()      launch() -> refresh_from_source()
    ล็อกไฟล์ของ Windows เป็นของ "แฮนเดิล" ไม่ใช่ของเธรด เปิดไฟล์เดิมซ้ำในโปรเซส
    เดียวกันแล้วขอล็อก = **บล็อกตัวเองค้างถาวร** ไม่มีใครมาปลดให้ (จะเป็นบั๊กที่
    เกิดเฉพาะตอนกดลบบอท ซึ่งกว่าจะเจอก็สายไปแล้ว)

    ใช้ล็อกของ OS ไม่ใช่ "สร้างไฟล์แล้วลบทิ้ง" เพราะถ้าโปรเซสตายกลางทาง ไฟล์ที่
    สร้างไว้จะค้างและบล็อกทุกงานตลอดไป ส่วนล็อกของ OS ระบบปล่อยให้เองเมื่อโปรเซสตาย
    """
    path_key = str(lock_file)
    with _local_guard:
        rlock = _local_locks.setdefault(path_key, threading.RLock())
    if not rlock.acquire(timeout=timeout):
        raise busy(f"{what}ถูกงานอื่นในโปรเซสนี้ใช้อยู่เกิน {int(timeout)} วินาที")

    ident = (threading.get_ident(), path_key)
    handle = None
    try:
        if _local_depth.get(ident, 0) == 0:
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            opened = open(lock_file, "a+b")
            deadline = time.time() + timeout
            while True:
                try:
                    opened.seek(0)
                    msvcrt.locking(opened.fileno(), msvcrt.LK_NBLCK, 1)
                    handle = opened
                    break
                except OSError:
                    if time.time() >= deadline:
                        opened.close()
                        raise busy(
                            f"{what}ถูกงานอื่นใช้อยู่เกิน {int(timeout)} วินาที "
                            f"({_read_info(info_file)})"
                        )
                    time.sleep(poll)
            # จดว่าใครถืออยู่ ไว้บอกผู้ใช้ตอนงานอื่นต้องรอ — ไม่ใช่กลไกของล็อกเอง
            # ต้องแยกจากไฟล์ล็อก เพราะไบต์ที่ msvcrt ล็อกไว้ โปรเซสอื่นอ่านไม่ได้
            try:
                info_file.write_text(
                    f"{label or 'ไม่ระบุงาน'} · PID {os.getpid()} · "
                    f"เริ่ม {datetime.now():%H:%M:%S}",
                    encoding="utf-8",
                )
            except OSError:
                pass

        _local_depth[ident] = _local_depth.get(ident, 0) + 1
        try:
            yield
        finally:
            _local_depth[ident] -= 1
            if _local_depth[ident] <= 0:
                _local_depth.pop(ident, None)
    finally:
        if handle is not None:
            try:
                info_file.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            handle.close()
        rlock.release()


# ------------------------------------------------------- ล็อกเบราว์เซอร์ข้ามโปรเซส

def browser_lock(timeout: float = 900.0, poll: float = 2.0, label: str = ""):
    """กันไม่ให้สองโปรเซสเปิดโปรไฟล์ Chrome เดียวกันพร้อมกัน

    **Chrome เปิดโปรไฟล์เดียวกันซ้อนกันไม่ได้** ตัวที่เปิดทีหลังจะไล่ตัวเดิมออก
    ทันที งานที่กำลังทำอยู่พังกลางคัน (เคยทำหน้าต่างล็อกอินของผู้ใช้หาย และเคยทำ
    งานสตอรีบอร์ดล้มด้วย "Target page, context or browser has been closed")

    เดิมกันด้วย threading.Lock ซึ่งกันได้แค่ภายในโปรเซสเดียว — พอแยกเป็นสอง
    เซิร์ฟเวอร์ ล็อกนั้นไม่กันข้ามกันอีกต่อไป ต้องใช้ล็อกระดับไฟล์ของ Windows แทน

    ตัวนี้ยังเป็น "ล็อกรวมตัวเดียว" อยู่โดยตั้งใจ เพราะโปรไฟล์ที่มันกันคือ
    `flow_browser_profile` ซึ่ง**มีตัวเดียวจริงๆ** — ไม่ใช่ทรัพยากรที่แยกเป็นรายตัว
    ได้เหมือนมือถือหรือโปรไฟล์บอท (ถ้าอยากรันขนานต้องแยกโปรไฟล์ก่อน ไม่ใช่แยกล็อก)

    ไฟล์ล็อกยังอยู่ที่ data/browser.lock ที่เดิม — ห้ามย้าย เพราะถ้าโปรเซสเก่าที่
    ยังไม่ได้รีสตาร์ตล็อกไฟล์เดิม แต่โปรเซสใหม่ไปล็อกไฟล์ใหม่ = ต่างคนต่างล็อก
    แล้วเปิด Chrome โปรไฟล์เดียวกันซ้อนกัน ซึ่งคือหายนะที่ล็อกนี้มีไว้กัน
    """
    return _resource_lock(
        BROWSER_LOCK_FILE, BROWSER_LOCK_INFO,
        timeout=timeout, poll=poll, label=label,
        busy=BrowserBusy, what="เบราว์เซอร์",
    )


def who_holds_browser() -> str:
    """ข้อความบอกว่าใครถือล็อกอยู่ — ใช้แจ้งผู้ใช้เท่านั้น เชื่อ 100% ไม่ได้

    เป็นแค่บันทึกประกอบ ไม่ใช่กลไกของล็อก ถ้าไฟล์หายหรืออ่านไม่ได้ก็ไม่กระทบ
    การกันงานชนกัน
    """
    return _read_info(BROWSER_LOCK_INFO)


# --------------------------------------------------- ล็อกมือถือ (แยกรายเครื่อง)

class PhoneBusy(RuntimeError):
    """มือถือเครื่องนั้นถูกอีกโปรเซสใช้อยู่"""


def _phone_lock_paths(serial: str) -> tuple[Path, Path]:
    key = _lock_key(serial)
    return LOCK_DIR / f"phone-{key}.lock", LOCK_DIR / f"phone-{key}.info"


def phone_lock(serial: str, timeout: float = 600.0, poll: float = 2.0, label: str = ""):
    """กันไม่ให้สองโปรเซสสั่ง ADB ใส่มือถือ **เครื่องเดียวกัน** พร้อมกัน

    **มือถือมีจอเดียว** สองโปรเซสยิง ADB ใส่เครื่องเดียวกันคือแตะทับกันเละทั้งคู่ —
    ฝั่งหนึ่งกำลังพิมพ์แคปชันอยู่ อีกฝั่ง force-stop แอปหรือกด Back ทิ้ง

    ของเดิม `PhoneGate` ใน app.py กันได้แค่ **ภายในโปรเซสเดียว** (งานโพสต์ vs
    Claude CLI) พอมีบอทตัวที่สี่ที่ใช้ ADB ด้วย ล็อกนั้นไม่กันข้ามโปรเซสอีกต่อไป
    — เรื่องเดียวกับที่เคยเจอกับ Chrome จนต้องทำ `browser_lock()`

    **ระยะ 2.1 เปลี่ยนจากล็อกรวมเป็นล็อกรายเครื่อง** ของเดิมใช้ `data/phone.lock`
    ไฟล์เดียวสำหรับมือถือทุกเครื่อง — เครื่อง A โพสต์อยู่ เครื่อง B ที่ว่างเปล่า
    ก็เริ่มไม่ได้ ซื้อมือถือเพิ่มแล้วไม่ได้ความเร็วเพิ่มเลย ตอนนี้แยกเป็น
    `data/locks/phone-<serial>.lock` คนละเครื่องจึงทำงานขนานกันได้จริง

    **serial บังคับใส่** และใส่ค่าว่างไม่ได้ — ตั้งใจให้พังเสียงดังตรงจุดที่เรียก
    ถ้าปล่อยให้ไม่ใส่ได้ คนที่ลืมใส่จะไปล็อกคนละดอกกับคนที่ใส่ แล้วสองงานจะแตะจอ
    เครื่องเดียวกันพร้อมกันโดยไม่มีใครรู้ตัว — พังเงียบแบบที่หาสาเหตุยากที่สุด

    timeout สั้นกว่าฝั่งเบราว์เซอร์ (10 นาที) เพราะงานมือถือหนึ่งกลุ่มใช้เวลา
    ราวหนึ่งถึงสองนาที รอเกินสิบนาทีแปลว่ามีอะไรค้าง ไม่ใช่แค่คิวยาว

    **ใครใช้ล็อกนี้บ้าง** (ต้องครบทุกฝั่งถึงจะกันได้จริง):
      · `fb_auto_post.PostRunner` — ทั้ง 4 ทาง (โพสต์ · ตามเก็บ · เก็บยอด · แก้รูป)
        ขอด้วย timeout สั้น 120 วินาที ไม่ได้ก็ล้มพร้อมข้อความ ไม่ค้างเงียบ
      · `fb_engage` — ขอ**ทีละโพสต์แล้วปล่อย** ไม่ถือยาวทั้งรอบ งานของผู้ใช้
        จะได้ไม่ต้องรอเกินหนึ่งโพสต์ (~40 วินาที)

    ฝั่ง fb_engage ยังถาม app.py ผ่าน HTTP ควบคู่ไปด้วยเป็นด่านที่สอง เพราะล็อกนี้
    บอกได้แค่ "มีคนถืออยู่ไหม" แต่ไม่รู้ว่าคิวงานฝั่งโน้นยาวแค่ไหน
    """
    if not str(serial or "").strip():
        raise ValueError(
            "phone_lock ต้องระบุ serial ของมือถือ — ล็อกแยกรายเครื่องแล้ว "
            "ถ้าไม่ระบุจะกลายเป็นสองงานแตะจอเครื่องเดียวกันพร้อมกันโดยไม่มีใครกัน"
        )
    lock_file, info_file = _phone_lock_paths(serial)
    return _resource_lock(
        lock_file, info_file, timeout=timeout, poll=poll, label=label,
        busy=PhoneBusy, what=f"มือถือ {serial}",
    )


def who_holds_phone(serial: str) -> str:
    """ข้อความบอกว่าใครถือล็อกมือถือเครื่องนั้นอยู่ — ใช้แจ้งผู้ใช้เท่านั้น"""
    return _read_info(_phone_lock_paths(serial)[1])


# ------------------------------------------- ล็อกโปรไฟล์บอท (แยกรายโปรไฟล์)

def _bot_lock_paths(profile_id: str) -> tuple[Path, Path]:
    key = _lock_key(profile_id)
    return LOCK_DIR / f"bot-{key}.lock", LOCK_DIR / f"bot-{key}.info"


def bot_lock(profile_id: str, timeout: float = 120.0, poll: float = 1.0, label: str = ""):
    """กันไม่ให้สองโปรเซสยุ่งกับโฟลเดอร์โปรไฟล์บอทตัวเดียวกันพร้อมกัน

    เรื่องเดียวกับ `browser_lock` เป๊ะ แต่คนละโปรไฟล์: Chrome เปิด user-data-dir
    เดียวกันซ้อนกันไม่ได้ และการ "รีเฟรชจากโปรไฟล์จริง" คือการเขียนทับไฟล์คุกกี้
    ทั้งชุด ถ้าอีกฝั่งกำลังเปิดอยู่ = ล็อกอินพัง ต้องล็อกอินใหม่ทุกเว็บ

    ของเดิม `bot_profiles` กันด้วย `threading.Lock` ซึ่งกันได้แค่ในโปรเซสเดียว
    พอระยะ 3 แยก `post_app.py` ออกไปคนละพอร์ต จะมีสองโปรเซสที่สั่งเปิดบอทได้
    ล็อกในโปรเซสจะมองไม่เห็นกัน — ต้องเป็นล็อกระดับไฟล์เท่านั้น

    แยกรายโปรไฟล์เพราะ**บอทคนละตัวคือคนละโฟลเดอร์** จึงรันขนานกันได้จริง
    (นั่นคือเหตุผลทั้งหมดที่ทำฟาร์มบอท ถ้าใช้ล็อกรวมก็เท่ากับทิ้งของที่ทำไว้)

    timeout สั้น (2 นาที) เพราะงานพวกนี้เป็นการก๊อปไฟล์กับสั่งเปิด/ปิดโปรแกรม
    หลักวินาที รอเกินสองนาทีแปลว่ามีอะไรค้าง ควรบอกผู้ใช้ ไม่ใช่รอเงียบ
    """
    if not str(profile_id or "").strip():
        raise ValueError("bot_lock ต้องระบุ profile_id ของบอท")
    lock_file, info_file = _bot_lock_paths(profile_id)
    return _resource_lock(
        lock_file, info_file, timeout=timeout, poll=poll, label=label,
        busy=BotBusy, what=f"โปรไฟล์บอท {profile_id}",
    )


def who_holds_bot(profile_id: str) -> str:
    """ข้อความบอกว่าใครถือล็อกโปรไฟล์บอทตัวนั้นอยู่ — ใช้แจ้งผู้ใช้เท่านั้น"""
    return _read_info(_bot_lock_paths(profile_id)[1])


# --------------------------------------- ไฟล์ข้อมูลที่สองเซิร์ฟเวอร์เขียนร่วมกัน (ระยะ 2.2)

class DataBusy(RuntimeError):
    """ไฟล์ข้อมูลนั้นถูกอีกโปรเซสถืออยู่"""


def data_lock(name: str, timeout: float = 30.0, poll: float = 0.2, label: str = ""):
    """ล็อกไฟล์ข้อมูลหนึ่งไฟล์ — ใช้ตอนอ่าน-แก้-เขียน ข้ามโปรเซส

    timeout สั้นมาก (30 วินาที) เพราะงานพวกนี้คือแก้ JSON ไม่กี่ KB หลักมิลลิวินาที
    รอเกินครึ่งนาทีแปลว่ามีอะไรผิดปกติ ไม่ใช่คิวยาว
    """
    key = _lock_key(name)
    return _resource_lock(
        LOCK_DIR / f"data-{key}.lock", LOCK_DIR / f"data-{key}.info",
        timeout=timeout, poll=poll, label=label,
        busy=DataBusy, what=f"ไฟล์ {name}",
    )


# replace ทับไฟล์ที่คนอื่นเปิดอ่านค้างอยู่จะโดน WinError 5 — ลองซ้ำสั้นๆ พอ
# (0.02+0.04+... รวมราว 1.3 วินาที ผู้อ่านถือไฟล์แค่ระดับมิลลิวินาที)
_REPLACE_TRIES = 10
_REPLACE_WAIT = 0.02


def read_json(path: Path, default):
    """อ่าน JSON แบบไม่ล้ม — ไฟล์ยังไม่มีหรืออ่านไม่ออกก็คืนค่าตั้งต้น

    **ต้องลองซ้ำเมื่อเปิดไฟล์ไม่ได้** ระหว่างที่อีกโปรเซส replace ไฟล์ทับ จะมีช่วง
    สั้นๆ ที่เปิดไฟล์ปลายทางไม่ได้เลย (Windows ล็อกชื่อไฟล์ตอน rename) วัดจากของจริง:
    อ่าน 404,074 ครั้งระหว่างอีกฝั่งเขียนรัวๆ **ไม่มีไฟล์เสียสักครั้ง** แต่เปิดไม่ได้
    ชั่วขณะ 435 ครั้ง (0.108%)

    ถ้าคืนค่าตั้งต้นทันทีตอนนั้น จะกลายเป็นเรื่องใหญ่: `load_config` จะได้ {} แล้ว
    ถอยไปใช้ค่าปริยายทั้งชุด ผู้ใช้เห็นตั้งค่าตัวเองหายไปเฉยๆ และถ้ากดบันทึกต่อ
    ค่าจริงจะถูกทับหายถาวร — ล้มเงียบแบบที่แพงที่สุด
    """
    for attempt in range(_REPLACE_TRIES):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default                       # ยังไม่เคยมีไฟล์ = ค่าตั้งต้นจริงๆ
        except OSError:                          # อีกฝั่งกำลัง replace อยู่ รอแป๊บ
            time.sleep(_REPLACE_WAIT * (attempt + 1))
        except ValueError:                       # ไฟล์เสียจริง (ไม่ควรเกิดหลังเขียน atomic)
            return default
    return default


def write_json_atomic(path: Path, payload) -> None:
    """เขียน JSON แบบที่อีกโปรเซสไม่มีวันอ่านเจอครึ่งๆ

    เขียนลงไฟล์ชั่วคราวก่อนแล้วค่อย replace ทับ — replace บนไดรฟ์เดียวกันเป็น
    ปฏิบัติการเดียวจบ อีกฝั่งจึงเห็นได้แค่ "ของเก่าทั้งไฟล์" หรือ "ของใหม่ทั้งไฟล์"

    **ชื่อไฟล์ชั่วคราวต้องมี PID** ของเดิมทั้งสองเซิร์ฟเวอร์ใช้ชื่อ `<ชื่อ>.tmp`
    เหมือนกัน สองโปรเซสเขียนพร้อมกันจะทับไฟล์ชั่วคราวของกันเอง แล้ว replace
    ไฟล์ที่เขียนค้างครึ่งทางทับของจริง — เสียหายกว่า "อัปเดตหาย" มาก

    **ต้องลองซ้ำตอน replace** — Windows ไม่ยอมให้ rename ทับไฟล์ที่โปรเซสอื่น
    "เปิดค้างอยู่" แม้จะเปิดแค่อ่าน เพราะ open() ของ Python บน Windows ไม่ได้ขอ
    FILE_SHARE_DELETE ผลคือได้ PermissionError (WinError 5) เป็นครั้งคราวเมื่อ
    อีกฝั่งบังเอิญอ่านพอดี — วัดจากของจริงแล้ว: เขียน 120 รอบพร้อมอ่านรัวๆ เจอชนจริง

    ปล่อยให้ล้มไม่ได้ เพราะ clip_app จับ OSError แล้วแค่เขียน log ว่าบันทึกไม่ได้
    = ผู้ใช้กดตั้งค่าแล้วไม่ติด โดยไม่มีอะไรบอกบนหน้าจอ ส่วน ApprovalStore ไม่จับเลย
    ผู้อ่านถือไฟล์แค่ระดับมิลลิวินาที ลองซ้ำสั้นๆ จึงผ่านเสมอ
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        last: OSError | None = None
        for attempt in range(_REPLACE_TRIES):
            try:
                temporary.replace(path)
                return
            except PermissionError as error:      # มีคนเปิดไฟล์ปลายทางค้างอยู่
                last = error
                time.sleep(_REPLACE_WAIT * (attempt + 1))
        raise OSError(
            f"เขียน {path.name} ไม่สำเร็จ — มีโปรเซสอื่นเปิดไฟล์ค้างนานผิดปกติ ({last})"
        ) from last
    finally:
        # replace สำเร็จแล้วไฟล์นี้จะไม่มีอยู่ ที่เก็บกวาดคือกรณีเขียนแล้วล้มกลางทาง
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def update_json(path: Path, mutate, default=None, timeout: float = 30.0, label: str = ""):
    """อ่าน-แก้-เขียน ไฟล์ JSON ให้จบเป็นชิ้นเดียว **ข้ามโปรเซส**

    ของเดิมทั้ง app.py และ clip_app.py ต่างคนต่างอ่านแล้วเขียนทับไฟล์เดียวกัน
    โดยกันแค่ `threading.Lock` ซึ่งมองไม่เห็นกันข้ามโปรเซส ผลคือค่าที่อีกฝั่ง
    เพิ่งบันทึกหายไปเงียบๆ (config.json กับ approvals.json เจอทั้งคู่)

    `mutate` แก้ค่าที่ได้ในที่แล้วคืน None หรือจะคืนค่าใหม่ทั้งก้อนก็ได้
    """
    with data_lock(path.name, timeout=timeout, label=label or f"แก้ {path.name}"):
        current = read_json(path, default)
        changed = mutate(current)
        payload = current if changed is None else changed
        write_json_atomic(path, payload)
        return payload


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
