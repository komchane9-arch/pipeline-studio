"""Pipeline Studio — เว็บแอปใหม่ตามผังลายมือ 6 หน้า (สร้างแยก ไม่แตะโปรเจกต์เดิม)

โครงตามผัง:
  ซ้าย  = Device no. + จอมือถือ (A)
  ขวา   = แท็บ Process (B): ① Input ② Process ③ Release ④ $ Publish
          เปิดทีละแท็บ พื้นที่ใครพื้นที่มัน (C)
  เฟือง = ตั้งค่า (D): Gemini API + Video setting + Image model

หลักที่ยกมาจากโปรเจกต์เดิม (คัดลอกไฟล์มา ไม่ผูกกลับไป):
  - flow_driver / flow_pipeline / flow_worker / tiktok_post / scrcpy_control
  - เก็บ API key ด้วย DPAPI ผูกกับผู้ใช้ Windows คนปัจจุบัน
  - คำสั่ง ADB ทุกตัวทำใน thread (asyncio.to_thread) ห้ามบล็อก event loop
  - log ทุกหน้า: ใกล้เต็ม 90% ของเพดาน → save เป็นไฟล์เก่าแล้วเริ่มไฟล์ใหม่
    (ตามผังหน้า Input ข้อ [log])

จอมือถือใช้ screencap เป็นภาพนิ่งรีเฟรชแทนสตรีม H.264 ของโปรเจกต์เดิม —
หน้าที่ของจอในผังนี้คือ "ดูสถานะ + เทรนตำแหน่งกด" ซึ่งภาพวินาทีละเฟรมพอ
และตัดปัญหา screenrecord ค้างสะสม (เคยทำสตรีมช้าจาก 0.5 วิเป็น 25 วิ) ทิ้งทั้งก้อน
"""

from __future__ import annotations

import asyncio
import atexit
import base64
import contextlib
import ctypes
import dataclasses
import json
import hashlib
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI, HTTPException, Request, UploadFile, File, Form,
    WebSocket, WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

import access_control
import bot_profiles
import devices as device_book
import studio_shared
import fb_auto_post
import fb_backup
import fb_comment_guard
import fb_pending
import fb_phone_clean
import fb_preflight
import fb_screen
import fb_report
import fb_routine
import facebook_group_post
import qr_code
import telegram_bot
import scrcpy_control
from shopee_service import shopee_collect

# พอร์ตย้ายได้ด้วย STUDIO_PORT — มีไว้เพื่อรัน "สำเนาโค้ดอีกชุด" (git worktree)
# ทดสอบพร้อมกับตัวจริงโดยไม่แย่งพอร์ตและไม่แย่ง data/ กัน:
#     set STUDIO_PORT=8966 && set STUDIO_DATA_DIR=data-wt && python app.py
# ต้องย้ายพร้อมกันทั้งสองอย่างเสมอ ไม่งั้นสำเนาจะไปเขียนทับข้อมูลของตัวจริง
PORT = int(os.environ.get("STUDIO_PORT", "") or 8866)

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

# data/ ย้ายที่ได้ด้วย STUDIO_DATA_DIR — ทดสอบโดยไม่แตะของจริง:
#     set STUDIO_DATA_DIR=data-test && python app.py
# มีเพราะเคยมีสคริปต์ทดสอบลบโปรไฟล์บอท Bot1..Bot10 ของจริงหายถาวร (13 ส.ค. 2026)
_data_name = os.environ.get("STUDIO_DATA_DIR", "data").strip() or "data"
DATA_DIR = Path(_data_name) if Path(_data_name).is_absolute() else BASE_DIR / _data_name


def _compute_version() -> str:
    """เวอร์ชัน = ลายนิ้วมือของไฟล์หน้าเว็บจริง ไม่ใช่เลขที่ต้องแก้เอง

    เดิมเป็นค่าคงที่ที่ต้อง bump ให้ตรงกัน 2-3 ที่ พอหลายแชทแก้พร้อมกันก็หลุด
    (13 ส.ค. 2026 ชนกัน 3 รอบใน 1 วัน: 56 -> 57 -> 60) และ "ลืมรีสตาร์ต"
    ก็ทำให้ขึ้นแบนเนอร์ผิดรุ่นทั้งที่โค้ดใหม่แล้ว

    คิดจากเนื้อไฟล์ที่เบราว์เซอร์แคชจริง — แก้ไฟล์ไหนเวอร์ชันขยับเอง
    หน้าเว็บกับเซิร์ฟเวอร์จึงตรงกันโดยธรรมชาติ แก้มือให้ผิดไม่ได้อีก
    """
    digest = hashlib.sha1()
    # ไล่ทุกไฟล์หน้าเว็บที่เบราว์เซอร์โหลดจริง เรียงชื่อให้ผลคงที่ทุกรอบ
    # ใช้ glob แทนรายชื่อตายตัว เพราะระยะ 2.3 แยก app.js เป็น core/phone/post/video/boot
    # ถ้าต้องเติมชื่อใหม่เข้าลิสต์เอง วันหนึ่งจะลืม แล้วกลับไปเป็น "แก้แล้วเวอร์ชันไม่ขยับ"
    # (นับชื่อไฟล์ด้วย — เปลี่ยนชื่อไฟล์ก็ต้องนับว่าเป็นคนละรุ่น)
    for path in sorted(WEB_DIR.glob("*.*")):
        if path.suffix.lower() not in (".html", ".js", ".css"):
            continue
        try:
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
        except OSError:
            pass
    return digest.hexdigest()[:8]


APP_VERSION = _compute_version()
LOG_DIR = DATA_DIR / "logs"
UPLOAD_DIR = DATA_DIR / "uploads"
CONFIG_FILE = DATA_DIR / "config.json"
GEMINI_KEY_FILE = DATA_DIR / "gemini_api_key.bin"
POSITION_DIR = DATA_DIR / "publish_positions"
FB_POST_DIR = studio_shared.POST_IMAGES      # รูปที่รับมาจาก Telegram
                                             # (ย้ายไป Google Drive แล้ว)

for directory in (DATA_DIR, LOG_DIR, UPLOAD_DIR, POSITION_DIR, FB_POST_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Pipeline Studio")

# ทะเบียนอุปกรณ์ที่ขอเข้าใช้จากมือถือ (เครื่องหลักอนุมัติทีละเครื่อง)
access_store = access_control.AccessStore(DATA_DIR / "access_devices.json")
class _RevalidateStatic(StaticFiles):
    """บังคับให้เบราว์เซอร์ถามก่อนใช้ไฟล์ในแคชทุกครั้ง

    หน้าเว็บโหลด boot.js?v=<แฮช> แต่โมดูลที่ boot.js import ต่อ (core/phone/post/video)
    ไม่มี ?v= ต่อท้าย ถ้าปล่อยให้เบราว์เซอร์เดาอายุไฟล์เอง จะได้ของใหม่ปนของเก่า
    (เช่น core.js ใหม่ + post.js เก่า) ซึ่งพังแบบเงียบและไล่หาสาเหตุยากมาก

    no-cache ไม่ได้แปลว่าห้ามแคช — แคชได้แต่ต้องถามก่อนใช้ ถ้าไฟล์ไม่เปลี่ยนได้ 304 ก็ยังเร็ว
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", _RevalidateStatic(directory=WEB_DIR), name="static")

_config_lock = threading.Lock()


# ------------------------------------------------------------------ DPAPI
# ยกมาจากโปรเจกต์เดิมตรงตัว — เข้ารหัสผูกกับบัญชี Windows ปัจจุบัน


class DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _windows_dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("การบันทึก API Key รองรับเฉพาะ Windows")
    source_buffer = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    destination = DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
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


CLAUDE_KEY_FILE = DATA_DIR / "claude_api_key.bin"


def _save_key(path: Path, key: str) -> None:
    # เขียนผ่าน .tmp แล้ว replace — โปรเซสดับกลางคันต้องไม่เหลือไฟล์ key ครึ่งเดียว
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(_windows_dpapi(key.encode("utf-8")))
    temporary.replace(path)


def _load_key(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return _windows_dpapi(path.read_bytes(), decrypt=True).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def save_gemini_key(key: str) -> None:
    _save_key(GEMINI_KEY_FILE, key)


def load_gemini_key() -> str | None:
    return _load_key(GEMINI_KEY_FILE)


# โทเคนบอทเก็บเข้ารหัสเหมือนคีย์ Gemini — ใครได้โทเคนไปคุมบอทเราได้ทันที
TELEGRAM_TOKEN_FILE = DATA_DIR / "telegram_token.bin"
CLIP_TOKEN_FILE = DATA_DIR / "telegram_clip_token.bin"


def save_telegram_token(token: str) -> None:
    _save_key(TELEGRAM_TOKEN_FILE, token)


def save_clip_token(token: str) -> None:
    _save_key(CLIP_TOKEN_FILE, token)


def load_clip_token() -> str | None:
    """บอทแยกสำหรับสายเจนคลิป — ไม่มีก็ถอยไปใช้บอทหลัก

    ทำไมต้องแยกโทเคน ไม่ใช่แยกแค่หัวข้อในแชทเดียว:
      getUpdates ของบอทหนึ่งตัวมีตัวอ่านได้ตัวเดียว งานโพสต์ Facebook กับงาน
      อนุมัติคลิปจึงเบียดกันในแชทเดียว — คนละบอทคือคนละคิว แยกขาดจริง
    """
    return _load_key(CLIP_TOKEN_FILE)


def load_telegram_token() -> str | None:
    return _load_key(TELEGRAM_TOKEN_FILE)


# ------------------------------------------------------------------- config

DEFAULT_CONFIG: dict[str, Any] = {
    # ตั้งค่า (หน้า D)
    "settings": {
        "video_mode": "frame",          # frame | common  (block ให้ติ๊กเลือก)
        "frame": "9:16",                # 9:16 | 16:9
        "video_model": "veo31_lite_lower",
        "omni_duration": 8,             # 4 | 6 | 8 | 10 (เฉพาะ Omni Flash)
        "image_model": "nano_banana_2", # nano_banana_2 | nano_banana_pro
    },
    # Input ①: สินค้าหลายรายการ
    "excel": {
        "source": "file",               # file | online  (เลือกได้แค่ 1)
        "file_path": "",
        "online_url": "",
        "loop_rounds": 1,               # ทำวนซ้ำสินค้าใน list กี่รอบ
    },
    # Input ②: สินค้าเดียวลองเทส
    "single": {
        "name": "",
        "detail": "",
        "image": "",                    # path ใน data/uploads
        "strip_text": False,            # รูปมีตัวอักษร → ให้ลบออกเหลือแต่รูป
    },
    # GEMS (ผังสั่งย้ายหัวข้อนี้มาไว้หน้า Input)
    "gems": [],                         # [{id, name, link, probe: {seconds, scenes}}]
    "gems_selected": "",
    # Release ③
    "release": {
        "trim_silence": True,
        "subtitle": "none",             # none | thai | thai_english
        "headline_ai": False,
        "headline_text": "",
    },
    # Publish $ — คิว 1-6 คือ "ขั้นตอนการกด" บนมือถือ (ผู้ใช้ยืนยันแล้ว)
    # action: train (เทรนตำแหน่ง) | shopee | lazada | hashtags
    "publish_queue": [],                # [{id, name, action, value}] สูงสุด 6
    "products": [],                     # รายการสินค้าที่อ่านจาก Excel
    "device_names": {},                 # {serial: ชื่อที่ผู้ใช้ตั้ง} โชว์ใน dropdown
    # โพสต์ลงกลุ่ม Facebook อัตโนมัติ (รับงานจาก Telegram)
    "facebook": {
        "serial": "",                   # ว่าง = ใช้เครื่องแรกที่พร้อมใช้งาน
        "gap_min": 15,                  # เว้นระยะระหว่างกลุ่มแบบสุ่ม (วินาที)
        "gap_max": 20,
        # True = ครบแคปชัน+รูปแล้วลงมือเลย ไม่ต้องรอกดยืนยันในแชท
        # ค่าเริ่มต้นเป็น False เพราะโพสต์แล้วเรียกคืนไม่ได้ ต้องให้คนกดยืนยันก่อน
        "auto_start": False,
    },
}

PUBLISH_ACTIONS = {"train", "shopee", "lazada", "hashtags"}

VIDEO_MODELS = {
    "omni_flash": "Omni Flash",
    "veo31_lite": "Veo 3.1 - Lite",
    "veo31_fast": "Veo 3.1 - Fast",
    "veo31_quality": "Veo 3.1 Quality",
    "veo31_lite_lower": "Veo 3.1 - Lite (Lower priority)",
}
# ติ๊ก Common ingredients แล้วเหลือให้เลือกแค่ 2 ตัวตามผัง
COMMON_MODELS = {"veo31_lite_lower", "omni_flash"}
IMAGE_MODELS = {"nano_banana_2": "Nano banana 2", "nano_banana_pro": "Nano banana pro"}


def load_config() -> dict:
    with _config_lock:
        try:
            stored = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def save_config(config: dict) -> None:
    """บันทึกตั้งค่า — ต้องล็อก**ข้ามโปรเซส** เพราะ clip_app.py ก็เขียนไฟล์นี้

    ของเดิมกันแค่ `_config_lock` ซึ่งเป็น threading.Lock มองไม่เห็น clip_app.py
    เลย และทั้งสองฝั่งยังใช้ชื่อไฟล์ชั่วคราว `config.tmp` ชื่อเดียวกันด้วย
    เขียนพร้อมกันเมื่อไรมีสิทธิ์ได้ไฟล์ที่เขียนค้างครึ่งทางทับของจริง

    ยังเหลือช่องที่แคบลงมากแต่ไม่หมด: หน้าเว็บอ่านค่าไปตอนหนึ่ง ผู้ใช้กดบันทึก
    ทีหลัง ถ้าระหว่างนั้น clip_app แก้คีย์ของมัน ค่านั้นจะถูกทับ — ปิดสนิทต้อง
    ให้ทุก endpoint แก้ทีละคีย์ผ่าน update_json ซึ่งเป็นงานคนละก้อน
    """
    with _config_lock:
        studio_shared.update_json(
            CONFIG_FILE, lambda _stored: config, default={},
            label="บันทึกตั้งค่าจากหน้าเว็บ",
        )


# ------------------------------------------------------------------- logs
# ตามผัง: ทุกแท็บมี log ของตัวเอง ใกล้เต็ม 90% → save แล้วเริ่มไฟล์ใหม่

LOG_LIMIT_BYTES = 200 * 1024
LOG_TABS = {"input", "gems", "gen_pic", "gen_video", "judge", "release", "publish"}
_log_lock = threading.Lock()


def log_path(tab: str) -> Path:
    return LOG_DIR / f"{tab}.log"


def append_log(tab: str, message: str) -> None:
    if tab not in LOG_TABS:
        raise ValueError(f"ไม่รู้จัก log ของแท็บ {tab}")
    line = f"{datetime.now():%H:%M:%S} {message}\n"
    with _log_lock:
        path = log_path(tab)
        # เกิน 90% ของเพดานแล้ว → เก็บไฟล์เดิมไว้พร้อม timestamp แล้วเริ่มใหม่
        if path.is_file() and path.stat().st_size >= LOG_LIMIT_BYTES * 0.9:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path.replace(LOG_DIR / f"{tab}-{stamp}.log")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def read_log(tab: str, tail: int = 60) -> list[str]:
    path = log_path(tab)
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-tail:]


# -------------------------------------------------------------------- ADB


def _find_adb() -> str:
    """หา adb.exe — path ที่รู้จักมาก่อน PATH

    บทเรียนโปรเจกต์เดิม: PATH เคยมี adb v1.0.32 เก่าค้าง แล้วไล่ฆ่า server
    กับ v1.0.41 จนสั่งมือถือไม่ได้ จึงเลือกตัวที่ควบคุมได้ก่อนเสมอ
    """
    for candidate in (
        BASE_DIR / "tools/platform-tools/adb.exe",
        Path("C:/project/2.Auto gen Video/7.web app/tools/platform-tools/adb.exe"),
        Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe",
        Path("C:/platform-tools/adb.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("adb")
    if found:
        return found
    raise RuntimeError(
        "ไม่พบ adb.exe — ติดตั้ง platform-tools แล้ววางที่ C:/platform-tools "
        "หรือ tools/platform-tools ในโปรเจกต์"
    )


ADB = _find_adb()


def run_adb(*args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [ADB, *args], capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as error:
        # แปลงเป็นข้อความอ่านได้ — ปล่อย raw จะเด้ง 500 traceback ใส่หน้าเว็บ
        raise RuntimeError(
            f"คำสั่ง adb ไม่ตอบภายใน {timeout} วินาที (มือถืออาจค้างหรือหลุด)"
        ) from error


def adb_message(result: subprocess.CompletedProcess) -> str:
    out = result.stdout.decode("utf-8", errors="replace").strip()
    err = result.stderr.decode("utf-8", errors="replace").strip()
    return " ".join(part for part in (out, err) if part)[:300]


def list_devices() -> list[dict]:
    """ทุกเครื่องรวม unauthorized/offline — ซ่อนไปเฉยๆ ผู้ใช้จะไม่รู้ว่าติดอะไร"""
    result = run_adb("devices", "-l", timeout=10)
    if result.returncode != 0:
        raise RuntimeError(f"adb devices ล้มเหลว: {adb_message(result)}")
    devices = []
    for line in result.stdout.decode("utf-8", errors="replace").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or line.startswith("*"):
            continue
        state = parts[1]
        model = next(
            (p.split(":", 1)[1] for p in parts if p.startswith("model:")), ""
        ) or next(
            (p.split(":", 1)[1] for p in parts if p.startswith("product:")), ""
        ) or "Android"
        note = ""
        if state == "unauthorized":
            note = "ปลดล็อกจอแล้วกดอนุญาต USB debugging บนมือถือ"
        elif state != "device":
            note = f"สถานะ {state} — เสียบสายใหม่หรือเช็ค Wireless debugging"
        devices.append({
            "serial": parts[0],
            "model": model.replace("_", " "),
            "state": state,
            "ready": state == "device",
            "note": note,
        })
    return devices


# ขนาดจอเปลี่ยนแทบไม่เกิด — cache ไว้ ไม่ต้องยิง `wm size` ทุกครั้งที่แตะ
_screen_size_cache: dict[str, tuple[int, int]] = {}


def screen_size(serial: str) -> tuple[int, int]:
    if serial in _screen_size_cache:
        return _screen_size_cache[serial]
    result = run_adb("-s", serial, "shell", "wm", "size", timeout=10)
    # เครื่องที่ตั้ง Override size จอจริงคือค่านั้น ไม่ใช่ Physical
    # (จับตัวแรกเฉยๆ จะได้ Physical แล้วพิกัดแตะเพี้ยนทั้งจอ)
    match = re.search(rb"Override size:\s*(\d{3,5})x(\d{3,5})", result.stdout)
    if not match:
        match = re.search(rb"(\d{3,5})x(\d{3,5})", result.stdout)
    size = (int(match.group(1)), int(match.group(2))) if match else (1080, 1920)
    _screen_size_cache[serial] = size
    return size


_serial_re = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")

# เช็คว่าเชื่อมต่ออยู่จริง — cache สั้นๆ กันยิง adb devices ถี่เกิน
_connected_cache: dict = {"at": 0.0, "serials": set()}
_connected_lock = threading.Lock()


def clean_serial(serial: str, must_be_connected: bool = False) -> str:
    serial = serial.strip()
    if not _serial_re.match(serial):
        raise HTTPException(status_code=400, detail="serial ไม่ถูกต้อง")
    if must_be_connected:
        with _connected_lock:
            if time.time() - _connected_cache["at"] > 3:
                _connected_cache["serials"] = {
                    d["serial"] for d in list_devices() if d["ready"]
                }
                _connected_cache["at"] = time.time()
            if serial not in _connected_cache["serials"]:
                raise HTTPException(
                    status_code=404,
                    detail=f"มือถือ {serial} ไม่ได้เชื่อมต่ออยู่ — กดรีเฟรชรายการอุปกรณ์",
                )
    return serial


# --------------------------------------------------------------- ตำแหน่งกด
# เทรนตำแหน่งการกดในมือถือ (หน้า Publish) — เก็บเป็นสัดส่วนจอ ต่อเครื่องต่อคิว


def position_file(serial: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", serial)[:80]
    return POSITION_DIR / f"{safe}.json"


def load_positions(serial: str) -> dict:
    try:
        return json.loads(position_file(serial).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_positions(serial: str, positions: dict) -> None:
    path = position_file(serial)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(positions, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


# -------------------------------------------------------------------- หน้าเว็บ


@app.get("/")
async def index() -> Response:
    """เสิร์ฟหน้าแรกพร้อมใส่เวอร์ชันให้อัตโนมัติ

    ไฟล์บนดิสก์เขียน ?v=__VERSION__ ไว้ แล้วแทนค่าตอนเสิร์ฟด้วย APP_VERSION
    ซึ่งคิดจากเนื้อไฟล์ชุดเดียวกัน — หน้าเว็บกับเซิร์ฟเวอร์จึงตรงกันเสมอ
    ไม่มีทางหลุดเหมือนตอนที่ต้อง bump เลขเองทีละที่
    """
    # คิดแฮชสดจากดิสก์ ไม่ใช้ APP_VERSION ที่ค้างตั้งแต่ตอนเซิร์ฟเวอร์เริ่ม
    # ต่างกันเมื่อไร = "แก้ไฟล์แล้วลืมรีสตาร์ต" ซึ่งเป็นเคสที่แบนเนอร์ต้องจับให้ได้
    # (ถ้าใช้ตัวเดียวกันทั้งคู่ มันจะตรงกันเสมอ แล้วแบนเนอร์ก็ไร้ประโยชน์)
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return Response(
        content=html.replace("__VERSION__", _compute_version()),
        media_type="text/html; charset=utf-8",
        # no-store — โปรเจกต์เดิมโดน Chrome cache หน้า HTML จนเวอร์ชันไม่ตรงมาแล้ว
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


@app.get("/api/gemini-quota")
async def gemini_quota_today() -> dict:
    """โควตา Gemini ชั้นฟรีที่ใช้ไปวันนี้ (ผู้ใช้สั่ง 26 ส.ค. 2026)

    **Google ไม่มีที่ให้ถามว่าเหลือกี่ครั้ง** ตัวเลขที่ได้จึงมาจากการนับเองว่า
    ระบบนี้ยิงไปกี่ครั้ง ส่วนเพดานจะรู้ก็ต่อเมื่อโดนปฏิเสธเพราะหมดโควตาแล้ว
    (คำตอบ 429 ของ Google มีเพดานจริงติดมาด้วย)

    ห้ามเดาตัวเลข "เหลืออีกเท่าไร" ให้เอง — เลขที่เดาแล้วผิดอันตรายกว่าไม่มีเลข
    เพราะคนจะวางแผนว่าจะเจนได้อีกกี่คลิปตามมัน
    """
    try:
        import gemini_quota
        data = gemini_quota.today()
        data["history"] = gemini_quota.history(7)
        return {"ok": True, **data}
    except Exception as error:                               # noqa: BLE001
        return {"ok": False, "detail": str(error), "rows": [], "total": 0, "dry": []}


@app.get("/api/system")
async def system_info() -> dict:
    return {
        "app_version": APP_VERSION,
        "gemini_key_saved": GEMINI_KEY_FILE.is_file(),
        "video_models": VIDEO_MODELS,
        "common_models": sorted(COMMON_MODELS),
        "image_models": IMAGE_MODELS,
    }


# ---------------------------------------------------------------- ตั้งค่า (D)


@app.get("/api/config")
async def get_config() -> dict:
    config = load_config()
    config["gemini_key_saved"] = GEMINI_KEY_FILE.is_file()
    return config


@app.post("/api/settings")
async def update_settings(request: Request) -> dict:
    payload = await request.json()
    config = load_config()
    settings = config["settings"]
    mode = payload.get("video_mode", settings["video_mode"])
    if mode not in {"frame", "common"}:
        raise HTTPException(status_code=400, detail="โหมดวิดีโอไม่ถูกต้อง")
    model = payload.get("video_model", settings["video_model"])
    if model not in VIDEO_MODELS:
        raise HTTPException(status_code=400, detail="ไม่รู้จักโมเดลวิดีโอ")
    # ติ๊ก Common แล้วโมเดลต้องอยู่ในกลุ่มที่ผังอนุญาตเท่านั้น
    if mode == "common" and model not in COMMON_MODELS:
        raise HTTPException(
            status_code=400,
            detail="โหมด Common ingredients เลือกได้แค่ Veo 3.1 - Lite (Lower priority) หรือ Omni Flash",
        )
    frame = payload.get("frame", settings["frame"])
    if frame not in {"9:16", "16:9"}:
        raise HTTPException(status_code=400, detail="สัดส่วนภาพไม่ถูกต้อง")
    duration = int(payload.get("omni_duration", settings["omni_duration"]))
    if duration not in {4, 6, 8, 10}:
        raise HTTPException(status_code=400, detail="ความยาวต้องเป็น 4/6/8/10 วินาที")
    image_model = payload.get("image_model", settings["image_model"])
    if image_model not in IMAGE_MODELS:
        raise HTTPException(status_code=400, detail="ไม่รู้จักโมเดลรูป")
    config["settings"] = {
        "video_mode": mode, "frame": frame, "video_model": model,
        "omni_duration": duration, "image_model": image_model,
    }
    save_config(config)
    return {"ok": True, "settings": config["settings"]}


@app.post("/api/gemini-key")
async def set_gemini_key(request: Request) -> dict:
    payload = await request.json()
    key = str(payload.get("key", "")).strip()
    if payload.get("clear"):
        GEMINI_KEY_FILE.unlink(missing_ok=True)
        return {"ok": True, "saved": False}
    if len(key) < 20:
        raise HTTPException(status_code=400, detail="API Key สั้นเกินไป")
    await asyncio.to_thread(save_gemini_key, key)
    return {"ok": True, "saved": True}


@app.post("/api/claude-key")
async def set_claude_key(request: Request) -> dict:
    """Claude API Key สำหรับขั้น Judge (ผู้ใช้เลือกเชื่อมผ่าน API)"""
    payload = await request.json()
    key = str(payload.get("key", "")).strip()
    if payload.get("clear"):
        CLAUDE_KEY_FILE.unlink(missing_ok=True)
        return {"ok": True, "saved": False}
    if not key.startswith("sk-ant-"):
        raise HTTPException(status_code=400, detail="Claude API Key ต้องขึ้นต้นด้วย sk-ant-")
    await asyncio.to_thread(_save_key, CLAUDE_KEY_FILE, key)
    return {"ok": True, "saved": True}


@app.post("/api/claude-key/test")
async def test_claude_key() -> dict:
    key = await asyncio.to_thread(_load_key, CLAUDE_KEY_FILE)
    if not key:
        return {"ok": False, "detail": "ยังไม่ได้บันทึก Claude API Key"}

    def probe() -> dict:
        import urllib.request

        body = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "ping"}],
        }).encode("utf-8")
        request_ = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urllib.request.urlopen(request_, timeout=20) as response:
                json.loads(response.read().decode("utf-8"))
            return {"ok": True, "detail": "ใช้งานได้"}
        except Exception as error:
            return {"ok": False, "detail": f"เรียกไม่ผ่าน: {error}"}

    return await asyncio.to_thread(probe)


@app.post("/api/gemini-key/test")
async def test_gemini_key() -> dict:
    """ไฟสถานะ 'พร้อมใช้งาน' — ยิงเรียกรายการโมเดลจริง ไม่ใช่แค่เช็คว่ามีไฟล์"""
    key = await asyncio.to_thread(load_gemini_key)
    if not key:
        return {"ok": False, "detail": "ยังไม่ได้บันทึก API Key"}

    def probe() -> dict:
        import urllib.request

        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": key},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
                count = len(data.get("models", []))
                return {"ok": True, "detail": f"ใช้งานได้ — เห็น {count} โมเดล"}
        except Exception as error:
            return {"ok": False, "detail": f"เรียกไม่ผ่าน: {error}"}

    return await asyncio.to_thread(probe)


# ------------------------------------------------------------------ Input ①②


@app.post("/api/excel")
async def update_excel(request: Request) -> dict:
    payload = await request.json()
    config = load_config()
    source = payload.get("source", config["excel"]["source"])
    if source not in {"file", "online"}:
        raise HTTPException(status_code=400, detail="เลือกได้แค่ Excel file หรือ Sheet online")
    rounds = int(payload.get("loop_rounds", config["excel"]["loop_rounds"]))
    config["excel"] = {
        "source": source,
        "file_path": str(payload.get("file_path", config["excel"]["file_path"])),
        "online_url": str(payload.get("online_url", config["excel"]["online_url"])),
        "loop_rounds": max(1, min(999, rounds)),
    }
    save_config(config)
    return {"ok": True, "excel": config["excel"]}


# สเปกไฟล์ Excel จริงของผู้ใช้ — ยกจาก extension autogen เดิม (sidepanel/app.js:62-69)
# ชื่อรุ่นอยู่ใต้ header "รุ่น" (ปกติคอลัมน์ E) และสเปก 13 หมวดอยู่ N–Z
SPEC_FIELDS = [
    "หน้าจอ", "ชิปเซ็ต / CPU / GPU", "RAM / ความจุ", "กล้องหลัง", "กล้องหน้า",
    "วิดีโอ", "แบตเตอรี่", "การชาร์จ", "เครือข่าย / SIM", "การเชื่อมต่อ",
    "OS / UI (ละเอียด)", "วัสดุ / การกันน้ำ", "เซ็นเซอร์ / ระบบเสียง / จุดเด่น",
]
FALLBACK_MODEL_COL = 4    # คอลัมน์ E
FALLBACK_SPEC_COL0 = 13   # คอลัมน์ N เป็นต้นไป
HEADER_SCAN_ROWS = 10     # หา header แค่ 10 แถวแรกต่อชีต (พฤติกรรมเดียวกับของเดิม)


def _norm_header(value) -> str:
    return " ".join(str(value or "").split())


def _cell(row: list, col: int) -> str:
    """ค่าเซลล์เป็นข้อความ — None/หลุดขอบคืนสตริงว่าง ไม่ใช่ 'None'"""
    if col >= len(row) or row[col] is None:
        return ""
    return str(row[col]).strip()


def parse_product_rows(sheets: list[list[list]]) -> tuple[list[dict], str]:
    """แปลงตาราง (ทุกชีต) เป็นรายการสินค้า — ใช้ร่วมกันทั้ง .xlsx และ CSV online

    ไล่หาแถว header ที่มีคำว่า "รุ่น" เอง (ไฟล์จริง header ไม่ใช่แถว 1 เสมอ)
    แล้ว map สเปก 13 หมวดตามชื่อ header หมวดที่ไม่เจอ fallback ตำแหน่ง N–Z
    detail ประกอบเป็น "หมวด: ค่า" ต่อบรรทัด แบบเดียวกับ buildSpecText ของเดิม
    """
    for sheet in sheets:
        header_index = -1
        model_col = -1
        for row_index, row in enumerate(sheet[:HEADER_SCAN_ROWS]):
            cells = [_norm_header(cell) for cell in row]
            if "รุ่น" in cells:
                header_index, model_col = row_index, cells.index("รุ่น")
                break
            partial = next((i for i, c in enumerate(cells) if "รุ่น" in c), -1)
            if partial >= 0:
                header_index, model_col = row_index, partial
                break
        if header_index < 0:
            continue

        header = [_norm_header(cell) for cell in sheet[header_index]]
        if model_col < 0:
            model_col = FALLBACK_MODEL_COL
        spec_cols: list[int] = []
        for field_index, field in enumerate(SPEC_FIELDS):
            found = next(
                (
                    i for i, cell in enumerate(header)
                    if cell and (field in cell or cell in field)
                ),
                FALLBACK_SPEC_COL0 + field_index,
            )
            spec_cols.append(found)

        rows: list[dict] = []
        seen: set[str] = set()
        duplicates = 0
        for row in sheet[header_index + 1:]:
            name = _cell(row, model_col)
            if not name:
                continue
            if name in seen:
                duplicates += 1     # รุ่นซ้ำในไฟล์ — เก็บแถวแรก กันเผาเครดิตซ้ำ
                continue
            seen.add(name)
            parts = []
            filled = 0
            for field, col in zip(SPEC_FIELDS, spec_cols):
                value = _cell(row, col)
                if value:
                    parts.append(f"{field}: {value}")
                    filled += 1
            rows.append({
                "name": name,
                "detail": "\n\n".join(parts),
                "spec_filled": filled,       # ครบกี่หมวดจาก 13 — UI เตือนก่อนรันได้
            })
        note = f"header แถวที่ {header_index + 1}, คอลัมน์รุ่นที่ {model_col + 1}"
        if duplicates:
            note += f", ข้ามรุ่นซ้ำ {duplicates} แถว"
        return rows, note
    raise RuntimeError('ไม่พบคอลัมน์ "รุ่น" ในไฟล์ — เช็คว่าเป็นไฟล์สเปกสินค้าตัวจริง')


@app.post("/api/excel/scan")
async def scan_excel() -> dict:
    """อ่านรายการสินค้า — รีเช็คไฟล์เดิม รายการใหม่ถูกเพิ่มเข้า list (ตามผัง)"""
    config = load_config()
    excel = config["excel"]

    def scan() -> tuple[list[dict], str]:
        if excel["source"] == "file":
            path = Path(excel["file_path"])
            if not path.is_file():
                raise RuntimeError(f"ไม่พบไฟล์ {path}")
            try:
                import openpyxl
            except ImportError as error:
                raise RuntimeError("ต้องติดตั้ง openpyxl ก่อน: pip install openpyxl") from error
            book = openpyxl.load_workbook(path, read_only=True, data_only=True)
            sheets = [
                [list(row) for row in sheet.iter_rows(values_only=True)]
                for sheet in book.worksheets
            ]
            book.close()
            rows, note = parse_product_rows(sheets)
            return rows, f"อ่านจากไฟล์ {path.name} ({note})"
        url = excel["online_url"].strip()
        if not url:
            raise RuntimeError("ยังไม่ได้ใส่ลิงก์ Sheet online")
        import csv
        import io
        import urllib.request

        # Google Sheet ต้องเป็นลิงก์ export CSV — แปลงให้อัตโนมัติถ้าเป็นลิงก์ปกติ
        match = re.search(r"docs.google.com/spreadsheets/d/([\w-]+)", url)
        if match and "export" not in url:
            url = f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv"
        with urllib.request.urlopen(url, timeout=20) as response:
            text = response.read().decode("utf-8", errors="replace")
        table = [list(row) for row in csv.reader(io.StringIO(text))]
        rows, note = parse_product_rows([table])
        return rows, f"อ่านจาก Sheet online ({note})"

    try:
        rows, source_text = await asyncio.to_thread(scan)
    except RuntimeError as error:
        append_log("input", f"สแกนรายการไม่สำเร็จ: {error}")
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not rows:
        append_log("input", "สแกนแล้วไม่พบรุ่นสินค้าเลย")
        raise HTTPException(status_code=400, detail="ไม่พบรุ่นสินค้าในไฟล์")

    known = {item["name"] for item in config["products"]}
    fresh = [row for row in rows if row["name"] not in known]
    config["products"].extend(fresh)
    save_config(config)
    complete = sum(1 for row in rows if row.get("spec_filled", 0) == len(SPEC_FIELDS))
    append_log(
        "input",
        f"{source_text} — พบ {len(rows)} รุ่น (สเปกครบ 13 หมวด {complete} รุ่น) "
        f"ใหม่ {len(fresh)} รายการ",
    )
    return {"ok": True, "total": len(config["products"]), "new": len(fresh),
            "products": config["products"]}


@app.post("/api/products/clear")
async def clear_products() -> dict:
    config = load_config()
    count = len(config["products"])
    config["products"] = []
    save_config(config)
    append_log("input", f"ล้างรายการสินค้า {count} รายการ")
    return {"ok": True}


@app.post("/api/single")
async def update_single(
    name: str = Form(""), detail: str = Form(""), strip_text: str = Form("false"),
    image: UploadFile | None = File(None),
) -> dict:
    config = load_config()
    single = config["single"]
    single["name"] = name.strip()[:200]
    single["detail"] = detail.strip()[:2000]
    single["strip_text"] = strip_text.lower() == "true"
    if image is not None and image.filename:
        suffix = Path(image.filename).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise HTTPException(status_code=400, detail="รองรับเฉพาะ jpg/png/webp")
        target = UPLOAD_DIR / f"single{suffix}"
        content = await image.read()
        if len(content) > 15 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="ไฟล์ใหญ่เกิน 15MB")
        target.write_bytes(content)
        single["image"] = target.name
    save_config(config)
    append_log("input", f"บันทึกสินค้าเดียว: {single['name'] or '(ไม่มีชื่อ)'}"
               + (" + รูป" if image is not None and image.filename else ""))
    return {"ok": True, "single": single}


@app.get("/api/single/image")
async def single_image() -> Response:
    config = load_config()
    name = config["single"].get("image", "")
    path = UPLOAD_DIR / name if name else None
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="ยังไม่มีรูป")
    return FileResponse(path, headers={"Cache-Control": "no-store"})


# -------------------------------------------------------------------- GEMS
# ผังสั่งให้หัวข้อ GEMS อยู่หน้า Input · เลือกแล้วมี test 1 รอบ เพื่อรู้ว่า
# GEMS ตัวนี้เจนคลิปยาวเท่าไร กี่ฉาก แล้วเด้งโชว์


@app.post("/api/gems")
async def add_gems(request: Request) -> dict:
    payload = await request.json()
    name = str(payload.get("name", "")).strip()
    link = str(payload.get("link", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="ตั้งชื่อ GEMS ก่อน")
    if not link.startswith("https://"):
        raise HTTPException(status_code=400, detail="ลิงก์ GEMS ต้องขึ้นต้นด้วย https://")
    config = load_config()
    counter = max([int(g["id"].split("_")[1]) for g in config["gems"]] or [0]) + 1
    entry = {"id": f"gems_{counter}", "name": name[:80], "link": link, "probe": None}
    config["gems"].append(entry)
    if not config["gems_selected"]:
        config["gems_selected"] = entry["id"]
    save_config(config)
    append_log("gems", f"เพิ่ม GEMS: {name}")
    return {"ok": True, "gems": entry}


@app.post("/api/gems/delete")
async def delete_gems(request: Request) -> dict:
    payload = await request.json()
    gems_id = str(payload.get("id", ""))
    config = load_config()
    before = len(config["gems"])
    config["gems"] = [g for g in config["gems"] if g["id"] != gems_id]
    if len(config["gems"]) == before:
        raise HTTPException(status_code=400, detail="ไม่พบ GEMS นี้")
    if config["gems_selected"] == gems_id:
        config["gems_selected"] = config["gems"][0]["id"] if config["gems"] else ""
    save_config(config)
    append_log("gems", f"ลบ GEMS {gems_id}")
    return {"ok": True}


@app.post("/api/gems/select")
async def select_gems(request: Request) -> dict:
    payload = await request.json()
    gems_id = str(payload.get("id", ""))
    config = load_config()
    if not any(g["id"] == gems_id for g in config["gems"]):
        raise HTTPException(status_code=400, detail="ไม่พบ GEMS นี้")
    config["gems_selected"] = gems_id
    save_config(config)
    return {"ok": True}


_probe_running = threading.Event()


@app.post("/api/gems/probe")
async def probe_gems(request: Request) -> dict:
    """test 1 รอบหลังเลือก GEMS — ส่งเข้า Gem จริงผ่านเบราว์เซอร์ (ผู้ใช้เลือกวิธีนี้)

    เปิดเบราว์เซอร์โปรไฟล์ของโปรเจกต์นี้ (แยกจาก Chrome หลักของผู้ใช้) พิมพ์ข้อมูล
    สินค้าตัวอย่างเข้า Gem แล้วอ่านว่าได้กี่ฉาก ยาวกี่วินาที ผลจำติดตัว GEMS
    เพื่อเด้งโชว์ทุกครั้งที่เลือก — รันเบื้องหลัง ผลไปโผล่ใน log + dropdown
    """
    payload = await request.json()
    gems_id = str(payload.get("id", ""))
    config = load_config()
    gems = next((g for g in config["gems"] if g["id"] == gems_id), None)
    if gems is None:
        raise HTTPException(status_code=400, detail="ไม่พบ GEMS นี้")
    if _probe_running.is_set():
        raise HTTPException(status_code=409, detail="กำลัง test GEMS ตัวอื่นอยู่")

    def work() -> None:
        _probe_running.set()
        try:
            append_log("gems", f"เริ่ม test {gems['name']} — เปิดเบราว์เซอร์เข้า Gem")
            import gem_driver

            probe = gem_driver.probe_gem(
                gems["link"], log=lambda m: append_log("gems", f"  {m}")
            )
            fresh = load_config()
            target = next((g for g in fresh["gems"] if g["id"] == gems_id), None)
            if target is not None:
                target["probe"] = probe
                save_config(fresh)
            append_log(
                "gems",
                f"test {gems['name']} เสร็จ: คลิป {probe['seconds']} วินาที "
                f"{probe['scenes']} ฉาก",
            )
        except Exception as error:
            append_log("gems", f"test ไม่สำเร็จ: {type(error).__name__}: {error}")
        finally:
            _probe_running.clear()

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "started": True}


# ------------------------------------------------------------------- logs API


@app.get("/api/logs/{tab}")
async def get_log(tab: str) -> dict:
    if tab not in LOG_TABS:
        raise HTTPException(status_code=404, detail="ไม่รู้จัก log นี้")
    return {"ok": True, "lines": read_log(tab)}


# ------------------------------------------------------------------ Release ③


@app.post("/api/release")
async def update_release(request: Request) -> dict:
    payload = await request.json()
    config = load_config()
    release = config["release"]
    if "trim_silence" in payload:
        release["trim_silence"] = bool(payload["trim_silence"])
    if "subtitle" in payload:
        if payload["subtitle"] not in {"none", "thai", "thai_english"}:
            raise HTTPException(status_code=400, detail="รูปแบบคำบรรยายไม่ถูกต้อง")
        release["subtitle"] = payload["subtitle"]
    if "headline_ai" in payload:
        release["headline_ai"] = bool(payload["headline_ai"])
    if "headline_text" in payload:
        release["headline_text"] = str(payload["headline_text"])[:120]
    save_config(config)
    append_log("release", "บันทึกตัวเลือกการตัดต่อ")
    return {"ok": True, "release": release}


@app.get("/api/release/clips")
async def release_clips() -> dict:
    """รายชื่อคลิปที่เจนเสร็จ (จาก data/flow_jobs ของโปรเจกต์นี้)"""
    jobs_dir = DATA_DIR / "flow_jobs"
    clips = []
    if jobs_dir.is_dir():
        for job in sorted(jobs_dir.iterdir(), reverse=True)[:12]:
            for video in sorted(job.glob("*.mp4")):
                clips.append({"job": job.name, "file": video.name,
                              "size_mb": round(video.stat().st_size / 1e6, 1)})
    return {"ok": True, "clips": clips[:24]}


# ------------------------------------------------------------------ Publish $


# ขั้นแรกของการโพสต์ Reels เป็นขั้นตายตัว: เปิดแอป Facebook เสมอ (ผู้ใช้สั่ง fix ไว้)
# ขั้นที่ผู้ใช้เพิ่มเอง 1-6 ขั้นถัดจากนี้ทั้งหมด
FACEBOOK_PACKAGE = "com.facebook.katana"


@app.post("/api/publish/open-facebook")
async def publish_open_facebook(request: Request) -> dict:
    """ขั้นตายตัวที่ 1 — เปิดแอป Facebook บนมือถือ (ไม่ใช้พิกัด)"""
    payload = await request.json()
    serial = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )

    def work() -> None:
        result = run_adb(
            "-s", serial, "shell", "monkey", "-p", FACEBOOK_PACKAGE,
            "-c", "android.intent.category.LAUNCHER", "1", timeout=15,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0 or b"No activities found" in output:
            raise RuntimeError("ไม่พบแอป Facebook บนเครื่องนี้ — ติดตั้งก่อน")

    try:
        await asyncio.to_thread(work)
    except RuntimeError as error:
        append_log("publish", f"เปิดแอป Facebook ไม่สำเร็จ: {error}")
        raise HTTPException(status_code=502, detail=str(error)) from error
    append_log("publish", "ขั้น 1 (ตายตัว): เปิดแอป Facebook แล้ว")
    return {"ok": True, "message": "เปิดแอป Facebook แล้ว"}


@app.post("/api/publish/queue")
async def save_queue(request: Request) -> dict:
    """บันทึกลำดับขั้นการกด 1-6 — แต่ละขั้นเลือกชนิดจาก dropdown ตามผัง"""
    payload = await request.json()
    items = payload.get("items")
    if not isinstance(items, list) or len(items) > 6:
        raise HTTPException(status_code=400, detail="ลำดับขั้นมีได้สูงสุด 6 ขั้น")
    cleaned = []
    for index, item in enumerate(items):
        action = str(item.get("action", "train"))
        if action not in PUBLISH_ACTIONS:
            raise HTTPException(status_code=400, detail=f"ไม่รู้จักชนิดขั้น {action}")
        cleaned.append({
            "id": str(item.get("id") or f"step_{index + 1}"),
            "name": str(item.get("name", ""))[:80],
            "action": action,
            # link shopee / link lazada / แฮชแท็ก เก็บในช่องเดียวกันตามชนิดที่เลือก
            "value": str(item.get("value", ""))[:500],
        })
    config = load_config()
    config["publish_queue"] = cleaned
    save_config(config)
    append_log("publish", f"บันทึกลำดับขั้นการกด {len(cleaned)} ขั้น")
    return {"ok": True, "items": cleaned}


@app.get("/api/publish/positions")
async def get_positions(serial: str) -> dict:
    return {"ok": True, "positions": load_positions(clean_serial(serial))}


@app.post("/api/publish/train")
async def train_position(request: Request) -> dict:
    """เทรนตำแหน่งการกดในมือถือ — เก็บเป็นสัดส่วนจอ ต่อเครื่อง ต่อช่องคิว"""
    payload = await request.json()
    serial = clean_serial(str(payload.get("serial", "")))
    slot = str(payload.get("slot", "")).strip()
    step = str(payload.get("step", "")).strip()[:40]
    x, y = int(payload.get("x", -1)), int(payload.get("y", -1))
    width = int(payload.get("source_width", 0))
    height = int(payload.get("source_height", 0))
    if not slot or not step or x < 0 or y < 0 or not width or not height:
        raise HTTPException(status_code=400, detail="ข้อมูลเทรนไม่ครบ")
    positions = load_positions(serial)
    positions.setdefault(slot, {})[step] = {
        "rx": round(x / width, 5), "ry": round(y / height, 5),
        "trained_at": datetime.now().isoformat(timespec="seconds"),
    }
    await asyncio.to_thread(save_positions, serial, positions)
    append_log("publish", f"เทรนตำแหน่ง {slot}/{step} ที่ {x},{y}")
    return {"ok": True}


# ------------------------------------------- ผังโพสต์วิดีโอ (เทรนเองต่อปลายทาง)
#
# แยกจาก /api/publish/train ข้างบนโดยตั้งใจ — ตัวนั้นเก็บพิกัดแบบช่องเดียวไม่มี
# ลำดับขั้น ส่วนชุดนี้เป็นผังเต็มที่เพิ่ม/ลบ/สลับขั้นได้ และมีตัวตรวจผลรายขั้น

import clip_store                                                # noqa: E402
import publish_flow                                              # noqa: E402
import publish_order                                             # noqa: E402
import hashtag as hashtag_lib                                    # noqa: E402

# มือถือมีจอเดียว สองงานยิง adb พร้อมกันจะกดทับกันทั้งคู่ — ล็อกให้รันทีละงาน
_publish_run_lock = threading.Lock()


def _flow_store(serial: str) -> "publish_flow.FlowStore":
    return publish_flow.FlowStore(serial, root=DATA_DIR)


def _clean_target(value: str) -> str:
    target = str(value or "").strip()
    if target not in publish_flow.DEFAULT_SEQUENCES:
        raise HTTPException(status_code=400, detail=f"ไม่รู้จักปลายทาง {target}")
    return target


def _flow_payload(store: "publish_flow.FlowStore", target: str) -> dict:
    positions = store.positions(target)
    steps = []
    for number, step in enumerate(store.sequence(target), start=1):
        entry = dataclasses.asdict(step)
        entry["order"] = number
        entry["verify_kind"] = step.verify_kind()
        entry["trained"] = step.id in positions
        entry["position"] = positions.get(step.id) or {}
        # ขั้นที่ "เทรนพิกัดได้" — รวมขั้นที่มีคำใบ้ find ด้วย เพราะ find หาไม่เจอ
        # เมื่อไรระบบจะถอยไปใช้พิกัด การมีพิกัดสำรองไว้จึงมีประโยชน์เสมอ
        entry["needs_position"] = step.kind in {
            "tap", "type_text", "paste_link", "type_hashtag",
        }
        steps.append(entry)
    return {
        "ok": True,
        "target": target,
        "target_name": publish_flow.TARGET_NAMES[target],
        "steps": steps,
        "kinds": publish_flow.KINDS,
        "verify_kinds": publish_flow.VERIFY_KINDS,
        "targets": publish_flow.TARGET_NAMES,
    }


@app.get("/api/publish/flow")
async def publish_flow_get(serial: str, target: str) -> dict:
    store = await asyncio.to_thread(_flow_store, clean_serial(serial))
    return _flow_payload(store, _clean_target(target))


@app.post("/api/publish/flow/step")
async def publish_flow_add(request: Request) -> dict:
    """แทรกขั้นใหม่ถัดจากขั้นที่ระบุ (ไม่ระบุ = ต่อท้าย)"""
    payload = await request.json()
    serial, target = clean_serial(str(payload.get("serial", ""))), _clean_target(
        payload.get("target")
    )
    store = _flow_store(serial)
    try:
        step = await asyncio.to_thread(
            store.insert_step, target,
            str(payload.get("name", "")).strip(),
            str(payload.get("after", "")).strip(),
            str(payload.get("kind", "tap")).strip(),
        )
    except publish_flow.StepError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    append_log("publish", f"[{target}] เพิ่มขั้น \"{step.name}\" ({step.kind})")
    return _flow_payload(store, target)


@app.patch("/api/publish/flow/step")
async def publish_flow_update(request: Request) -> dict:
    """แก้ชื่อ/ชนิด/ข้อความ/วิธีตรวจ ของขั้นหนึ่ง"""
    payload = await request.json()
    serial, target = clean_serial(str(payload.get("serial", ""))), _clean_target(
        payload.get("target")
    )
    step_id = str(payload.get("id", "")).strip()
    changes = {}
    for key in ("name", "kind", "find", "value", "verify", "verify_text"):
        if key in payload:
            changes[key] = str(payload[key])[:200]
    if "optional" in payload:
        changes["optional"] = bool(payload["optional"])
    for key in ("settle", "verify_timeout"):
        if key in payload:
            try:
                changes[key] = max(0.0, min(120.0, float(payload[key])))
            except (TypeError, ValueError):
                pass
    store = _flow_store(serial)
    try:
        step = await asyncio.to_thread(store.update_step, target, step_id, **changes)
    except publish_flow.StepError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    append_log("publish", f"[{target}] แก้ขั้น \"{step.name}\"")
    return _flow_payload(store, target)


@app.delete("/api/publish/flow/step")
async def publish_flow_delete(serial: str, target: str, id: str) -> dict:
    store = _flow_store(clean_serial(serial))
    target = _clean_target(target)
    if not await asyncio.to_thread(store.delete_step, target, id):
        raise HTTPException(status_code=404, detail="ไม่พบขั้นนี้")
    append_log("publish", f"[{target}] ลบขั้น {id}")
    return _flow_payload(store, target)


@app.post("/api/publish/flow/move")
async def publish_flow_move(request: Request) -> dict:
    payload = await request.json()
    serial, target = clean_serial(str(payload.get("serial", ""))), _clean_target(
        payload.get("target")
    )
    offset = -1 if str(payload.get("direction", "up")) == "up" else 1
    store = _flow_store(serial)
    await asyncio.to_thread(
        store.move_step, target, str(payload.get("id", "")), offset
    )
    return _flow_payload(store, target)


@app.post("/api/publish/flow/reset")
async def publish_flow_reset(request: Request) -> dict:
    payload = await request.json()
    serial, target = clean_serial(str(payload.get("serial", ""))), _clean_target(
        payload.get("target")
    )
    store = _flow_store(serial)
    await asyncio.to_thread(store.reset, target)
    append_log("publish", f"[{target}] คืนผังตั้งต้น (พิกัดที่เทรนไว้ยังอยู่)")
    return _flow_payload(store, target)


@app.post("/api/publish/flow/train")
async def publish_flow_train(request: Request) -> dict:
    """จำพิกัดของขั้นหนึ่ง — เก็บเป็นสัดส่วนจอเพื่อย้ายเครื่องได้"""
    payload = await request.json()
    serial, target = clean_serial(str(payload.get("serial", ""))), _clean_target(
        payload.get("target")
    )
    store = _flow_store(serial)
    try:
        point = await asyncio.to_thread(
            store.train, target, str(payload.get("id", "")),
            int(payload.get("x", -1)), int(payload.get("y", -1)),
            int(payload.get("source_width", 0)), int(payload.get("source_height", 0)),
        )
    except (publish_flow.StepError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    append_log(
        "publish",
        f"[{target}] เทรน {payload.get('id')} ที่สัดส่วน {point['rx']}, {point['ry']}",
    )
    return _flow_payload(store, target)


@app.delete("/api/publish/flow/position")
async def publish_flow_clear_position(serial: str, target: str, id: str) -> dict:
    store = _flow_store(clean_serial(serial))
    target = _clean_target(target)
    await asyncio.to_thread(store.clear_position, target, id)
    return _flow_payload(store, target)


# ---------------------------------------------------------- แฮชแท็กของสินค้า


@app.get("/api/publish/items")
async def publish_items() -> dict:
    """รายชื่อสินค้าที่มีงานอยู่ — ใช้เลือกว่าจะเตรียมโพสต์ตัวไหน"""
    runs = await asyncio.to_thread(clip_store.list_runs, DATA_DIR)
    items = [
        {
            "item_id": run.get("item_id", ""),
            "name": (run.get("name") or "")[:60],
            "has_video": bool(run.get("video_count")),
            "has_tags": bool((run.get("hashtag_plan") or {}).get("tags")),
        }
        for run in runs
        if run.get("item_id")
    ]
    return {"ok": True, "items": items}


@app.get("/api/publish/hashtags")
async def publish_hashtags(item_id: str, rebuild: bool = False) -> dict:
    """ชุดแท็ก 5 ตัวของสินค้า — สกัดครั้งแรกแล้วเก็บไว้ ผู้ใช้แก้ได้ทีหลัง"""
    run = await asyncio.to_thread(clip_store.load_run, DATA_DIR, item_id)
    if not run:
        raise HTTPException(status_code=404, detail="ไม่พบงานของสินค้านี้")
    plan = run.get("hashtag_plan")
    if rebuild or not plan:
        key = load_gemini_key()
        plan = await asyncio.to_thread(
            hashtag_lib.plan_for_run, run, key,
            lambda message: append_log("publish", message),
        )
        await asyncio.to_thread(
            clip_store.set_hashtag_plan, DATA_DIR, item_id, plan
        )
    return {"ok": True, "plan": plan, "mention_min": hashtag_lib.MENTION_MIN}


@app.post("/api/publish/hashtags")
async def publish_hashtags_save(request: Request) -> dict:
    """บันทึกยี่ห้อ/ชนิด/รายละเอียดที่ผู้ใช้แก้ แล้วประกอบแท็กใหม่ให้"""
    payload = await request.json()
    item_id = str(payload.get("item_id", "")).strip()
    details = [str(item).strip() for item in (payload.get("details") or [])][:3]
    plan = {
        "brand": str(payload.get("brand", "")).strip(),
        "kind": str(payload.get("kind", "")).strip(),
        "details": [item for item in details if item],
    }
    plan["tags"] = hashtag_lib.build_candidates(
        plan["brand"], plan["kind"], plan["details"]
    )
    await asyncio.to_thread(clip_store.set_hashtag_plan, DATA_DIR, item_id, plan)
    append_log("publish", f"แก้ชุดแฮชแท็กของ {item_id}: {' '.join(plan['tags'])}")
    return {"ok": True, "plan": plan}


# --------------------------------------------------------------- เดินผังจริง


def _wake_for_publish(serial: str):
    """ปลุกจอ + ปัดหน้าล็อกก่อนเริ่มเดินผัง — คืนข้อความบอกว่าทำอะไรไป

    **ทำไมต้องมี** ตรวจ 26 ส.ค. 2026: ทั้ง `publish_flow.py` ไม่มีคำสั่งปลุกจอ
    เลยสักบรรทัด (grep "wake" ได้ 0 ผลลัพธ์) และตัวตรวจของขั้นแรก (`app_frontmost`)
    ดูแค่ว่าแอปไหนอยู่หน้าสุด ซึ่ง **ผ่านได้ทั้งที่ `mWakefulness=Asleep`** —
    เจอกับตัวจริง: ขั้น "เข้าแอป Shopee" รายงานว่าผ่าน ทั้งที่จอดับและมีหน้าล็อกบัง

    `fb_screen.wake()` ยืนยันด้วยว่า**แตะจอได้จริง** ไม่ใช่แค่สั่งปลุกแล้วเชื่อ
    """
    def work() -> str:
        notes = []
        # ---- ปิดแอนิเมชันของ Android ก่อนเสมอ (บทเรียน 28 ส.ค. 2569) ----
        #
        # **นี่คือตัวที่ทำให้อ่านหน้าจอไม่ได้เลยทั้งคืน** `uiautomator dump`
        # รอให้หน้าจอ "นิ่ง" ก่อนถึงจะอ่าน ถ้าแอนิเมชันเปิดอยู่ หน้าจอไม่เคย
        # นิ่ง มันจึงตอบ "could not get idle state" ทุกครั้ง แล้วทุกขั้นที่
        # ต้องอ่านจอจะล้มหมด — ตัวอ่านยอดแฮชแท็กพังทั้งชุดเพราะข้อนี้
        #
        # วัดผลหลังปิด: ขั้น "แตะช่องแคปชัน" เร็วขึ้นจาก **193 วินาที
        # เหลือ 16 วินาที** และอ่านผังจอได้ทุกครั้ง
        #
        # ตั้งทุกครั้งไม่ต้องเช็คก่อน — คำสั่งนี้เบามากและไม่มีผลข้างเคียง
        # ถ้าค่าเป็น 0 อยู่แล้ว
        try:
            for key in ("window_animation_scale", "transition_animation_scale",
                        "animator_duration_scale"):
                run_adb("-s", serial, "shell", "settings", "put", "global",
                        key, "0", timeout=15)
        except Exception as error:                             # noqa: BLE001
            # ปิดไม่ได้ไม่ใช่เหตุให้ล้มทั้งงาน แต่ต้องดัง เพราะถ้าเปิดอยู่
            # ขั้นที่ต้องอ่านจอจะพังทีหลังแล้วไล่หาสาเหตุยาก
            append_log("publish", f"⚠️ ปิดแอนิเมชันมือถือไม่สำเร็จ: {error} — "
                                  f"ขั้นที่ต้องอ่านหน้าจออาจล้ม")

        shell = _screen_shell(serial)
        if not fb_screen.is_awake(shell):
            if not fb_screen.wake(shell, log=lambda x: append_log("publish", x)):
                raise RuntimeError("ปลุกจอไม่ขึ้น — จออาจติดหน้าล็อกที่ต้องใส่รหัส")
            notes.append(f"ปลุกจอ {device_book.label(serial)} แล้ว")

        # ---- กันจอดับระหว่างเดินผัง (เจ้าของสั่ง 28 ส.ค. 2569) ----------
        #
        # *"ให้รู้ว่าเรากำลังใช้เครื่องอยู่ ห้ามปิด"*
        #
        # บัตรคิวจอกันตัวหรี่จอได้ก็จริง **แต่กันได้เฉพาะตอนที่ถือบัตรอยู่**
        # ระหว่างเดินผังทีละขั้น (`only`) บัตรถูกคืนทุกครั้งที่จบขั้น
        # ตัวหรี่จอจึงเห็นว่าจอว่างแล้วดับจอกลางงาน — เกิดจริงคืน 27 ส.ค.
        #
        # `stay_on_while_plugged_in=7` = ห้ามดับจอตราบใดที่เสียบสายอยู่
        # (มือถือที่ใช้โพสต์เสียบสายตลอดอยู่แล้ว) ปลดล็อกเมื่อจบงาน
        try:
            run_adb("-s", serial, "shell", "settings", "put", "global",
                    "stay_on_while_plugged_in", "7", timeout=15)
        except Exception as error:                             # noqa: BLE001
            append_log("publish", f"⚠️ สั่งห้ามจอดับไม่สำเร็จ: {error}")
        return " · ".join(notes)
    return work


def _clip_sender(serial: str, item_id: str, run: dict):
    """ส่งคลิปของงานนี้เข้ามือถือ ให้เป็นวิดีโอใบล่าสุดในแกลเลอรี

    ผู้ใช้สั่ง 26 ส.ค. 2026: *"ให้เตรียมคลิปเข้าเครื่องเลยตั้งแต่กดเริ่มงาน"*

    **ทำไมต้องมี** ขั้น "เลือกคลิปที่จะโพสต์" แตะพิกัดที่เทรนไว้เฉยๆ มันไม่ได้
    อ่านว่าช่องนั้นเป็นคลิปอะไร — ถ้าคลิปของงานไม่ได้อยู่ในเครื่อง มันจะหยิบคลิป
    เก่าของสินค้าอื่นมาโพสต์แล้วเดินจนจบโดยไม่มีอะไรฟ้อง ซึ่งถอนไม่ได้
    (เจอจริง 26 ส.ค.: ในจอ 3 มีแต่คลิปจากตอนเทรน 25 ส.ค. สองใบ)

    **ต้องยืนยันว่าเป็นใบล่าสุดจริง ไม่ใช่แค่ส่งเข้าไปแล้วเชื่อ** — ระบบแกลเลอรี
    ของ Android รู้จักไฟล์ก็ต่อเมื่อถูกสแกน ถ้าสแกนไม่ติดไฟล์จะอยู่ในเครื่อง
    แต่ไม่โผล่ในตัวเลือกคลิป ซึ่งอาการเหมือน "ไม่ได้ส่ง" ทุกประการ

    **ไม่ลบคลิปเก่าทิ้ง** ของในเครื่องเป็นของผู้ใช้ ที่นี่แค่ทำให้ของเราใหม่กว่า
    """
    videos = list(run.get("videos") or [])
    if not videos:
        return None                      # งานยังไม่มีคลิป — ไม่มีอะไรให้ส่ง
    local = clip_store.file_path(DATA_DIR, item_id, videos[0])

    def work() -> str:
        if not local.is_file():
            raise RuntimeError(f"ไม่พบไฟล์คลิปในเครื่องคอม: {local}")
        size = local.stat().st_size
        name = f"{item_id}-{local.name}"
        remote = f"{PHONE_POST_REMOTE_DIR}/{name}"

        def sh(*args: str) -> str:
            return run_adb("-s", serial, "shell", *args, timeout=60).stdout.decode(
                "utf-8", errors="replace")

        run_adb("-s", serial, "shell", "mkdir", "-p", PHONE_POST_REMOTE_DIR, timeout=20)
        # มีอยู่แล้วขนาดเท่ากัน = ไม่ต้องส่งซ้ำ (11 MB ต่อรอบ) แต่ยังต้อง "ดัน
        # เวลาให้เป็นเดี๋ยวนี้" อยู่ดี ไม่งั้นคลิปอื่นที่ส่งทีหลังจะใหม่กว่า
        here = sh("stat", "-c", "%s", remote).strip()
        again = here.isdigit() and int(here) == size
        if not again:
            pushed = run_adb("-s", serial, "push", str(local), remote, timeout=600)
            if pushed.returncode != 0:
                raise RuntimeError(
                    "ส่งคลิปเข้ามือถือไม่สำเร็จ: "
                    + pushed.stderr.decode("utf-8", errors="replace")[:150])
        sh("touch", remote)
        sh("content", "call", "--uri", "content://media",
           "--method", "scan_file", "--arg", remote)
        time.sleep(1.5)

        # ยืนยันกับระบบแกลเลอรีเอง ไม่ใช่เชื่อว่าสแกนติด
        #
        # **ห้ามใส่ LIMIT ในค่า --sort** Android ปฏิเสธด้วย "Invalid token LIMIT"
        # (เจอจริง 26 ส.ค. 2026 บน REDMI 15C) ต้องดึงมาทั้งหมดแล้วอ่านแถวแรกเอง
        rows = [line for line in sh(
            "content", "query", "--uri", "content://media/external/video/media",
            "--projection", "_display_name", "--sort", "'date_added DESC'",
        ).splitlines() if line.startswith("Row:")]
        first = rows[0] if rows else ""
        if name not in first:
            raise RuntimeError(
                f"ส่งคลิปเข้าเครื่องแล้วแต่แกลเลอรียังไม่เห็นเป็นใบล่าสุด "
                f"(ใบล่าสุดตอนนี้: {first.strip()[:120] or 'อ่านไม่ได้'}) — "
                "ถ้าเดินต่อจะไปหยิบคลิปผิดใบมาโพสต์")
        mb = size / 1048576
        return (f"คลิปอยู่ในเครื่องแล้วและเป็นใบล่าสุด: {name} ({mb:.1f} MB)"
                + (" — มีอยู่ก่อนแล้ว ไม่ได้ส่งซ้ำ" if again else ""))
    return work


def _shot_after_step(serial: str, target: str, item_id: str):
    """เก็บภาพหน้าจอ **หลังจบทุกขั้น** (เจ้าของสั่ง 28 ส.ค. 2569)

    *"ให้ทำการ capture ภาพไว้ทุกครั้งหลังทำแต่ละขั้นตอนเสร็จ"*

    **ทำไมคุ้มแม้จะเปลืองที่** การโพสต์เป็นสิ่งที่ถอนไม่ได้ พอมีอะไรผิดแล้ว
    ย้อนดูไม่ได้ว่าตอนนั้นหน้าจอเป็นยังไง จะตอบไม่ได้เลยว่าพลาดตรงไหน —
    เจอมาแล้ว 25 ส.ค. ที่ล้มรวด 13 ใบแล้วไม่มีภาพสักใบให้ดู (กติกาข้อ 2.6.1)

    เก็บผ่าน `evidence.py` ตัวเดียวกับที่ระบบใช้อยู่ — มันกลืน error เองหมด
    ถ้าแคปไม่ได้ก็จดว่าแคปไม่ได้ **ไม่ทำให้งานโพสต์ล้มตาม**
    """
    import evidence                                            # noqa: PLC0415

    def shot(step, ok: bool, message: str) -> None:
        mark = "ผ่าน" if ok else "ไม่ผ่าน"
        try:
            xml = run_adb("-s", serial, "shell", "uiautomator", "dump",
                          "/sdcard/step.xml", timeout=30)
            markup = run_adb("-s", serial, "shell", "cat", "/sdcard/step.xml",
                             timeout=30).stdout.decode("utf-8", "replace")
        except Exception:                                      # noqa: BLE001
            markup = ""
        try:
            png = run_adb("-s", serial, "exec-out", "screencap", "-p",
                          timeout=60).stdout
        except Exception:                                      # noqa: BLE001
            png = b""
        saved = evidence.capture(
            f"{target} {step.id} {mark}", tag="publish", markup=markup,
            note=(f"สินค้า {item_id} · เครื่อง {serial}"
                  f"\n{step.name}\n{message}"))
        if saved and png:
            try:
                Path(str(saved).replace(".txt", ".png")).write_bytes(png)
            except Exception:                                  # noqa: BLE001
                pass

    return shot


def _build_context(
    serial: str, target: str, item_id: str, report
) -> "publish_flow.RunContext":
    """ประกอบบริบทการรันจากงานจริงในคิว — แคปชัน ลิงก์ และแท็กมาจาก run.json"""
    run = clip_store.load_run(DATA_DIR, item_id) if item_id else {}
    plan = (run or {}).get("hashtag_plan") or {}
    store = _flow_store(serial)
    width, height = screen_size(serial)
    return publish_flow.RunContext(
        serial=serial,
        store=store,
        target=target,
        screen=(width, height),
        tap=lambda x, y: run_adb("-s", serial, "shell", "input", "tap", str(x), str(y)),
        type_text=lambda text: adb_type_text(serial, text),
        # คัดลอก-วางบนมือถือ — ใช้กับขั้น "วางลิงก์" (ผู้ใช้สั่ง 25 ส.ค. 2026)
        #
        # ผ่านช่องควบคุมของ scrcpy ตัวเดียวกับปุ่มคัดลอกในหน้าจอมือถือบนเว็บ
        # (`adb shell service call clipboard` ใช้ไม่ได้ตั้งแต่ Android 10)
        # ตัวเดินผังจะถอยไปพิมพ์ทีละตัวเองถ้าตรงนี้ล้ม — และขึ้น log ว่าถอย
        set_clipboard=lambda text, paste=True: scrcpy_control.set_clipboard(
            ADB, serial, text, paste),
        run_adb=lambda *args: run_adb("-s", serial, *args, timeout=25).stdout,
        caption=(run or {}).get("caption") or clip_store.build_caption(run or {}),
        # ต้องเป็นลิงก์ที่ผู้ใช้ส่งมาทาง Telegram เท่านั้น — ลิงก์ที่ระบบแปลงเอง
        # ไม่มีรหัสผู้แนะนำ โพสต์ไปก็ไม่ได้ค่าคอม
        link=(run or {}).get("affiliate_url") or "",
        # **อ่านสองที่ ไม่ใช่ที่เดียว** (แก้ 27 ส.ค. 2569)
        #
        # แฮชแท็กถูกเก็บสองแบบตามที่มาของมัน
        #   hashtag_plan.tags  มาจากตัววางแผนแท็ก (มี 21 จาก 103 งาน)
        #   hashtags           มาจากขั้นทำแฮชแท็กในสายคลิป (มี 27 งาน)
        #
        # ของเดิมอ่านแค่ `hashtag_plan.tags` ผลคืองานที่มีแท็กจากอีกทาง
        # จะโพสต์ขึ้นโดย **ไม่มีแฮชแท็กเลยสักตัว** และไม่มีอะไรฟ้อง —
        # ตัวเดินผังแค่บอกว่า "ไม่มีแฮชแท็กให้ใส่ ข้ามไป" แล้วเดินต่อ
        # เจอตอนไล่เดินผังทีละขั้นกับของจริง (จอ 27P2A มีแท็ก 5 ตัวแต่ไม่ถูกพิมพ์)
        hashtags=list(plan.get("tags") or (run or {}).get("hashtags") or []),
        log=lambda message: append_log("publish", message),
        report=report,
        # เตรียมของก่อนแตะจอขั้นแรก (ผู้ใช้สั่ง 26 ส.ค. 2026) — อยู่นอกผัง
        # เพราะขั้นในผังถูกลบได้จากหน้าเว็บ ถ้าลบขั้นส่งคลิปทิ้ง ผังจะยังเดินจนจบ
        # แล้วโพสต์คลิปของสินค้าอื่น ซึ่งถอนไม่ได้
        wake_screen=_wake_for_publish(serial),
        send_clip=_clip_sender(serial, item_id, run or {}) if item_id else None,
    )


@app.post("/api/publish/flow/run")
async def publish_flow_run(request: Request) -> dict:
    """เดินผังทั้งชุด หรือทดลองทีละขั้น (ส่ง only มาเป็นเลขขั้น)"""
    payload = await request.json()
    serial = clean_serial(str(payload.get("serial", "")), True)
    target = _clean_target(payload.get("target"))
    item_id = str(payload.get("item_id", "")).strip()
    only = payload.get("only")

    # ด่านลำดับการลง — Shopee Video → Facebook Reels → TikTok ห่างกันอย่างน้อย 1 วัน
    #
    # ตรวจ **ก่อน** จับล็อกและก่อนแตะมือถือ เพราะถ้าปล่อยให้เดินผังไปแล้วค่อยรู้
    # ว่าผิดลำดับ = โพสต์ขึ้นจริงไปแล้ว ถอนไม่ได้ (ต้องไปลบเองในแอป)
    # ไม่ตรวจตอนสั่งเดินทีละขั้น (`only`) เพราะนั่นคือการไล่เทรนผัง ไม่ใช่โพสต์จริง
    if item_id and not only:
        run = clip_store.load_run(DATA_DIR, item_id) or {}
        ok, why = publish_order.check(run, target)
        if not ok:
            append_log("publish", f"[{target}] ไม่ได้เดินผัง — {why}")
            raise HTTPException(status_code=409, detail=why)

        # ---- ต้องมีแฮชแท็กก่อนถึงจะลงได้ (เพิ่ม 28 ส.ค. 2569) --------
        #
        # **ตรวจก่อนแตะมือถือ ไม่ใช่ไปตายกลางผัง** ผังใช้เวลา 10 นาทีต่อใบ
        # ถ้าปล่อยให้เดินไปจนถึงขั้นที่ 12 แล้วค่อยรู้ = เสีย 6 นาทีฟรี
        # และมือถือค้างอยู่กลางหน้าโพสต์ที่ต้องมาเก็บกวาดต่อ
        #
        # **เจอจริง 28 ส.ค. 02:27** คลิป Pocket WiFi6 ขึ้น Shopee โดย
        # ไม่มีแฮชแท็กสักตัว แล้วระบบรายงานว่า "22/22 สำเร็จ" —
        # ถ้าเจ้าของไม่ทักว่า "ทำไมยังไม่มีแฮชแท็ก" ก็ไม่มีใครรู้เลย
        tags = ((run.get("hashtag_plan") or {}).get("tags")
                or run.get("hashtags") or [])
        if not tags:
            detail = ("สินค้านี้ยังไม่มีแฮชแท็ก — ลงไปก็ไม่มีแท็กสักตัว "
                      "สร้างก่อนด้วยปุ่ม 🏷 ในใบงาน หรือ /tags ในแชท")
            append_log("publish", f"[{target}] ไม่ได้เดินผัง — {detail}")
            raise HTTPException(status_code=409, detail=detail)

    if not _publish_run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="มีงานโพสต์รันอยู่แล้ว รอให้จบก่อน")

    def work() -> dict:
        # ---- กดบัตรคิวจอก่อนแตะเครื่อง (กติกาข้อ 9 ของโปรเจกต์) ----------
        #
        # **ของเดิมไม่ได้กดบัตรเลย** จับแต่ `_publish_run_lock` ซึ่งเป็นล็อกใน
        # โปรเซสตัวเอง คนอื่นมองไม่เห็น ผลคือระหว่างโพสต์จริง:
        #   · ตัวหรี่จอเห็นว่า "จอว่าง" แล้ว **ดับจอกลางงาน**
        #   · ตัวล้างเครื่องเห็นว่าจอว่างแล้ว **ลบทุกอย่างใน /sdcard/Movies/autopost**
        #     ซึ่งคือที่ที่คลิปของงานถูกวางไว้พอดี
        #
        # ทั้งสองอย่างเกิดขึ้นจริงกับตาเมื่อ 26 ส.ค. 2026 ระหว่างไล่เทสทีละขั้น
        # (log 21:00:26 "ล้างเครื่อง W4FYYPYTLFYLIFHM — ลบไฟล์ 1 ใบ" แล้วโฟลเดอร์
        # คลิปว่างเปล่า) ถ้าเกิดตอนโพสต์จริงจะได้ "เลือกคลิป" บนแกลเลอรีที่ไม่มี
        # คลิปของเราอยู่แล้ว = โพสต์คลิปผิดใบ ซึ่งถอนไม่ได้
        #
        # `phone_queue.slot` กันได้ทั้งสองตัว เพราะทั้งคู่ต้องขอล็อกเดียวกันนี้ก่อน
        # ลงมือ (และเป็นล็อกข้ามโปรเซส บอทที่รันแยกอยู่ก็เห็น)
        import phone_queue                                        # noqa: PLC0415
        what = ("ไล่ทีละขั้น" if only else "โพสต์") + f" {target}"
        # **ปล่อย `_publish_run_lock` ใน finally ชั้นนอกสุดเสมอ** — ถ้าไปปล่อย
        # ข้างในบล็อกคิว แล้วขอคิวไม่ได้ (คนอื่นถือจออยู่) ล็อกจะค้างตลอดกาล
        # แล้วทุกคำขอโพสต์หลังจากนั้นจะโดนตอบว่า "มีงานโพสต์รันอยู่แล้ว" ทั้งที่ว่าง
        try:
            with phone_queue.slot(serial, owner="งานโพสต์คลิป", task=what,
                                  lane="post", timeout=600.0):
                context = _build_context(serial, target, item_id,
                                         _shot_after_step(serial, target, item_id))
                if only:
                    number = int(only)
                    # ทดลองทีละขั้น = กำลังพิสูจน์ว่าพิกัดที่เทรนไว้ถูกจริง
                    # ต้องแตะตรงจุดเป๊ะ ไม่งั้นถ้าเยื้องแล้วบังเอิญไปโดนปุ่มพอดี
                    # จะเก็บพิกัดที่ผิดไว้โดยไม่รู้ตัว แล้วไปพังตอนเดินผังจริง
                    context.tap_jitter = 0
                    context.settle_jitter = 0.0
                    return publish_flow.run_flow(
                        context, start_at=number, stop_after=number)
                return publish_flow.run_flow(context)
        finally:
            # คืนคีย์บอร์ดเดิมเสมอ แม้ผังจะล้มกลางคัน — ทิ้งไว้ที่
            # ADBKeyboard เจ้าของหยิบมือถือขึ้นมาจะพิมพ์อะไรไม่ได้เลย
            adb_restore_keyboard(serial)
            _publish_run_lock.release()

    try:
        result = await asyncio.to_thread(work)
    except publish_flow.StepError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    # โฆษณาที่ปิดไประหว่างทางต้องขึ้น log ด้วย — ถ้าตัวเลขนี้ค่อยๆ เพิ่ม แปลว่า
    # แอปเริ่มยิงโฆษณาถี่ขึ้น ควรรู้ตั้งแต่ก่อนที่ผังจะพังเอง ไม่ใช่ปิดเงียบๆ
    ads = result.get("ads_closed") or []
    append_log(
        "publish",
        f"[{target}] เดินผัง {result['done']}/{result['total']} ขั้น — "
        f"{'สำเร็จ' if result['ok'] else 'ไม่สำเร็จ'}"
        + (f" · ปิดโฆษณาที่เด้งแทรก {len(ads)} ครั้ง" if ads else ""),
    )

    # เขียนผลกลับลงงาน — **จุดนี้เคยขาดหายไปทั้งระบบ**
    #
    # ตรวจ 18 ส.ค. 2026: `clip_store.mark_posted()` เขียนไว้ครบตั้งแต่แรกแต่ไม่มีโค้ด
    # ตัวไหนเรียกเลยสักที่ (grep ทั้งโปรเจกต์ได้ 0 ผลลัพธ์) ผลคือ run.json ทั้ง 17 ไฟล์
    # มีคีย์ publish แค่ 3 ไฟล์ และทั้ง 6 รายการเป็น pending · posted_at ว่างเปล่า
    # คือระบบไม่เคยรู้เลยว่าโพสต์อะไรไปแล้วบ้าง เดินผังซ้ำสินค้าเดิมก็ไม่มีอะไรเตือน
    #
    # ไม่บันทึกเมื่อสั่งเดินทีละขั้น (`only`) เพราะนั่นคือการไล่เทรนผัง ไม่ใช่โพสต์จริง
    # บันทึกไปจะกลายเป็นประวัติเท็จซึ่งแย่กว่าไม่มีประวัติ
    if item_id and not only:
        note = ("" if result["ok"]
                else f"เดินผังไม่จบ หยุดที่ขั้น {result['done']}/{result['total']}")
        try:
            await asyncio.to_thread(
                clip_store.mark_posted, DATA_DIR, item_id, target, "", note)
        except clip_store.ClipStoreError as error:
            append_log("publish", f"[{target}] บันทึกผลการโพสต์ไม่ได้: {error}")

    return {"ok": True, **result}


# ---------------------------------------------------------------- จอมือถือ (A)


def _device_rows() -> list[dict]:
    """รายชื่อมือถือที่หน้าเว็บใช้ได้เลย — ทะเบียนผสมกับสถานะสายตอนนี้

    ต้องรวมสองอย่าง เพราะแต่ละอย่างรู้คนละครึ่ง: ทะเบียนรู้ว่า "เครื่องนี้ชื่ออะไร
    เปิดใช้ไหม รับสายไหน" ส่วน adb รู้ว่า "ตอนนี้เสียบอยู่ไหม" เครื่องที่ถอดสาย
    ต้องยังโผล่ในรายการพร้อมป้ายว่าไม่ได้เสียบ ไม่ใช่หายไปเฉยๆ จนผู้ใช้นึกว่า
    ค่าที่ตั้งไว้หายด้วย
    """
    try:
        live = list_devices()
    except RuntimeError as error:
        append_log("publish", f"อ่านรายชื่อมือถือไม่ได้: {error}")
        live = []
    device_book.sync(live)                 # เครื่องใหม่เข้าทะเบียนแบบปิดไว้ก่อน
    state = {d["serial"]: d for d in live}
    rows = []
    for entry in device_book.listing():
        serial = entry["serial"]
        seen = state.get(serial, {})
        rows.append({
            **entry,
            "custom_name": entry.get("name", ""),   # ชื่อเดิมที่หน้าเว็บเก่าใช้
            "label": device_book.label(serial),
            "model": seen.get("model") or entry.get("model", ""),
            "state": seen.get("state", "offline"),
            "ready": bool(seen.get("ready")),
            "note": seen.get("note", "" if seen else "ไม่ได้เสียบอยู่"),
            "is_default": serial == device_book.default_serial(),
            "holder": phone_gate.held_by(serial),
            "job": fb_runner.running().get(serial, ""),
        })
    return rows


@app.get("/api/devices")
async def devices() -> dict:
    rows = await asyncio.to_thread(_device_rows)
    return {
        "ok": True,
        "devices": rows,
        "lanes": device_book.LANES,
        "default_serial": device_book.default_serial(),
        # หน้าเว็บใช้ตัวนี้ตัดสินว่าจะวางกี่จอ — ล้อตามเครื่องที่เปิดใช้จริง
        "enabled": [d["serial"] for d in rows if d["enabled"]],
    }


@app.post("/api/device-name")
async def set_device_name(request: Request) -> dict:
    """ตั้งชื่อเล่นให้มือถือ — โชว์แทนชื่อรุ่นใน dropdown (เก็บต่อ serial)"""
    payload = await request.json()
    serial = clean_serial(str(payload.get("serial", "")))
    name = str(payload.get("name", "")).strip()[:40]
    # เขียนลงทะเบียนเป็นหลัก — ตัวทะเบียนสะท้อนกลับไป config.device_names ให้เอง
    # เพื่อให้ `fb_limits` กับหน้าเว็บเก่าที่ยังอ่านที่นั่นไม่พังตาม
    await asyncio.to_thread(device_book.upsert, serial, name=name)
    return {"ok": True, "serial": serial, "name": name}


@app.post("/api/device")
async def save_device(request: Request) -> dict:
    """แก้ทะเบียนมือถือหนึ่งเครื่อง — เปิด/ปิด · สายงาน · บัญชี · ตัวหลัก

    ส่งมาเฉพาะฟิลด์ที่จะแก้ ตัวที่ไม่ส่งจะไม่ถูกแตะ — หน้าตั้งค่าของแต่ละจอ
    จึงบันทึกทีละช่องได้โดยไม่กลบค่าที่จออื่นเพิ่งบันทึกไป
    """
    payload = await request.json()
    serial = clean_serial(str(payload.get("serial", "")))
    fields = {}
    for key in ("name", "account", "bot_profile", "note"):
        if key in payload:
            fields[key] = str(payload.get(key) or "").strip()[:120]
    if "enabled" in payload:
        fields["enabled"] = bool(payload["enabled"])
    if "lanes" in payload:
        lanes = payload.get("lanes") or []
        fields["lanes"] = [str(x) for x in lanes if str(x) in device_book.LANES]

    def apply() -> dict:
        entry = (device_book.set_enabled(serial, fields.pop("enabled"))
                 if "enabled" in fields else device_book.get(serial))
        if fields:
            entry = device_book.upsert(serial, **fields)
        if payload.get("make_default"):
            device_book.set_default(serial)
        return entry or {}

    try:
        entry = await asyncio.to_thread(apply)
    except device_book.DeviceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "device": entry, "default_serial": device_book.default_serial()}


@app.post("/api/device/copy-settings")
async def copy_device_settings(request: Request) -> dict:
    """ปุ่ม "โหลดค่าจากเครื่องอื่น" — ก๊อปค่าตั้งข้ามจอ ไม่ก๊อปตัวตน"""
    payload = await request.json()
    source = clean_serial(str(payload.get("source", "")))
    target = clean_serial(str(payload.get("target", "")))
    keys = [str(k) for k in (payload.get("keys") or [])] or None
    try:
        merged = await asyncio.to_thread(
            device_book.copy_settings, source, target, keys
        )
    except device_book.DeviceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "settings": merged,
            "note": f"โหลดค่าจาก {device_book.label(source)} มาแล้ว"}


@app.post("/api/device/forget")
async def forget_device(request: Request) -> dict:
    """ปุ่ม − ลบจอ — เอาเครื่องออกจากทะเบียน (เสียบใหม่ก็กลับมาแบบปิดไว้)"""
    payload = await request.json()
    serial = clean_serial(str(payload.get("serial", "")))
    if fb_runner.busy_on(serial) or phone_gate.held_by(serial):
        raise HTTPException(
            status_code=409,
            detail=f"{device_book.label(serial)} กำลังทำงานอยู่ — หยุดงานก่อนค่อยลบ",
        )
    gone = await asyncio.to_thread(device_book.remove, serial)
    return {"ok": True, "removed": gone}


@app.post("/api/pick-file")
async def pick_file(request: Request) -> dict:
    """เด้งหน้าต่างเลือกไฟล์ของ Windows จริง แล้วคืน path เต็ม

    ทำได้เพราะแอปนี้รันบนเครื่องเดียวกับผู้ใช้ — เบราว์เซอร์เองให้ path เต็ม
    ไม่ได้ (ได้แค่ C:\\fakepath) จึงให้ฝั่งเซิร์ฟเวอร์เปิด dialog แทน
    รันเป็นโปรเซสแยกเพราะ tkinter ไม่ถูกกับ thread ของเซิร์ฟเวอร์
    """
    payload = await request.json()
    kinds = {
        "excel": "[('Excel/CSV', '*.xlsx *.xlsm *.csv'), ('ทุกไฟล์', '*.*')]",
        "any": "[('ทุกไฟล์', '*.*')]",
    }
    filetypes = kinds.get(str(payload.get("kind", "excel")), kinds["excel"])
    script = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "root.attributes('-topmost', True)\n"
        f"print(filedialog.askopenfilename(filetypes={filetypes}))\n"
    )

    def open_dialog() -> str:
        import sys

        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result.stdout.decode("utf-8", errors="replace").strip()

    try:
        path = await asyncio.to_thread(open_dialog)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="ไม่ได้เลือกไฟล์ภายใน 5 นาที")
    return {"ok": True, "path": path}   # path ว่าง = ผู้ใช้กดยกเลิก


# เครื่องที่เคลียร์ screenrecord ค้างไปแล้ว (ทำครั้งเดียวต่อเครื่องต่อการรัน)
_screenrecord_cleaned: set[str] = set()
# ปลุกจอครั้งล่าสุดตอนดูจอผ่านหน้าเว็บ (serial → เวลา)
_screen_view_at: dict[str, float] = {}


@app.get("/api/screen")
async def screen(serial: str) -> Response:
    """ภาพหน้าจอปัจจุบัน — PNG นิ่งทีละเฟรม รีเฟรชจากฝั่งหน้าเว็บ

    จงใจไม่ใช้ screenrecord สตรีม: บทเรียนโปรเจกต์เดิมคือโปรเซสค้างสะสม
    จนสตรีมช้าจาก 0.5 วิเป็น 25 วิ ภาพนิ่งพอสำหรับดูสถานะ + เทรนตำแหน่ง
    """
    cleaned = await asyncio.to_thread(clean_serial, serial, True)
    # ทางนี้ก็คือ "มีคนกำลังดูจอ" เหมือนกัน — ต้องกันตัวดูแลจอไม่ให้ดับจอใส่
    _watching_ping(cleaned)

    def capture() -> bytes:
        # เคลียร์ screenrecord ที่อาจค้างจากโปรเจกต์เดิม/scrcpy ครั้งเดียวต่อเครื่อง
        # ของค้างพวกนี้กินตัวเข้ารหัสจนเครื่องหนัก (วัดจริง: ภาพแรก 0.5 วิ → 25 วิ)
        if cleaned not in _screenrecord_cleaned:
            run_adb("-s", cleaned, "shell", "pkill -f screenrecord", timeout=8)
            _screenrecord_cleaned.add(cleaned)
        # ตั้งแต่มีตัวดับจออัตโนมัติ **ต้องปลุกก่อนถ่ายภาพจอ** ไม่งั้นผู้ใช้กด
        # "เริ่มดูจอ" แล้วเห็นแต่สีดำ แล้วนึกว่าระบบพัง
        #
        # เช็คทุก 10 วินาทีพอ ไม่ใช่ทุกเฟรม — เฟรมรีเฟรชถี่กว่านั้นมาก
        # ใส่ทุกเฟรมคือบวกคำสั่ง ADB เพิ่มอีกเท่าตัวโดยไม่ได้อะไร
        if time.time() - _screen_view_at.get(cleaned, 0.0) > 10.0:
            _screen_view_at[cleaned] = time.time()
            fb_screen.wake(fb_screen.make_shell(cleaned, ADB))
        result = run_adb("-s", cleaned, "exec-out", "screencap", "-p", timeout=20)
        if result.returncode != 0:
            raise RuntimeError(adb_message(result))
        frame = result.stdout
        # adb รุ่นเก่าแปลง LF→CRLF ทำ PNG พัง — อาการคือ header เป็น \x89PNG\r\r\n
        # (เช็คแค่ 4 ไบต์แรกจะปล่อยภาพเสียผ่านไปเงียบๆ)
        if frame.startswith(b"\x89PNG\r\r\n"):
            frame = frame.replace(b"\r\n", b"\n")
        if not frame.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("ข้อมูลที่ได้ไม่ใช่ PNG — เช็คเวอร์ชัน adb")
        return frame

    try:
        image = await asyncio.to_thread(capture)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=f"อ่านหน้าจอไม่ได้: {error}") from error
    return Response(content=image, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


def scale_to_device(
    serial: str, x: int, y: int, width: int, height: int
) -> tuple[int, int]:
    """แปลงพิกัดจากภาพบนเว็บเป็นพิกัดจอจริง พร้อมสลับแกนตอนจอแนวนอน

    ภาพ screencap หมุนตามเครื่อง — ถ้า orientation ของภาพต้นทางกับจอจริง
    ไม่ตรงกัน ต้องสลับ w/h ก่อนสเกล ไม่งั้นพิกัดกลับด้านทั้งจอ
    """
    real_w, real_h = screen_size(serial)
    if (width > height) != (real_w > real_h):
        real_w, real_h = real_h, real_w
    return (
        max(0, min(real_w - 1, round(x / width * real_w))),
        max(0, min(real_h - 1, round(y / height * real_h))),
    )


@app.post("/api/tap")
async def tap(request: Request) -> dict:
    payload = await request.json()
    serial = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )
    x, y = int(payload.get("x", -1)), int(payload.get("y", -1))
    width = int(payload.get("source_width", 0))
    height = int(payload.get("source_height", 0))
    if x < 0 or y < 0 or not width or not height:
        raise HTTPException(status_code=400, detail="พิกัดไม่ครบ")

    def do_tap() -> tuple[int, int]:
        real_x, real_y = scale_to_device(serial, x, y, width, height)
        result = run_adb(
            "-s", serial, "shell", "input", "tap", str(real_x), str(real_y)
        )
        if result.returncode != 0:
            # เงียบไว้ผู้ใช้จะได้ ok ทั้งที่ไม่มีอะไรเกิดขึ้นบนมือถือ
            raise RuntimeError(f"แตะไม่สำเร็จ: {adb_message(result)}")
        return real_x, real_y

    try:
        real_x, real_y = await asyncio.to_thread(do_tap)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"ok": True, "x": real_x, "y": real_y}


# ---------------------------------------------- พิมพ์ข้อความไทย (ADBKeyboard)
# ยกจากโปรเจกต์เดิมทั้งชุด — `input text` ธรรมดารับได้แค่ ASCII
# ขั้น Publish (แคปชัน/แฮชแท็ก/ลิงก์) ต้องพิมพ์ไทย จึงต้องมีทางนี้

ADB_KEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"


# คีย์บอร์ดเดิมของแต่ละเครื่องก่อนที่เราจะสลับไป ADBKeyboard
#
# **ต้องคืนให้เจ้าของเครื่องเมื่อจบงานเสมอ** ADBKeyboard ไม่มีปุ่มให้คนกด
# ถ้าทิ้งไว้ เจ้าของหยิบมือถือขึ้นมาแล้วพิมพ์อะไรไม่ได้เลย
_ime_before: dict[str, str] = {}


def adb_use_thai_keyboard(serial: str) -> bool:
    """สลับไปใช้ ADBKeyboard เพื่อพิมพ์ไทย — คืน True ถ้าพร้อมพิมพ์แล้ว

    **ต้องสลับให้เอง ไม่ใช่โยน error ทิ้ง** (แก้ 27 ส.ค. 2569)

    ของเดิมแค่ตรวจว่าคีย์บอร์ดที่ใช้อยู่ใช่ ADBKeyboard ไหม ไม่ใช่ก็โยน
    "ต้องติดตั้งและเปิดใช้ ADBKeyboard บนมือถือก่อน" ทั้งที่ **ติดตั้งไว้แล้ว**
    แค่ไม่ได้เปิดใช้ — เจอตอนไล่เดินผังจริง แฮชแท็กไทยจึงพิมพ์ไม่ลงสักตัว
    """
    current = adb_current_ime(serial)
    if current == ADB_KEYBOARD_IME:
        return True
    installed = run_adb("-s", serial, "shell", "ime", "list", "-a", "-s",
                        timeout=15).stdout.decode("utf-8", "replace")
    if ADB_KEYBOARD_IME not in installed:
        return False                    # ไม่ได้ติดตั้งไว้จริงๆ ตัวเรียกจะบอกเอง
    _ime_before.setdefault(serial, current)
    run_adb("-s", serial, "shell", "ime", "enable", ADB_KEYBOARD_IME, timeout=15)
    run_adb("-s", serial, "shell", "ime", "set", ADB_KEYBOARD_IME, timeout=15)
    time.sleep(1.0)                     # ระบบต้องใช้เวลาสลับ พิมพ์ทันทีจะหลุด
    ok = adb_current_ime(serial) == ADB_KEYBOARD_IME
    append_log("publish", f"สลับไปใช้ ADBKeyboard เพื่อพิมพ์ไทย"
                          + ("" if ok else " — สลับไม่สำเร็จ"))
    return ok


def adb_restore_keyboard(serial: str) -> None:
    """คืนคีย์บอร์ดเดิมให้เจ้าของเครื่อง — เรียกเมื่อจบงานเสมอ"""
    before = _ime_before.pop(serial, "")
    if not before or before == ADB_KEYBOARD_IME:
        return
    try:
        run_adb("-s", serial, "shell", "ime", "set", before, timeout=15)
        append_log("publish", f"คืนคีย์บอร์ดเดิมให้เครื่องแล้ว ({before.split('/')[0]})")
    except Exception as error:                                 # noqa: BLE001
        # คืนไม่ได้ต้องดัง — เจ้าของจะพิมพ์อะไรไม่ได้เลยถ้าค้างที่ ADBKeyboard
        append_log("publish", f"⚠️ คืนคีย์บอร์ดเดิมไม่สำเร็จ: {error} — "
                              f"ตั้งเองที่ ตั้งค่า > ภาษาและการป้อนข้อมูล")


def adb_current_ime(serial: str) -> str:
    result = run_adb(
        "-s", serial, "shell", "settings", "get", "secure", "default_input_method",
        timeout=10,
    )
    return result.stdout.decode("utf-8", errors="replace").strip()


def adb_use_keyboard(serial: str) -> bool:
    """สลับไป ADBKeyboard คืน False ถ้าเครื่องไม่มีตัวนี้"""
    listing = run_adb("-s", serial, "shell", "ime", "list", "-a", "-s", timeout=10)
    if ADB_KEYBOARD_IME not in listing.stdout.decode("utf-8", errors="replace"):
        return False
    run_adb("-s", serial, "shell", "ime", "enable", ADB_KEYBOARD_IME, timeout=10)
    run_adb("-s", serial, "shell", "ime", "set", ADB_KEYBOARD_IME, timeout=10)
    time.sleep(1.0)
    return adb_current_ime(serial) == ADB_KEYBOARD_IME


# คีย์บอร์ดที่สลับไปแล้วผู้ใช้พิมพ์เองไม่ได้ — ข้ามตอนหาตัวสำรอง
SKIP_IME_HINTS = ("autofill", "kdeconnect", "remotekeyboard")


def adb_normal_ime(serial: str) -> str:
    """คีย์บอร์ดปกติตัวแรกที่ **เปิดใช้อยู่** (ไม่นับ ADBKeyboard)

    ต้องใช้ `ime list -s` ห้ามใส่ `-a`: `-a` รวมคีย์บอร์ดที่ยังไม่ได้เปิดใช้มาด้วย
    แล้ว `ime set` ไปตัวที่ปิดอยู่จะเงียบไปเฉยๆ ไม่มีอะไรเปลี่ยน
    (เจอจริง — เครื่องนี้มี KDE Connect remote keyboard อยู่บนสุดของรายการ)
    """
    listing = run_adb("-s", serial, "shell", "ime", "list", "-s", timeout=10)
    for line in listing.stdout.decode("utf-8", errors="replace").splitlines():
        name = line.strip()
        if not name or ADB_KEYBOARD_IME in name:
            continue
        if any(hint in name.lower() for hint in SKIP_IME_HINTS):
            continue
        return name
    return ""


def adb_restore_ime(serial: str, original: str) -> str:
    """คืนคีย์บอร์ดเดิม แล้วคืนชื่อตัวที่ใช้อยู่จริงหลังคืนค่า

    ห้ามข้ามเมื่อ original เป็น ADBKeyboard เอง — นั่นคือกรณี "ค้างจากรอบก่อน"
    ถ้าข้ามไปมือถือจะติดอยู่กับ ADBKeyboard ตลอดไปจนพิมพ์เองไม่ได้
    """
    target = (
        original if original and original != ADB_KEYBOARD_IME
        else adb_normal_ime(serial)
    )
    if not target:
        return adb_current_ime(serial)
    run_adb("-s", serial, "shell", "ime", "set", target, timeout=10)
    time.sleep(0.8)
    return adb_current_ime(serial)


@app.post("/api/phone/keyboard/restore")
async def phone_restore_keyboard(request: Request) -> dict:
    """ปุ่มฉุกเฉิน: ปิด ADBKeyboard กลับไปใช้คีย์บอร์ดปกติของมือถือ

    มีไว้เพราะงานที่ถูกฆ่ากลางคัน (ปิดเซิร์ฟเวอร์/สายหลุด) จะไม่ได้คืนค่าคีย์บอร์ด
    แล้วมือถือพิมพ์เองไม่ได้จนกว่าจะมีคนไปสลับให้
    """
    payload = await request.json()
    serial = clean_serial(str(payload.get("serial", "")), must_be_connected=True)
    now = await asyncio.to_thread(adb_restore_ime, serial, "")
    if now == ADB_KEYBOARD_IME:
        raise HTTPException(
            status_code=500,
            detail="ยังสลับกลับไม่ได้ — เปิดคีย์บอร์ดปกติในตั้งค่ามือถือแล้วลองใหม่",
        )
    append_log("publish", f"คืนคีย์บอร์ดของ {serial} เป็น {now}")
    return {"ok": True, "ime": now, "message": f"กลับไปใช้ {now.split('/')[0]} แล้ว"}


DEFAULT_ADB_TIMEOUT = 15


def adb_type_text(serial: str, text: str) -> None:
    """พิมพ์ข้อความลงมือถือ — ไทย/อีโมจิส่งเป็น base64 ผ่าน ADBKeyboard"""
    if not text:
        return
    if not text.isascii() and adb_current_ime(serial) != ADB_KEYBOARD_IME:
        adb_use_thai_keyboard(serial)      # ติดตั้งไว้แล้วแค่ยังไม่ได้เปิดใช้
    if adb_current_ime(serial) == ADB_KEYBOARD_IME:
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        run_adb(
            "-s", serial, "shell",
            f'am broadcast -a ADB_INPUT_B64 --es msg "{encoded}"',
            timeout=15,
        )
        time.sleep(0.4)
        return
    if not text.isascii():
        raise RuntimeError(
            "พิมพ์ภาษาไทยไม่ได้ — ต้องติดตั้งและเปิดใช้ ADBKeyboard บนมือถือก่อน"
        )
    run_adb("-s", serial, "shell", "input", "text", text.replace(" ", "%s"))


# ================================================ ระบบกดหน้าจอมือถือ (ยกจากโปรเจกต์เดิม)
# ยกมาทั้งชุด: สตรีม H.264 หน่วงต่ำ · กดค้าง/ลากเรียลไทม์ผ่าน scrcpy ·
# ปุ่มลัด · พิมพ์ข้อความ — พร้อมกลไกกันนิ้วค้างที่พิสูจน์แล้วในโปรเจกต์เดิม

ADB_TOUCH_ACTIONS = {"DOWN", "MOVE", "UP", "CANCEL"}
# กันนิ้วค้างบนมือถือถาวร ถ้าหน้าเว็บปิด/สตรีมหลุดก่อนส่ง UP
ADB_HOLD_TIMEOUT_SECONDS = 60.0
ADB_KEY_EVENTS = {
    "BACK": "KEYCODE_BACK",
    "HOME": "KEYCODE_HOME",
    "RECENTS": "KEYCODE_APP_SWITCH",
    "POWER": "KEYCODE_POWER",
    "ENTER": "KEYCODE_ENTER",
    "DELETE": "KEYCODE_DEL",
    "VOLUME_UP": "KEYCODE_VOLUME_UP",
    "VOLUME_DOWN": "KEYCODE_VOLUME_DOWN",
}

_hold_timers: dict[str, threading.Timer] = {}
_hold_lock = threading.Lock()


def cancel_hold_watchdog(serial: str) -> None:
    with _hold_lock:
        timer = _hold_timers.pop(serial, None)
    if timer is not None:
        timer.cancel()


def arm_hold_watchdog(serial: str, release_touch) -> None:
    """ตั้งเวลาปล่อยนิ้วอัตโนมัติ เผื่อ UP ไม่มาถึง (ปิดแท็บ/เน็ตหลุดกลางคัน)

    ไม่งั้นมือถือค้างเหมือนมีนิ้วกดอยู่จนกว่าจะสั่ง UP ใหม่
    """
    cancel_hold_watchdog(serial)

    def release() -> None:
        with _hold_lock:
            _hold_timers.pop(serial, None)
        try:
            release_touch()
        except (RuntimeError, OSError, ValueError, scrcpy_control.ScrcpyUnavailable):
            pass

    timer = threading.Timer(ADB_HOLD_TIMEOUT_SECONDS, release)
    timer.daemon = True
    timer.start()
    with _hold_lock:
        _hold_timers[serial] = timer


def oriented_device_size(serial: str, width: int, height: int) -> tuple[int, int]:
    """ขนาดจอจริงที่หมุนให้ตรงกับภาพต้นทาง — ใช้เป็นกรอบพิกัดที่ส่งให้ scrcpy"""
    real_w, real_h = screen_size(serial)
    if width and height and (width > height) != (real_w > real_h):
        real_w, real_h = real_h, real_w
    return real_w, real_h


def device_stream_size(serial: str, max_long_edge: int = 1280) -> str | None:
    """ขนาดสตรีมที่คงสัดส่วนจริง ลดขอบยาวเหลือ ≤1280 — ลดหน่วงเข้ารหัส/ส่ง/ถอด"""
    width, height = screen_size(serial)
    long_edge = max(width, height)
    if long_edge > max_long_edge:
        scale = max_long_edge / long_edge
        width = max(2, int(width * scale)) // 2 * 2
        height = max(2, int(height * scale)) // 2 * 2
    return f"{width}x{height}"


_sdk_cache: dict[str, int | None] = {}


def device_sdk_level(serial: str) -> int | None:
    if serial in _sdk_cache:
        return _sdk_cache[serial]
    level: int | None = None
    try:
        result = run_adb(
            "-s", serial, "shell", "getprop", "ro.build.version.sdk", timeout=6
        )
        match = re.search(r"\d{1,3}", result.stdout.decode("utf-8", errors="replace"))
        if match:
            level = int(match.group(0))
    except RuntimeError:
        pass
    _sdk_cache[serial] = level
    return level


def device_supports_hold(serial: str) -> bool:
    """`input motionevent` (กดค้างจริง) มีตั้งแต่ Android 10 (SDK 29) ขึ้นไป

    อ่านเวอร์ชันไม่ได้ = ถือว่าไม่รองรับ ดีกว่าเดาผิดแล้วกดไม่ติดโดยไม่มีสัญญาณ
    """
    level = device_sdk_level(serial)
    return level is not None and level >= 29


def h264_start_codes(buffer: bytearray) -> list[tuple[int, int]]:
    starts: list[tuple[int, int]] = []
    index = 0
    while index <= len(buffer) - 3:
        if index <= len(buffer) - 4 and buffer[index:index + 4] == b"\x00\x00\x00\x01":
            starts.append((index, 4))
            index += 4
        elif buffer[index:index + 3] == b"\x00\x00\x01":
            starts.append((index, 3))
            index += 3
        else:
            index += 1
    return starts


def _close_reason(text: str, limit: int = 120) -> str:
    """ข้อความปิด WebSocket ยาวได้ไม่เกิน 123 ไบต์ตามมาตรฐาน

    ภาษาไทยตัวละ 3 ไบต์ ถ้าส่งยาวเกินเฟรมปิดจะเสียรูปแล้วเบราว์เซอร์จะได้
    รหัส 1006 (หลุดผิดปกติ) แทนรหัสจริง — กลายเป็นซ่อนสาเหตุอีกชั้นหนึ่ง
    """
    raw = str(text or "").encode("utf-8")[:limit]
    return raw.decode("utf-8", "ignore")


def _websocket_is_local(websocket: WebSocket) -> bool:
    host = websocket.client.host if websocket.client else ""
    return host in {"127.0.0.1", "::1", "localhost"}


def _websocket_is_allowed(websocket: WebSocket) -> bool:
    """เครื่องหลัก **หรือ** เครื่องที่อนุมัติแล้ว เปิดท่อเร็วได้

    เดิมด่านนี้รับแค่ 127.0.0.1 เขียนไว้ตั้งแต่ commit แรก (13 ส.ค. 2569)
    ตอนที่ยังไม่มีระบบอนุมัติเครื่อง พอมีระบบแล้วไม่มีใครกลับมาต่อให้
    ผลคือคอมเครื่องที่สองซึ่ง **อนุมัติผ่านแล้ว** ถูกไล่ตั้งแต่ยังไม่ทันเปิดท่อ
    แล้วตกไปใช้ภาพนิ่งเงียบๆ โดยหน้าเว็บโทษว่าเบราว์เซอร์ไม่รองรับ

    วัดจริง 25 ส.ค. 2569 จากคอมเครื่องที่สอง: ภาพนิ่ง 1,380 ms/ภาพ ·
    ท่อวิดีโอ 169 ms/ภาพ = ช้ากว่า 8 เท่า · ท่อนิ้วก็โดนกฎเดียวกัน
    ทำให้ส่งได้ ~50 ครั้ง/วินาที แทนที่จะเป็น 120-240

    **ไม่ได้เปิดสิทธิ์อะไรใหม่** — เครื่องที่อนุมัติแล้วดูจอและแตะจอได้อยู่ก่อนแล้ว
    ผ่าน /api/screen · /api/phone/touch · /api/phone/swipe ซึ่งไม่มีด่านนี้กั้น
    ด่านนี้จึงกันได้แค่ "ความเร็ว" ไม่ได้กัน "สิทธิ์" — เป็นด่านที่ทำร้ายเจ้าของ
    โดยไม่กันใครเลย ใบเดียวกับหน้าเว็บ (gate_remote_devices) คือใบที่ถูกต้อง
    """
    if _websocket_is_local(websocket):
        return True
    token = websocket.cookies.get(
        access_control.ACCESS_COOKIE, ""
    ) or websocket.headers.get(access_control.ACCESS_TOKEN_HEADER, "")
    record = access_store.find_by_token(token)
    return bool(record and record.get("status") == "approved")


@app.post("/api/phone/session")
async def phone_session(request: Request) -> dict:
    """เปิดช่องทางเรียลไทม์ล่วงหน้าตอนกดเริ่มดูจอ

    push ไฟล์ + สตาร์ต scrcpy-server กินเวลาหลักวินาที ถ้าไปทำตอนแตะครั้งแรก
    ผู้ใช้จะรู้สึกว่าคลิกแรกหน่วง
    """
    payload = await request.json()
    serial = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )
    if not scrcpy_control.is_available():
        return {"ok": True, "realtime": False, "reason": "ไม่พบ scrcpy-server"}
    try:
        name = await asyncio.to_thread(scrcpy_control.ensure_session, ADB, serial)
    except scrcpy_control.ScrcpyUnavailable as error:
        return {"ok": True, "realtime": False, "reason": str(error)}
    return {"ok": True, "realtime": True, "device_name": name}


@app.post("/api/phone/touch")
async def phone_touch(request: Request) -> dict:
    """กดค้าง/ลากแบบเรียลไทม์ — นิ้วค้างบนมือถือจริงตราบใดที่ยังไม่ปล่อยเมาส์

    ทางหลักคือ scrcpy-server (ฉีด MotionEvent ตรง เร็วระดับนิ้วจริง)
    ใช้ไม่ได้ค่อยถอยไป `input motionevent` ซึ่งช้ากว่ามาก (~30 event/วินาที)
    """
    payload = await request.json()
    action = str(payload.get("action", "")).strip().upper()
    if action not in ADB_TOUCH_ACTIONS:
        raise HTTPException(status_code=400, detail="ไม่รองรับการกดแบบนี้")
    serial = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )
    width = int(payload.get("source_width", 0))
    height = int(payload.get("source_height", 0))
    if not width or not height:
        raise HTTPException(status_code=400, detail="ต้องส่งขนาดภาพต้นทางมาด้วย")
    x, y = await asyncio.to_thread(
        scale_to_device, serial, int(payload.get("x", 0)), int(payload.get("y", 0)),
        width, height,
    )

    def send() -> dict:
        frame = oriented_device_size(serial, width, height)
        if scrcpy_control.is_available():
            try:
                scrcpy_control.send_touch(ADB, serial, action, x, y, *frame)
            except scrcpy_control.ScrcpyUnavailable:
                pass
            else:
                if action in ("DOWN", "MOVE"):
                    arm_hold_watchdog(
                        serial,
                        lambda: scrcpy_control.send_touch(
                            ADB, serial, "UP", x, y, *frame
                        ),
                    )
                else:
                    cancel_hold_watchdog(serial)
                return {"ok": True, "supported": True, "realtime": True}
        if not device_supports_hold(serial):
            return {"ok": True, "supported": False}
        run_adb("-s", serial, "shell", "input", "motionevent", action, str(x), str(y))
        if action in ("DOWN", "MOVE"):
            arm_hold_watchdog(
                serial,
                lambda: run_adb(
                    "-s", serial, "shell", "input", "motionevent", "UP", str(x), str(y)
                ),
            )
        else:
            cancel_hold_watchdog(serial)
        return {"ok": True, "supported": True, "realtime": False}

    return await asyncio.to_thread(send)


@app.post("/api/phone/key")
async def phone_key(request: Request) -> dict:
    """กดปุ่มบนมือถือ — ทางที่แม่นกว่าการลากนิ้วเสมอ

    วางตัวชี้ข้อความด้วยการลากนิ้วต้องอาศัยภาพที่ทันนิ้ว ซึ่งผ่านสายไม่มีวันเท่า
    จอจริง ส่วนปุ่มเลื่อนทีละตัวอักษร **แม่น 100% ไม่ว่าภาพจะช้าแค่ไหน**
    """
    payload = await request.json()
    name = str(payload.get("key", "")).strip()
    keycode = scrcpy_control.KEYCODES.get(name)
    # **ปุ่มระบบอยู่คนละตาราง** BACK · HOME · RECENTS · POWER · VOLUME_* ส่งผ่าน
    # ช่อง scrcpy ไม่ได้ ต้องใช้ `input keyevent` ของ Android
    #
    # ของเดิมมี endpoint ที่รู้จักปุ่มพวกนี้อยู่จริง แต่ประกาศ /api/phone/key
    # **ซ้ำสองรอบ** FastAPI หยิบตัวแรกไปใช้ ตัวหลังจึงเป็นโค้ดตายที่ไม่เคยถูกเรียก
    # ผลคือปุ่มลัดบนหน้าเว็บ 5 จาก 6 ปุ่มตอบ 400 มาตลอดโดยไม่มีใครรู้
    # (วัดจริง 25 ส.ค. 2569: POWER · HOME · RECENTS · VOLUME_UP · VOLUME_DOWN
    #  ตอบ "ไม่รู้จักปุ่ม" ทั้งหมด เหลือ back ตัวเดียวที่ใช้ได้)
    android_key = ADB_KEY_EVENTS.get(name.upper()) if keycode is None else None
    if keycode is None and android_key is None:
        raise HTTPException(status_code=400, detail=f"ไม่รู้จักปุ่ม “{name}”")
    serial = await asyncio.to_thread(clean_serial, str(payload.get("serial", "")), True)
    meta = scrcpy_control.META_CTRL if payload.get("ctrl") else 0
    repeat = max(1, min(int(payload.get("repeat", 1) or 1), 50))

    def press() -> dict:
        if android_key is not None:
            for _ in range(repeat):
                run_adb("-s", serial, "shell", "input", "keyevent", android_key)
            return {"ok": True, "realtime": False}
        if scrcpy_control.is_available():
            try:
                session = scrcpy_control._get_or_open(ADB, serial)
                for _ in range(repeat):
                    session.send_key(keycode, meta)
                return {"ok": True, "realtime": True}
            except scrcpy_control.ScrcpyUnavailable:
                pass
        # ทางถอย: ช้ากว่ามาก (วัดจริง ~155 ms/ครั้ง) และสั่ง CTRL ร่วมไม่ได้
        if meta:
            raise HTTPException(status_code=503,
                                detail="ต้องใช้ scrcpy ถึงจะกดปุ่มพร้อม Ctrl ได้")
        for _ in range(repeat):
            run_adb("-s", serial, "shell", "input", "keyevent", str(keycode))
        return {"ok": True, "realtime": False}

    return await asyncio.to_thread(press)


@app.post("/api/phone/caption")
async def phone_caption(request: Request) -> dict:
    """ใส่ข้อความลงช่องที่โฟกัสอยู่บนมือถือ

    `replace=True` คือเลือกทั้งหมดแล้วทับ — ทางที่ทำให้ **ไม่ต้องกดค้างแล้วลาก
    ตัวชี้ให้ตรงตำแหน่งอีกเลย** ซึ่งเป็นงานที่ทำผ่านสายแล้วทรมานที่สุด

    ผู้ใช้ต้องแตะช่องบนจอให้โฟกัสก่อน — เราไม่เดาตำแหน่งช่องให้ เพราะเดาผิด
    แล้วข้อความจะไปโผล่ผิดที่ ซึ่งแย่กว่าไม่ทำอะไรเลย
    """
    payload = await request.json()
    text = str(payload.get("text", ""))
    if not text.strip():
        raise HTTPException(status_code=400, detail="ยังไม่ได้พิมพ์ข้อความ")
    serial = await asyncio.to_thread(clean_serial, str(payload.get("serial", "")), True)
    replace = bool(payload.get("replace", True))

    def send() -> dict:
        if not scrcpy_control.is_available():
            raise HTTPException(status_code=503,
                                detail="ต้องใช้ scrcpy — ข้อความไทยส่งทาง input text ไม่ได้")
        try:
            session = scrcpy_control._get_or_open(ADB, serial)
            how = session.replace_all(text) if replace else session.type_text(text)
        except scrcpy_control.ScrcpyUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {"ok": True, "how": how, "chars": len(text)}

    return await asyncio.to_thread(send)


@app.websocket("/ws/phone/input")
async def phone_input_socket(websocket: WebSocket, serial: str) -> None:
    """ช่องส่งการแตะ/ลากแบบต่อค้าง

    ยิง HTTP ทีละ event ได้แค่ ~50 ครั้ง/วินาที ต่ำกว่านิ้วจริงมาก (120-240)
    ช่องนี้ตัดค่าใช้จ่ายต่อ request ทิ้ง และ socket ขาดก็ปล่อยนิ้วทันที
    ไม่ต้องรอ watchdog 60 วินาที
    """
    if not _websocket_is_allowed(websocket):
        await websocket.close(code=1008, reason="เครื่องนี้ยังไม่ได้รับอนุญาต")
        return
    await websocket.accept()
    try:
        cleaned = await asyncio.to_thread(clean_serial, serial, True)
    except HTTPException as error:
        # **ต้องติดเหตุผลไปกับการปิดท่อด้วย** ของเดิมปิดเปล่าๆ ด้วยรหัส 1008
        # หน้าเว็บจึงขึ้นได้แค่ "สตรีมหลุด (รหัส 1008)" ซึ่งบอกอะไรไม่ได้เลย
        # แล้วยังไปต่อใหม่ซ้ำอีก 3 ครั้งทั้งที่เครื่องไม่ได้เสียบสายอยู่
        # ใช้รหัส 4404 (ช่วงของแอปเอง) เพื่อให้ฝั่งหน้าเว็บแยกออกว่า
        # "เครื่องไม่พร้อม" ต่างจาก "ท่อสะดุด" — อันแรกต่อใหม่ไปก็เท่านั้น
        await websocket.send_json({"error": error.detail})
        await websocket.close(code=4404, reason=_close_reason(error.detail))
        return
    if not scrcpy_control.is_available():
        await websocket.send_json({"error": "ยังไม่มีช่องทางสัมผัสเรียลไทม์"})
        await websocket.close(code=1011)
        return

    pressed: tuple[int, int, int, int] | None = None
    try:
        while True:
            message = await websocket.receive_json()
            action = str(message.get("action", "")).strip().upper()
            if action not in ADB_TOUCH_ACTIONS:
                continue
            width = int(message.get("source_width", 0))
            height = int(message.get("source_height", 0))
            if not width or not height:
                continue
            frame = await asyncio.to_thread(
                oriented_device_size, cleaned, width, height
            )
            x, y = await asyncio.to_thread(
                scale_to_device, cleaned, int(message.get("x", 0)),
                int(message.get("y", 0)), width, height,
            )
            await asyncio.to_thread(
                scrcpy_control.send_touch, ADB, cleaned, action, x, y, *frame
            )
            pressed = (x, y, *frame) if action in ("DOWN", "MOVE") else None
    except (
        WebSocketDisconnect, ConnectionError, RuntimeError, ValueError,
        HTTPException, scrcpy_control.ScrcpyUnavailable,
    ):
        return
    finally:
        # ปิดแท็บ/หลุดกลางคันระหว่างกดค้าง ต้องปล่อยนิ้วทันที
        if pressed is not None:
            try:
                await asyncio.to_thread(
                    scrcpy_control.send_touch, ADB, cleaned, "UP", *pressed
                )
            except scrcpy_control.ScrcpyUnavailable:
                pass


# ---------------------------------------------- ใครกำลังดูจอเครื่องไหนอยู่
#
# **ทำไมต้องจด** ตัวดูแลจอ (`_screen_pump_one`) เช็คก่อนดับจอไว้ 5 ชั้น — งานโพสต์ ·
# งานตั้งเวลา · ล็อกไฟล์ · ประตูจอ · เวลาที่มือถือไม่ถูกแตะ — แต่**ไม่มีชั้นไหน
# รู้เลยว่ามีคนนั่งดูจออยู่ผ่านหน้าเว็บ** เพราะการนั่งดูเฉยๆ ไม่ได้แตะจอ มือถือจึง
# นับว่าไม่มีคนใช้ แล้วดับจอใส่หน้าคนที่กำลังดูอยู่ทุก 3 นาที
# (เห็นในบันทึกคืน 22 ส.ค. 2569: "ดับจอมือถือแล้ว" ซ้ำๆ ตลอดคืน)
#
# จดทั้งสองทางที่หน้าเว็บใช้ดูจอ — ท่อวิดีโอ และการถ่ายรูปทีละใบ
_watching: dict[str, float] = {}
_watching_lock = threading.Lock()
WATCHING_GRACE_SECONDS = 12.0     # ไม่มีสัญญาณเกินเท่านี้ = เลิกดูแล้ว
MAX_STREAM_REVIVALS = 5           # ปลุกช่องวิดีโอคืนได้กี่ครั้งก่อนยอมแพ้
STREAM_HANDOVER_SECONDS = 3.0     # รอรุ่นก่อนออกจากลูปนานสุดเท่าไรก่อนเดินหน้า
STREAM_SUPERSEDED_CODE = 4409     # รหัสปิดที่แปลว่า "มีคนอื่นมาดูแทนแล้ว อย่าต่อใหม่"
STREAM_TAKEOVER_COOLDOWN = 10.0   # เปลี่ยนมือได้ถี่สุดเท่าไร (กันผลัดกันเตะออก)
# **ช่วงตั้งท่อ** — ตั้งแต่ได้สิทธิ์จนภาพเริ่มไหลใช้เวลาจริงหลายวินาที
# (ปลุกจอ → ถามขนาดจอ → ล้างของค้าง → เปิดช่อง scrcpy) ถ้าช่วงนี้ยังนับว่า
# "ไม่มีใครดูอยู่" คนถัดไปจะแทรกเข้ามาได้ทันทีแล้วแย่งตัวเข้ารหัสกันเหมือนเดิม
# วัดจริง 27 ส.ค. 2569: คนที่สองเข้ามาตอนวินาทีที่ 4 แล้ว **ได้สิทธิ์ไปทั้งที่
# คนแรกยังตั้งท่ออยู่** — ด่านจึงเหมือนไม่มีอยู่จริง
#
# ตั้งเป็นเวลาหมดอายุ ไม่ใช่ธงค้าง เพื่อไม่ให้เครื่องถูกล็อกถาวรถ้าคนตั้งท่อ
# ล้มกลางคัน (เช่น adb ค้าง) — แย่สุดคือรอ 20 วินาทีแล้วปล่อยเอง
STREAM_SETUP_GRACE = 20.0

# ---- หนึ่งเครื่อง = หนึ่งช่องวิดีโอ ----------------------------------------
#
# **รากเหง้าที่ไล่เจอ 27 ส.ค. 2569** มือถือมีตัวเข้ารหัสวิดีโอ **ชุดเดียว**
# (เขียนไว้เองแล้วที่ scrcpy_control.py — "ตัวเข้ารหัสมีชุดเดียว") แต่ไม่มีด่านไหน
# กันไม่ให้เปิดช่องที่สองต่อเครื่อง พอเปิดสองช่องมันแย่งตัวเข้ารหัสกันจนตัวหนึ่งหลุด
#
# ที่ทำให้กลายเป็นวนไม่จบคือ **มีสองระบบกู้คืนที่ไม่รู้จักกัน**
#     ฝั่งเซิร์ฟเวอร์  ปลุกช่องคืนเองสูงสุด MAX_STREAM_REVIVALS ครั้ง
#     ฝั่งหน้าเว็บ     ต่อ WebSocket ใหม่เองเมื่อท่อปิด (phone.js)
# หลุดหนึ่งครั้งจึงได้ช่องใหม่ **สองช่อง** → แย่งกันอีก → หลุดอีก → วนไม่จบ
#
# วัดจริงตอน 13:57 น. — มือถือ 3 เครื่องมี forward ของ scrcpy อยู่ 5 ช่อง
# (สองเครื่องมีเครื่องละ 2 ช่อง) และบันทึกเซิร์ฟเวอร์นับ "scrcpy พร้อม" ได้ 795 ครั้ง
#
# ทางแก้ที่รากคือ **ให้มีเจ้าของช่องได้ทีละคน** ใครมาใหม่ได้สิทธิ์ไป ส่วนคนเก่า
# ถูกปิดด้วยรหัสถาวรเพื่อไม่ให้หน้าเว็บต่อกลับมาแย่งอีก (ไม่งั้นจะกลายเป็นผลัดกัน
# เตะออกไปมาไม่จบ ซึ่งแย่กว่าเดิม)
_stream_generation: dict[str, int] = {}   # รุ่นล่าสุดที่ได้สิทธิ์ดูจอเครื่องนั้น
_stream_running: dict[str, int] = {}      # ตอนนี้มีลูปสตรีมวิ่งอยู่กี่ตัว
_stream_video: dict[str, object] = {}     # ช่องวิดีโอที่รุ่นล่าสุดถืออยู่
_stream_handover_at: dict[str, float] = {}  # เปลี่ยนมือครั้งล่าสุดเมื่อไร
_stream_claim_at: dict[str, float] = {}   # ได้สิทธิ์ล่าสุดเมื่อไร (ใช้คุมช่วงตั้งท่อ)
_stream_gate = threading.Lock()


def _stream_claim(serial: str, *, force: bool = False) -> int:
    """ขอสิทธิ์ดูจอเครื่องนี้ — คืนหมายเลขรุ่น หรือ 0 ถ้ายังไม่ถึงคิว

    **แย่งจอได้เฉพาะตอนคนกดปุ่มเอง** (`force`) การต่อใหม่อัตโนมัติของหน้าเว็บ
    ไม่มีสิทธิ์ — ไม่งั้นแท็บที่เปิดค้างทิ้งไว้จะคอยดึงจอกลับไปเรื่อยๆ ทั้งที่
    ไม่มีคนนั่งดู แล้วคนที่กำลังใช้งานจริงจะถูกเตะออกเป็นระยะโดยไม่รู้สาเหตุ
    วัดจริง 27 ส.ค. 2569: แท็บค้างแท็บเดียวดันให้เปิดช่องใหม่ 6.1 ครั้ง/นาที
    (ปกติควรเปิดเฉพาะตอนคนกด = เกือบ 0)

    หน้าเว็บรุ่นเก่าที่ค้างในเบราว์เซอร์ไม่รู้จักธงนี้ จึงกลายเป็นไม่มีพิษภัย
    โดยอัตโนมัติ — ไม่ต้องไล่ปิดทีละแท็บ

    **ต้องมีช่วงพักระหว่างการเปลี่ยนมือ** ไม่งั้นสองหน้าต่างที่ต่างคนต่างต่อใหม่
    อัตโนมัติจะผลัดกันเตะกันออกด้วยความเร็วสูงสุดที่เครื่องทำได้ ซึ่ง **แย่กว่า
    ตอนไม่มีด่านเสียอีก** — วัดจริง 27 ส.ค. 2569 ตอนใส่ด่านแต่ยังไม่มีช่วงพัก
    เปิดช่องใหม่พุ่งเป็น 24 ครั้ง/นาที เทียบกับก่อนใส่ด่าน 1.13 ครั้ง/นาที
    (ตัวเลขก่อนแก้จากเลน video: 12:40 น. 708 ครั้ง → 13:57 น. 795 ครั้ง)

    กติกาจึงเป็น: **ไม่มีใครดูอยู่ = ให้เลย** (กรณีรีเฟรชหน้าเว็บ ซึ่งพบบ่อยสุด)
    ส่วน **มีคนดูอยู่ = แย่งได้ แต่ห้ามถี่กว่าทุก STREAM_TAKEOVER_COOLDOWN วินาที**
    คนที่มาไม่ทันได้รหัสปิดถาวรกลับไป จะได้ไม่ต่อวนอีก
    """
    now = time.time()
    with _stream_gate:
        # "มีคนดูอยู่" = กำลังดูจริง **หรือ** เพิ่งได้สิทธิ์ไปแล้วยังตั้งท่อไม่เสร็จ
        busy = (_stream_running.get(serial, 0) > 0
                or now - _stream_claim_at.get(serial, 0.0) < STREAM_SETUP_GRACE)
        if busy and not force:
            return 0
        if busy and (now - _stream_handover_at.get(serial, 0.0)
                     < STREAM_TAKEOVER_COOLDOWN):
            return 0
        if busy:
            _stream_handover_at[serial] = now
        _stream_claim_at[serial] = now
        generation = _stream_generation.get(serial, 0) + 1
        _stream_generation[serial] = generation
        old = _stream_video.pop(serial, None)
    # ปิดช่องของรุ่นก่อนทันที ไม่ต้องรอให้มันรู้ตัวเอง — ตัวเข้ารหัสจะได้ว่าง
    # ให้รุ่นใหม่ทันที ปิดซ้ำไม่เป็นไร close() ของ scrcpy ทนการเรียกซ้ำอยู่แล้ว
    if old is not None:
        with contextlib.suppress(Exception):
            old.close()
    return generation


def _stream_is_current(serial: str, generation: int) -> bool:
    with _stream_gate:
        return _stream_generation.get(serial, 0) == generation


def _stream_enter(serial: str) -> None:
    with _stream_gate:
        _stream_running[serial] = _stream_running.get(serial, 0) + 1


def _stream_leave(serial: str, generation: int = 0) -> None:
    with _stream_gate:
        left = _stream_running.get(serial, 0) - 1
        if left > 0:
            _stream_running[serial] = left
        else:
            _stream_running.pop(serial, None)
        # ออกหมดแล้ว = เครื่องว่างจริง อย่าให้ "ช่วงตั้งท่อ" ค้างกั้นคนถัดไป
        # **แต่ต้องเป็นรุ่นล่าสุดเท่านั้น** คนที่เพิ่งถูกเตะออกห้ามมาล้างของ
        # คนที่มาแทน ไม่งั้นคนใหม่จะเสียเกราะช่วงตั้งท่อไปทั้งที่ยังตั้งไม่เสร็จ
        if left <= 0 and _stream_generation.get(serial, 0) == generation:
            _stream_claim_at.pop(serial, None)


def _stream_running_count(serial: str) -> int:
    with _stream_gate:
        return _stream_running.get(serial, 0)


def _stream_hold(serial: str, generation: int, video: object) -> None:
    """จดว่าช่องนี้เป็นของรุ่นไหน — รุ่นเก่าที่โดนเตะแล้วห้ามมาจดทับ"""
    with _stream_gate:
        if _stream_generation.get(serial, 0) == generation:
            _stream_video[serial] = video


def _stream_drop(serial: str, generation: int) -> None:
    with _stream_gate:
        if _stream_generation.get(serial, 0) == generation:
            _stream_video.pop(serial, None)


def _watching_start(serial: str) -> None:
    with _watching_lock:
        _watching[serial] = time.time()


def _watching_ping(serial: str) -> None:
    """ทางถ่ายรูปทีละใบไม่มีการเชื่อมต่อค้างไว้ — ต่ออายุทุกครั้งที่ขอภาพ"""
    _watching_start(serial)


def _watching_stop(serial: str) -> None:
    with _watching_lock:
        _watching.pop(serial, None)


def someone_watching(serial: str) -> bool:
    with _watching_lock:
        last = _watching.get(serial, 0.0)
    return (time.time() - last) < WATCHING_GRACE_SECONDS


@app.get("/api/phone/queue")
async def phone_queue_board() -> dict:
    """กระดานคิวจอมือถือ — ใครถือจออยู่ ใครรอ รอมานานเท่าไร

    **ทำไมต้องขึ้นหน้าเว็บ** ของเดิมดูได้จากบรรทัดคำสั่งอย่างเดียว ซึ่งแปลว่า
    เจ้าของต้องนึกได้เองว่าต้องไปพิมพ์ดู — บทเรียนเดิมของโปรเจกต์นี้บอกไว้แล้วว่า
    อะไรที่ต้องพึ่งความจำ สุดท้ายไม่มีใครทำ (เรื่อง `claims: 0`)
    """
    def read() -> dict:
        import phone_queue                                      # noqa: PLC0415
        rows = []
        for group in phone_queue.board():
            serial = group["device"]
            run = group["running"]
            rows.append({
                "serial": serial,
                "label": device_book.label(serial),
                "running": None if not run else {
                    "owner": run["owner"], "task": run["task"],
                    "seconds": time.time() - (run["started_at"] or run["created_at"]),
                    "ticket": run["id"],
                },
                "waiting": [{
                    "owner": row["owner"], "task": row["task"],
                    "seconds": time.time() - row["created_at"], "ticket": row["id"],
                } for row in group["waiting"]],
            })
        return {"ok": True, "devices": rows}

    try:
        return await asyncio.to_thread(read)
    except Exception as error:                                  # noqa: BLE001
        # กระดานพังต้องไม่ทำให้หน้าเว็บทั้งหน้าพัง — คืนว่างพร้อมเหตุผล
        return {"ok": False, "devices": [], "error": str(error)}


@app.websocket("/ws/phone/stream")
async def phone_stream(websocket: WebSocket, serial: str, take: str = "") -> None:
    """สตรีมหน้าจอ H.264 หน่วงต่ำ — ฝั่งหน้าเว็บถอดด้วย WebCodecs"""
    if not _websocket_is_allowed(websocket):
        await websocket.close(code=1008, reason="เครื่องนี้ยังไม่ได้รับอนุญาต")
        return
    await websocket.accept()
    try:
        cleaned = await asyncio.to_thread(clean_serial, serial, True)
    except HTTPException as error:
        # **ต้องติดเหตุผลไปกับการปิดท่อด้วย** ของเดิมปิดเปล่าๆ ด้วยรหัส 1008
        # หน้าเว็บจึงขึ้นได้แค่ "สตรีมหลุด (รหัส 1008)" ซึ่งบอกอะไรไม่ได้เลย
        # แล้วยังไปต่อใหม่ซ้ำอีก 3 ครั้งทั้งที่เครื่องไม่ได้เสียบสายอยู่
        # ใช้รหัส 4404 (ช่วงของแอปเอง) เพื่อให้ฝั่งหน้าเว็บแยกออกว่า
        # "เครื่องไม่พร้อม" ต่างจาก "ท่อสะดุด" — อันแรกต่อใหม่ไปก็เท่านั้น
        await websocket.send_json({"error": error.detail})
        await websocket.close(code=4404, reason=_close_reason(error.detail))
        return

    # ---- ขอสิทธิ์ดูจอก่อนแตะอะไรทั้งนั้น ----
    # ต้องอยู่ **ก่อน** ปลุกจอและก่อนเปิดช่องวิดีโอ ไม่งั้นสองรุ่นจะไปสั่ง
    # `pkill -f screenrecord` ใส่กันเองระหว่างที่อีกฝั่งกำลังเปิดช่องอยู่พอดี
    generation = _stream_claim(cleaned, force=take not in ("", "0", "false"))
    if not generation:
        # เพิ่งเปลี่ยนมือไปหมาดๆ — ปฏิเสธด้วยรหัสถาวรเพื่อหยุดวงจรผลัดกันเตะ
        await websocket.close(
            code=STREAM_SUPERSEDED_CODE,
            reason="มีหน้าต่างอื่นกำลังดูจอเครื่องนี้อยู่")
        return
    # รอรุ่นก่อนออกจากลูปให้เรียบร้อย — ตัวเข้ารหัสบนมือถือมีชุดเดียว
    # เปิดซ้อนตอนที่ตัวเก่ายังไม่ปล่อย = ได้ช่องที่เปิดไม่ขึ้นหรือภาพเสีย
    deadline = time.time() + STREAM_HANDOVER_SECONDS
    while _stream_running_count(cleaned) and time.time() < deadline:
        await asyncio.sleep(0.1)

    # **ต้องปลุกจอก่อนสตรีม** — ตั้งแต่มีตัวดับจออัตโนมัติ ถ้าไม่ปลุก
    # `screenrecord` จะได้แต่ภาพดำ ผู้ใช้กด "เริ่มดูจอ" แล้วเห็นจอว่างเปล่า
    # แล้วนึกว่าระบบพัง (เจอจริงตอนเทสใน Chrome 18 ส.ค. — ครั้งแรกใส่ไว้แค่
    # ทาง screencap ซึ่งเป็นทางสำรอง ไม่ใช่ทางที่หน้าเว็บใช้จริง)
    await asyncio.to_thread(
        lambda: fb_screen.wake(fb_screen.make_shell(cleaned, ADB))
    )
    stream_size = await asyncio.to_thread(device_stream_size, cleaned)
    size_arguments = ["--size", stream_size] if stream_size else []

    # ฆ่า screenrecord ที่ค้างบนมือถือก่อนเริ่มสตรีมใหม่เสมอ
    # ของค้างสะสมแย่งตัวเข้ารหัสกัน (วัดจริง: ค้าง 2 สตรีม → ภาพแรก 25 วิ,
    # ล้างแล้วเหลือ 0.5 วิ)
    await asyncio.to_thread(
        lambda: run_adb("-s", cleaned, "shell", "pkill -f screenrecord", timeout=8)
    )
    await asyncio.sleep(0.4)

    # ---- ทางหลัก: ช่องวิดีโอของ scrcpy ----
    # `screenrecord` เป็นเครื่องมือ "อัดวิดีโอ" ไม่ใช่ "มิเรอร์" มันบัฟเฟอร์เพื่อให้ไฟล์สวย
    # และมีเพดาน 175 วินาทีต้องรีสตาร์ตเรื่อยๆ ส่วน scrcpy ออกแบบมาเพื่อมิเรอร์โดยตรง
    # วัดจริง 20 ส.ค. 2026 เครื่องเดียวกัน: เฟรมแรก 1,166 ms -> 84 ms (เร็วกว่า 14 เท่า)
    # เปิดไม่ได้ก็ถอยไป screenrecord เหมือนเดิม ไม่ปล่อยให้จอดำ
    video = None
    if scrcpy_control.is_available():
        try:
            video = await asyncio.to_thread(
                scrcpy_control.open_video, ADB, cleaned, 1024, 30)
            _live_scids.setdefault(cleaned, set()).add(getattr(video, "scid", ""))
            # จดว่าช่องนี้เป็นของรุ่นเรา — ถ้าระหว่างที่เปิดอยู่มีรุ่นใหม่มาแทน
            # การจดจะไม่เกิดขึ้น แล้วด่านต้นลูปข้างล่างจะพาเราออกไปเองทันที
            _stream_hold(cleaned, generation, video)
            print(f"[stream] scrcpy พร้อม {video.width}x{video.height}", flush=True)
        except scrcpy_control.ScrcpyUnavailable as error:
            # app.py ไม่มี logger — เขียนลง stdout ซึ่ง restart_studio ต่อเข้า
            # data/server.log ไว้แล้ว (เคยพลาดเรียก logger ตรงนี้จน endpoint พังทั้งตัว)
            print(f"[stream] เปิดช่องวิดีโอ scrcpy ไม่ได้ ถอยไป screenrecord: {error}",
                  flush=True)
            video = None

    receive_task = asyncio.create_task(websocket.receive())
    process: subprocess.Popen | None = None
    revivals = 0
    _watching_start(cleaned)
    _stream_enter(cleaned)
    try:
        while True:
            process = None if video is not None else subprocess.Popen(
                [
                    ADB, "-s", cleaned, "exec-out", "screenrecord",
                    "--output-format=h264", *size_arguments,
                    "--bit-rate", "4000000", "--time-limit", "175", "-",
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if video is not None:
                # scrcpy คืนมาเป็นแพ็กเก็ตที่ตัดหัวออกแล้ว เป็น Annex-B ล้วน
                # จึงป้อนเข้าตรรกะตัด NAL ข้างล่างได้เหมือนกันเป๊ะ ไม่ต้องแก้อะไรต่อ
                def read_available() -> bytes:
                    return video.read_available()
            else:
                if process.stdout is None:
                    raise RuntimeError("เปิดสตรีมหน้าจอไม่สำเร็จ")

                # อ่านเท่าที่มีจริง ไม่รอจนครบบล็อก — จอที่นิ่งข้อมูลไหลทีละน้อย
                # ถ้ารอครบ 16KB คีย์เฟรมแรกจะค้างใน pipe หลายวินาทีก่อนโผล่
                # (อาการที่เจอจริง: ได้แค่ SPS+PPS 27 ไบต์แล้วเงียบ)
                stream_fd = process.stdout.fileno()

                def read_available() -> bytes:
                    try:
                        return os.read(stream_fd, 16384)
                    except OSError:
                        return b""

            buffer = bytearray()
            while True:
                # ---- ด่านสละสิทธิ์ ----
                # มีหน้าต่างอื่นมาขอดูจอเครื่องนี้แล้ว = เราต้องออกทันที
                # **ห้ามสู้กลับ** ถ้าเราต่อใหม่อีกจะกลายเป็นผลัดกันเตะออกไม่จบ
                # ปิดด้วยรหัสถาวรเพื่อบอกหน้าเว็บว่า "อย่าต่อกลับมา"
                if not _stream_is_current(cleaned, generation):
                    with contextlib.suppress(Exception):
                        await websocket.close(
                            code=STREAM_SUPERSEDED_CODE,
                            reason="มีหน้าต่างอื่นเปิดดูจอเครื่องนี้แทนแล้ว")
                    return
                read_task = asyncio.create_task(asyncio.to_thread(read_available))
                done, _ = await asyncio.wait(
                    {read_task, receive_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if receive_task in done:
                    read_task.cancel()
                    return
                chunk = read_task.result()
                if not chunk:
                    # ช่อง scrcpy: ว่างเปล่าแปลว่า "จอยังไม่ขยับ" ไม่ใช่ "ช่องปิด"
                    # ตีความผิดตรงนี้จะกลายเป็นวนเปิดสตรีมใหม่ไม่หยุด ซึ่งเป็นบั๊ก
                    # เดียวกับที่เพิ่งไล่แก้ใน screenrecord
                    if video is not None and video.alive:
                        continue
                    break
                if video is not None:
                    # ---- ทาง scrcpy: ส่งทันที ห้ามกั๊กก้อนสุดท้ายไว้ ----
                    #
                    # **บั๊กที่แก้อยู่ตรงนี้** ของเดิมใช้เงื่อนไข `len(starts) >= 2`
                    # คือจะยอมส่งภาพที่ i ก็ต่อเมื่อ *หัวของภาพที่ i+1* มาถึงแล้ว
                    # ผลคือภาพล่าสุดค้างอยู่ในเซิร์ฟเวอร์เสมอ — ผู้ใช้กดปุ่มบนหน้าเว็บ
                    # มือถือทำทันที แต่ภาพผลลัพธ์ไม่ถูกส่งจนกว่าจอจะขยับอีกครั้ง
                    # และจอที่นิ่งส่งภาพแค่ ~1.4 ใบ/วินาที (ตัวเลขจาก read_available)
                    # = หน่วงได้เป็นวินาที ทั้งที่ท่อว่างและเร็วอยู่แล้ว
                    #
                    # `read_available()` ของ scrcpy คืน **แพ็กเก็ตสมบูรณ์ทีละก้อน**
                    # (รู้ความยาวจากหัวแพ็กเก็ต) จึงตัด NAL ได้ครบทุกก้อนรวมก้อน
                    # สุดท้าย ไม่ต้องรออะไรทั้งนั้น
                    #
                    # ยังตัดทีละ NAL เหมือนเดิมเพราะฝั่งหน้าเว็บแยก SPS/PPS/ภาพ
                    # ด้วยไบต์แรกของแต่ละข้อความ ถ้าส่งรวมก้อนเดียวจะแยกไม่ออก
                    starts = h264_start_codes(chunk)
                    if not starts:
                        await websocket.send_bytes(bytes(chunk))
                    for index, (position, _) in enumerate(starts):
                        end = (starts[index + 1][0] if index + 1 < len(starts)
                               else len(chunk))
                        await websocket.send_bytes(bytes(chunk[position:end]))
                    continue

                # ---- ทาง screenrecord (ทางถอย): เป็นสายไบต์ล้วน ----
                # ทางนี้ไม่มีขอบเขตแพ็กเก็ตให้ยึด จึงยังต้องเห็นหัวของก้อนถัดไป
                # ก่อนถึงจะรู้ว่าก้อนนี้จบตรงไหน — กั๊กหนึ่งก้อนเป็นราคาที่เลี่ยงไม่ได้
                buffer.extend(chunk)
                starts = h264_start_codes(buffer)
                while len(starts) >= 2:
                    position = starts[0][0]
                    end = starts[1][0]
                    await websocket.send_bytes(bytes(buffer[position:end]))
                    del buffer[:end]
                    starts = [(s - end, size) for s, size in starts[1:]]

            if buffer:
                await websocket.send_bytes(bytes(buffer))
            # ทางนี้เขียนไว้ตอนมีแต่ `screenrecord` ซึ่งจบเองทุก 175 วินาทีแล้ว
            # วนกลับไปเปิดใหม่ พอเพิ่มทาง scrcpy เข้ามา `process` เป็น None
            # แต่บรรทัดนี้ยังเรียก `.wait()` ตรงๆ — หลุดเป็น AttributeError ที่
            # `except` ข้างล่างไม่ได้จับ ผลคือ socket ตายแล้วหน้าเว็บถอยไปใช้
            # ภาพนิ่ง **โดยไม่มีใครรู้ว่าทำไม** (เจอในบันทึกเซิร์ฟเวอร์ 21 ส.ค.)
            #
            # ทางถอยที่กลบความผิดพลาดของตัวเองไว้ อันตรายกว่าไม่มีทางถอยเลย
            if process is not None:
                process.wait(timeout=2)
                process = None
            elif video is None or not video.alive:
                # **ห้ามเงียบ** ของเดิม break ทิ้งเฉยๆ หน้าเว็บเลยตกไปใช้ภาพนิ่ง
                # ถาวรโดยไม่มีใครรู้ว่าเพราะอะไร (ภาพนิ่งช้ากว่าท่อวิดีโอ ~9 เท่า:
                # วัดจริง 1,500 ms/ภาพ เทียบกับ 169 ms) — ต้องบอกให้รู้เสมอ
                # ช่องปิดเพราะ "มีคนอื่นมาดูแทน" ไม่ใช่ความผิดพลาด — ห้ามปลุกคืน
                # และห้ามเขียนบันทึกให้รก (นี่คือบรรทัดที่เคยท่วม log 795 ครั้ง)
                if not _stream_is_current(cleaned, generation):
                    with contextlib.suppress(Exception):
                        await websocket.close(
                            code=STREAM_SUPERSEDED_CODE,
                            reason="มีหน้าต่างอื่นเปิดดูจอเครื่องนี้แทนแล้ว")
                    return
                print(f"[stream] ช่องวิดีโอของ {cleaned} ปิดตัว "
                      f"(ปลุกคืนมาแล้ว {revivals} ครั้ง)", flush=True)
                if revivals >= MAX_STREAM_REVIVALS:
                    print(f"[stream] ปลุกครบ {revivals} ครั้งแล้วยังไม่อยู่ — ยอมแพ้",
                          flush=True)
                    break
                revivals += 1
                with contextlib.suppress(Exception):
                    _live_scids.get(cleaned, set()).discard(getattr(video, "scid", ""))
                    await asyncio.to_thread(video.close)
                try:
                    video = await asyncio.to_thread(
                        scrcpy_control.open_video, ADB, cleaned, 1024, 30)
                    _live_scids.setdefault(cleaned, set()).add(getattr(video, "scid", ""))
                    _stream_hold(cleaned, generation, video)
                    print(f"[stream] ปลุกช่องวิดีโอคืนแล้ว (ครั้งที่ {revivals}) "
                          f"{video.width}x{video.height}", flush=True)
                except scrcpy_control.ScrcpyUnavailable as error:
                    print(f"[stream] ปลุกช่องวิดีโอไม่ขึ้น: {error}", flush=True)
                    break
            await asyncio.sleep(0.15)
    except (WebSocketDisconnect, ConnectionError, RuntimeError):
        return
    finally:
        _watching_stop(cleaned)
        # คืนสิทธิ์เสมอ ไม่ว่าออกทางไหน — ถ้าลืมคืน คนถัดไปจะต้องรอครบ
        # STREAM_HANDOVER_SECONDS ทุกครั้งโดยไม่มีใครรู้ว่าเพราะอะไร
        _stream_drop(cleaned, generation)
        _stream_leave(cleaned, generation)
        receive_task.cancel()
        if video is not None:
            _live_scids.get(cleaned, set()).discard(getattr(video, "scid", ""))
            await asyncio.to_thread(video.close)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        # **ต้องฆ่าตัวที่รันอยู่บนมือถือด้วย** — `terminate()` ข้างบนฆ่าได้แค่ `adb`
        # ฝั่งคอม ส่วน `screenrecord` บนเครื่องยังวิ่งต่อจนครบ 175 วินาทีของมันเอง
        # โค้ดเดิมมี pkill แค่ตอน "เริ่ม" สตรีม จึงดูเหมือนปกติเวลาเปิดดูใหม่
        # แต่ถ้าปิดหน้าเว็บแล้วไม่เปิดอีก ตัวบนมือถือจะค้างกินตัวเข้ารหัสเงียบๆ
        # (วัดจริง 20 ส.ค. 2026: ปิด socket แล้วยังเหลือ screenrecord ค้างบนเครื่อง
        #  ของค้างแบบนี้เคยทำภาพแรกช้าจาก 0.5 วิ เป็น 25 วิ)
        try:
            await asyncio.to_thread(
                lambda: run_adb("-s", cleaned, "shell", "pkill -f screenrecord", timeout=8)
            )
        except Exception:              # noqa: BLE001 - เก็บกวาดล้มไม่ควรทำ endpoint พัง
            pass


@app.post("/api/phone/wake")
async def phone_wake(request: Request) -> dict:
    """ปลุกจอมือถือให้ติด + ปัดหน้าล็อกออก — **ไม่ใช่ปุ่มสลับเปิด/ปิด**

    ทิ้งเครื่องไว้นานจอดับเอง แล้วคนที่มาแตะจอต่อจะกดลงบนจอดำโดยไม่รู้ตัว
    ปุ่ม ⏻ ของเดิมส่ง POWER ซึ่ง "สลับ" — จอติดอยู่แล้วกดคือดับ จึงต้องมีตัวที่
    สั่งให้ "ติด" อย่างเดียว ใช้ได้โดยไม่ต้องเดาว่าตอนนี้จออยู่สถานะไหน

    ใช้ `fb_screen.wake` ตัวเดียวกับที่ขั้นโพสต์ใช้ — ปลุกแล้ว **ยืนยันว่าแตะจอ
    ได้จริง** ไม่ใช่สั่งแล้วเชื่อว่าติด (สั่งอย่างเดียวเคยได้จอดำแล้วบอทกดมั่วต่อ)
    """
    payload = await request.json()
    serial = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )

    def work() -> dict:
        # งานจรที่แค่มาปลุกจอ **ห้ามเข้าแถว** ไม่งั้นไปแทรกหน้างานจริง (กติกาข้อ 9)
        with studio_shared.phone_lock(
            serial, label="ปลุกจอจากหน้าเว็บ", queue=False
        ):
            shell = fb_screen.make_shell(serial, ADB)
            before = fb_screen.wakefulness(shell)
            woke = fb_screen.wake(shell, log=lambda text: append_log("publish", text))
            return {
                "ok": bool(woke),
                "before": before or "ไม่รู้",
                "after": fb_screen.wakefulness(shell) or "ไม่รู้",
            }

    result = await asyncio.to_thread(work)
    if not result["ok"]:
        # **ห้ามตอบ ok แล้วปล่อยผ่าน** ปลุกไม่ขึ้นแต่บอกว่าสำเร็จ = คนไปสั่งงานต่อ
        # บนจอดำแล้วงงว่าทำไมไม่มีอะไรเกิดขึ้น
        raise HTTPException(
            status_code=502,
            detail=f"ปลุกจอไม่ขึ้น (ตอนนี้: {result['after']}) — เช็คสาย/สิทธิ์ debugging",
        )
    return result


# ======================================= สุขภาพหน่วยความจำมือถือ + เคลียร์เอง
#
# **ทำไมต้องโชว์** 25 ส.ค. 2569 มือถือขึ้น "หน่วยความจำไม่พอ" ตอนเปิดแอป
# ไล่หาสาเหตุอยู่นานเพราะไม่มีตัวเลขให้ดูเลย ต้องต่อ ADB เข้าไปอ่านเอง
# ตัวเลขจริงตอนนั้น: แรมว่าง 0.11 GB จาก 5.52 GB · ถูกดันไปไว้ที่ช้า 1.39 GB
# ส่วนเนื้อที่เก็บของว่างตั้ง 85 GB — **คนละเรื่องกันคนละตัว ต้องแยกให้เห็นทั้งคู่**
#
# **ทำไมต้องเคลียร์เอง** ล้างด้วยมือได้แรมคืน 0.64 GB (ว่าง 0.11 -> 0.75 GB)
# แต่เดี๋ยวก็เต็มอีก ปล่อยไว้คือรอให้พังแล้วค่อยมาไล่ใหม่ทุกครั้ง
#
# **ห้ามเคลียร์ทับงานที่กำลังทำ** เคลียร์คือ force-stop แอป ถ้าไปตัดกลางงานโพสต์
# จะได้โพสต์ครึ่งใบแล้วต้องมาตามเก็บเอง จึงต้อง **กดบัตรคิวปกติ** (กติกาข้อ 9)
# ให้รอจนงานที่ทำอยู่จบก่อน แล้วค่อยเคลียร์ แล้วคิวถัดไปค่อยเดินต่อ
PHONE_HEALTH_TTL = 20.0            # อ่านซ้ำถี่กว่านี้ไม่ได้อะไร มีแต่ทำให้ ADB อ่วม
PHONE_HEALTH_ROUND = 180.0         # ตัวเฝ้าวนตรวจทุกกี่วินาที
PHONE_CLEAN_COOLDOWN = 30 * 60.0   # ล้างแล้วอย่าเพิ่งล้างซ้ำ ให้เวลาเครื่องตั้งตัว
PHONE_CLEAN_WAIT = 1800.0          # รอคิวมือถือได้นานสุด (งานโพสต์หนึ่งใบไม่เกินนี้)
_phone_health_cache: dict[str, tuple[float, dict]] = {}
_phone_health_lock = threading.Lock()
_phone_cleaned_at: dict[str, float] = {}
_phone_cleaning: set[str] = set()
# ล้างแล้วได้คืนน้อยกว่านี้ (GB) ถือว่า "ล้างไปก็เท่านั้น" แล้วถอยห่างขึ้นเรื่อยๆ
PHONE_CLEAN_MIN_GAIN = 0.10
# swap สูงจะนับว่า "เต็ม" ก็ต่อเมื่อแรมตึงด้วย — ต่ำกว่านี้ถือว่าเครื่องยังสบาย
PHONE_SWAP_RAM_FLOOR = 60
# ตัวถ่ายจอที่ "มีคนดูอยู่จริง" ตอนนี้ แยกรายเครื่อง — ตัวที่ไม่อยู่ในนี้คือของค้าง
_live_scids: dict[str, set[str]] = {}
PHONE_CLEAN_BACKOFF_MAX = 12       # 30 นาที x 12 = 6 ชั่วโมงเป็นอย่างมาก
_phone_clean_backoff: dict[str, int] = {}


def _phone_full_pct() -> int:
    """เพดานที่ถือว่า 'เต็ม' — ผู้ใช้กำหนด 90% ไว้ 25 ส.ค. 2569

    อ่านจาก config เพื่อให้จูนได้โดยไม่ต้องแก้โค้ด — วัดจริงวันนั้นแรมใช้ไป 67%
    ตอนที่เครื่องเริ่มบ่นแล้ว ถ้า 90 ไม่เคยเข้าเงื่อนไขเลยให้ลดลงได้ทันที
    """
    try:
        value = int(load_config().get("phone_full_pct", 90))
    except (TypeError, ValueError):
        return 90
    return max(50, min(99, value))


def _phone_swap_limit() -> float:
    """ของที่ถูกยัดลงที่ช้าเกินกี่ GB ถึงเรียกว่าเต็ม — เจ้าของสั่ง 1 GB"""
    try:
        value = float(load_config().get("phone_swap_limit_gb", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return max(0.2, min(8.0, value))


def _parse_meminfo(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if parts and parts[0].isdigit():
            out[key.strip()] = int(parts[0]) / 1024 / 1024      # GB
    return out


def _read_phone_health(serial: str, *, force: bool = False) -> dict:
    """แรม + เนื้อที่ของมือถือเครื่องหนึ่ง — มีแคชกันยิง ADB ถี่เกิน

    เครื่องที่มีคนถือจออยู่จะคืนของในแคชพร้อมธง `busy` **ไม่แย่งจอ** เพราะแค่มาดู
    ตัวเลข ไม่คุ้มกับการไปขวางงานจริง (กติกาข้อ 9 — งานจรห้ามเข้าแถว)
    """
    now = time.time()
    with _phone_health_lock:
        cached = _phone_health_cache.get(serial)
    if cached and not force and now - cached[0] < PHONE_HEALTH_TTL:
        return cached[1]

    data: dict = {"serial": serial, "at": now, "busy": False}
    try:
        with studio_shared.phone_lock(
            serial, timeout=3.0, poll=0.5, label="อ่านหน่วยความจำมือถือ", queue=False
        ):
            shell = fb_phone_clean.make_shell(serial, ADB)
            mem = _parse_meminfo(shell("cat /proc/meminfo"))
            disk = shell("df -k /data | tail -1") or ""
    except Exception as error:              # noqa: BLE001 - เครื่องไม่ว่าง/ถอดสาย
        if cached:
            stale = dict(cached[1])
            stale["busy"] = True
            return stale
        return {**data, "ok": False, "why": str(error)[:120]}

    total = mem.get("MemTotal", 0.0)
    avail = mem.get("MemAvailable", 0.0)
    swap_total = mem.get("SwapTotal", 0.0)
    swap_free = mem.get("SwapFree", 0.0)
    parts = disk.split()
    disk_total = disk_free = 0.0
    if len(parts) >= 4 and parts[1].isdigit() and parts[3].isdigit():
        disk_total = int(parts[1]) / 1024 / 1024
        disk_free = int(parts[3]) / 1024 / 1024

    ram_pct = round((total - avail) * 100 / total) if total else 0
    disk_pct = round((disk_total - disk_free) * 100 / disk_total) if disk_total else 0
    limit = _phone_full_pct()
    data.update({
        "ok": True,
        "ram_pct": ram_pct,
        "ram_free_gb": round(avail, 2),
        "ram_total_gb": round(total, 2),
        # แรมที่ถูกดันไปเก็บในที่ช้า — เยอะแปลว่าเครื่องหายใจไม่ทันแล้ว
        "swap_used_gb": round(max(0.0, swap_total - swap_free), 2),
        "disk_pct": disk_pct,
        "disk_free_gb": round(disk_free, 1),
        "disk_total_gb": round(disk_total, 1),
        "limit": limit,
        "ram_full": ram_pct >= limit,
        "disk_full": disk_pct >= limit,
        "cleaning": serial in _phone_cleaning,
    })
    # **เลข % อย่างเดียวไม่พอ** วัดจริง 25 ส.ค. 2569: ตอนเครื่องขึ้น
    # "หน่วยความจำไม่พอ" แรมใช้ไปแค่ 67% — เพราะพอแรมจะเต็ม Android จะยัดของ
    # ลง swap (พื้นที่เก็บของซึ่งช้ากว่าแรมสิบเท่า) เสียก่อนทุกที เลข % จึงวนอยู่
    # 65-70% ตลอดและไม่มีวันแตะ 90 ที่ตั้งไว้
    #
    # ตัวที่บอกความจริงคือ **ของที่ถูกยัดลง swap ไปแล้วเท่าไร** — ตอนเครื่องบ่น
    # คือ 1.39 GB · หลังล้างลงมาเหลือ 1.31 GB แล้วไต่กลับขึ้นไปเรื่อยๆ
    # เจ้าของจึงสั่ง (25 ส.ค. 2569) ให้เพิ่มเงื่อนไข "เกิน 1 GB = เคลียร์"
    swap_limit = _phone_swap_limit()
    data["swap_limit_gb"] = swap_limit
    # **ต้องดูคู่กับแรมด้วย** ตัวเลข swap เป็น "ประวัติ" ไม่ใช่ "สภาพตอนนี้" —
    # Linux ไม่ดึงของกลับขึ้นแรมจนกว่าจะมีคนเรียกใช้ ล้างเครื่องเสร็จแล้ว swap จึง
    # ค้างสูงอยู่ทั้งที่แรมโล่งแล้ว ถ้าดู swap อย่างเดียวจะสั่งล้างซ้ำไม่จบ
    #
    # จุดตัด 60% มาจากของจริงสองจุด (25 ส.ค. 2569 เครื่องเดียวกัน):
    #   ตอนขึ้น "หน่วยความจำไม่พอ"  แรม 67% · swap 1.39 GB  -> ต้องล้าง
    #   หลังกวาดตัวส่งภาพค้าง       แรม 55% · swap 1.19 GB  -> สบายแล้ว ไม่ต้องล้าง
    data["swap_full"] = (data["swap_used_gb"] >= swap_limit
                         and ram_pct >= PHONE_SWAP_RAM_FLOOR)
    data["need_clean"] = bool(
        data["ram_full"] or data["disk_full"] or data["swap_full"]
    )
    data["why_clean"] = (
        f"แรม {ram_pct}% ถึงเพดาน {limit}%" if data["ram_full"]
        else f"เนื้อที่ {disk_pct}% ถึงเพดาน {limit}%" if data["disk_full"]
        else f"ของถูกยัดลงที่ช้า {data['swap_used_gb']} GB เกิน {swap_limit} GB"
        if data["swap_full"] else ""
    )
    data["text"] = (f"แรม {ram_pct}% (ว่าง {data['ram_free_gb']} GB) · "
                    f"เก็บของ {disk_pct}% (ว่าง {data['disk_free_gb']} GB) · "
                    f"ที่ช้า {data['swap_used_gb']}/{swap_limit} GB")
    with _phone_health_lock:
        _phone_health_cache[serial] = (now, data)
    return data


def _clean_phone_when_free(serial: str) -> None:
    """เคลียร์เครื่องหนึ่งเครื่อง — **ต่อคิวปกติ รองานที่ทำอยู่ให้จบก่อน**"""
    import phone_queue                                          # noqa: PLC0415
    label = device_book.label(serial)
    _phone_cleaning.add(serial)
    try:
        why = (_read_phone_health(serial).get("why_clean") or "").strip()
        append_log("publish", f"หน่วยความจำ {label} เต็ม"
                              + (f" ({why})" if why else "")
                              + " — ขอคิวเพื่อเคลียร์ ถ้ามีงานทำอยู่จะรอให้จบก่อน")
        with phone_queue.slot(serial, owner="ตัวเฝ้าหน่วยความจำ",
                              task="เคลียร์แรม/เนื้อที่", lane="ดูแลเครื่อง",
                              timeout=PHONE_CLEAN_WAIT):
            before = _read_phone_health(serial, force=True)
            fb_phone_clean.clean(serial, adb=ADB,
                                 log=lambda text: append_log("publish", text))
            after = _read_phone_health(serial, force=True)
        _phone_cleaned_at[serial] = time.time()
        # **ล้างแล้วไม่ดีขึ้น = อย่าล้างซ้ำถี่ๆ** (หลักการโปรเจกต์: retry ต้องเปลี่ยน
        # อะไรบางอย่าง ไม่ใช่ยิงของเดิมซ้ำ) วัดจริง 25 ส.ค. 2569: เครื่องแรม 5.52 GB
        # ที่ต้องเปิด Shopee ค้างไว้ 574 MB ล้างแล้วคืนได้แค่ ~0.01 GB เพราะของที่
        # กินอยู่คือแอปงานกับระบบซึ่งปิดไม่ได้ — ปล่อยไว้จะกลายเป็นล้างทุก 30 นาที
        # ตลอดไปโดยไม่ได้อะไร กินเวลาเครื่องและรบกวนคิวมือถือเปล่าๆ
        gain = (after.get("ram_free_gb", 0) - before.get("ram_free_gb", 0)) \
            + (before.get("swap_used_gb", 0) - after.get("swap_used_gb", 0))
        if gain < PHONE_CLEAN_MIN_GAIN:
            old = _phone_clean_backoff.get(serial, 1)
            _phone_clean_backoff[serial] = min(old * 2, PHONE_CLEAN_BACKOFF_MAX)
            extra = f" · ได้คืนแค่ {gain:.2f} GB จึงเว้นรอบหน้ายาวขึ้นเป็น " \
                    f"{PHONE_CLEAN_COOLDOWN * _phone_clean_backoff[serial] / 60:.0f} นาที"
        else:
            _phone_clean_backoff[serial] = 1
            extra = f" · ได้คืน {gain:.2f} GB"
        append_log("publish",
                   f"เคลียร์ {label} เสร็จ — แรม {before.get('ram_pct')}% → "
                   f"{after.get('ram_pct')}% · ที่ช้า {before.get('swap_used_gb')} → "
                   f"{after.get('swap_used_gb')} GB{extra}")
    except Exception as error:              # noqa: BLE001
        # **ห้ามเงียบ** เคลียร์ไม่สำเร็จแล้วไม่บอก = เครื่องเต็มต่อไปโดยไม่มีใครรู้
        append_log("publish", f"เคลียร์ {label} ไม่สำเร็จ: {error}")
    finally:
        _phone_cleaning.discard(serial)


def _phone_memory_round() -> None:
    for row in _device_rows():
        serial = row.get("serial", "")
        if not serial or row.get("ready") is False or not row.get("enabled", True):
            continue
        if serial in _phone_cleaning:
            continue
        # ไล่ตัวถ่ายจอที่ไม่มีคนดูออกก่อนเสมอ — ทำได้เร็วและไม่รบกวนใคร
        # จึงไม่ต้องรอให้แรมเต็มก่อน (ของค้าง 12 ตัวเคยกินไป 596 MB)
        try:
            with studio_shared.phone_lock(
                serial, timeout=3.0, poll=0.5, label="ไล่ตัวถ่ายจอค้าง", queue=False
            ):
                gone = _sweep_idle_streamers(serial)
            if gone:
                append_log("publish", f"ไล่ตัวถ่ายจอที่ไม่มีคนดูบน "
                                      f"{device_book.label(serial)} — {gone} ตัว")
        except studio_shared.PhoneBusy:
            pass                            # เครื่องไม่ว่าง = เรื่องปกติ ข้ามรอบนี้เงียบได้
        except Exception as error:          # noqa: BLE001
            # **ห้ามเงียบ** ของเดิมกลืนทุก error ไว้หมด ทำให้ตัวไล่พังเงียบได้โดย
            # ไม่มีใครรู้ — เกิดจริง 26 ส.ค. 2569: ตัวไล่ไม่ทำงาน 3 ชั่วโมงเต็ม
            # จนมีของค้าง 20 ตัวบนเครื่องเดียว แต่ log ไม่มีสักบรรทัดให้ไล่
            append_log("publish", f"ไล่ตัวถ่ายจอค้างบน "
                                  f"{device_book.label(serial)} ไม่สำเร็จ: {error}")
        wait = PHONE_CLEAN_COOLDOWN * _phone_clean_backoff.get(serial, 1)
        if time.time() - _phone_cleaned_at.get(serial, 0.0) < wait:
            continue
        health = _read_phone_health(serial)
        if health.get("ok") and health.get("need_clean") and not health.get("busy"):
            threading.Thread(target=_clean_phone_when_free, args=(serial,),
                             daemon=True).start()


def _sweep_orphan_streamers() -> None:
    """กวาดตัวส่งภาพหน้าจอที่ค้างบนมือถือจากรอบก่อน — ทำครั้งเดียวตอนเปิดเซิร์ฟเวอร์

    **รากเหง้าที่เพิ่งเจอ 25 ส.ค. 2569** ตอนปิดสตรีมโค้ดสั่ง `pkill -f scid=<id>`
    ฆ่าตัวบนมือถือถูกต้องอยู่แล้ว **แต่ตอนรีสตาร์ตเซิร์ฟเวอร์มันตายก่อนได้สั่ง**
    ตัวบนมือถือจึงค้างอยู่ตัวหนึ่งต่อการรีสตาร์ตหนึ่งครั้ง

    วัดจริงวันนั้น: รีสตาร์ตไป 7 รอบ เหลือค้าง 5 ตัว ตัวละราว 166 MB
    กวาดทิ้งแล้วแรมที่ใช้ได้เพิ่มขึ้น **0.64 GB** ซึ่งมากกว่าปิด Shopee (0.59 GB)
    — ของค้างของเราเองคือตัวกินแรมอันดับหนึ่งของเครื่องมาตลอดโดยไม่มีใครรู้

    **ทำตอนเปิดเซิร์ฟเวอร์เท่านั้น** เพราะตอนนั้นยังไม่มีสตรีมของเราสักตัว
    อะไรที่ค้างอยู่จึงเป็นของรอบก่อนแน่นอน ถ้าไปกวาดตอนอื่นจะไปตัดคนที่ดูจออยู่
    และเจาะจงชื่อไฟล์ jar ของเราเอง ไม่แตะ scrcpy ตัวจริงที่ผู้ใช้อาจเปิดไว้
    """
    time.sleep(8)              # รอ ADB ตั้งตัวก่อน อย่ายิงตอนเซิร์ฟเวอร์เพิ่งเปิด
    # **จับด้วยชื่อคลาส ไม่ใช่ชื่อไฟล์ jar** — ชื่อไฟล์ส่งผ่าน CLASSPATH ไม่ได้อยู่
    # ในบรรทัดคำสั่ง `pkill -f scrcpy-server-webapp.jar` จึงไม่เคยแมตช์อะไรเลย
    # (เสียเวลาไล่อยู่พักหนึ่ง — บรรทัดจริงคือ
    #  "app_process / com.genymobile.scrcpy.Server 4.1 scid=... video=true ...")
    #
    # ปลอดภัยเพราะทำ **ตอนเปิดเซิร์ฟเวอร์เท่านั้น** ยังไม่มีสตรีมของเราสักตัว
    # ถ้าผู้ใช้เปิด scrcpy ตัวจริงบนคอมค้างไว้พอดีจะโดนด้วย — ยอมรับได้ เพราะเปิดใหม่
    # ได้ทันที ส่วนของค้างที่ปล่อยไว้กินแรมมือถือถาวรจนเครื่องบ่นว่าหน่วยความจำไม่พอ
    mark = "com.genymobile.scrcpy.Server"
    try:
        rows = _device_rows()
    except Exception as error:              # noqa: BLE001
        append_log("publish", f"กวาดตัวส่งภาพค้างไม่ได้ (อ่านรายชื่อเครื่องไม่ออก): {error}")
        return
    for row in rows:
        serial = row.get("serial", "")
        if not serial or row.get("ready") is False:
            continue
        try:
            with studio_shared.phone_lock(
                serial, timeout=5.0, poll=0.5,
                label="กวาดตัวส่งภาพค้าง", queue=False,
            ):
                shell = fb_phone_clean.make_shell(serial, ADB)
                # **นับจากชื่อโปรเซส ไม่ใช่ชื่อไฟล์** — `ps -A` บน Android โชว์แค่
                # ชื่อโปรเซสซึ่งคือ "app_process" ไม่ได้โชว์บรรทัดคำสั่งเต็ม
                # ส่วน `pkill -f` มองบรรทัดคำสั่งเต็มได้ จึงเจาะจง jar ของเราได้
                def count() -> int:
                    out = shell("ps -A | grep app_process") or ""
                    return len([l for l in out.splitlines() if l.strip()])

                before = count()
                if not before:
                    continue
                # pkill บน Android ฆ่าได้ทีละตัว ต้องวนจนไม่มีอะไรตายเพิ่ม
                # มีเพดานรอบไว้เสมอ ห้ามวนไม่จบ (กติกาโปรเจกต์)
                left = before
                for _ in range(10):
                    shell(f'pkill -f "{mark}"')
                    time.sleep(1.0)
                    now = count()
                    if now >= left:
                        break
                    left = now
                killed = before - left
                if killed > 0:
                    append_log("publish",
                               f"กวาดตัวส่งภาพหน้าจอที่ค้างจากรอบก่อนบน "
                               f"{device_book.label(serial)} — {killed} ตัว")
        except Exception as error:          # noqa: BLE001
            append_log("publish", f"กวาดตัวส่งภาพค้างบน {serial} ไม่สำเร็จ: {error}")


def _adb_forward_scids() -> set[str]:
    """`scid` ของช่องต่อที่ ADB ยืนยันว่ายังเปิดอยู่จริง — ทุกเครื่องรวมกัน

    อ่านจาก `adb forward --list` ซึ่งเป็นทะเบียนของ ADB เอง ไม่ใช่ของเรา จึงไม่
    เพี้ยนตามความจำที่ค้างของเซิร์ฟเวอร์ แต่ละบรรทัดหน้าตาแบบนี้

        7a95129e tcp:53234 localabstract:scrcpy_4f8e5825

    อ่านไม่ได้ให้คืนเซตว่าง แล้วให้ผู้เรียกถอยไปใช้ทะเบียนในหน่วยความจำแทน —
    **ห้ามคืนเซตว่างแล้วปล่อยให้ผู้เรียกไล่ทุกตัวทิ้ง** เพราะ ADB สะดุดชั่วคราว
    จะกลายเป็นจอดับหมดทุกหน้าเว็บพร้อมกัน
    """
    out = ""
    with contextlib.suppress(Exception):
        done = subprocess.run(                              # noqa: S603
            [ADB, "forward", "--list"], capture_output=True, text=True,
            errors="replace", timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = done.stdout or ""
    mark = "localabstract:scrcpy_"
    return {line.rsplit(mark, 1)[1].strip()
            for line in out.splitlines() if mark in line}


def _sweep_idle_streamers(serial: str) -> int:
    """ไล่ตัวถ่ายจอบนมือถือที่ **ไม่มีใครดูแล้ว** ออก — เก็บเฉพาะตัวที่ใช้งานอยู่จริง

    **ทำไมตัวกวาดตอนบูตอย่างเดียวไม่พอ** วัดจริง 26 ส.ค. 2569: เปิดหน้าเว็บค้างไว้
    หลายที่พร้อมกัน (คอมหลัก + คอมสอง + ไอแพด รวม 34 การเชื่อมต่อ) ทุกหน้าสั่งเปิด
    ตัวถ่ายจอของตัวเอง สะสมได้ **12 ตัวบนเครื่องเดียว กินแรม 596 MB** ภายในไม่กี่นาที
    ตัวกวาดตอนบูตช่วยไม่ได้เลยเพราะของพวกนี้เกิดหลังบูต

    **ห้ามไล่มั่ว** ตัวที่หน้าเว็บกำลังใช้ดูอยู่จริงต้องไม่โดน จึงเทียบด้วย `scid`
    ซึ่งเป็นรหัสประจำตัวที่เราตั้งตอนเปิด — ตัวไหนไม่มีชื่ออยู่ในทะเบียนคือของค้าง
    (ช่องแตะจอใช้ scrcpy คนละตัวและมี scid ของมันเอง ต้องนับเป็นของใช้งานด้วย)

    **ห้ามเชื่อทะเบียนในหน่วยความจำอย่างเดียว** วัดจริง 26 ส.ค. 2569 เวลา 18:25 น.:
    เครื่อง Xiaomi มีตัวถ่ายจอ 11 ชุด (22 โปรเซส) แต่ช่องต่อที่ยังใช้งานจริงมี
    **ชุดเดียว** — อีก 10 ชุดค้างอยู่โดยที่ `_live_scids` ยังจำว่า "มีคนดู"
    ตัวไล่จึงไม่แตะเลยสักตัวตลอด 3 ชั่วโมง (ไม่มีบรรทัด "ไล่ตัวถ่ายจอ" ใน
    publish.log แม้แต่ครั้งเดียว) เพราะทะเบียนนี้**โตอย่างเดียว ไม่เคยหด**
    เมื่อหน้าเว็บหลุดแบบผิดปกติจนโค้ดคืนของไม่ทัน

    ตัวชี้ขาดจึงต้องเป็นของที่ **ADB ยืนยันเอง** ไม่ใช่ความจำของเรา: ตัวถ่ายจอที่ยัง
    มีคนดูจริงต้องมีช่องต่อ `localabstract:scrcpy_<scid>` เปิดค้างอยู่เสมอ
    (`scrcpy_control` เปิดให้ตอนต่อ และถอนตอนปิด) ไม่มีช่องต่อ = ไม่มีใครดูแน่นอน
    ต่อให้ทะเบียนจะยังจำชื่อมันอยู่ก็ตาม
    """
    live = _adb_forward_scids()
    with contextlib.suppress(Exception):
        session = scrcpy_control._sessions.get(serial)      # noqa: SLF001
        if session is not None:
            live.add(str(getattr(session, "scid", "")))
    # ทะเบียนในหน่วยความจำใช้เป็น "ตัวช่วยกันพลาด" เท่านั้น — ถ้าช่องต่ออ่านไม่ได้
    # (ADB สะดุด) จะได้ไม่ไล่ของที่ยังใช้อยู่ทิ้งทั้งยวง
    if not live:
        live = set(_live_scids.get(serial, set()))
    shell = fb_phone_clean.make_shell(serial, ADB)
    pids = [p for p in (shell("pgrep -f com.genymobile.scrcpy.Server") or "").split()
            if p.isdigit()]
    killed = 0
    for pid in pids:
        line = shell(f"tr '\\000' ' ' < /proc/{pid}/cmdline") or ""
        scid = next((w.split("=", 1)[1] for w in line.split() if w.startswith("scid=")), "")
        if scid and scid in live:
            continue
        # ไม่รู้ว่าเป็นของใคร = ของค้างแน่ เพราะของเราทุกตัวลงทะเบียน scid ไว้
        shell(f"kill -9 {pid}")
        killed += 1
    return killed


def _phone_watch_keeper() -> None:
    """เฝ้าสายมือถือ — หลุดแล้วต่อคืนเอง · ต่อคืนไม่ได้ก็บอกให้รู้ทันที

    แยกเป็นไฟล์ `phone_watch.py` เพราะต้องสั่งจากบรรทัดคำสั่งได้ด้วยตอนไล่ปัญหา
    (`python phone_watch.py board`) และเพื่อให้โปรเจกต์อื่นเรียกใช้ซ้ำได้
    """
    time.sleep(45)          # ให้เซิร์ฟเวอร์ตั้งตัวก่อน อย่าไปแย่ง ADB ตอนเพิ่งเปิด
    try:
        import phone_watch                              # noqa: PLC0415
    except Exception as error:                          # noqa: BLE001
        append_log("publish", f"เปิดตัวเฝ้าสายมือถือไม่ได้: {error}")
        return
    while True:
        try:
            for what in phone_watch.heal_once(verbose=False):
                append_log("publish", f"สายมือถือ: {what}")
        except Exception as error:                      # noqa: BLE001
            # **ห้ามเงียบ** ตัวเฝ้าที่ตายเงียบแย่กว่าไม่มีตัวเฝ้า เพราะเราจะนึกว่ามีคนดูอยู่
            append_log("publish", f"ตัวเฝ้าสายมือถือสะดุด: {error}")
        time.sleep(phone_watch.GAP)


def _phone_memory_keeper() -> None:
    """เฝ้าหน่วยความจำมือถือทุกเครื่อง เต็มเมื่อไรเคลียร์ให้เองโดยไม่ตัดงานที่ทำอยู่"""
    time.sleep(30)          # ให้เซิร์ฟเวอร์ตั้งตัวก่อน อย่าไปแย่ง ADB ตอนเพิ่งเปิด
    while True:
        try:
            _phone_memory_round()
        except Exception as error:          # noqa: BLE001
            append_log("publish", f"ตัวเฝ้าหน่วยความจำมือถือสะดุด: {error}")
        time.sleep(PHONE_HEALTH_ROUND)


@app.get("/api/phone/health")
async def phone_health(serial: str = "") -> dict:
    """แรม/เนื้อที่ของมือถือ — หน้าเว็บเอาไปโชว์บนแถบสถานะด้านบน"""
    if serial:
        rows = [{"serial": await asyncio.to_thread(clean_serial, serial, True)}]
    else:
        rows = [r for r in await asyncio.to_thread(_device_rows)
                if r.get("serial") and r.get("ready") is not False]
    out = []
    for row in rows:
        health = await asyncio.to_thread(_read_phone_health, row["serial"])
        out.append({**health, "label": device_book.label(row["serial"])})
    return {"ok": True, "limit": _phone_full_pct(), "devices": out}


@app.post("/api/phone/clean")
async def phone_clean(request: Request) -> dict:
    """สั่งเคลียร์ด้วยมือ — ต่อคิวเหมือนกัน ไม่ตัดงานที่กำลังทำอยู่"""
    payload = await request.json()
    serial = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )
    if serial in _phone_cleaning:
        return {"ok": True, "already": True, "message": "กำลังเคลียร์อยู่แล้ว"}
    threading.Thread(target=_clean_phone_when_free, args=(serial,),
                     daemon=True).start()
    return {"ok": True, "queued": True,
            "message": "เข้าคิวเคลียร์แล้ว — ถ้ามีงานทำอยู่จะรอให้จบก่อน"}


@app.post("/api/phone/text")
async def phone_text(request: Request) -> dict:
    """พิมพ์ข้อความลงช่องที่โฟกัสอยู่บนมือถือ — ไทยได้ผ่าน ADBKeyboard"""
    payload = await request.json()
    text = str(payload.get("text", ""))
    if not 1 <= len(text) <= 500:
        raise HTTPException(status_code=400, detail="ข้อความต้องมี 1–500 ตัวอักษร")
    serial = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )

    def work() -> dict:
        original = ""
        try:
            # ไทย/อีโมจิต้องสลับไป ADBKeyboard ก่อน แล้วคืนคีย์บอร์ดเดิมเสมอ
            if not text.isascii():
                original = adb_current_ime(serial)
                if not adb_use_keyboard(serial):
                    original = ""
                    raise RuntimeError(
                        "พิมพ์ภาษาไทยไม่ได้ — ติดตั้งและเปิดใช้ ADBKeyboard บนมือถือก่อน"
                    )
            adb_type_text(serial, text)
            return {"ok": True, "typed": len(text)}
        finally:
            if original:
                try:
                    adb_restore_ime(serial, original)
                except RuntimeError:
                    pass

    try:
        return await asyncio.to_thread(work)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/phone/swipe")
async def phone_swipe(request: Request) -> dict:
    """ปัดหน้าจอ — ใช้ตอน scrcpy ใช้ไม่ได้ หรือสั่งปัดตรงๆ จากปุ่ม"""
    payload = await request.json()
    serial = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )
    width = int(payload.get("source_width", 0))
    height = int(payload.get("source_height", 0))
    if not width or not height:
        raise HTTPException(status_code=400, detail="ต้องส่งขนาดภาพต้นทางมาด้วย")
    duration = max(50, min(3000, int(payload.get("duration", 250))))

    def work() -> dict:
        x1, y1 = scale_to_device(
            serial, int(payload.get("x1", 0)), int(payload.get("y1", 0)), width, height
        )
        x2, y2 = scale_to_device(
            serial, int(payload.get("x2", 0)), int(payload.get("y2", 0)), width, height
        )
        run_adb(
            "-s", serial, "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(duration),
        )
        return {"ok": True, "from": [x1, y1], "to": [x2, y2]}

    return await asyncio.to_thread(work)


# ============================================ ส่งลิงก์/ข้อความ 2 ทาง (คอม ↔ มือถือ)
# มือถือ → คอม: เปิดหน้า /send-link บนมือถือ วางลิงก์แล้วส่งเข้ากล่องบนคอม
#              (มือถือวิ่งเข้าคอมผ่าน `adb reverse` ไม่ต้องอยู่ Wi-Fi วงเดียวกัน)
# คอม → มือถือ: ตั้งคลิปบอร์ดมือถือผ่าน scrcpy (ไทย/อีโมจิได้) หรือวางลงช่องเลย

LINK_INBOX_FILE = DATA_DIR / "link_inbox.json"
LINK_INBOX_LIMIT = 200
_inbox_lock = threading.Lock()

VIDEO_LINK_RE = re.compile(
    r"https?://[^\s<>\"']*(?:tiktok\.com|douyin\.com|facebook\.com|fb\.watch"
    r"|shopee\.[a-z.]+|lazada\.[a-z.]+|instagram\.com|youtube\.com|youtu\.be)"
    r"[^\s<>\"']*",
    re.I,
)


def extract_links(text: str) -> list[str]:
    """ดึงลิงก์ออกจากข้อความที่แชร์มา — ข้อความแชร์จากแอปมักมีคำอื่นปนมาด้วย"""
    seen: list[str] = []
    for match in VIDEO_LINK_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,)]}…")
        if url not in seen:
            seen.append(url)
    return seen


def link_platform(url: str) -> str:
    low = url.lower()
    for key, label in (
        ("tiktok", "TikTok"), ("douyin", "Douyin"), ("shopee", "Shopee"),
        ("lazada", "Lazada"), ("instagram", "Instagram"),
        ("youtu", "YouTube"), ("facebook", "Facebook"), ("fb.watch", "Facebook"),
    ):
        if key in low:
            return label
    return "ลิงก์"


def load_inbox() -> list[dict]:
    try:
        return json.loads(LINK_INBOX_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_inbox(items: list[dict]) -> None:
    temporary = LINK_INBOX_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(items[-LINK_INBOX_LIMIT:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(LINK_INBOX_FILE)


@app.get("/send-link")
async def send_link_page() -> FileResponse:
    """หน้าสำหรับเปิดบนมือถือ — วางลิงก์แล้วส่งเข้าคอม"""
    return FileResponse(
        WEB_DIR / "send-link.html",
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


@app.post("/api/links")
async def add_link(request: Request) -> dict:
    """รับลิงก์จากมือถือ — ไม่บังคับ local เพราะเรียกจากเบราว์เซอร์บนมือถือ"""
    payload = await request.json()
    text = str(payload.get("text", ""))[:20000]
    links = extract_links(text)
    if not links:
        raise HTTPException(
            status_code=400,
            detail="ไม่พบลิงก์ในข้อความ (รองรับ TikTok / Facebook / Shopee / Lazada / YouTube / IG)",
        )
    with _inbox_lock:
        items = load_inbox()
        existing = {item["url"] for item in items}
        added = []
        for url in links:
            if url in existing:
                continue
            entry = {
                "id": f"{int(time.time() * 1000)}{len(items)}",
                "url": url,
                "platform": link_platform(url),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            items.append(entry)
            existing.add(url)
            added.append(entry)
        save_inbox(items)
    if added:
        append_log("input", f"รับลิงก์จากมือถือ {len(added)} รายการ: {added[0]['url'][:60]}")
    return {"ok": True, "added": len(added), "skipped": len(links) - len(added),
            "items": added}


@app.get("/api/links")
async def list_links() -> dict:
    with _inbox_lock:
        items = load_inbox()
    return {"ok": True, "items": list(reversed(items)), "count": len(items)}


@app.delete("/api/links")
async def clear_links(item_id: str = "") -> dict:
    with _inbox_lock:
        items = load_inbox()
        before = len(items)
        items = [i for i in items if i["id"] != item_id] if item_id else []
        save_inbox(items)
    return {"ok": True, "removed": before - len(items)}


@app.post("/api/phone/clipboard")
async def phone_clipboard(request: Request) -> dict:
    """คอม → มือถือ: ตั้งคลิปบอร์ดบนมือถือ (paste=true คือวางลงช่องที่โฟกัสเลย)

    ใช้ scrcpy เพราะส่ง UTF-8 ตรงๆ ไทย/อีโมจิผ่านหมด
    scrcpy ใช้ไม่ได้ค่อยถอยไปพิมพ์ผ่าน ADBKeyboard (ได้แค่วางลงช่อง ไม่เข้าคลิปบอร์ด)
    """
    payload = await request.json()
    text = str(payload.get("text", ""))
    if not 1 <= len(text) <= 20000:
        raise HTTPException(status_code=400, detail="ข้อความต้องมี 1–20000 ตัวอักษร")
    paste = bool(payload.get("paste", False))
    serial = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )

    def work() -> dict:
        if scrcpy_control.is_available():
            try:
                scrcpy_control.set_clipboard(ADB, serial, text, paste)
                return {
                    "ok": True, "method": "scrcpy",
                    "message": "วางลงช่องบนมือถือแล้ว" if paste
                               else "คัดลอกเข้าคลิปบอร์ดมือถือแล้ว (กดวางในแอปได้เลย)",
                }
            except scrcpy_control.ScrcpyUnavailable:
                pass
        original = ""
        try:
            if not text.isascii():
                original = adb_current_ime(serial)
                if not adb_use_keyboard(serial):
                    original = ""
                    raise RuntimeError(
                        "ส่งข้อความไทยไม่ได้ — ต้องมี scrcpy หรือ ADBKeyboard บนมือถือ"
                    )
            adb_type_text(serial, text)
            return {"ok": True, "method": "adbkeyboard",
                    "message": "พิมพ์ลงช่องที่โฟกัสอยู่บนมือถือแล้ว"}
        finally:
            if original:
                try:
                    adb_restore_ime(serial, original)
                except RuntimeError:
                    pass

    try:
        return await asyncio.to_thread(work)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/bridge")
async def bridge_status() -> dict:
    """เช็คว่ามือถือเครื่องไหนเปิดทางวิ่งเข้าคอมแล้วบ้าง (adb reverse)"""

    def check() -> list[dict]:
        found = []
        for device in list_devices():
            if not device["ready"]:
                continue
            result = run_adb("-s", device["serial"], "reverse", "--list", timeout=8)
            listed = result.stdout.decode("utf-8", errors="replace")
            device["bridged"] = f"tcp:{PORT}" in listed
            found.append(device)
        return found

    return {"ok": True, "port": PORT, "devices": await asyncio.to_thread(check)}


@app.post("/api/bridge/connect")
async def bridge_connect(request: Request) -> dict:
    """เปิดทางให้มือถือเข้าเว็บนี้ผ่านสาย USB

    `adb reverse` ทำให้ localhost:PORT บนมือถือวิ่งมาที่เซิร์ฟเวอร์บนคอม
    จึงไม่ต้องอยู่ Wi-Fi วงเดียวกันและไม่ต้องเปิดพอร์ตออกเน็ต
    """
    payload = await request.json()
    serial = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )

    def work() -> dict:
        result = run_adb(
            "-s", serial, "reverse", f"tcp:{PORT}", f"tcp:{PORT}", timeout=10
        )
        if result.returncode != 0:
            raise RuntimeError(adb_message(result))
        return {"ok": True, "url": f"http://localhost:{PORT}/send-link"}

    try:
        outcome = await asyncio.to_thread(work)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=f"เปิดทางไม่สำเร็จ: {error}") from error
    append_log("input", f"เปิดทาง USB ให้ {serial} เข้าเว็บได้แล้ว")
    return outcome


@app.post("/api/bridge/disconnect")
async def bridge_disconnect(request: Request) -> dict:
    payload = await request.json()
    serial = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )
    await asyncio.to_thread(
        lambda: run_adb("-s", serial, "reverse", "--remove", f"tcp:{PORT}", timeout=8)
    )
    return {"ok": True}


@app.post("/api/bridge/open")
async def bridge_open(request: Request) -> dict:
    """เปิดหน้า /send-link บนเบราว์เซอร์ของมือถือให้เลย (ไม่ต้องพิมพ์ URL เอง)"""
    payload = await request.json()
    serial = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )

    def work() -> dict:
        run_adb("-s", serial, "reverse", f"tcp:{PORT}", f"tcp:{PORT}", timeout=10)
        url = f"http://localhost:{PORT}/send-link"
        result = run_adb(
            "-s", serial, "shell", "am", "start", "-a",
            "android.intent.action.VIEW", "-d", url, timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(adb_message(result))
        return {"ok": True, "url": url}

    try:
        return await asyncio.to_thread(work)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=f"เปิดหน้าไม่สำเร็จ: {error}") from error


# ================================================= ส่งคลิปเข้ามือถือ + เปิดแอปให้โพสต์
# ยกจากโปรเจกต์เดิม: push ไฟล์ → สั่งให้ระบบแกลเลอรีรู้จัก (ได้ content:// กลับมา)
# → เปิดแอปด้วย intent SEND พร้อมคลิปนั้น ผู้ใช้กดโพสต์เอง

PHONE_POST_REMOTE_DIR = "/sdcard/Movies/autopost"
PHONE_POST_MAX_BYTES = 512 * 1024 * 1024
CONTENT_URI_RE = re.compile(r"content://media/external/video/media/\d+")

PHONE_POST_TARGETS: dict[str, dict] = {
    "reels": {
        "label": "Facebook Reels",
        "packages": ["com.facebook.katana"],
        "share": True,
        "hint": "เมื่อ Facebook ถามปลายทางให้เลือก Reel (คลิปควรยาว 3–90 วินาที แนวตั้ง)",
    },
    "facebook": {
        "label": "Facebook",
        "packages": ["com.facebook.katana"],
        "share": True,
        "hint": "Facebook จะเปิดหน้าเขียนโพสต์พร้อมวิดีโอ เลือกผู้ชมแล้วกดโพสต์",
    },
    "tiktok": {
        "label": "TikTok",
        "packages": ["com.zhiliaoapp.musically", "com.ss.android.ugc.trill"],
        "share": True,
        "hint": "TikTok จะเปิดหน้าตัดต่อ ตรวจคลิปแล้วกดถัดไป → โพสต์",
    },
    "shopee": {
        "label": "Shopee Video",
        "packages": ["com.shopee.th", "com.shopee.id", "com.shopee.my"],
        "share": False,
        "hint": "Shopee ไม่มีช่องทางส่งวิดีโอตรง — เปิดแอปแล้วไป ฉัน → Shopee Video → อัปโหลด",
    },
}


def installed_packages(serial: str) -> str:
    result = run_adb("-s", serial, "shell", "pm", "list", "packages", timeout=20)
    return result.stdout.decode("utf-8", errors="replace")


def video_share_handlers(serial: str) -> str:
    """แอปที่รับ intent แชร์วิดีโอได้ — เช็คก่อนส่ง ไม่งั้นเปิดแล้วคลิปไม่ติดไปด้วย"""
    result = run_adb(
        "-s", serial, "shell", "cmd", "package", "query-activities",
        "-a", "android.intent.action.SEND", "-t", "video/mp4", timeout=20,
    )
    return result.stdout.decode("utf-8", errors="replace")


@app.get("/api/phone-post/targets")
async def phone_post_targets() -> dict:
    return {
        "ok": True,
        "targets": [
            {"key": key, "label": value["label"], "hint": value["hint"]}
            for key, value in PHONE_POST_TARGETS.items()
        ],
    }


@app.post("/api/phone-post/push")
async def phone_post_push(
    serial: str = Form(...), file: UploadFile = File(...)
) -> dict:
    """ส่งคลิปเข้ามือถือแล้วให้ระบบแกลเลอรีรู้จักไฟล์ (ต้องได้ content:// ถึงแชร์ได้)"""
    clean = await asyncio.to_thread(clean_serial, serial, True)
    suffix = Path(file.filename or "clip.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".webm", ".mkv"}:
        raise HTTPException(status_code=400, detail="รองรับเฉพาะ MP4, MOV, WebM, MKV")
    stem = re.sub(r"[^A-Za-z0-9_\-]+", "_", Path(file.filename or "clip").stem)[:40]
    stem = stem.strip("_") or "clip"
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    name = f"{stem}_{stamp}{suffix}"
    remote_path = f"{PHONE_POST_REMOTE_DIR}/{name}"

    staging = DATA_DIR / "phone_post"
    staging.mkdir(parents=True, exist_ok=True)
    local_path = staging / name
    written = 0
    try:
        with local_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > PHONE_POST_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="ไฟล์ใหญ่เกิน 512 MB")
                output.write(chunk)
        await file.close()

        def push() -> None:
            run_adb("-s", clean, "shell", "mkdir", "-p", PHONE_POST_REMOTE_DIR, timeout=15)
            result = run_adb("-s", clean, "push", str(local_path), remote_path, timeout=600)
            if result.returncode != 0:
                raise RuntimeError(adb_message(result))

        await asyncio.to_thread(push)
    except RuntimeError as error:
        raise HTTPException(
            status_code=502, detail=f"ส่งไฟล์เข้ามือถือไม่สำเร็จ: {error}"
        ) from error
    finally:
        local_path.unlink(missing_ok=True)   # ไฟล์อยู่บนมือถือแล้ว ไม่เก็บซ้ำบนคอม

    def index_file() -> str:
        scan = run_adb(
            "-s", clean, "shell", "content", "call", "--uri", "content://media",
            "--method", "scan_file", "--arg", remote_path, timeout=60,
        )
        match = CONTENT_URI_RE.search(scan.stdout.decode("utf-8", errors="replace"))
        if match:
            return match.group(0)
        # Android 13+ คืน Bundle ที่ไม่พิมพ์ URI ออกมา ต้องไปค้นเอาเองจาก MediaStore
        #
        # ค้นด้วย _display_name ไม่ใช่ _data เพราะ MediaStore เก็บ path เป็น
        # /storage/emulated/0/... แต่เราส่งเป็น /sdcard/... เทียบตรงๆ ไม่มีวันเจอ
        # (ชื่อไฟล์มี timestamp ต่อท้ายอยู่แล้วจึงไม่ชนกับคลิปอื่น —
        #  ห้ามใช้ "วิดีโอล่าสุด" เพราะอาจได้คลิปส่วนตัวของผู้ใช้ไปแชร์แทน)
        file_name = remote_path.rsplit("/", 1)[-1]
        query = run_adb(
            "-s", clean, "shell", "content", "query",
            "--uri", "content://media/external/video/media",
            "--projection", "_id",
            "--where", f"\"_display_name='{file_name}'\"", timeout=60,
        )
        found = re.search(r"_id=(\d+)", query.stdout.decode("utf-8", errors="replace"))
        return f"content://media/external/video/media/{found.group(1)}" if found else ""

    content_uri = await asyncio.to_thread(index_file)
    append_log(
        "publish",
        f"ส่งคลิปเข้ามือถือ {name} ({written / 1e6:.1f} MB)"
        + (" — แกลเลอรีรู้จักแล้ว" if content_uri else " — ยังไม่เข้าแกลเลอรี"),
    )
    return {
        "ok": True, "remote_path": remote_path, "content_uri": content_uri,
        "size_bytes": written, "indexed": bool(content_uri), "name": name,
    }


@app.post("/api/phone-post/launch")
async def phone_post_launch(request: Request) -> dict:
    """เปิดแอปปลายทางพร้อมคลิปที่ส่งเข้าเครื่องแล้ว"""
    payload = await request.json()
    platform = str(payload.get("platform", "")).strip()
    config = PHONE_POST_TARGETS.get(platform)
    if config is None:
        raise HTTPException(status_code=400, detail="ไม่รองรับแพลตฟอร์มนี้")
    clean = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )
    content_uri = str(payload.get("content_uri", "")).strip()
    if content_uri and not CONTENT_URI_RE.fullmatch(content_uri):
        raise HTTPException(status_code=400, detail="ที่อยู่วิดีโอในมือถือไม่ถูกต้อง")

    def work() -> dict:
        installed = installed_packages(clean)
        package = next((p for p in config["packages"] if p in installed), None)
        if package is None:
            raise LookupError(f"ยังไม่ได้ติดตั้งแอป {config['label']} บนเครื่องนี้")
        handlers = (
            video_share_handlers(clean) if config["share"] and content_uri else ""
        )
        if content_uri and package in handlers:
            result = run_adb(
                "-s", clean, "shell", "am", "start",
                "-a", "android.intent.action.SEND", "-t", "video/mp4",
                "--eu", "android.intent.extra.STREAM", content_uri,
                "--grant-read-uri-permission", "-p", package, timeout=45,
            )
            mode = "share"
        else:
            result = run_adb(
                "-s", clean, "shell", "monkey", "-p", package,
                "-c", "android.intent.category.LAUNCHER", "1", timeout=30,
            )
            mode = "open"
        if result.returncode != 0:
            raise RuntimeError(adb_message(result))
        return {
            "ok": True, "mode": mode, "package": package,
            "message": (
                f"เปิด {config['label']} พร้อมคลิปแล้ว" if mode == "share"
                else f"เปิดแอป {config['label']} แล้ว (ต้องเลือกคลิปเองในแอป)"
            ),
            "hint": config["hint"],
        }

    try:
        outcome = await asyncio.to_thread(work)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=f"เปิดแอปไม่สำเร็จ: {error}") from error
    append_log("publish", outcome["message"])
    return outcome


@app.delete("/api/phone-post/file")
async def phone_post_cleanup(request: Request) -> dict:
    """ลบคลิปที่ส่งเข้ามือถือทิ้ง — ไม่ให้ไฟล์กองสะสมในเครื่อง"""
    payload = await request.json()
    clean = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )
    remote_path = str(payload.get("remote_path", "")).strip()
    # ลบได้เฉพาะในโฟลเดอร์ของเราเอง กันสั่งลบไฟล์อื่นบนเครื่อง
    if not remote_path.startswith(f"{PHONE_POST_REMOTE_DIR}/") or ".." in remote_path:
        raise HTTPException(status_code=400, detail="ลบได้เฉพาะไฟล์ที่แอปนี้ส่งเข้าไป")
    await asyncio.to_thread(
        lambda: run_adb("-s", clean, "shell", "rm", "-f", remote_path, timeout=20)
    )
    return {"ok": True}


# ==================================================== เชื่อมต่อมือถือผ่าน Wi-Fi
# Android 11+ ใช้ Wireless debugging: จับคู่ด้วยรหัส 6 หลักครั้งเดียว
# แล้วต่อที่พอร์ตอีกตัว (คนละพอร์ตกับตอนจับคู่ — จุดที่พลาดกันบ่อยที่สุด)

ADB_ENDPOINT_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}:\d{1,5}$")
PAIR_CODE_RE = re.compile(r"^\d{6}$")


def validate_endpoint(endpoint: str) -> str:
    clean = endpoint.strip()
    if not ADB_ENDPOINT_RE.fullmatch(clean) or clean.startswith("-"):
        raise HTTPException(
            status_code=400, detail="กรอก IP และพอร์ตแบบ 192.168.1.20:37123"
        )
    return clean


@app.post("/api/wifi/pair")
async def wifi_pair(request: Request) -> dict:
    payload = await request.json()
    endpoint = validate_endpoint(str(payload.get("endpoint", "")))
    code = str(payload.get("code", "")).strip()
    if not PAIR_CODE_RE.fullmatch(code):
        raise HTTPException(status_code=400, detail="รหัสจับคู่ต้องเป็นตัวเลข 6 หลัก")

    def work() -> str:
        result = run_adb("pair", endpoint, code, timeout=25)
        message = adb_message(result)
        if result.returncode != 0 or "failed" in message.lower():
            raise RuntimeError(message or "จับคู่ไม่สำเร็จ")
        return message

    try:
        message = await asyncio.to_thread(work)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "message": message or "จับคู่มือถือสำเร็จ"}


@app.post("/api/wifi/connect")
async def wifi_connect(request: Request) -> dict:
    payload = await request.json()
    endpoint = validate_endpoint(str(payload.get("endpoint", "")))

    def work() -> str:
        result = run_adb("connect", endpoint, timeout=20)
        message = adb_message(result)
        if result.returncode != 0 or "failed" in message.lower():
            raise RuntimeError(message or "เชื่อมต่อไม่สำเร็จ")
        return message

    try:
        message = await asyncio.to_thread(work)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    _connected_cache["at"] = 0.0     # มีเครื่องใหม่แล้ว ให้ตรวจรายชื่อใหม่ทันที
    return {"ok": True, "message": message or "เชื่อมต่อมือถือสำเร็จ"}


@app.post("/api/wifi/disconnect")
async def wifi_disconnect(request: Request) -> dict:
    payload = await request.json()
    serial = str(payload.get("serial", "")).strip()
    if ":" not in serial:
        raise HTTPException(status_code=400, detail="เลือกอุปกรณ์ Wi-Fi ที่จะยกเลิก")
    validate_endpoint(serial)
    await asyncio.to_thread(lambda: run_adb("disconnect", serial, timeout=15))
    _connected_cache["at"] = 0.0
    return {"ok": True, "message": "ยกเลิกการเชื่อมต่อแล้ว"}


# ==================================================== เข้าใช้จากมือถือ (ขออนุญาต)
# เครื่องหลัก (localhost) มีสิทธิ์เต็มเสมอ · เครื่องอื่นในวง LAN ต้องรออนุมัติ
# หน้าที่เปิดได้โดยไม่ต้องอนุมัติมีแค่หน้าถามสถานะกับหน้า /mobile เท่านั้น

PUBLIC_PATHS = {"/mobile", "/send-link", "/api/access/status", "/api/system"}


@app.middleware("http")
async def gate_remote_devices(request: Request, call_next):
    path = request.url.path
    if (
        access_control.is_local_request(request)
        or path in PUBLIC_PATHS
        or path.startswith("/static/")
    ):
        return await call_next(request)

    token = request.cookies.get(access_control.ACCESS_COOKIE, "") or request.headers.get(
        access_control.ACCESS_TOKEN_HEADER, ""
    )
    record = access_store.find_by_token(token)
    if record is None or record.get("status") != "approved":
        # คนเปิดหน้าเว็บ กับโค้ดที่ยิง API ต้องได้คนละอย่าง
        #
        # เดิมโยน JSON 403 ให้ทุกคนเท่ากัน ผลคือเปิด http://<เครื่อง>:8866/ จาก
        # คอมอีกเครื่องแล้วเจอ {"detail": "..."} ดิบๆ เต็มจอ ไม่มีทางรู้ว่าต้องไปไหนต่อ
        # ทั้งที่มีหน้า /mobile ที่อธิบายขั้นตอนขออนุญาตไว้ครบแล้ว
        #
        # แยกด้วย Accept: เบราว์เซอร์ที่กดเข้าหน้าเว็บส่ง text/html มาเสมอ
        # ส่วน fetch() ของหน้าเว็บขอ JSON — ตัวหลังต้องได้ 403 เหมือนเดิม
        # ไม่งั้นโค้ดฝั่งหน้าเว็บจะได้ HTML แล้ว throw ข้อความที่อ่านไม่รู้เรื่อง
        wants_page = "text/html" in request.headers.get("accept", "")
        if wants_page and path != "/mobile":
            return RedirectResponse("/mobile", status_code=303)
        return JSONResponse(
            status_code=403,
            content={
                "detail": "อุปกรณ์นี้ยังไม่ได้รับอนุญาตจากเครื่องหลัก",
                "access_status": (record or {}).get("status", "unknown"),
            },
        )
    access_store.touch(
        record,
        access_control.client_ip(request),
        request.headers.get("user-agent", ""),
    )
    return await call_next(request)


def mobile_url() -> str | None:
    address = access_control.lan_ip()
    return f"http://{address}:{PORT}/mobile" if address else None


@app.get("/mobile")
async def mobile_page() -> FileResponse:
    """หน้าแรกสำหรับมือถือ — ขออนุญาตก่อน อนุมัติแล้วถึงใช้เครื่องมือได้"""
    return FileResponse(
        WEB_DIR / "mobile.html",
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


@app.get("/api/access/status")
async def access_status(request: Request) -> JSONResponse:
    """มือถือถามว่า 'ฉันได้รับอนุญาตหรือยัง' — เครื่องใหม่จะถูกขึ้นทะเบียนอัตโนมัติ"""
    ip = access_control.client_ip(request)
    if access_control.is_local_request(request):
        return JSONResponse({
            "role": "admin", "status": "approved", "device": "เครื่องหลัก",
            "ip": ip, "mobile_url": mobile_url(),
        })

    user_agent = request.headers.get("user-agent", "")
    token = request.cookies.get(access_control.ACCESS_COOKIE, "") or request.headers.get(
        access_control.ACCESS_TOKEN_HEADER, ""
    )
    record = access_store.find_by_token(token)
    fresh_token = None
    if record is None:
        fresh_token = secrets.token_urlsafe(32)
        record = access_store.create(fresh_token, ip, user_agent)
    else:
        access_store.touch(record, ip, user_agent, persist=True)

    payload = {
        "role": "device",
        "status": record.get("status", "pending"),
        "device": record.get("device"),
        "ip": ip,
    }
    # ส่งโทเคนกลับให้เก็บใน localStorage ด้วย เพราะบางเบราว์เซอร์บนมือถือทิ้งคุกกี้
    # ถ้าไม่มีทางสำรอง ทุกครั้งที่ถามสถานะจะกลายเป็นเครื่องใหม่และไม่มีวันได้รับอนุมัติ
    if fresh_token:
        payload["token"] = fresh_token
    response = JSONResponse(payload)
    if fresh_token:
        response.set_cookie(
            access_control.ACCESS_COOKIE, fresh_token,
            max_age=365 * 24 * 60 * 60, httponly=True, samesite="lax",
            secure=request.url.scheme == "https",
        )
    return response


def require_admin(request: Request) -> None:
    if not access_control.is_local_request(request):
        raise HTTPException(
            status_code=403, detail="จัดการสิทธิ์ได้จากเครื่องหลักเท่านั้น"
        )


@app.get("/api/access/devices")
async def access_devices(request: Request) -> dict:
    require_admin(request)
    return {"ok": True, "devices": access_store.listing(), "mobile_url": mobile_url()}


@app.delete("/api/access/devices/revoked")
async def purge_revoked(request: Request) -> dict:
    """ลบอุปกรณ์ที่ถอนสิทธิ์แล้วออกจากรายชื่อ

    ต้องประกาศ **ก่อน** /api/access/devices/{device_id} ไม่งั้นคำว่า revoked
    จะถูกจับเป็น device_id แล้วตอบ 404
    """
    require_admin(request)
    return {"ok": True, "removed": access_store.purge_revoked()}


@app.post("/api/access/devices/{device_id}/approve")
async def approve_device(device_id: str, request: Request) -> dict:
    require_admin(request)
    record = access_store.set_status(device_id, "approved")
    if record is None:
        raise HTTPException(status_code=404, detail="ไม่พบอุปกรณ์นี้")
    append_log("input", f"อนุญาตอุปกรณ์ {record['device']} ({record['ip']})")
    return {"ok": True, "device": access_control.public_device(record)}


@app.delete("/api/access/devices/{device_id}")
async def revoke_device(device_id: str, request: Request) -> dict:
    require_admin(request)
    record = access_store.set_status(device_id, "revoked")
    if record is None:
        raise HTTPException(status_code=404, detail="ไม่พบอุปกรณ์นี้")
    return {"ok": True, "device": access_control.public_device(record)}


# ============================================ อนุมัติจุดขายทาง Telegram
# Gemini คัดจุดขายเสร็จ → ส่งเข้า Telegram พร้อมปุ่ม → ผู้ใช้กดอนุมัติ/ขอแก้/ไม่เอา
# ระบบไม่รอค้าง: บันทึกคำขอแล้วตอบกลับทันที มี watcher เฝ้าคำตอบให้เบื้องหลัง

approval_store = telegram_bot.ApprovalStore(DATA_DIR / "approvals.json")
approval_watcher = telegram_bot.ApprovalWatcher(
    approval_store,
    get_token=load_telegram_token,
    log=lambda message: append_log("input", message),
)


# บอทที่สองสำหรับสายเจนคลิป — คนละโทเคน คนละคิว getUpdates
# ต้องมี watcher ของตัวเอง: ตัวอ่าน getUpdates ผูกกับโทเคน ไม่ใช่กับโปรแกรม
clip_watcher = telegram_bot.ApprovalWatcher(
    approval_store,
    get_token=load_clip_token,
    log=lambda message: append_log("input", f"[บอทคลิป] {message}"),
)


def _remember_chat_id(chat_id: str) -> None:
    """watcher เห็นใครทักมาก็จำ chat id ให้เลย ผู้ใช้ไม่ต้องกดบันทึกซ้ำ"""
    config = load_config()
    if config.get("telegram_chat_id") == chat_id:
        return
    config["telegram_chat_id"] = chat_id
    save_config(config)
    append_log("input", f"จำ chat id ของ Telegram แล้ว ({chat_id})")


def _remember_clip_chat_id(chat_id: str) -> None:
    config = load_config()
    if config.get("telegram_clip_chat_id") == chat_id:
        return
    config["telegram_clip_chat_id"] = chat_id
    save_config(config)
    append_log("input", f"จำ chat id ของบอทคลิปแล้ว ({chat_id})")


approval_watcher.on_chat_seen = _remember_chat_id
clip_watcher.on_chat_seen = _remember_clip_chat_id


def clip_channel() -> tuple[str, str]:
    """โทเคน + chat id ที่ใช้กับสายเจนคลิป

    ตั้งบอทคลิปไว้ก็ใช้ตัวนั้น ยังไม่ได้ตั้งก็ถอยไปใช้บอทหลักเหมือนเดิม —
    ของเดิมที่ตั้งค่าไว้แล้วต้องไม่พังเพราะมีบอทตัวที่สองโผล่มา
    """
    token = load_clip_token()
    config = load_config()
    if token and config.get("telegram_clip_chat_id"):
        return token, config["telegram_clip_chat_id"]
    for spare_token, spare_chat in extra_channels("clip"):
        return spare_token, spare_chat
    return _fb_telegram()


# ย้ายตาม STUDIO_PORT ไปด้วย — สำเนาที่รันบน 8966 ต้องเปิดสายคลิปของตัวเองที่ 8977
# ไม่งั้นมันจะไปใช้ clip_app ของตัวจริงร่วมกัน แล้วคิวงานคลิปจะปนกันสองชุด
CLIP_PORT = int(os.environ.get("STUDIO_CLIP_PORT", "") or (PORT + 11))


def clip_server_up(timeout: float = 1.5) -> bool:
    """8877 มีคนฟังอยู่ไหม — เช็คด้วยการต่อจริง ไม่ใช่เดาจากตารางโปรเซส"""
    import socket

    with socket.socket() as probe:
        probe.settimeout(timeout)
        return probe.connect_ex(("127.0.0.1", CLIP_PORT)) == 0


def ensure_clip_server() -> bool:
    """เปิดเซิร์ฟเวอร์สายคลิปให้ด้วย ถ้ายังไม่ได้เปิด

    **ทำไมต้องมี** ตัวอ่านข้อความของบอท @ClipAiABot อยู่ในโปรเซส clip_app.py
    ถ้าโปรเซสนั้นไม่ขึ้น บอทจะเงียบสนิทโดยไม่มีอะไรฟ้อง — ผู้ใช้พิมพ์คำสั่งไป
    แล้วรอเก้อ (เกิดจริง 12 ส.ค.: เครื่องรีบูต 22:46 แล้วมีแต่ 8866 ที่กลับมา
    ผู้ใช้กด /flow on แล้วเงียบ กว่าจะรู้ว่าเซิร์ฟเวอร์ดับก็ผ่านไปนาน)

    เปิด Pipeline Studio = ได้ทั้งสองสายเสมอ ตามที่ผู้ใช้สั่ง 12 ส.ค.
    """
    if clip_server_up():
        return False
    script = BASE_DIR / "clip_app.py"
    if not script.is_file():
        append_log("input", f"ไม่พบ {script.name} — เปิดสายคลิปอัตโนมัติไม่ได้")
        return False
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
        # เก็บ output ลงไฟล์ ไม่ทิ้งลง DEVNULL
        #
        # เจอจริง 13 ส.ค.: สายคลิปพิมพ์เตือน "ใช้โปรไฟล์บอทไม่ได้ — ใช้โปรไฟล์
        # เดิมแทน" ทุกครั้งที่เจนคลิป แต่คำเตือนถูกทิ้งลง DEVNULL ทั้งหมด อาการ
        # ที่ผู้ใช้เห็นเลยเหลือแค่ "Flow ยังไม่ได้ล็อกอิน" ซึ่งชี้ผิดทาง
        # PYTHONIOENCODING จำเป็น — พอ stdout ไม่ใช่คอนโซล Python จะใช้ cp1252
        # แล้ว print ภาษาไทยจะพังทั้งโปรเซส (แก้บั๊กหนึ่งไปทำอีกบั๊กหนึ่งแทน)
        # ส่ง STUDIO_CLIP_PORT ต่อให้ลูกด้วย ไม่งั้นสำเนาที่รันคนละพอร์ต (worktree)
        # จะสั่งเปิดสายคลิปแล้วลูกไปฟังพอร์ตเดิม = ไปชนกับตัวจริง
        # (STUDIO_DATA_DIR ติดไปเองอยู่แล้วเพราะสืบทอด os.environ ทั้งก้อน)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", STUDIO_CLIP_PORT=str(CLIP_PORT))
        log_file = open(DATA_DIR / "clip_server.log", "a", encoding="utf-8")
        try:
            subprocess.Popen(
                [sys.executable, str(script)], cwd=str(BASE_DIR),
                stdout=log_file, stderr=subprocess.STDOUT,
                creationflags=flags, env=env,
            )
        finally:
            log_file.close()   # ลูกถือสำเนาของตัวเองแล้ว พ่อไม่ต้องค้างไว้
    except OSError as error:
        append_log("input", f"เปิดเซิร์ฟเวอร์สายคลิปไม่สำเร็จ: {error}")
        return False
    # ยืนยันว่าขึ้นจริง ไม่ใช่แค่สั่งไปแล้วเชื่อว่าติด
    for _ in range(20):
        time.sleep(0.5)
        if clip_server_up():
            append_log("input", f"เปิดเซิร์ฟเวอร์สายคลิป (พอร์ต {CLIP_PORT}) ให้อัตโนมัติแล้ว")
            return True
    append_log("input", f"สั่งเปิดสายคลิปแล้วแต่พอร์ต {CLIP_PORT} ยังไม่ตอบใน 10 วินาที")
    return False


MASS_BOT_HEARTBEAT = DATA_DIR / "fb_mass_bot.heartbeat"
MASS_BOT_STALE = 90     # ชีพจรค้างเกินกี่วิ ถือว่าบอทตาย


def mass_bot_running() -> bool:
    """บอทหาโพสต์แมสยังมีชีวิตไหม — เช็คจากไฟล์ชีพจรที่ fb_mass_bot เขียนทุกรอบ poll

    ไม่เช็คจากไฟล์ล็อก เพราะเปิดไฟล์ที่ถูก msvcrt ล็อกจากอีกโปรเซสได้
    PermissionError (เข้าใจผิดว่าบอทตายทั้งที่รันอยู่ แล้ว spawn ซ้ำ)
    ชีพจรสดกว่า MASS_BOT_STALE วิ = ยังมีชีวิต
    """
    try:
        stamp = int(MASS_BOT_HEARTBEAT.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return (time.time() - stamp) < MASS_BOT_STALE


def ensure_mass_bot() -> bool:
    """ปลุกบอทหาโพสต์แมส (fb_mass_bot.py) ถ้ามีบอท role mass ตั้งไว้แต่ยังไม่รัน

    **ทำไมต้องมี** ตัวอ่านคำสั่งของบอท @NewestBoyBot อยู่ในโปรเซส fb_mass_bot.py
    ถ้าโปรเซสนั้นตาย บอทจะเงียบสนิท ผู้ใช้พิมพ์ /find /add ไปแล้วรอเก้อ
    (เกิดจริง 13 ส.ค.: โปรเซสตายตอน session teardown ไม่มีใครปลุก คำสั่งไม่ทำงาน)
    เหตุผลเดียวกับ [ensure_clip_server] — แต่ตัวนี้เช็คซ้ำเป็นระยะ ไม่ใช่แค่ตอนสตาร์ต
    """
    has_mass = any(b.get("role") == "mass" and extra_bot_token(b["id"])
                   for b in extra_bots())
    if not has_mass or mass_bot_running():
        return False
    script = BASE_DIR / "fb_mass_bot.py"
    if not script.is_file():
        return False
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            [sys.executable, str(script)], cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags)
        append_log("input", "ปลุกบอทหาโพสต์แมส (fb_mass_bot) อัตโนมัติ")
        return True
    except OSError as error:
        append_log("input", f"เปิด fb_mass_bot ไม่สำเร็จ: {error}")
        return False


def _clip_alert(text: str) -> None:
    """ส่งข่าวสถานะเข้าแชทสายคลิป — ส่งไม่ออกต้องไม่ทำให้ตัวเฝ้าตาย"""
    token, chat_id = clip_channel()
    if not token or not chat_id:
        return
    try:
        telegram_bot.send_message(token, chat_id, text)
    except Exception as error:                                  # noqa: BLE001
        append_log("input", f"แจ้งสถานะเข้า Telegram ไม่ได้: {error}")


def _clip_server_keeper() -> None:
    """เฝ้าให้สายคลิป (8877) รันอยู่เสมอ **และบอกให้รู้ด้วย**

    เดิม ensure_clip_server() ถูกเรียกครั้งเดียวตอนเปิดเครื่อง ถ้ามันตายทีหลัง
    ไม่มีใครปลุกและไม่มีใครบอก — เกิดจริง 2 ครั้งในสัปดาห์เดียว ผู้ใช้รู้ตอน
    พิมพ์คำสั่งแล้วบอทเงียบ ซึ่งกว่าจะบังเอิญไปสั่งก็ผ่านไปนาน

    แจ้ง **เฉพาะตอนสถานะเปลี่ยน** ไม่ใช่ทุกนาที — เตือนที่ดังตลอดเวลาเท่ากับ
    ไม่มีเตือน เดี๋ยวก็เลิกอ่านกัน
    """
    was_up = True                    # ตอน startup เพิ่งเรียก ensure_clip_server ไป
    while True:
        try:
            if clip_server_up():
                if not was_up:
                    _clip_alert("✅ สายคลิปกลับมาทำงานแล้ว")
                was_up = True
            else:
                append_log("input", "สายคลิป (8877) ไม่ตอบ — กำลังปลุกใหม่")
                revived = ensure_clip_server()
                if revived and clip_server_up():
                    # ปลุกขึ้นแล้วค่อยบอก พร้อมบอกว่าเคยดับ จะได้ไปดู log ย้อนได้
                    _clip_alert(
                        "♻️ <b>สายคลิปเคยดับ — ปลุกกลับมาแล้ว</b>\n"
                        "งานที่ค้างอยู่ในคิวยังอยู่ครบ · <code>/queue</code> ดูสถานะ\n"
                        "สาเหตุการดับดูได้ที่ <code>data/clip_server.log</code>"
                    )
                    was_up = True
                else:
                    if was_up:      # บอกครั้งเดียวตอนเพิ่งพัง ไม่ย้ำทุกนาที
                        _clip_alert(
                            "🚨 <b>สายคลิปดับ และปลุกไม่ขึ้น</b>\n"
                            "บอทเจนคลิปจะไม่ตอบจนกว่าจะแก้ — "
                            "ดู <code>data/clip_server.log</code>"
                        )
                    was_up = False
        except Exception as error:                              # noqa: BLE001
            append_log("input", f"keeper สายคลิปผิดพลาด: {error}")
        time.sleep(60)


def _mass_bot_keeper() -> None:
    """เฝ้าให้ fb_mass_bot รันอยู่เสมอ — ตายเมื่อไรปลุกใหม่ใน ≤60 วิ"""
    while True:
        try:
            ensure_mass_bot()
        except Exception as error:                              # noqa: BLE001
            append_log("input", f"keeper fb_mass_bot ผิดพลาด: {error}")
        time.sleep(60)


# ------------------------------------------------- ตัวเฝ้าตัวเก็บข้อมูลโพสต์
#
# **ทำไมต้องมี** `fb_posts_collect.py` เป็นโปรเซสยาวตัวเดียวในระบบที่ไม่มีใครเฝ้า
# และไม่มีใครสั่งเปิดให้อัตโนมัติ — สายคลิปมี `_clip_server_keeper` บอทหาโพสต์แมส
# มี `_mass_bot_keeper` แต่ตัวเก็บข้อมูลไม่มีอะไรเลย
#
# ผลที่วัดได้จริง 22 ส.ค. 2569: Bot8/Bot9 ทำจบกลุ่มละใบแล้วออกไปเมื่อ 14:44
# แล้ว **ไม่มีใครปลุกอีกเลยเป็นเวลา ~20 ชั่วโมง** ทั้งที่ยังมี 124 กลุ่มรอเก็บอยู่ในคิว
# (ค่า `--groups` เริ่มต้นเป็น 1 = เก็บจบกลุ่มเดียวแล้วออกเองตามออกแบบ)
#
# ก่อนหน้านั้นเครื่องรีบูต 6 ครั้งใน 68 นาที ก็ไม่มีใครปลุกกลับเช่นกัน — บทเรียน
# เดียวกันเป๊ะกับที่จดไว้ใน `ensure_clip_server` เมื่อ 12 ส.ค. ("เครื่องรีบูตแล้ว
# มีแต่ 8866 ที่กลับมา") แค่ย้ายบ้านมาเกิดกับตัวเก็บข้อมูลแทน
POSTS_COLLECT_SCRIPT = BASE_DIR / "fb_posts_collect.py"
POSTS_COLLECT_GAP = 60.0            # เช็คทุกกี่วินาที
POSTS_COLLECT_COOLDOWN = 180.0      # ปลุกบอทตัวเดิมซ้ำได้เร็วสุดแค่ไหน
POSTS_COLLECT_OFF = DATA_DIR / "posts_collect_keeper.off"   # สร้างไฟล์นี้ = สั่งหยุด
_posts_collect_woke: dict[str, float] = {}


def posts_collect_bots() -> list[str]:
    """บอทที่ **เคยเก็บข้อมูลจริงมาก่อน** เท่านั้น

    ห้ามคิดชื่อบอทขึ้นเอง — ตัวเก็บข้อมูลเปิดเบราว์เซอร์แล้วล็อกอิน Facebook จริง
    ถ้าเดาชื่อผิดจะไปปลุกบัญชีที่เจ้าของไม่ได้ตั้งใจใช้ ซึ่งเสี่ยงโดนตีธง
    เครื่องใหม่ที่ไม่เคยรันเลยจะไม่ถูกแตะ จนกว่าเจ้าของจะสั่งรันเองครั้งแรก
    """
    import sqlite3                                             # noqa: PLC0415
    try:
        with sqlite3.connect(f"file:{DATA_DIR / 'fb_posts.db'}?mode=ro", uri=True,
                             timeout=5) as conn:
            return [r[0] for r in conn.execute(
                "SELECT DISTINCT bot FROM collect_run WHERE bot!='' ORDER BY bot")]
    except Exception:                                          # noqa: BLE001
        return []


def posts_collect_work_left() -> int:
    """ยังมีกลุ่มรอเก็บอยู่กี่กลุ่ม — ไม่มีงานก็ไม่ต้องปลุกใคร"""
    import sqlite3                                             # noqa: PLC0415
    try:
        with sqlite3.connect(f"file:{DATA_DIR / 'fb_posts.db'}?mode=ro", uri=True,
                             timeout=5) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM fb_group WHERE state IN ('pending','failed') "
                "AND attempts < 3").fetchone()[0]
    except Exception:                                          # noqa: BLE001
        return 0


def ensure_posts_collect() -> list[str]:
    """ปลุกตัวเก็บข้อมูลที่ไม่ได้ทำงานอยู่ — คืนรายชื่อบอทที่ปลุก

    ใช้ชีพจรของ `heartbeat` ตัดสินว่ายังทำงานอยู่ไหม (ตัวเก็บเต้นทุก 15 วิ)
    **ไม่แยกระหว่าง "ตาย" กับ "ทำเสร็จแล้วออกไป"** เพราะทั้งสองอย่างแปลว่า
    "ตอนนี้ไม่มีใครเก็บข้อมูล ทั้งที่ยังมีงานค้าง" ซึ่งต้องปลุกเหมือนกัน
    """
    if POSTS_COLLECT_OFF.exists() or not POSTS_COLLECT_SCRIPT.is_file():
        return []
    left = posts_collect_work_left()
    if left <= 0:
        return []

    # `heartbeat.py` เป็นของแชทอื่นที่ยังไม่ได้เก็บเข้า git ตอนเขียนตัวนี้ —
    # ถ้าวันหนึ่งไฟล์นั้นหายไป ตัวเฝ้าต้อง **เงียบแล้วไม่ทำอะไร** ไม่ใช่ทำให้
    # เซิร์ฟเวอร์ 8866 พังทั้งตัว (เคยเจอมาแล้วว่าโค้ดที่พังใน keeper
    # ลากทั้ง endpoint ตายตาม)
    try:
        import heartbeat                                       # noqa: PLC0415
    except ImportError:
        return []
    woke = []
    now = time.time()
    for bot in posts_collect_bots():
        if heartbeat.alive(f"fb_posts_collect_{bot}"):
            continue
        if now - _posts_collect_woke.get(bot, 0.0) < POSTS_COLLECT_COOLDOWN:
            continue          # เพิ่งปลุกไป ให้เวลามันตั้งตัวก่อน กันวนปลุกรัว
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
                subprocess, "DETACHED_PROCESS", 0)
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            log_path = DATA_DIR / "logs" / f"{bot}_stdout.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(log_path, "a", encoding="utf-8")
            try:
                subprocess.Popen(
                    [sys.executable, str(POSTS_COLLECT_SCRIPT), bot],
                    cwd=str(BASE_DIR), stdout=handle, stderr=subprocess.STDOUT,
                    creationflags=flags, env=env)
            finally:
                handle.close()
            _posts_collect_woke[bot] = now
            woke.append(bot)
            append_log("publish",
                       f"ปลุกตัวเก็บข้อมูล {bot} อัตโนมัติ — ยังมี {left} กลุ่มรอเก็บ")
        except OSError as error:
            append_log("publish", f"ปลุกตัวเก็บข้อมูล {bot} ไม่สำเร็จ: {error}")
    return woke


def _posts_collect_keeper() -> None:
    """เฝ้าให้มีตัวเก็บข้อมูลทำงานอยู่เสมอตราบใดที่ยังมีกลุ่มค้างในคิว"""
    while True:
        try:
            ensure_posts_collect()
        except Exception as error:                              # noqa: BLE001
            append_log("publish", f"keeper ตัวเก็บข้อมูลผิดพลาด: {error}")
        time.sleep(POSTS_COLLECT_GAP)


@app.on_event("startup")
async def _start_watcher() -> None:
    _fb_seed_groups()
    _fb_reclaim_interrupted()
    moved = fb_groups.split_into_sets()
    if moved:
        append_log("publish", f"แบ่งกลุ่มเข้าชุดอัตโนมัติ {moved} กลุ่ม (ชุดละไม่เกิน 6)")
    approval_watcher.start()
    # ห้าม clip_watcher.start() ที่นี่ — บอทคลิปอ่าน getUpdates อยู่ที่ clip_app.py
    # โทเคนเดียวมีตัวอ่านได้ตัวเดียว อ่านซ้อนกันจะได้ 409 Conflict แล้วข้อความหาย
    BOT_DIR.mkdir(parents=True, exist_ok=True)
    sync_extra_watchers()
    threading.Thread(target=_fb_scheduler, daemon=True).start()
    ensure_clip_server()
    # เฝ้าสายคลิปต่อจากนี้ด้วย — เปิดครั้งเดียวตอน startup ไม่พอ มันตายทีหลังได้
    threading.Thread(target=_clip_server_keeper, daemon=True).start()
    # บอทหาโพสต์แมสเป็นโปรเซสแยก (role mass) — ให้ app.py ปลุกและเฝ้าให้ฟื้นเอง
    threading.Thread(target=_mass_bot_keeper, daemon=True).start()
    # ตัวเก็บข้อมูลโพสต์เป็นตัวสุดท้ายที่ยังไม่มีใครเฝ้า — เคยหยุดเงียบ 20 ชม.
    # ทั้งที่มี 124 กลุ่มรอ เพราะมันเก็บจบกลุ่มเดียวแล้วออกเองตามออกแบบ
    threading.Thread(target=_posts_collect_keeper, daemon=True).start()

    # เฝ้าหน่วยความจำมือถือ — เต็มเกินเพดานแล้วเคลียร์ให้เอง โดยกดบัตรคิวปกติ
    # จึงรอจนงานที่กำลังทำอยู่จบก่อนเสมอ ไม่ตัดกลางงานโพสต์
    threading.Thread(target=_phone_memory_keeper, daemon=True).start()

    # กวาดตัวส่งภาพหน้าจอที่ค้างจากรอบก่อน
    threading.Thread(target=_sweep_orphan_streamers, daemon=True).start()

    # เฝ้าสายมือถือ — หลุดแล้วต่อคืนให้เอง และร้องดังเมื่อต่อคืนเองไม่ได้
    # (ก่อน 26 ส.ค. 2569 ไม่มีตัวต่อคืนเลยสักตัว หลุดแล้วค้างจนคนมาเห็นเอง)
    threading.Thread(target=_phone_watch_keeper, daemon=True).start()


# บอท 2 ตัว: main = โพสต์ Facebook · clip = สายเจนคลิป (อนุมัติจุดขาย/คลิป)
# แต่ละตัวมีโทเคน · chat id · watcher ของตัวเอง เพราะ getUpdates ผูกกับโทเคน
TELEGRAM_BOTS = {
    "main": {
        "chat_key": "telegram_chat_id", "save": save_telegram_token,
        "load": load_telegram_token, "watcher": approval_watcher,
        "file": TELEGRAM_TOKEN_FILE,
        "label": "บอทหลัก (โพสต์ Facebook)",
    },
    "clip": {
        "chat_key": "telegram_clip_chat_id", "save": save_clip_token,
        "load": load_clip_token, "watcher": clip_watcher,
        "file": CLIP_TOKEN_FILE,
        "label": "บอทเจนคลิป",
    },
}


# ------------------------------------------------- ทะเบียนบอทเพิ่มเติม (หลายตัว)
#
# ของเดิมมี 2 ช่องตายตัว (บอทหลัก + บอทคลิป) ซึ่งพอโทเคนช่องใดช่องหนึ่งหาย
# งานทั้งสายก็เงียบไปเลย และเพิ่มบอทตัวที่ 3 ไม่ได้ — ตรงนี้เป็นทะเบียนแบบเพิ่มได้
# ไม่จำกัดจำนวน แต่ละตัวเลือกได้ว่าทำหน้าที่อะไร (facebook / clip)
#
# ทำไมต้องมี watcher ต่อบอทหนึ่งตัว: getUpdates ผูกกับ "โทเคน" ไม่ใช่กับโปรแกรม
# บอทหนึ่งตัวมีตัวอ่านได้ตัวเดียว แต่คนละบอทอ่านพร้อมกันได้ไม่ชนกัน

BOT_DIR = DATA_DIR / "bots"
BOT_ROLES = {
    "facebook": "รับงานโพสต์ Facebook",
    "clip": "สายเจนคลิป",
    # สายหาโพสต์แมส — fb_mass_bot.py (โปรเซสแยก) เป็นคนเฝ้า ไม่ใช่ 8866/8877
    "mass": "หาโพสต์แมสในกลุ่ม",
    # สายตามยอดโพสต์ + ตอบคอมเมนต์ — fb_engage_bot.py (โปรเซสแยก) เป็นคนเฝ้า
    "engage": "ตามยอดโพสต์ + ตอบคอมเมนต์",
}


def extra_bots() -> list[dict]:
    items = load_config().get("extra_bots")
    return [dict(item) for item in items] if isinstance(items, list) else []


def save_extra_bots(items: list[dict]) -> None:
    config = load_config()
    config["extra_bots"] = items
    save_config(config)


def extra_bot_file(bot_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", bot_id)[:40]
    return BOT_DIR / f"{safe}.bin"


def extra_bot_token(bot_id: str) -> str:
    return _load_key(extra_bot_file(bot_id)) or ""


def extra_channels(role: str) -> list[tuple[str, str]]:
    """(โทเคน, chat id) ของบอทเพิ่มเติมทุกตัวที่ทำหน้าที่นี้และพร้อมใช้"""
    ready = []
    for bot in extra_bots():
        if bot.get("role") != role:
            continue
        token = extra_bot_token(bot["id"])
        if token and bot.get("chat_id"):
            ready.append((token, bot["chat_id"]))
    return ready


def _remember_extra_chat(bot_id: str, chat_id: str) -> None:
    items = extra_bots()
    for item in items:
        if item["id"] == bot_id and item.get("chat_id") != chat_id:
            item["chat_id"] = chat_id
            save_extra_bots(items)
            append_log("input", f"จำ chat id ของบอท {item['name']} แล้ว ({chat_id})")
            return


_extra_watchers: dict[str, telegram_bot.ApprovalWatcher] = {}


def sync_extra_watchers() -> None:
    """เปิด/ปิดตัวเฝ้าข้อความให้ตรงกับทะเบียนบอทปัจจุบัน"""
    wanted = {bot["id"]: bot for bot in extra_bots()}
    for bot_id in list(_extra_watchers):
        if bot_id not in wanted:
            _extra_watchers.pop(bot_id).stop()
    for bot_id, bot in wanted.items():
        if bot_id in _extra_watchers:
            continue
        name = bot.get("name", bot_id)
        if bot.get("role") == "mass":
            # บอทสายหาโพสต์แมสเป็นหน้าที่ของ fb_mass_bot.py (โปรเซสแยก)
            # เหตุผลเดียวกับ clip ด้านล่าง: getUpdates มีตัวอ่านได้ตัวเดียวต่อโทเคน
            continue
        if bot.get("role") == "engage":
            # บอทสายตามยอด/ตอบคอมเมนต์เป็นหน้าที่ของ fb_engage_bot.py
            # เหตุผลเดียวกัน: อ่านโทเคนซ้อนกัน = 409 Conflict
            #
            # **ยังไม่ปลุกให้อัตโนมัติเหมือนสาย mass** เพราะบอทตัวนั้นยังไม่เคย
            # ทดสอบกับมือถือจริง — ปลุกเองตอนรีสตาร์ตแล้วมันไปแตะจอผิดจังหวะ
            # จะพาลทำให้งานโพสต์พังด้วย ต้องรันมือจนกว่าจะทดสอบผ่าน
            continue
        if bot.get("role") == "clip":
            # บอทสายคลิปเป็นหน้าที่ของ clip_app.py (พอร์ต 8877) ไม่ใช่ของที่นี่
            #
            # เจอจริง 11 ส.ค.: โค้ดเดิมพยายามผูก _clip_telegram_text ซึ่งนิยามอยู่ใน
            # clip_app.py คนละไฟล์ → NameError ตอน startup แล้ว **เซิร์ฟเวอร์ 8866
            # ล้มทั้งตัว** เพียงเพราะมีบอทเพิ่มเติมตัวหนึ่งตั้งหน้าที่เป็น clip
            #
            # ต่อให้ย้ายฟังก์ชันมาก็ยังผิดอยู่ดี เพราะ getUpdates ของโทเคนหนึ่งตัว
            # มีตัวอ่านได้ตัวเดียว ถ้าที่นี่อ่านด้วยจะชน 409 กับ 8877
            continue
        watcher = telegram_bot.ApprovalWatcher(
            approval_store,
            get_token=lambda i=bot_id: extra_bot_token(i),
            log=lambda message, n=name: append_log("input", f"[{n}] {message}"),
        )
        watcher.on_chat_seen = lambda chat, i=bot_id: _remember_extra_chat(i, chat)
        watcher.on_photo = _telegram_photo
        watcher.on_text = _telegram_text
        watcher.on_command = _telegram_command
        watcher.on_callback = _telegram_callback
        _extra_watchers[bot_id] = watcher
        watcher.start()
        append_log("input", f"เปิดตัวเฝ้าข้อความของบอท {name} ({bot.get('role')})")


_BOT_TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")


def _clean_bot_token(raw: str) -> str:
    """ดึงเฉพาะโทเคนออกจากสิ่งที่ผู้ใช้วางมา

    BotFather ส่งมาเป็นประโยคยาว ("Use this token to access the HTTP API: 123:AAF…")
    ผู้ใช้มักวางมาทั้งก้อน หรือคัดลอกมาไม่ครบเหลือแต่เลข ID — ดึงส่วนที่เป็นโทเคนจริง
    ให้ ถ้าไม่เจอรูปแบบที่ใช่ก็คืนข้อความที่ตัดช่องว่างแล้วไปให้ Telegram ตัดสิน
    """
    text = (raw or "").strip()
    found = _BOT_TOKEN_RE.search(text)
    return found.group(0) if found else text


def _bot_spec(name) -> dict:
    spec = TELEGRAM_BOTS.get(str(name or "main"))
    if spec is None:
        raise HTTPException(status_code=400, detail="ไม่รู้จักบอทนี้")
    return spec


@app.get("/api/telegram/config")
async def telegram_config() -> dict:
    """สถานะบอทแต่ละตัว — ถามชื่อจริงจาก Telegram ไม่ใช่บอกแค่ว่ามีไฟล์โทเคน

    ต้องเห็นชื่อ @ ของบอทถึงจะรู้ว่าช่องไหนเป็นตัวไหน (เคยวางโทเคนผิดช่องมาแล้ว
    แล้วบอทที่ใช้งานอยู่หายไปเลยโดยไม่รู้ตัว)
    """
    config = load_config()

    def describe(loader) -> dict:
        token = loader()
        if not token:
            return {"saved": False, "username": "", "ok": False, "error": ""}
        try:
            info = telegram_bot.describe_bot(token)
            return {"saved": True, "username": info["username"], "ok": True, "error": ""}
        except telegram_bot.TelegramError as error:
            return {"saved": True, "username": "", "ok": False, "error": str(error)[:120]}

    main, clip = await asyncio.gather(
        asyncio.to_thread(describe, load_telegram_token),
        asyncio.to_thread(describe, load_clip_token),
    )
    return {
        "ok": True,
        "token_saved": main["saved"],
        "chat_id": config.get("telegram_chat_id", ""),
        "auto_send": bool(config.get("telegram_auto_send", True)),
        "clip_token_saved": clip["saved"],
        "clip_chat_id": config.get("telegram_clip_chat_id", ""),
        "bots": {
            "main": {**main, "chat_id": config.get("telegram_chat_id", ""),
                     "label": TELEGRAM_BOTS["main"]["label"]},
            "clip": {**clip, "chat_id": config.get("telegram_clip_chat_id", ""),
                     "label": TELEGRAM_BOTS["clip"]["label"]},
        },
        # ไม่ได้ตั้งบอทคลิป = สายเจนคลิปวิ่งผ่านบอทหลักตัวเดียวกัน
        "clip_uses_main": not clip["saved"],
    }


def _backup_token(which: str, label: str, token: str) -> Path:
    """เก็บสำเนาโทเคนก่อนที่มันจะหายจากช่อง — เข้ารหัสเหมือนของจริง

    โทเคนอยู่ที่ไฟล์เดียวไม่มีสำเนา พอถูกแทนที่คือหายถาวร ต้องไปขอใหม่จาก
    BotFather ทุกครั้ง สำรองไว้ให้กู้กลับได้ถ้าเผลอ
    """
    folder = DATA_DIR / "bots_backup"
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9_-]", "_", label or "unknown")[:40]
    path = folder / f"{which}-{name}-{time.strftime('%Y%m%d-%H%M%S')}.bin"
    _save_key(path, token)
    return path


@app.delete("/api/telegram/config")
async def telegram_clear_config(bot: str = "main") -> dict:
    """ลบโทเคนออกจากช่อง — ต้องทำก่อนถ้าจะเปลี่ยนบอทของช่องนั้น

    มีไว้เป็นทางออกของกติกา "ห้ามเขียนทับ" การเปลี่ยนบอทจึงต้องตั้งใจสองจังหวะ
    ลบแล้วค่อยใส่ใหม่ พลาดวางผิดช่องจะไม่ทำให้บอทที่ใช้งานอยู่หายอีก
    """
    spec = _bot_spec(bot)
    token = spec["load"]() or ""
    if not token:
        return {"ok": True, "message": f"ช่อง \"{spec['label']}\" ว่างอยู่แล้ว"}
    label = ""
    try:
        label = (await asyncio.to_thread(
            telegram_bot.describe_bot, token
        )).get("username", "")
    except telegram_bot.TelegramError:
        label = "unknown"
    saved = await asyncio.to_thread(_backup_token, bot, label, token)
    spec["watcher"].stop()
    spec["file"].unlink(missing_ok=True)
    config = load_config()
    config[spec["chat_key"]] = ""
    save_config(config)
    append_log("input", f"ลบโทเคนช่อง {spec['label']} (@{label}) · สำรองไว้ {saved.name}")
    return {
        "ok": True,
        "message": f"ลบ @{label} ออกจากช่อง \"{spec['label']}\" แล้ว "
                   f"— สำรองไว้ที่ data/bots_backup/{saved.name}",
    }


@app.post("/api/telegram/config")
async def telegram_save_config(request: Request) -> dict:
    """บันทึกโทเคนบอท + chat id (หา chat id ให้เองถ้าเคยทักบอทแล้ว)"""
    payload = await request.json()
    which = str(payload.get("bot", "main"))
    spec = _bot_spec(which)
    typed = _clean_bot_token(str(payload.get("token", "")))
    token = typed or (spec["load"]() or "")
    if not token:
        raise HTTPException(status_code=400, detail="ยังไม่ได้ใส่โทเคนบอท")

    # **ตรวจก่อนบันทึกเสมอ** — ห้ามเขียนทับของเดิมแล้วค่อยไปรู้ทีหลังว่าใช้ไม่ได้
    # (เคยเกิดจริง: วางโทเคนมาไม่ครบเหลือแต่เลข ID โทเคนบอทที่ใช้งานได้อยู่หายไปเลย)
    try:
        info = await asyncio.to_thread(telegram_bot.describe_bot, token)
    except telegram_bot.TelegramError as error:
        detail = str(error)
        if "404" in detail:
            detail = (
                "Telegram ไม่รู้จักโทเคนนี้ — คัดลอกมาไม่ครบหรือถูกยกเลิกไปแล้ว\n"
                "โทเคนเต็มหน้าตาแบบนี้: 1234567890:AAF… (ยาวประมาณ 46 ตัว)\n"
                "ขอใหม่ได้ที่ @BotFather → /mybots → เลือกบอท → API Token"
            )
        raise HTTPException(status_code=400, detail=detail) from error

    replaced = ""
    if typed:
        # เก็บสำเนาโทเคนเดิมก่อนเขียนทับ **เสมอ**
        #
        # เจอจริง 11 ส.ค.: วางโทเคน @ClipAiABot ลงช่อง "บอทหลัก" ซึ่งเป็นโทเคนที่
        # ถูกต้องสมบูรณ์ ระบบจึงบันทึกให้โดยไม่ถามอะไร แล้ว @BeginerABot ที่อยู่
        # ช่องนั้นก็หายถาวร เพราะโทเคนเก็บไว้ที่ไฟล์เดียวไม่มีสำเนา
        #
        # ตัวตรวจเดิมถามแค่ว่า "โทเคนใช้ได้ไหม" ไม่เคยถามว่า "ช่องนี้มีใครอยู่แล้ว"
        old = spec["load"]() or ""
        if old and old != typed:
            # ช่องนี้มีบอทอยู่แล้ว — เช็คว่าเป็นคนละตัวไหม
            alive = ""
            try:
                alive = (await asyncio.to_thread(
                    telegram_bot.describe_bot, old
                )).get("username", "")
            except telegram_bot.TelegramError:
                alive = ""          # โทเคนเดิมตายแล้ว ทับได้ไม่มีอะไรให้เสีย

            if alive and alive.casefold() != (info.get("username") or "").casefold():
                # **ห้ามเขียนทับบอทคนละตัว** — ต้องตั้งใจลบก่อนเท่านั้น
                #
                # เจอจริง 11 ส.ค.: วางโทเคน @ClipAiABot ลงช่อง "บอทหลัก" ซึ่งเป็น
                # โทเคนที่ถูกต้องสมบูรณ์ ระบบจึงบันทึกให้เงียบๆ แล้ว @BeginerABot
                # หายถาวรเพราะโทเคนเก็บไว้ไฟล์เดียวไม่มีสำเนา
                # ตัวตรวจเดิมถามแค่ "โทเคนใช้ได้ไหม" ไม่เคยถาม "ช่องนี้มีใครอยู่"
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"ช่อง \"{spec['label']}\" ตอนนี้เป็น @{alive} อยู่ "
                        f"จะเขียนทับด้วย @{info.get('username','')} ไม่ได้\n\n"
                        f"ถ้าตั้งใจเปลี่ยนจริง ให้ลบโทเคนช่องนี้ก่อน "
                        f"(ปุ่มลบ หรือ DELETE /api/telegram/config?bot={which}) "
                        f"แล้วค่อยวางโทเคนใหม่\n"
                        f"ถ้าไม่ได้ตั้งใจ แปลว่าวางผิดช่อง — @{info.get('username','')} "
                        f"น่าจะต้องไปอยู่อีกช่องหนึ่ง"
                    ),
                )
            replaced = alive or "(โทเคนเดิมใช้ไม่ได้แล้ว)"
            await asyncio.to_thread(_backup_token, which, replaced, old)
        await asyncio.to_thread(spec["save"], typed)      # ผ่านแล้วค่อยบันทึก

    watcher = spec["watcher"]
    chat_id = str(payload.get("chat_id", "")).strip()
    config = load_config()
    if not chat_id:
        # เอาจาก watcher ก่อน — ห้ามเรียก getUpdates เองตรงนี้ เพราะ offset ใช้ร่วมกัน
        # เรียกซ้อนกันจะแย่งข้อความกันจนหา chat id ไม่เจอทั้งคู่
        chat_id = watcher.last_chat_id or config.get(spec["chat_key"], "")
    if not chat_id and not watcher.thread:
        # watcher ยังไม่ทำงาน (เพิ่งใส่โทเคน) ถามเองรอบเดียวได้
        chat_id = await asyncio.to_thread(telegram_bot.find_chat_id, token)
    config[spec["chat_key"]] = chat_id
    if which == "main":
        config["telegram_auto_send"] = bool(payload.get("auto_send", True))
    save_config(config)
    # เริ่มตัวเฝ้าได้เฉพาะบอทที่ **เซิร์ฟเวอร์นี้เป็นเจ้าของ**
    #
    # บอทคลิปถูกอ่านโดย clip_app.py (พอร์ต 8877) ถ้าที่นี่สั่ง start ด้วย จะกลายเป็น
    # สองโปรเซสอ่าน getUpdates ของโทเคนเดียวกัน → Telegram ตอบ 409 แล้วข้อความ
    # หายสลับไปมา (เจอจริง 11 ส.ค. 20:23 เป็นต้นไป: 8866 มี 2 สาย / 8877 มี 0 สาย)
    #
    # โค้ดตอนเปิดเซิร์ฟเวอร์มีคอมเมนต์ห้ามไว้อยู่แล้ว แต่เส้นทาง "กดบันทึกโทเคน"
    # หลุดกติกานี้ไป เพราะ start() ถูกเรียกท้ายฟังก์ชันโดยไม่ดูว่าเป็นช่องไหน
    if which != "clip":
        watcher.start()
    message = (
        f"เชื่อม {spec['label']} = @{info['username']} แล้ว" if chat_id
        else f"เชื่อม @{info['username']} แล้ว แต่ยังไม่รู้ chat id — "
             "ทัก /start ให้บอทในแอป Telegram แล้วกดบันทึกอีกครั้ง"
    )
    if replaced:
        # เตือนให้เห็นทันทีว่าเพิ่งทับใคร — วางผิดช่องจะได้รู้ตัวตรงนั้น
        # ไม่ใช่ไปรู้ทีหลังตอนบอทอีกตัวเงียบไป
        message = (
            f"⚠️ ช่องนี้เดิมเป็น @{replaced} — ถูกแทนที่ด้วย @{info['username']} แล้ว\n"
            "โทเคนเดิมสำรองไว้ที่ data/bots_backup/ (ถ้าวางผิดช่องยังกู้ได้)\n" + message
        )
    return {
        "ok": True, "bot": info, "chat_id": chat_id,
        "replaced": replaced, "message": message,
    }


@app.get("/api/telegram/bots")
async def telegram_list_bots() -> dict:
    """รายชื่อบอทเพิ่มเติม — ไม่คืนโทเคนออกไป คืนแค่ว่ามีหรือยัง"""
    items = []
    for bot in extra_bots():
        items.append({
            "id": bot["id"],
            "name": bot.get("name", bot["id"]),
            "role": bot.get("role", "facebook"),
            "chat_id": bot.get("chat_id", ""),
            "token_saved": bool(extra_bot_token(bot["id"])),
            "watching": bot["id"] in _extra_watchers,
        })
    return {"ok": True, "bots": items, "roles": BOT_ROLES}


@app.post("/api/telegram/bots")
async def telegram_add_bot(request: Request) -> dict:
    """เพิ่มบอทใหม่ หรือแก้บอทเดิม (ส่ง id มาด้วยถ้าจะแก้)"""
    payload = await request.json()
    # กันฝั่งหน้าเว็บส่ง body ผิดรูป — เดิมเด้ง 500 AttributeError อ่านไม่รู้เรื่อง
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="รูปแบบข้อมูลที่ส่งมาไม่ถูกต้อง")
    token = _clean_bot_token(str(payload.get("token", "")))
    bot_id = str(payload.get("id", "")).strip()
    role = str(payload.get("role", "facebook"))
    if role not in BOT_ROLES:
        raise HTTPException(status_code=400, detail="หน้าที่ของบอทไม่ถูกต้อง")

    items = extra_bots()
    existing = next((b for b in items if b["id"] == bot_id), None)
    if token:
        try:
            info = await asyncio.to_thread(telegram_bot.describe_bot, token)
        except telegram_bot.TelegramError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    elif existing is None:
        raise HTTPException(status_code=400, detail="ยังไม่ได้ใส่โทเคนบอท")
    else:
        info = {"username": existing.get("username", ""), "name": existing["name"]}

    if existing is None:
        # บอทตัวเดิมที่เพิ่มซ้ำ = แก้ตัวเดิม ไม่ใช่สร้างรายการใหม่
        #
        # เจอจริง 11 ส.ค.: @TikTokAiABot ถูกเพิ่ม 5 ครั้ง ได้ 5 รายการคนละ id
        # ระบบจึงสร้างตัวเฝ้า 5 ตัวมาแย่ง getUpdates ของโทเคนเดียวกันเอง
        # → Telegram ตอบ 409 ทุกตัว ไม่มีใครอ่านได้เลย กลายเป็น "บอทเชื่อมไม่ได้"
        username = (info.get("username") or "").casefold()
        existing = next(
            (b for b in items
             if username and str(b.get("username", "")).casefold() == username),
            None,
        )
    if existing is None:
        bot_id = f"b{int(time.time() * 1000) % 1_000_000_000}"
        existing = {"id": bot_id}
        items.append(existing)
    existing.update({
        "name": str(payload.get("name", "")).strip()[:40]
                or info.get("username") or existing.get("name") or bot_id,
        "role": role,
        "username": info.get("username", existing.get("username", "")),
        "chat_id": str(payload.get("chat_id", existing.get("chat_id", ""))).strip(),
    })
    if token:
        BOT_DIR.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(_save_key, extra_bot_file(existing["id"]), token)
    save_extra_bots(items)
    # ปิดตัวเฝ้าเดิมก่อน เพื่อให้สร้างใหม่ด้วยหน้าที่/โทเคนล่าสุด
    watcher = _extra_watchers.pop(existing["id"], None)
    if watcher:
        watcher.stop()
    sync_extra_watchers()
    append_log("input", f"บันทึกบอท {existing['name']} ({role})")
    return {"ok": True, "bot": {**existing, "token_saved": True},
            "message": f"บันทึกบอท @{existing.get('username') or existing['name']} แล้ว"}


@app.delete("/api/telegram/bots/{bot_id}")
async def telegram_delete_bot(bot_id: str) -> dict:
    items = extra_bots()
    kept = [b for b in items if b["id"] != bot_id]
    if len(kept) == len(items):
        raise HTTPException(status_code=404, detail="ไม่พบบอทนี้")
    save_extra_bots(kept)
    watcher = _extra_watchers.pop(bot_id, None)
    if watcher:
        watcher.stop()
    extra_bot_file(bot_id).unlink(missing_ok=True)      # ลบโทเคนทิ้งด้วย
    append_log("input", f"ลบบอท {bot_id} ออกจากทะเบียน")
    return {"ok": True}


@app.post("/api/telegram/bots/{bot_id}/test")
async def telegram_test_bot(bot_id: str) -> dict:
    bot = next((b for b in extra_bots() if b["id"] == bot_id), None)
    if bot is None:
        raise HTTPException(status_code=404, detail="ไม่พบบอทนี้")
    token = extra_bot_token(bot_id)
    if not token or not bot.get("chat_id"):
        raise HTTPException(
            status_code=400,
            detail="ยังไม่ครบ — ใส่โทเคนแล้วทัก /start ให้บอทหนึ่งครั้ง",
        )
    try:
        await asyncio.to_thread(
            telegram_bot.call, token, "sendMessage",
            {"chat_id": bot["chat_id"],
             "text": f"ทดสอบบอท {bot['name']} จาก Pipeline Studio ✅"},
        )
    except telegram_bot.TelegramError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"ok": True, "message": "ส่งข้อความทดสอบแล้ว"}


@app.post("/api/telegram/test")
async def telegram_test(request: Request) -> dict:
    body = await request.body()
    spec = _bot_spec((json.loads(body) if body else {}).get("bot", "main"))
    token = spec["load"]()
    chat_id = load_config().get(spec["chat_key"], "")
    if not token or not chat_id:
        raise HTTPException(status_code=400, detail="ยังตั้งค่าบอทไม่ครบ")
    try:
        await asyncio.to_thread(
            telegram_bot.call, token, "sendMessage",
            {"chat_id": chat_id, "text": f"ทดสอบ {spec['label']} จาก Pipeline Studio ✅"},
        )
    except telegram_bot.TelegramError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"ok": True, "message": "ส่งข้อความทดสอบแล้ว"}


def request_approval(product: str, highlights: list[str], extra: dict | None = None) -> dict:
    """สร้างคำขออนุมัติแล้วส่งเข้า Telegram (ถ้าตั้งค่าไว้)"""
    entry = approval_store.add(product, highlights, extra)
    token, chat_id = clip_channel()
    if not token or not chat_id:
        approval_store.update(entry["id"], channel="web")
        append_log("input", "ยังไม่ได้ตั้งค่า Telegram — อนุมัติที่หน้าเว็บแทน")
        return {**entry, "channel": "web"}
    try:
        message_id = telegram_bot.send_approval(token, chat_id, entry)
        approval_store.update(entry["id"], message_id=message_id, channel="telegram")
        append_log("input", f"ส่งจุดขายไปให้อนุมัติทาง Telegram แล้ว ({entry['id']})")
        return {**entry, "channel": "telegram", "message_id": message_id}
    except telegram_bot.TelegramError as error:
        # ส่งไม่ออกต้องไม่ทำให้การดึงข้อมูลทั้งก้อนล้ม — ถอยไปอนุมัติหน้าเว็บ
        approval_store.update(entry["id"], channel="web")
        append_log("input", f"ส่ง Telegram ไม่สำเร็จ ({error}) — อนุมัติที่หน้าเว็บแทน")
        return {**entry, "channel": "web", "error": str(error)}


@app.post("/api/approvals/video")
async def request_video_approval(request: Request) -> dict:
    """Approve รอบสองตามผัง — คลิปเจนเสร็จแล้วส่งเข้า Telegram ให้ดูก่อนโพสต์

    ต้องประกาศก่อน /api/approvals/{approval_id}/... ไม่งั้นคำว่า video
    จะถูกจับเป็น approval_id
    """
    payload = await request.json()
    video = Path(str(payload.get("video", "")).strip())
    product = str(payload.get("product", "")).strip() or video.name
    if not video.is_file():
        raise HTTPException(status_code=400, detail=f"ไม่พบไฟล์คลิป {video}")

    entry = approval_store.add(product, [], extra={"kind": "video", "video": str(video)})
    token, chat_id = clip_channel()
    if not token or not chat_id:
        approval_store.update(entry["id"], channel="web")
        return {"ok": True, **entry, "channel": "web"}
    try:
        message_id = await asyncio.to_thread(
            telegram_bot.send_video_approval, token, chat_id, entry, video
        )
    except telegram_bot.TelegramError as error:
        approval_store.update(entry["id"], channel="web")
        append_log("release", f"ส่งคลิปเข้า Telegram ไม่สำเร็จ ({error}) — อนุมัติหน้าเว็บแทน")
        return {"ok": True, **entry, "channel": "web", "error": str(error)}
    approval_store.update(entry["id"], message_id=message_id, channel="telegram")
    append_log("release", f"ส่งคลิปให้อนุมัติทาง Telegram แล้ว ({entry['id']})")
    return {"ok": True, **entry, "channel": "telegram", "message_id": message_id}


@app.post("/api/approvals/{approval_id}/resend")
async def resend_approval(approval_id: str) -> dict:
    """ส่งการ์ดขออนุมัติเข้า Telegram ซ้ำ — ใช้เมื่อข้อความหายหรืออยากทดสอบใหม่

    ตั้งสถานะกลับเป็น pending ด้วย ไม่งั้นกดปุ่มในการ์ดใหม่แล้วผลไม่เปลี่ยน
    (การ์ดเก่ายังกดได้อยู่ แต่ผลจะทับกัน — อันไหนกดทีหลังชนะ)
    """
    entry = approval_store.get(approval_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="ไม่พบคำขอนี้")
    token, chat_id = clip_channel()
    if not token or not chat_id:
        raise HTTPException(status_code=400, detail="ยังตั้งค่าบอทไม่ครบ")
    entry = approval_store.update(approval_id, status="pending", decided_at=None)
    try:
        message_id = await asyncio.to_thread(
            telegram_bot.send_approval, token, chat_id, entry
        )
    except telegram_bot.TelegramError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    approval_store.update(approval_id, message_id=message_id, channel="telegram")
    return {"ok": True, "id": approval_id, "message_id": message_id}


@app.get("/api/approvals")
async def list_approvals() -> dict:
    return {"ok": True, "items": approval_store.listing()[:30]}


@app.get("/api/approvals/{approval_id}")
async def get_approval(approval_id: str) -> dict:
    entry = approval_store.get(approval_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="ไม่พบคำขอนี้")
    return {"ok": True, **entry}


@app.post("/api/approvals/{approval_id}")
async def decide_approval(approval_id: str, request: Request) -> dict:
    """อนุมัติ/ปฏิเสธจากหน้าเว็บ — ทางสำรองเมื่อไม่ได้ใช้ Telegram"""
    payload = await request.json()
    status = str(payload.get("status", "")).strip()
    if status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="สถานะต้องเป็น approved หรือ rejected")
    changes: dict = {
        "status": status,
        "decided_at": datetime.now().isoformat(timespec="seconds"),
    }
    highlights = payload.get("highlights")
    if isinstance(highlights, list) and highlights:
        changes["highlights"] = [str(item).strip() for item in highlights if str(item).strip()]
        changes["edited"] = True

    # **ของที่ผู้ใช้เห็นต้องแก้ได้ทุกอย่าง ไม่ใช่แค่จุดขาย** (หลักการข้อ 3 ของโปรเจกต์)
    # ตัวคัดอัตโนมัติเลือกชื่อ/รูปผิดได้เสมอ ของเดิมรับกลับมาแค่ `highlights`
    # ชื่อที่แก้กับรูปที่เขี่ยออกจึงหายไปเงียบๆ ตอนกดอนุมัติ แล้วขั้นถัดไป
    # หยิบของเดิมไปใช้ทั้งที่ผู้ใช้แก้แล้ว — เสียเครดิตเจนคลิปฟรีเพราะเรื่องนี้
    product = str(payload.get("product", "")).strip()
    if product:
        changes["product"] = product
        changes["edited"] = True
    images = payload.get("images")
    if isinstance(images, list):
        # เก็บเฉพาะไฟล์ที่มีอยู่จริง — กันพาธค้างจากหน้าเว็บที่เปิดทิ้งไว้ข้ามวัน
        kept = [str(p) for p in images if str(p).strip() and Path(str(p)).is_file()]
        if kept:
            changes["images"] = kept
            changes["edited"] = True
    spare = payload.get("features")
    if isinstance(spare, list):
        changes["features"] = [str(item).strip() for item in spare if str(item).strip()]

    entry = approval_store.update(approval_id, **changes)
    if entry is None:
        raise HTTPException(status_code=404, detail="ไม่พบคำขอนี้")
    return {"ok": True, **entry}


# ================================== โพสต์ลงกลุ่ม Facebook อัตโนมัติ (Telegram)
# ผู้ใช้ส่ง "แคปชัน + รูป" เข้าบอท → บอทตอบการ์ดให้ติ๊กกลุ่ม → กดโพสต์ →
# เครื่องไล่โพสต์ทีละกลุ่มผ่าน ADB แล้วรายงานผลกลับเข้าแชท
#
# ทำไมต้องกดยืนยันก่อนโพสต์ (ค่าเริ่มต้น):
#   โพสต์ลงกลุ่มแล้วเรียกคืนไม่ได้ และผิดกลุ่มทีเดียวโดนเตะออกจากกลุ่มได้เลย
#   จะให้ยิงทันทีที่ส่งรูปก็ทำได้ แต่ต้องเปิด auto_start เอง

fb_groups = fb_auto_post.GroupStore(studio_shared.post_file("fb_groups.json"))
fb_jobs = fb_auto_post.JobStore(studio_shared.post_file("fb_jobs.json"))
fb_runner = fb_auto_post.RunnerPool()

# กลุ่มที่ผู้ใช้เคยโพสต์จริงมาแล้ว — ใส่ให้ตั้งแต่แรกจะได้ไม่ต้องพิมพ์ใหม่
# ลบทิ้งได้ตามปกติ และจะเติมให้ครั้งเดียวตอนไฟล์ยังไม่มีเท่านั้น
FB_SEED_GROUPS = [
    ("184764596840853", "รีวิวของใช้&ของแต่งบ้าน Shopee / Lazada"),
    ("577202126940489", "แชร์ตรงปกมาก shopee / lazada"),
    ("1911903035616571", "รีวิวครอบจักรวาล"),
    ("3572170672880410", "รีวิวของดีประจำวัน"),
    ("329297298358942", "ช้อปขั้นเทพ"),
]


def _fb_reclaim_interrupted() -> None:
    """เก็บกวาดงานที่ค้างสถานะ "กำลังโพสต์" จากโปรเซสที่ตายไปแล้ว

    เปิดเซิร์ฟเวอร์ใหม่ = ไม่มีอะไรกำลังรันอยู่จริงแน่นอน งานที่ยังเป็น running
    จึงเป็นซากจากรอบก่อนที่ถูกตัดกลางคัน (รีสตาร์ต / โปรเซสถูกฆ่า / ไฟดับ)

    ไม่เก็บกวาด = ค้างตลอดกาล เพราะ on_done ของรอบนั้นไม่มีวันทำงานแล้ว
    เธรดตายไปพร้อมโปรเซส (เจอจริง 12 ส.ค. งาน p545241529: รีสตาร์ตตอน 22:50:59
    ระหว่างโพสต์กลุ่มที่ 5 · สถานะค้าง running · finished_at = None)
    """
    stuck = [
        j for j in fb_jobs.listing()
        if j.get("status") == fb_auto_post.STATUS_RUNNING
    ]
    for job in stuck:
        done = sum(1 for r in (job.get("results") or []) if r.get("posted"))
        total = len(job.get("groups") or []) or done
        fb_jobs.update(
            job["id"], status=fb_auto_post.STATUS_FAILED,
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )
        append_log(
            "publish",
            f"[{job['id']}] ถูกตัดกลางคันตอนเซิร์ฟเวอร์ปิด — "
            f"โพสต์ไปแล้ว {done}/{total} กลุ่ม",
        )
    if stuck:
        append_log("publish", f"เก็บกวาดงานค้างจากรอบก่อน {len(stuck)} งาน")


def _fb_seed_groups() -> None:
    if studio_shared.post_file("fb_groups.json").is_file():
        return
    for group_id, name in FB_SEED_GROUPS:
        fb_groups.add(group_id, name)
    append_log("publish", f"ใส่กลุ่มตั้งต้นให้ {len(FB_SEED_GROUPS)} กลุ่ม (ลบได้)")


def _fb_settings() -> dict:
    return load_config().get("facebook") or {}


def _fb_gap_range(serial: str = "") -> tuple[float, float]:
    """เว้นระยะระหว่างกลุ่มของ**เครื่องนั้น** — ไม่ส่ง serial มาก็ได้ค่ากลาง

    ต้องแยกรายเครื่องเพราะแต่ละเครื่องคนละบัญชี บัญชีที่เพิ่งโดนเตือนสแปมต้อง
    เว้นห่างกว่าบัญชีที่ยังสะอาด — บังคับให้ทั้งสองเครื่องใช้ค่าเดียวกันแปลว่า
    ต้องเลือกระหว่าง "ช้าทั้งคู่" กับ "เสี่ยงทั้งคู่"
    """
    settings = device_book.settings(serial) if serial else _fb_settings()
    low = float(settings.get("gap_min", 15) or 15)
    high = float(settings.get("gap_max", 20) or 20)
    return (min(low, high), max(low, high))


def _fb_serial(serial: str = "", *, allow_default: bool = True) -> str:
    """เครื่องที่จะใช้โพสต์ — ถามทะเบียนมือถือเป็นหลัก

    ของเดิม "ไม่ได้ตั้งไว้ก็หยิบเครื่องแรกที่พร้อม" ซึ่งเป็นการ**เดา** พอเสียบเครื่อง
    ที่สองเข้ามา ลำดับของ `adb devices` เปลี่ยนเมื่อไรก็โพสต์ลงบัญชีผิดเครื่องทันที
    โดยไม่มีอะไรเตือน — ความเสียหายแบบนั้นกู้คืนไม่ได้

    ตอนนี้ให้ทะเบียนเป็นคนตอบ: บอก serial มาก็ใช้ตัวนั้น · ไม่บอกแล้วมีเครื่อง
    เปิดใช้เครื่องเดียวก็ใช้เครื่องนั้น · มีหลายเครื่องจะถอยไปใช้ "เครื่องตัวหลัก"
    ที่ผู้ใช้ตั้งไว้เอง (ไม่ใช่เดา) · ไม่มีตัวหลักด้วยก็ปฏิเสธพร้อมบอกชื่อทุกเครื่อง
    ให้เลือก

    ยังตรวจว่าเครื่องนั้นเสียบอยู่จริงไหมเหมือนเดิม — ทะเบียนรู้ว่า "ควรใช้เครื่องไหน"
    แต่ไม่รู้ว่า "ตอนนี้สายหลุดหรือเปล่า"
    """
    try:
        picked = device_book.resolve(serial, lane="post", allow_default=allow_default)
    except device_book.DeviceError as error:
        raise fb_auto_post.AutoPostError(str(error)) from error
    ready = [d["serial"] for d in list_devices() if d["ready"]]
    if picked not in ready:
        raise fb_auto_post.AutoPostError(
            f"มือถือ {device_book.label(picked)} ไม่ได้เชื่อมต่ออยู่ — "
            "เสียบสายแล้วกดรีเฟรชรายการอุปกรณ์"
        )
    return picked


def _fb_telegram() -> tuple[str, str]:
    """โทเคน + chat id ที่ใช้คุยเรื่องงานโพสต์

    บอทหลักไม่พร้อม (โทเคนหาย/ยังไม่ตั้ง) ก็ใช้บอทเพิ่มเติมที่ตั้งหน้าที่เป็น
    facebook แทน — จะได้ไม่เงียบทั้งระบบเพราะบอทตัวเดียวมีปัญหา
    """
    token = load_telegram_token() or ""
    chat_id = load_config().get("telegram_chat_id", "")
    if token and chat_id:
        return token, chat_id
    for spare_token, spare_chat in extra_channels("facebook"):
        return spare_token, spare_chat
    return token, chat_id


def _fb_say(chat_id: str, text: str, keyboard: dict | None = None) -> int:
    """ส่งข้อความเข้าแชท — ส่งไม่ออกต้องไม่ทำให้งานทั้งก้อนล้ม"""
    token, default_chat = _fb_telegram()
    target = chat_id or default_chat
    if not token or not target:
        return 0
    try:
        return telegram_bot.send_message(token, target, text, keyboard)
    except telegram_bot.TelegramError as error:
        append_log("publish", f"ส่งข้อความเข้า Telegram ไม่ได้: {error}")
        return 0


FB_STATUS_LABEL = {
    fb_auto_post.STATUS_WAIT_CAPTION: "รอแคปชัน — พิมพ์ข้อความที่จะโพสต์มาได้เลย",
    fb_auto_post.STATUS_WAIT_IMAGE: "รอรูป — ส่งรูปที่จะแนบมาได้เลย",
    fb_auto_post.STATUS_READY: "พร้อมโพสต์ — ติ๊กกลุ่มแล้วกด 🚀",
    fb_auto_post.STATUS_RUNNING: "กำลังโพสต์…",
    fb_auto_post.STATUS_DONE: "โพสต์เสร็จแล้ว",
    fb_auto_post.STATUS_FAILED: "ล้มเหลว",
    fb_auto_post.STATUS_CANCELLED: "ยกเลิกแล้ว",
}


def _fb_card(job: dict) -> tuple[str, dict | None]:
    """ข้อความ + ปุ่มของการ์ดงานหนึ่งใบ"""
    escape = telegram_bot._escape
    caption = job.get("caption", "")
    lines = [
        f"📮 <b>งานโพสต์ {job['id']}</b>",
        f"🖼 รูป: {len(job.get('images') or ([job['image']] if job.get('image') else []))} ใบ"
        f" (สูงสุด {facebook_group_post.MAX_PHOTOS})"
        if job.get("image") else "🖼 รูป: — ยังไม่ได้ส่ง",
        f"📝 แคปชัน: {escape(caption[:300]) if caption else '— ยังไม่มี'}",
        *( _fb_comment_lines(job) or ["💬 คอมเมนต์: — ไม่มี (/comment)"] ),
        f"📦 ชุดกลุ่ม: {escape(job.get('set', '') or 'ทั้งหมด')}",
        f"⏰ เวลาโพสต์: {_fb_when_text(job.get('run_at', '')) or '— กดเอง (/schedule)'}",
        f"สถานะ: {FB_STATUS_LABEL.get(job['status'], job['status'])}",
    ]

    results = job.get("results") or []
    if results:
        lines.append("")
        lines.append(fb_auto_post.summarize(results, fb_groups.label))

    if job["status"] not in fb_auto_post.OPEN_STATUSES:
        # งานที่ปิดไปแล้วอาจยัง "ตามเก็บ" อยู่บนมือถือ (สถานะเป็น done แต่ตัวรันทำงานอยู่)
        # ต้องมีปุ่มหยุดให้กด ไม่งั้นผู้ใช้กดยกเลิกไม่ได้เลยทั้งที่มือถือยังทำงาน
        if fb_runner.job_running(job["id"]):
            return "\n".join(lines), {"inline_keyboard": [[
                {"text": "⏹ หยุดงานที่กำลังทำ", "callback_data": f"fb:x:{job['id']}"},
            ]]}
        return "\n".join(lines), None

    selected = set(job.get("groups") or [])
    rows = []
    for group in fb_groups.listing():
        mark = "✅" if group["group_id"] in selected else "⬜"
        rows.append([{
            "text": f"{mark} {group['name'][:40]}",
            "callback_data": f"fb:t:{job['id']}:{group['group_id']}",
        }])
    # แถวปุ่มสลับชุด — กดแล้วเปลี่ยนกลุ่มทั้งชุดในงานนี้เลย
    buckets = fb_groups.sets()
    if len(buckets) > 1:
        rows.append([
            {
                "text": f"📦 {name} ({len(items)})",
                "callback_data": f"fb:set:{job['id']}:{name}",
            }
            for name, items in list(buckets.items())[:4]
        ])
    if not rows:
        lines += ["", "⚠️ ยังไม่มีกลุ่มในรายการ — ส่งลิงก์กลุ่มมาในแชทนี้เพื่อเพิ่ม"]
    else:
        lines += ["", "แตะชื่อกลุ่มเพื่อเปิด/ปิดการโพสต์กลุ่มนั้น"]
    rows.append([
        {
            "text": f"☑️ เลือกทั้งชุด ({len(selected)}/{fb_auto_post.MAX_GROUPS_PER_POST})",
            "callback_data": f"fb:all:{job['id']}",
        },
        {"text": "⬜ ไม่เลือกเลย", "callback_data": f"fb:none:{job['id']}"},
    ])
    ready = job["status"] == fb_auto_post.STATUS_READY and selected
    rows.append([
        {
            "text": f"🚀 โพสต์ {len(selected)} กลุ่ม" if ready else "🚀 ยังโพสต์ไม่ได้",
            "callback_data": f"fb:go:{job['id']}",
        },
        {"text": "🗑 ยกเลิกงาน", "callback_data": f"fb:x:{job['id']}"},
    ])
    return "\n".join(lines), {"inline_keyboard": rows}


def _fb_show_card(job: dict) -> dict:
    """ส่งการ์ดใหม่ (ครั้งแรก) หรือแก้ใบเดิมให้เป็นสถานะล่าสุด"""
    token, default_chat = _fb_telegram()
    chat_id = job.get("chat_id") or default_chat
    if not token or not chat_id:
        return job
    text, keyboard = _fb_card(job)
    try:
        if job.get("message_id"):
            telegram_bot.edit_message(token, chat_id, job["message_id"], text, keyboard)
            return job
        message_id = telegram_bot.send_message(token, chat_id, text, keyboard)
    except telegram_bot.TelegramError as error:
        append_log("publish", f"อัปเดตการ์ดงานไม่สำเร็จ: {error}")
        return job
    return fb_jobs.update(job["id"], message_id=message_id, chat_id=chat_id) or job


def _fb_new_job(chat_id: str, **fields) -> dict:
    """เปิดงานใหม่ พร้อมปิด**ร่าง**เก่าที่ค้างอยู่

    ต้องปิดร่างเก่าทิ้ง ไม่งั้นรูปที่ส่งมาทีหลังจะไปเข้ากับงานไหนก็เดาไม่ถูก
    (ผู้ใช้ส่งรูปใหม่ = ตั้งใจเริ่มงานใหม่ ไม่ใช่แก้ของเก่า)

    **แต่ห้ามแตะงานที่ตั้งเวลาไว้แล้ว** — งานที่มี run_at คืองานที่ผู้ใช้สั่งเสร็จ
    เรียบร้อยแล้ว ไม่ใช่ร่างที่ค้างอยู่

    เจอจริง 13 ส.ค.: ตั้งงาน p616725077 ไว้ 18:30 ตอน 17:26 พอส่งงานใหม่เข้ามา
    ตอน 17:37 งาน 18:30 ถูกล้างทิ้ง**เงียบสนิท** — ไม่มีทั้ง log และข้อความแจ้ง
    เพราะเรียก update() ตรงๆ ไม่ผ่าน _fb_cancel_job สุดท้ายไม่ได้โพสต์ทั้ง 6 กลุ่ม
    โดยไม่มีใครรู้จนผู้ใช้มาถามเองตอน 19:13

    รอบนี้จึงเพิ่มทั้งสองอย่าง: ไม่แตะงานที่ตั้งเวลา และยกเลิกทีต้องดังพอให้รู้ตัว
    """
    for old in fb_jobs.listing():
        if old["status"] not in fb_auto_post.OPEN_STATUSES:
            continue
        if old.get("run_at"):
            continue                 # ตั้งเวลาไว้แล้ว = ไม่ใช่ร่าง อย่าไปยุ่ง
        fb_jobs.update(old["id"], status=fb_auto_post.STATUS_CANCELLED)
        append_log("publish", f"[{old['id']}] ปิดร่างเก่าเพราะเริ่มงานใหม่")
        # บอกเฉพาะร่างที่มีเนื้อจริง — ร่างเปล่าไม่ต้องกวนผู้ใช้
        if chat_id and (old.get("caption") or old.get("images")
                        or old.get("image")):
            _fb_say(chat_id, f"🗑 ปิดร่าง {old['id']} เพราะเริ่มงานใหม่")
    active_set = load_config().get("facebook", {}).get("set", "")
    return fb_jobs.add(
        chat_id=chat_id, set=active_set,
        groups=fb_groups.enabled_ids(active_set), **fields,
    )


def _fb_cancel_job(job_id: str) -> str:
    """ยกเลิกงาน — และ**สั่งหยุดตัวรันด้วย** ถ้างานนี้กำลังทำอยู่บนมือถือ

    เดิมกดยกเลิกแล้วแค่เปลี่ยนสถานะในไฟล์ ตัวรันที่ไล่กดบนมือถืออยู่ไม่รู้เรื่องเลย
    ผู้ใช้เห็นการ์ดขึ้นว่า "ยกเลิกแล้ว" แต่มือถือยังไล่โพสต์กลุ่มถัดไปต่อจนครบ
    (เจอจริง 11 ส.ค. — ผู้ใช้กดยกเลิกแล้วงานยังรันอยู่)

    หยุดได้เร็วสุดคือ "จบกลุ่มที่ทำค้างอยู่ก่อน" ไม่ตัดกลางคัน เพราะตัดตอนกำลัง
    เขียนโพสต์จะทิ้งฉบับร่างค้างไว้ แล้วรอบหน้าเจอกล่องถามฉบับร่างบังหน้ากลุ่ม
    """
    job = fb_jobs.get(job_id)
    if job is None:
        return "ไม่พบงานนี้"
    fb_jobs.update(job_id, status=fb_auto_post.STATUS_CANCELLED)
    # หยุดงานนี้ไม่ว่ามันไปรันอยู่บนเครื่องไหน — ของเดิมถามตัวรันตัวเดียวของระบบ
    # ซึ่งพอมีหลายเครื่องจะตอบว่า "ไม่ได้ทำงานนี้อยู่" แล้วมือถือก็โพสต์ต่อเงียบๆ
    stopped = fb_runner.stop_job(job_id)
    if stopped:
        append_log("publish", f"[{job_id}] ผู้ใช้สั่งยกเลิก — "
                              f"สั่งหยุดตัวรันบน {device_book.label(stopped)} แล้ว")
        return "ยกเลิกแล้ว — หยุดหลังกลุ่มที่กำลังทำอยู่จบ"
    append_log("publish", f"[{job_id}] ยกเลิกงาน")
    return "ยกเลิกงานแล้ว"


REPOST_LIMIT = 6


def _fb_repostable() -> list[dict]:
    """งานเก่าที่เอามาโพสต์ซ้ำได้ — ต้องมีทั้งแคปชันและไฟล์รูปที่ยังอยู่จริง

    ไม่กรองตามสถานะ เพราะงานที่ล้มกลางคันหรือถูกยกเลิกก็เป็นตัวที่อยากทำใหม่
    มากที่สุด แต่ต้องเช็คว่าไฟล์รูปยังอยู่ ไม่งั้นกดแล้วไปตายตอนจะโพสต์
    """
    out: list[dict] = []
    seen: set[str] = set()
    for job in fb_jobs.listing():
        if job["status"] in fb_auto_post.OPEN_STATUSES:
            continue                     # ยังไม่ได้โพสต์ ไม่ต้องทำซ้ำ
        caption = (job.get("caption") or "").strip()
        if not caption:
            continue
        # ยุบงานที่แคปชันเหมือนกันให้เหลือใบล่าสุดใบเดียว
        #
        # การกดทำซ้ำสร้าง "งานใหม่" ที่ตัวมันเองก็เข้าเงื่อนไขนี้อีก กดสามรอบ
        # รายการจะกลายเป็นสำเนาของโพสต์เดียวกันสามใบแล้วดันโพสต์อื่นตกขอบ
        # (เจอจริง 11 ส.ค.: รายการ 6 ช่อง เหลือโพสต์ที่ต่างกันจริงแค่ 3)
        key = " ".join(caption.split())[:120]
        if key in seen:
            continue
        seen.add(key)
        shots = [p for p in (job.get("images") or [job.get("image", "")]) if p]
        if not any(Path(p).is_file() for p in shots):
            continue
        out.append(job)
        if len(out) >= REPOST_LIMIT:
            break
    return out


def _fb_copy_asset(source: str, target: Path) -> str:
    """คัดลอกไฟล์รูปให้งานใหม่เป็นเจ้าของเอง คืน path ใหม่ ("" = คัดลอกไม่ได้)

    ต้องคัดลอก ไม่ใช่ชี้ไปไฟล์เดิมร่วมกัน — ถ้าใช้ไฟล์ร่วมกัน วันหลังลบงานเก่า
    หรือเขียนทับ งานใหม่จะรูปหายตามไปด้วยโดยไม่รู้ตัว
    """
    origin = Path(source)
    if not origin.is_file():
        return ""
    target.write_bytes(origin.read_bytes())
    return str(target)


def _fb_clone_job(job_id: str, chat_id: str) -> tuple[dict | None, str]:
    """สร้างงานใหม่จากงานเก่า — คืน (งานใหม่, ข้อความบอกปัญหา)

    คัดลอกมาทั้ง แคปชัน · รูปโพสต์ · คอมเมนต์ · รูปแนบคอมเมนต์ · ชุดกลุ่ม
    แต่**ไม่ลอกผลลัพธ์และเวลาที่ตั้งไว้** เพราะงานใหม่ต้องเริ่มนับหนึ่งจริงๆ
    """
    source = fb_jobs.get(job_id)
    if source is None:
        return None, f"ไม่พบงาน {job_id}"
    caption = (source.get("caption") or "").strip()
    if not caption:
        return None, f"งาน {job_id} ไม่มีแคปชัน ทำซ้ำไม่ได้"

    fresh = _fb_new_job(chat_id, caption=caption)
    new_id = fresh["id"]

    old_shots = [p for p in (source.get("images") or [source.get("image", "")]) if p]
    images = []
    for order, path in enumerate(old_shots[:facebook_group_post.MAX_PHOTOS], 1):
        copied = _fb_copy_asset(path, FB_POST_DIR / f"{new_id}-{order}.jpg")
        if copied:
            images.append(copied)
    if not images:
        fb_jobs.update(new_id, status=fb_auto_post.STATUS_CANCELLED)
        return None, f"ไฟล์รูปของงาน {job_id} หายไปแล้ว ทำซ้ำไม่ได้"

    comments = _fb_comments(source)
    shots = []
    for order, path in enumerate(_fb_comment_images(source), 1):
        shots.append(
            _fb_copy_asset(path, FB_POST_DIR / f"{new_id}-c{order}.jpg") if path else ""
        )

    # ใช้ชุดกลุ่มเดิมถ้ากลุ่มยังอยู่ครบ ไม่งั้นถอยไปใช้ค่าเริ่มต้นปัจจุบัน
    wanted = [g for g in (source.get("groups") or []) if fb_groups.get(g)]
    changes = {
        "image": images[0], "images": images,
        "comments": comments, "comment": comments[0] if comments else "",
        "comment_images": shots,
        "status": fb_auto_post.STATUS_READY,
    }
    if wanted:
        changes["groups"] = wanted[:fb_auto_post.MAX_GROUPS_PER_POST]
        changes["set"] = source.get("set", "")
    fresh = fb_jobs.update(new_id, **changes) or fresh
    append_log(
        "publish",
        f"ทำซ้ำงาน {job_id} เป็น {new_id} "
        f"(รูป {len(images)} ใบ · คอมเมนต์ {len(comments)} ข้อความ)",
    )
    return fresh, ""


def _fb_repost_card() -> tuple[str, dict | None]:
    """การ์ดให้กดเลือกว่าจะทำโพสต์ไหนซ้ำ"""
    items = _fb_repostable()
    if not items:
        return (
            "ยังไม่มีงานเก่าให้ทำซ้ำ — ต้องเป็นงานที่โพสต์ไปแล้ว "
            "และไฟล์รูปยังอยู่ในเครื่อง"
        ), None
    lines = ["🔁 <b>ทำโพสต์ซ้ำ</b> — เลือกงานที่จะเริ่มใหม่", ""]
    rows = []
    for order, job in enumerate(items, 1):
        head = (job.get("caption") or "").strip().splitlines()[0][:45]
        shots = len([p for p in (job.get("images") or []) if p]) or 1
        talk = len(_fb_comments(job))
        clips = sum(1 for p in _fb_comment_images(job) if p)
        when = (job.get("finished_at") or job.get("created_at") or "")[5:16].replace("T", " ")
        lines.append(
            f"<b>{order}.</b> {telegram_bot._escape(head)}\n"
            f"    {when} · 🖼{shots} · 💬{talk}{'📎' * bool(clips)} · "
            f"{FB_STATUS_LABEL.get(job['status'], job['status']).split(' —')[0]}"
        )
        # สองปุ่มต่อแถว — ดูรูปก่อนตัดสินใจ แล้วค่อยกดทำซ้ำ
        #
        # แคปชันอย่างเดียวแยกไม่ออกว่าใบไหนเป็นใบไหน โพสต์ขายของหลายใบใช้ข้อความ
        # คล้ายกันมาก ("แกรร 1 แถม 1 …") ตัวที่ต่างกันจริงคือรูป
        rows.append([
            {
                "text": f"{order}. {head[:20]} · 💬{talk}",
                "callback_data": f"fb:rp:{job['id']}",
            },
            {
                "text": f"📷{shots}" + (f"+{clips}" if clips else ""),
                "callback_data": f"fb:ri:{job['id']}",
            },
            {"text": "✏️", "callback_data": f"fb:ed:{job['id']}"},
        ])
    lines += ["", "กด <b>ชื่อโพสต์</b> = ได้<b>งานใหม่</b> ที่ลอกแคปชัน รูป "
              "และคอมเมนต์มาให้ครบ",
              "กด <b>📷</b> = ดูรูปของใบนั้นก่อน (ทั้งรูปในโพสต์และรูปในคอมเมนต์)",
              "กด <b>✏️</b> = เอามาแก้ก่อนโพสต์ (แคปชัน · รูป · คอมเมนต์ · กลุ่ม)",
              "เลือกกลุ่มใหม่ได้ก่อนกด 🚀 · ของเดิมไม่ถูกแตะต้อง"]
    return "\n".join(lines), {"inline_keyboard": rows}


# ------------------------------------------------------- จุดต่อจากบอท Telegram


def _fb_comment_photo(chat_id: str, file_id: str, caption: str, token: str) -> None:
    """รูปที่ส่งมาพร้อมคำสั่ง /comment = รูปแนบของคอมเมนต์ ไม่ใช่รูปโพสต์

    แยกสองอย่างนี้ด้วยแคปชันของรูปที่ส่งมา จึงไม่ต้องมีคำสั่งใหม่ให้จำเพิ่ม:
      ส่งรูปเปล่า / รูปพร้อมแคปชัน  → รูปของโพสต์
      ส่งรูปพร้อม "/comment …"      → รูปของคอมเมนต์
    """
    job = fb_jobs.latest_active(chat_id)
    if job is None:
        _fb_say(chat_id, "ยังไม่มีงานในคิว — ส่งรูปกับแคปชันเปิดงานก่อน")
        return
    maximum = facebook_group_post.MAX_COMMENTS
    argument = caption[len("/comment"):].strip()
    slot_text, _, rest = argument.partition(" ")
    if slot_text.isdigit():
        slot, text_value = int(slot_text), rest.strip()
    else:
        slot, text_value = 0, argument
    if slot and not 1 <= slot <= maximum:
        _fb_say(chat_id, f"มีได้แค่ช่อง 1 ถึง {maximum}")
        return
    current = _fb_comments(job)
    if not slot:
        slot = min(len(current) + 1, maximum) if text_value else 1

    destination = FB_POST_DIR / f"{job['id']}-c{slot}.jpg"
    try:
        telegram_bot.download_file(token, file_id, destination)
    except telegram_bot.TelegramError as error:
        append_log("publish", f"รับรูปคอมเมนต์จาก Telegram ไม่สำเร็จ: {error}")
        _fb_say(chat_id, f"รับรูปไม่สำเร็จ: {error}")
        return

    if text_value:
        while len(current) < slot:
            current.append("")
        current[slot - 1] = text_value
        _fb_set_comments(job["id"], current)
    job = _fb_set_comment_image(job["id"], slot, str(destination)) or job
    append_log("publish", f"แนบรูปเข้าคอมเมนต์ช่อง {slot} ของงาน {job['id']}")

    texts = _fb_comments(job)
    if slot > len(texts) or not texts[slot - 1].strip():
        _fb_say(chat_id, (
            f"📎 เก็บรูปไว้ให้คอมเมนต์ช่อง {slot} ของงาน <b>{job['id']}</b> แล้ว\n"
            f"ยังไม่มีข้อความในช่องนี้ — พิมพ์ "
            f"<code>/comment {slot} ข้อความ</code> ต่อได้เลย"
        ))
        return
    _fb_show_card(job)
    _fb_say(chat_id, (
        f"📎 แนบรูปเข้าคอมเมนต์ช่อง {slot} ของงาน <b>{job['id']}</b> แล้ว\n"
        f"💬{slot} {telegram_bot._escape(texts[slot - 1][:80])}"
    ))


def _telegram_photo(chat_id: str, file_id: str, caption: str, media_group: str) -> None:
    token, _ = _fb_telegram()
    if not token:
        return
    # แยกทางตั้งแต่ต้น: รูปที่มาพร้อม /comment เป็นของคอมเมนต์ ไม่ใช่ของโพสต์
    if (caption or "").strip().startswith("/comment"):
        _fb_comment_photo(chat_id, file_id, (caption or "").strip(), token)
        return
    # อัลบั้มหลายรูปมาเป็นข้อความแยกกันแต่ media_group_id เดียวกัน — เก็บเข้างานเดิม
    album_job = None
    if media_group:
        album_job = next(
            (j for j in fb_jobs.listing()[:5] if j.get("media_group") == media_group),
            None,
        )
        if album_job is not None:
            existing = album_job.get("images") or []
            if len(existing) >= facebook_group_post.MAX_PHOTOS:
                append_log(
                    "publish",
                    f"อัลบั้มเกิน {facebook_group_post.MAX_PHOTOS} ใบ — ใช้ "
                    f"{facebook_group_post.MAX_PHOTOS} ใบแรก",
                )
                return

    if album_job is not None:
        job = album_job
    else:
        open_job = fb_jobs.latest_open(chat_id)
        if open_job and open_job["status"] == fb_auto_post.STATUS_WAIT_IMAGE:
            job = open_job                   # ส่งแคปชันมาก่อน แล้วเพิ่งตามรูปมา
        else:
            job = _fb_new_job(chat_id, caption=caption, media_group=media_group)

    order = len(job.get("images") or []) + 1
    destination = FB_POST_DIR / f"{job['id']}-{order}.jpg"
    try:
        telegram_bot.download_file(token, file_id, destination)
    except telegram_bot.TelegramError as error:
        append_log("publish", f"รับรูปจาก Telegram ไม่สำเร็จ: {error}")
        _fb_say(chat_id, f"รับรูปไม่สำเร็จ: {error}")
        return

    text = caption or job.get("caption", "")
    images = (job.get("images") or []) + [str(destination)]
    job = fb_jobs.update(
        job["id"], image=images[0], images=images, caption=text,
        media_group=media_group,
        status=(
            fb_auto_post.STATUS_READY if text.strip()
            else fb_auto_post.STATUS_WAIT_CAPTION
        ),
    ) or job
    append_log(
        "publish",
        f"รับงานโพสต์ {job['id']} จาก Telegram แล้ว (รูป {len(images)} ใบ)",
    )
    job = _fb_show_card(job)
    _fb_maybe_auto_start(job)


def _telegram_text(chat_id: str, text: str) -> None:
    # วางลิงก์กลุ่มมาในแชท = อยากเพิ่มกลุ่ม ไม่ใช่แคปชัน
    if fb_auto_post.looks_like_group_link(text):
        try:
            entry = fb_groups.add(text)
        except fb_auto_post.AutoPostError as error:
            append_log("publish", f"เพิ่มกลุ่มจากลิงก์ไม่สำเร็จ: {error}")
            _fb_say(chat_id, f"เพิ่มกลุ่มไม่ได้: {error}")
            return
        word = "มีอยู่แล้ว — อัปเดตให้" if entry.get("duplicated") else "เพิ่มแล้ว"
        _fb_say(
            chat_id,
            f"➕ กลุ่ม <code>{entry['group_id']}</code> {word}\n"
            f"ตั้งชื่อ: <code>/name {entry['group_id']} ชื่อที่อยากให้เรียก</code>",
        )
        append_log("publish", f"เพิ่มกลุ่ม {entry['group_id']} จาก Telegram")
        return

    job = fb_jobs.latest_open(chat_id)
    # พิมพ์ข้อความตอนงานพร้อมโพสต์อยู่แล้ว = **แก้แคปชัน** ของงานนั้น
    # (ยังไม่ได้กดโพสต์ ยังแก้ทัน) ไม่ใช่เปิดงานใหม่ — ถ้าอยากเริ่มใหม่ให้ส่งรูปใหม่
    if job and job["status"] in (
        fb_auto_post.STATUS_WAIT_CAPTION, fb_auto_post.STATUS_READY
    ):
        job = fb_jobs.update(
            job["id"], caption=text,
            status=(
                fb_auto_post.STATUS_READY if job.get("image")
                else fb_auto_post.STATUS_WAIT_IMAGE
            ),
        ) or job
    else:
        job = _fb_new_job(
            chat_id, caption=text, status=fb_auto_post.STATUS_WAIT_IMAGE
        )
    # ต้องมี log ทุกทางที่รับข้อความ ไม่งั้นข้อความที่ตกไปผิดทาง (เช่นลิงก์รูปแบบใหม่
    # ที่ยังไม่รู้จัก กลายเป็นแคปชัน) จะเงียบหาย ไม่มีร่องรอยให้ตามเลย
    append_log(
        "publish",
        f"รับข้อความเข้างาน {job['id']} ({job['status']}): {text[:60]}",
    )
    job = _fb_show_card(job)
    _fb_maybe_auto_start(job)


def _fb_maybe_auto_start(job: dict) -> None:
    if job["status"] != fb_auto_post.STATUS_READY:
        return
    if not _fb_settings().get("auto_start"):
        return
    note = _fb_run_job(job["id"])
    if note:
        _fb_say(job.get("chat_id", ""), note)


FB_HELP = (
    "🤖 <b>โพสต์ลงกลุ่ม Facebook อัตโนมัติ</b>\n\n"
    "1) ส่ง <b>รูปพร้อมแคปชัน</b> มาในแชทนี้ (หรือส่งแยกกันก็ได้)\n"
    "2) บอทตอบการ์ดมาให้ <b>ติ๊กเลือกกลุ่ม</b>\n"
    "3) กด 🚀 แล้วเครื่องจะไล่โพสต์ทีละกลุ่ม เว้นระยะแบบสุ่ม\n\n"
    "โพสต์เสร็จแต่ละกลุ่มจะรายงานผลที่นี่ทันที พร้อม<b>ลิงก์โพสต์</b> "
    "และกด<b>ถูกใจ</b>ให้อัตโนมัติทุกโพสต์\n\n"
    "<b>แก้งานในคิว</b>\n"
    "• /caption &lt;ข้อความ&gt; — แก้ข้อความโพสต์\n"
    "• /comment &lt;ข้อความ&gt; — เพิ่มคอมเมนต์ (สูงสุด 2 ข้อความ)\n"
    "• /comment 2 &lt;ข้อความ&gt; — แก้คอมเมนต์ช่องที่ 2\n"
    "• /comment - — ล้างคอมเมนต์ทิ้ง\n"
    "• <b>ส่งรูปพร้อมแคปชัน</b> <code>/comment ข้อความ</code> = แนบรูปเข้าคอมเมนต์\n"
    "  (ระบุช่องได้: <code>/comment 2 ข้อความ</code> · ส่งรูปเปล่าๆ = รูปของโพสต์)\n\n"
    "<b>จัดการกลุ่ม</b>\n"
    "• วางลิงก์กลุ่มมาเฉยๆ = เพิ่มกลุ่ม (ลิงก์ปุ่มแชร์ในแอปก็ได้)\n"
    "• /groups — ดูรายการ เปิด/ปิด/ลบ\n"
    "• /name &lt;รหัสกลุ่ม&gt; &lt;ชื่อ&gt; — ตั้งชื่อกลุ่ม\n\n"
    "<b>ดูผลงาน</b>\n"
    "• /queue — ดูคิวงานที่รอโพสต์\n"
    "• /repost — ทำโพสต์เก่าซ้ำ (เด้งรายการให้กดเลือก ลอกแคปชัน/รูป/คอมเมนต์มาครบ)\n"
    "• /status — เช็คสถานะ 4 อย่าง: โพสต์ · ถูกใจ · คอมเมนต์ · ถูกใจคอมเมนต์\n"
    "• /sets — ดูชุดกลุ่ม (มีเลขกำกับไว้อ้างอิง)\n"
    "• /newset &lt;ชื่อชุด&gt; 1,2,3,4,5,6 — จัดหลายกลุ่มเข้าชุดเดียวทีเดียว\n"
    "• /moveset &lt;เลข&gt; &lt;ชื่อชุด&gt; — ย้ายทีละกลุ่ม\n"
    "• /setname &lt;เลข📦&gt; &lt;ชื่อใหม่&gt; — เปลี่ยนชื่อกลุ่มใหญ่\n"
    "  (หรือกดปุ่ม 📦 หน้าชื่อกลุ่มใน /groups เพื่อย้ายกลุ่มย่อยเข้า-ออก)\n"
    "• /schedule &lt;เวลา&gt; — ตั้งเวลาโพสต์ครั้งเดียว (20:30 / 9/8 20:30 / +30)\n"
    "• /routine — โพสต์ประจำวัน: ตั้งเวลาไว้แล้วเอาโพสต์เก่ามาลงเองทุกวัน\n"
    "• /edit &lt;รหัสงาน&gt; — เอางานเก่ามาแก้ก่อนโพสต์ (/edit รูป = เปลี่ยนรูป)\n"
    "• /followup — ตามเก็บ: เปิดโพสต์จากแจ้งเตือนแล้วกดถูกใจ/คอมเมนต์ให้\n"
    "• /collect — เก็บยอดถูกใจ/คอมเมนต์/แชร์ ของโพสต์ทุกกลุ่ม\n"
    "• /fiximage — แก้รูปของโพสต์ที่ลงไปแล้วให้เป็นรูปที่ถูก\n"
    "• /links — ลิงก์โพสต์ที่เก็บไว้ (ใส่ตัวเลขต่อท้ายเพื่อดูย้อนหลังมากขึ้น)\n"
    "• /pending — โพสต์ที่ยังไม่ขึ้น (รอผู้ดูแลอนุมัติ) · /pending run เพื่อไล่เลย\n"
    "• /report — สรุปว่ากลุ่มไหน/เวลาไหนได้ผลจริง (/report 7 = ดู 7 วัน)\n"
    "• /health — ตรวจความพร้อมของเครื่องก่อนเริ่มงาน\n"
    "• /uncomment — ปลดพักคอมเมนต์ (ตอนโดนพักเพราะนึกว่าถูกบล็อก)\n"
    "• /preview — ดูตัวอย่างก่อนโพสต์ (รูปไหนเข้าคอมเมนต์ไหน)\n"
    "• /quotafb — โควตาโพสต์/คอมเมนต์ ต่อชั่วโมงและต่อวัน + ของที่ค้าง\n"
    "• /clean — ล้างเครื่องเดี๋ยวนี้ (ปกติล้างเองทุกวัน 00:01)\n"
    "• /backup — สำรองข้อมูลเดี๋ยวนี้ (ปกติสำรองเองวันละครั้ง)\n"
    "• /cancel — ยกเลิกงานที่ค้าง\n"
    "• /stop — สั่งหยุดงานที่กำลังโพสต์"
)


def _fb_set_names() -> list[str]:
    """ชื่อกลุ่มใหญ่ทั้งหมด เรียงคงที่ — ใช้เลขลำดับแทนชื่อใน callback_data

    ชื่อชุดเป็นภาษาไทยยาวได้ถึง 30 ตัว = 90 ไบต์ใน UTF-8 ซึ่งเกินเพดาน 64 ไบต์
    ของ callback_data ใน Telegram จึงส่งเป็น "เลขที่เท่าไรในรายการ" แทน
    """
    return list(fb_groups.sets().keys())


def _fb_groups_card() -> tuple[str, dict | None]:
    items = fb_groups.listing()
    if not items:
        return "ยังไม่มีกลุ่มในรายการ — วางลิงก์กลุ่มมาในแชทนี้เพื่อเพิ่ม", None
    lines = ["📋 <b>กลุ่มทั้งหมด</b>", ""]
    rows = []
    for index, group in enumerate(items, 1):
        mark = "✅" if group.get("enabled", True) else "⬜"
        bucket = group.get("set") or fb_auto_post.DEFAULT_SET
        lines.append(
            f"{index}. {mark} {telegram_bot._escape(group['name'])}"
            f"  <i>({telegram_bot._escape(bucket)})</i>"
        )
        rows.append([
            # ช่องหน้าสุด = กลุ่มใหญ่ที่กลุ่มนี้สังกัด กดเพื่อย้าย
            {
                "text": f"📦 {bucket[:12]}",
                "callback_data": f"fb:gs:{group['group_id']}",
            },
            {
                "text": f"{mark} {group['name'][:20]}",
                "callback_data": f"fb:ge:{group['group_id']}",
            },
            {"text": "🗑", "callback_data": f"fb:gd:{group['group_id']}"},
        ])
    lines += [
        "",
        "📦 = กลุ่มใหญ่ที่สังกัด · แตะเพื่อย้าย",
        "แตะชื่อ = เปิด/ปิดใช้กลุ่มนั้นเป็นค่าเริ่มต้นของงานใหม่",
        f"เปลี่ยนชื่อกลุ่มใหญ่: <code>/setname &lt;เลข&gt; &lt;ชื่อใหม่&gt;</code> "
        f"(ดูเลขจาก /sets)",
    ]
    return "\n".join(lines), {"inline_keyboard": rows}


def _fb_set_picker_card(group_id: str) -> tuple[str, dict | None]:
    """การ์ดเลือกว่าจะย้ายกลุ่มย่อยนี้ไปกลุ่มใหญ่ไหน"""
    group = fb_groups.get(group_id)
    if group is None:
        return "ไม่พบกลุ่มนี้", None
    buckets = fb_groups.sets()
    now = group.get("set") or fb_auto_post.DEFAULT_SET
    limit = fb_auto_post.MAX_GROUPS_PER_POST
    lines = [
        f"📦 <b>ย้ายกลุ่มย่อย</b>",
        f"“{telegram_bot._escape(group['name'])}”",
        f"ตอนนี้อยู่: <b>{telegram_bot._escape(now)}</b>",
        "",
        f"กลุ่มใหญ่หนึ่งรับได้ไม่เกิน {limit} กลุ่มย่อย",
    ]
    rows = []
    row: list[dict] = []
    for index, (name, members) in enumerate(buckets.items(), 1):
        count = len(members)
        here = any(m["group_id"] == group_id for m in members)
        full = count >= limit and not here
        tag = "✅" if here else ("🚫" if full else "📦")
        row.append({
            "text": f"{tag} {name[:12]} {count}/{limit}",
            "callback_data": f"fb:gsm:{group_id}:{index}",
        })
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        {"text": "➕ กลุ่มใหญ่ใหม่", "callback_data": f"fb:gsn:{group_id}"},
        {"text": "↩︎ กลับ", "callback_data": "fb:gsb"},
    ])
    return "\n".join(lines), {"inline_keyboard": rows}


def _fb_links_text(limit_text: str = "") -> str:
    """รายการลิงก์โพสต์ที่เก็บไว้ — เรียกดูจากในแชทได้ตลอด

    ไล่จากงานล่าสุดลงไป งานหนึ่งงานคือการโพสต์หนึ่งรอบ (หลายกลุ่ม)
    """
    try:
        limit = max(1, min(10, int(limit_text)))
    except ValueError:
        limit = 3
    blocks: list[str] = []
    for job in fb_jobs.listing():
        entries = [e for e in (job.get("results") or []) if e.get("link")]
        if not entries:
            continue
        when = (job.get("finished_at") or job.get("created_at") or "").replace("T", " ")
        head = f"📮 <b>{job['id']}</b> · {when}\n   “{telegram_bot._escape(job.get('caption', '')[:50])}”"
        lines = [head]
        for entry in entries:
            liked = entry.get("liked") or (entry.get("verified") or {}).get("liked")
            marks = ("❤️" if liked else "🤍")
            marks += "💬" if entry.get("commented") else ""
            post_id = entry.get("post_id") or ""
            lines.append(
                f"{marks} {fb_groups.label(entry['group_id'])}\n"
                f"{entry['link']}"
                + (f"\n   <code>โพสต์ {post_id}</code>" if post_id else "")
            )
        blocks.append("\n".join(lines))
        if len(blocks) >= limit:
            break
    if not blocks:
        return (
            "ยังไม่มีลิงก์โพสต์ที่เก็บไว้\n"
            "ลิงก์จะถูกเก็บอัตโนมัติทุกครั้งที่โพสต์สำเร็จ"
        )
    return "🔗 <b>ลิงก์โพสต์ที่เก็บไว้</b>\n\n" + "\n\n".join(blocks)


# ตามเก็บได้ศูนย์ติดกันกี่รอบถึงจะบอกว่า "ติดขัด" แล้วเลิกแจ้งรอบปกติ
#
# 3 เพราะรอบเดียวหรือสองรอบยังเป็นเรื่องปกติ (โพสต์อาจยังรออนุมัติ) แต่สามรอบ
# ติดกันที่ได้ศูนย์ทุกช่อง แปลว่าไม่ใช่เรื่องจังหวะเวลาแล้ว
ZERO_STREAK_ALERT = 3

# นับรอบที่ได้ศูนย์ติดกันของแต่ละงาน — อยู่ในหน่วยความจำพอ
# รีสตาร์ตแล้วเริ่มนับใหม่ไม่เป็นไร เพราะ fb_pending มีเพดานจำนวนครั้งคุมอีกชั้น
_fb_zero_rounds: dict[str, int] = {}


def _fb_zero_streak(job_id: str, nothing: bool) -> int:
    """คืนจำนวนรอบที่ได้ศูนย์ติดกันของงานนี้ (ได้ผลจริงเมื่อไร นับใหม่)"""
    if not nothing:
        _fb_zero_rounds.pop(job_id, None)
        return 0
    _fb_zero_rounds[job_id] = _fb_zero_rounds.get(job_id, 0) + 1
    return _fb_zero_rounds[job_id]


def _fb_followup(comment_override: str = "", job_id: str = "",
                 queued: bool = False) -> str:
    """ตามเก็บงานล่าสุด: เปิดโพสต์จากแจ้งเตือน แล้วกดถูกใจ + คอมเมนต์

    ทำไมต้องมีรอบสอง: กลุ่มส่วนใหญ่ตั้งให้ผู้ดูแลตรวจก่อนโพสต์ขึ้น ตอนกดโพสต์เสร็จ
    โพสต์จึงยัง "รออนุมัติ" ไม่ปรากฏในฟีด ยังกดถูกใจหรือคอมเมนต์ไม่ได้เลย
    พอผู้ดูแลอนุมัติแล้วจะมีแจ้งเตือน "ผู้ดูแลอนุมัติรูปภาพของคุณใน …" ซึ่งกดแล้ว
    เข้าหน้าโพสต์ของเราตรงๆ — แม่นกว่าเลื่อนหาในฟีดมาก
    """
    # ระบุรหัสงานได้ — จำเป็นตอนเข้าคิวรอจอ เพราะระหว่างรออาจมีงานใหม่เกิดขึ้น
    # ถ้ายังเลือก "งานล่าสุดที่มีผลลัพธ์" เหมือนเดิม จะไปตามเก็บผิดงาน
    job = fb_jobs.get(job_id) if job_id else \
        next((j for j in fb_jobs.listing() if j.get("results")), None)
    if job is None:
        return f"ไม่พบงาน {job_id}" if job_id else "ยังไม่มีงานที่โพสต์ไปแล้ว"
    serial, note = _fb_gate("followup", job, queued, str(job.get("serial") or ""))
    if note:
        return note
    # ข้ามกลุ่มที่ "ครบแล้ว" — ไม่ใช่ไล่ทุกกลุ่มที่โพสต์สำเร็จ
    #
    # รอบโพสต์ทำถูกใจ/คอมเมนต์/เก็บลิงก์ให้เสร็จได้เลยถ้ากลุ่มนั้นไม่ต้องรออนุมัติ
    # ถ้ายังไล่ตามเก็บอีกจะหาโพสต์ไม่เจอ — แจ้งเตือน "ผู้ดูแลอนุมัติแล้ว" ไม่มีอยู่จริง
    # เพราะไม่เคยต้องอนุมัติ ส่วนฟีดก็จมไปแล้ว — จบด้วยรายงาน "ถูกใจ 0/5"
    # ซึ่งอ่านแล้วเหมือนล้มเหลว ทั้งที่ความจริงคือไม่มีอะไรต้องทำ
    # (เจอจริง 12 ส.ค. งาน p525306924: ครบทั้ง 5 กลุ่มตั้งแต่รอบโพสต์)
    want_comment = bool(_fb_comments(job))
    # โดนพักคอมเมนต์อยู่ = ตัดงานคอมเมนต์ออกจากรอบนี้ไปเลย ไม่ใช่ไปตันทีละกลุ่ม
    #
    # ถ้าไม่ตัดตรงนี้ รอบตามเก็บจะยังเปิดโพสต์ทีละกลุ่ม (กลุ่มละ ~13 วินาที)
    # แล้วค่อยไปโดนด่านปฏิเสธข้างใน — เสียเวลาจอฟรีทั้งที่รู้ผลตั้งแต่ยังไม่ออกตัว
    comment_hold = fb_comment_guard.hold_reason() if want_comment else ""
    if comment_hold:
        want_comment = False

    def _needs_work(entry: dict) -> bool:
        if not entry.get("posted"):
            return False
        if not entry.get("liked"):
            return True
        if want_comment and not (entry.get("commented") and entry.get("comment_liked")):
            return True
        return not entry.get("link")

    # ส่งลิงก์ที่เคยเก็บได้ไปด้วย — รอบตามเก็บจะเปิดโพสต์จากลิงก์นั้นเป็นทางแรก
    # ซึ่งพาเข้า "หน้าโพสต์เดี่ยว" ตรงๆ ไม่ต้องพึ่งทั้งแจ้งเตือนและการเรียงฟีด
    targets = [
        {"group_id": r["group_id"], "name": fb_groups.label(r["group_id"]),
         "link": r.get("link", ""), "post_id": r.get("post_id", "")}
        for r in job["results"] if _needs_work(r)
    ]
    if not targets:
        done = sum(1 for r in job["results"] if r.get("posted"))
        if comment_hold:
            return (f"⏸ งาน {job['id']} เหลือแค่งานคอมเมนต์ แต่ตอนนี้{comment_hold}\n"
                    "ไม่ออกตัวไปเสียเวลาจอเปล่าๆ — ค่อยสั่ง /followup ใหม่ตอนพ้นเวลาพัก")
        if done:
            return (f"✅ งาน {job['id']} ครบแล้วทั้ง {done} กลุ่ม — ถูกใจ คอมเมนต์ "
                    "และลิงก์เก็บครบตั้งแต่รอบโพสต์ ไม่ต้องตามเก็บ")
        return "งานล่าสุดไม่มีกลุ่มที่โพสต์สำเร็จ"

    job_id = job["id"]
    chat_id = job.get("chat_id", "")
    # ใช้คอมเมนต์ทั้งรายการ ไม่ใช่แค่ข้อความแรก — ไม่งั้นงานที่ตั้งไว้ 2 ข้อความ
    # จะได้แค่ข้อความเดียว และรูปแนบที่เรียงตรงช่องกันจะเลื่อนไปผิดช่องด้วย
    override = comment_override.strip()
    comment = override or _fb_comments(job)
    comment_shots = [] if override else _fb_comment_images(job)
    # ยังมีกลุ่มที่ต้องกดถูกใจ/เก็บลิงก์อยู่ จึงยังออกตัว — แต่ตัดคอมเมนต์ทิ้ง
    # ไม่ให้ไปเปิดแผงคอมเมนต์แล้วพิมพ์ทิ้งเปล่าๆ ระหว่างโดนพัก
    if comment_hold and not override:
        comment = ""
        comment_shots = []

    def on_log(line: str) -> None:
        append_log("publish", f"[{job_id}·ตามเก็บ] {line}")
        fb_jobs.append_log(job_id, line)

    def on_result(entry: dict) -> None:
        _fb_stamp_post_id(entry)
        fb_jobs.upsert_result(job_id, entry)
        step = f"[{entry['index']}/{entry['total']}] " if entry.get("index") else ""
        _fb_say(chat_id, step + fb_auto_post.result_line(entry, fb_groups.label))

    def on_done(results: list[dict], error: str) -> None:
        liked = sum(1 for r in results if r.get("liked"))
        commented = sum(1 for r in results if r.get("commented"))
        links = sum(1 for r in results if r.get("link"))
        nothing = not liked and not commented and not links
        streak = _fb_zero_streak(job_id, nothing)

        # **รอบที่ได้ศูนย์ซ้ำๆ ต้องไม่ส่งข้อความหน้าตาปกติอีก**
        #
        # ของเดิมส่ง "🏁 จบแล้ว ถูกใจ 0/1" ทุกรอบเท่ากันหมด ผลที่เกิดจริง
        # 14-15 ส.ค. 2026: งาน p617465263 วน 196 รอบ ได้ศูนย์ 100% และส่ง
        # ข้อความหน้าตาเดียวกันเข้าแชทครบทุกรอบ — ไม่ได้เงียบ แต่ดังจนกลายเป็น
        # เสียงรบกวน แล้วสัญญาณจริงจมหายไปกับข้อความปกติ
        #
        # ครบเกณฑ์แล้วส่ง "ครั้งเดียว" ว่าติดขัด จากนั้นเงียบจนกว่าจะได้ผลจริง
        if nothing and streak >= ZERO_STREAK_ALERT:
            if streak == ZERO_STREAK_ALERT:
                _fb_say(chat_id, (
                    f"🛑 <b>งาน {job_id} ตามเก็บไม่ได้ผล {streak} รอบติด</b>\n"
                    f"ทุกรอบได้ ถูกใจ 0 · คอมเมนต์ 0 · ลิงก์ 0\n\n"
                    "แปลว่าโพสต์น่าจะไม่ขึ้นจริง (รอผู้ดูแลอนุมัติ หรือไม่อนุมัติ)\n"
                    "จะไม่แจ้งรอบที่ได้ศูนย์อีกจนกว่าจะเก็บอะไรได้จริง\n\n"
                    "ดูสถานะ: /pending · สั่งเองอีกครั้ง: /followup"
                ))
            append_log(
                "publish",
                f"[{job_id}·ตามเก็บ] จบ — ได้ศูนย์ติดกัน {streak} รอบ (ไม่แจ้งซ้ำ)",
            )
            return

        _fb_say(chat_id, (
            f"🏁 <b>ตามเก็บงาน {job_id} จบแล้ว</b>\n"
            f"ถูกใจ {liked}/{len(results)}"
            + (f" · คอมเมนต์ {commented}/{len(results)}" if comment else "")
            + f" · เก็บลิงก์ {links}/{len(results)}"
            + ("\n\nดูลิงก์ทั้งหมด: /links" if links else "")
            + (f"\n\n⚠️ {telegram_bot._escape(error)}" if error else "")
        ))
        append_log(
            "publish",
            f"[{job_id}·ตามเก็บ] จบ — ถูกใจ {liked}/{len(results)} · ลิงก์ {links}",
        )

    try:
        fb_runner.for_device(serial).start_followup(
            job_id=job_id, adb=ADB, serial=serial, caption=job["caption"],
            targets=targets, comment=comment, on_log=on_log,
            on_result=on_result, on_done=on_done, comment_images=comment_shots,
            clipboard=_fb_clipboard(serial),
        )
    except fb_auto_post.AutoPostError as error:
        return str(error)
    append_log("publish", f"[{job_id}] เริ่มตามเก็บ {len(targets)} กลุ่ม")
    return (
        f"🔁 เริ่มตามเก็บ {len(targets)} กลุ่ม — เปิดโพสต์จากแจ้งเตือนแล้วกดถูกใจ"
        + ("/คอมเมนต์ให้" if comment else "")
    )


EDIT_IMAGE_WORDS = ("รูป", "รูปภาพ", "image", "images", "photo")


def _fb_edit_start(chat_id: str, job_id: str = "", want_image: bool = False) -> str:
    """เปิดงานขึ้นมาแก้ — คืนข้อความบอกผล (การ์ดถูกส่งแยกอีกใบ)

    **งานที่โพสต์ไปแล้วจะถูกทำสำเนาก่อนเสมอ ไม่แก้ทับของเดิม**

    เพราะ `/followup` `/collect` `/fiximage` ทั้งสามตัว **หาโพสต์บนจอด้วยการ
    เทียบแคปชัน** (ส่ง `caption=job["caption"]` เข้าไปตรงๆ) ถ้าแก้แคปชันของงานที่
    ลงไปแล้ว ระบบจะหาโพสต์ใบนั้นไม่เจออีกเลย — ตามเก็บไม่ได้ เก็บยอดไม่ได้
    แก้รูปไม่ได้ และประวัติว่า "ตอนนั้นโพสต์อะไรลงไป" ก็เพี้ยนตามไปด้วย

    ส่วนงานที่ยังไม่ได้โพสต์ (ร่าง) แก้ทับได้เลย ไม่มีอะไรอ้างอิงอยู่
    """
    if job_id:
        source = fb_jobs.get(job_id)
        if source is None:
            return f"ไม่พบงาน {job_id}"
        posted = bool(source.get("results")) or \
            source["status"] not in fb_auto_post.OPEN_STATUSES
        if posted:
            job, problem = _fb_clone_job(job_id, chat_id)
            if job is None:
                return problem
            note = (f"📄 ทำสำเนา {job_id} → <b>{job['id']}</b> ขึ้นมาแก้\n"
                    f"<i>ของเดิมไม่ถูกแตะ — ถ้าแก้ทับ จะตามเก็บ/เก็บยอด/แก้รูป "
                    f"ของโพสต์ที่ลงไปแล้วไม่ได้อีก</i>")
        else:
            job, note = source, f"✏️ เปิดแก้งาน <b>{job_id}</b>"
    else:
        job = fb_jobs.latest_open(chat_id)
        if job is None:
            return ("ยังไม่มีงานที่กำลังทำอยู่ — ส่งรูปพร้อมแคปชันเข้ามาเพื่อเริ่มงานใหม่\n"
                    "หรือ <code>/edit &lt;รหัสงาน&gt;</code> เพื่อเอางานเก่ามาแก้ "
                    "(ดูรหัสได้จาก /repost)")
        note = f"✏️ แก้งาน <b>{job['id']}</b> ที่ทำค้างอยู่"

    if want_image:
        # เคลียร์รูปแล้วตั้งสถานะเป็น "รอรูป" — รูปใบถัดไปที่ส่งเข้ามาจะเข้างานนี้เอง
        # ผ่านทางเดินเดิมของการส่งรูป ไม่ต้องมีทางพิเศษให้ดูแลเพิ่ม
        job = fb_jobs.update(job["id"], images=[], image="",
                             status=fb_auto_post.STATUS_WAIT_IMAGE) or job
        note += "\n\n📷 <b>ล้างรูปเดิมแล้ว — ส่งรูปใหม่เข้ามาได้เลย</b>"

    used_by = [r for r in fb_routine.listing()
               if job_id and job_id in (r.get("sources") or [])]
    if used_by:
        times = " · ".join(r["time"] for r in used_by)
        note += (f"\n\n⚠️ งาน {job_id} ถูกใช้ในโพสต์ประจำวัน {times} "
                 f"ซึ่งยังชี้ที่ใบเก่าอยู่\n"
                 f"อยากให้ตารางใช้ใบใหม่ ต้องตั้งใหม่: "
                 f"<code>/routine del &lt;เลข&gt;</code> แล้ว "
                 f"<code>/routine add {used_by[0]['time']} {job['id']}</code>")

    _fb_show_card(job)
    return note + "\n\n" + _fb_edit_help()


def _fb_edit_help() -> str:
    return (
        "<b>แก้อะไรได้บ้าง</b>\n"
        "📝 <code>/caption ข้อความใหม่</code>\n"
        "💬 <code>/comment ข้อความ</code> · <code>/comment 2 ข้อความ</code> · "
        "<code>/comment -</code> ล้าง\n"
        "📷 <code>/edit รูป</code> แล้วส่งรูปใหม่เข้ามา (ส่งอัลบั้มได้)\n"
        "📎 ส่งรูปพร้อมข้อความ <code>/comment</code> = รูปแนบคอมเมนต์\n"
        "📦 เลือกกลุ่มจากปุ่มบนการ์ด · ⏰ <code>/schedule 20:30</code>\n"
        "🚀 พร้อมแล้วกดปุ่มโพสต์บนการ์ด"
    )


def _fb_edit_command(chat_id: str, argument: str) -> str:
    """ตัวแปลคำสั่ง /edit"""
    parts = argument.split()
    job_id, want_image = "", False
    for word in parts:
        if word.lower() in EDIT_IMAGE_WORDS:
            want_image = True
        elif not job_id:
            job_id = word.strip()
    return _fb_edit_start(chat_id, job_id, want_image)


def _routine_label(job_id: str) -> str:
    """ชื่อเรียกงานเก่าแบบสั้น — รหัส + ต้นแคปชัน ให้รู้ว่าโพสต์ไหน"""
    job = fb_jobs.get(job_id)
    if job is None:
        return f"{job_id} ⚠️ ไม่มีงานนี้แล้ว"
    head = (job.get("caption") or "").strip().splitlines()[0][:28]
    return f"{job_id} · {telegram_bot._escape(head)}"


def _routine_check_source(job_id: str) -> str:
    """งานนี้เอามาลงซ้ำได้จริงไหม — คืนข้อความปัญหา ("" = ใช้ได้)

    ตรวจตั้งแต่ตอนตั้งตาราง ไม่ใช่ตอนถึงเวลา — ถ้ารอไปเจอตอน 09:00 ผู้ใช้จะรู้ว่า
    ตารางเสียก็ต่อเมื่อวันนั้นไม่มีโพสต์ขึ้น ซึ่งสายเกินไปแล้ว
    """
    job = fb_jobs.get(job_id)
    if job is None:
        return f"ไม่พบงาน {job_id}"
    if not (job.get("caption") or "").strip():
        return f"งาน {job_id} ไม่มีแคปชัน"
    images = [p for p in (job.get("images") or [job.get("image", "")]) if p]
    if not any(Path(p).is_file() for p in images):
        return f"ไฟล์รูปของงาน {job_id} หายไปแล้ว"
    return ""


def _routine_fire(record: dict, forced: bool = False) -> str:
    """ลงโพสต์ของตารางนี้หนึ่งรอบ — คืนข้อความบอกผล

    **สร้างงานแล้วตั้ง `run_at` เป็นเดี๋ยวนี้ ไม่ได้สั่งรันตรงๆ** เพื่อให้ไหลเข้า
    ตัวตั้งเวลาเดิมทั้งหมด — คิวรอจอ · ด่านตรวจความพร้อม · การเตือนโพสต์ซ้ำ
    ทำงานเหมือนงานที่ผู้ใช้ตั้งเวลาเองทุกประการ ไม่ต้องมีทางเดินพิเศษให้ดูแลสองที่
    """
    source = fb_routine.current_source(record)
    chat_id = record.get("chat_id", "")
    problem = _routine_check_source(source)
    if problem:
        append_log("publish", f"[ตาราง {record['time']}] ข้าม — {problem}")
        fb_routine.mark_skipped(record["id"])
        return f"⚠️ ตาราง {record['time']} ข้ามรอบนี้ — {problem}"
    job, note = _fb_clone_job(source, chat_id)
    if job is None:
        append_log("publish", f"[ตาราง {record['time']}] ทำซ้ำไม่สำเร็จ — {note}")
        fb_routine.mark_skipped(record["id"])
        return f"⚠️ ตาราง {record['time']} ทำซ้ำไม่สำเร็จ — {note}"
    fb_jobs.update(job["id"], run_at=datetime.now().isoformat(timespec="seconds"))
    fb_routine.mark_fired(record["id"], job["id"])
    append_log(
        "publish",
        f"[ตาราง {record['time']}] สร้างงาน {job['id']} จาก {source}"
        + (" (สั่งเอง)" if forced else ""),
    )
    return (f"🗓 <b>โพสต์ประจำวัน {record['time']}</b>\n"
            f"ทำซ้ำ {source} → งาน <b>{job['id']}</b> · เริ่มโพสต์เดี๋ยวนี้")


def _routine_pump() -> None:
    """ถึงเวลาไหนแล้วก็ลงให้ — เกาะไปกับตัวตั้งเวลาที่วนอยู่แล้ว"""
    for record in fb_routine.missed():
        # ตกรอบไปไกลเกิน CATCHUP_MINUTES — ข้ามแล้วบอกให้รู้ ไม่ใช่เงียบ
        fb_routine.mark_skipped(record["id"])
        append_log(
            "publish",
            f"[ตาราง {record['time']}] เลยเวลามาเกิน "
            f"{fb_routine.CATCHUP_MINUTES} นาที — ข้ามของวันนี้",
        )
        _fb_say(record.get("chat_id", ""),
                f"⏭ ข้ามโพสต์ประจำวัน {record['time']} ของวันนี้ "
                f"(เลยเวลามานานเกินไป)")
    for record in fb_routine.due():
        note = _routine_fire(record)
        _fb_say(record.get("chat_id", ""), note)


def _fb_routine_command(chat_id: str, argument: str) -> str:
    """ตัวแปลคำสั่ง /routine ทั้งหมด"""
    text = argument.strip()
    if not text:
        return fb_routine.summary_text(label=_routine_label)

    word, _, rest = text.partition(" ")
    word, rest = word.lower(), rest.strip()

    if word == "add":
        times, _, jobs = rest.partition(" ")
        wanted = [j.strip() for j in jobs.replace(",", " ").split() if j.strip()]
        if not wanted:
            return ("บอกด้วยว่าจะเอาโพสต์ไหนมาลง เช่น\n"
                    "<code>/routine add 9:00 p782116693</code>\n"
                    "หลายเวลา/หลายโพสต์: "
                    "<code>/routine add 9:00,10:00 p782116693,p617465263</code>\n"
                    "ดูรหัสงานเก่าได้จาก /repost")
        for job_id in wanted:
            problem = _routine_check_source(job_id)
            if problem:
                return f"⚠️ {problem} — ตั้งตารางไม่ได้"
        try:
            added = fb_routine.add(
                times.replace(",", " ").split(), wanted, chat_id=chat_id
            )
        except fb_routine.RoutineError as error:
            return f"⚠️ {error}"
        names = " · ".join(r["time"] for r in added)
        append_log("publish",
                   f"ตั้งโพสต์ประจำวัน {names} จาก {', '.join(wanted)}")
        return (f"🗓 ตั้งโพสต์ประจำวันแล้ว: <b>{names}</b>\n"
                + fb_routine.summary_text(label=_routine_label))

    if word in ("del", "delete", "rm", "off", "on", "run"):
        if not rest.isdigit():
            return f"ใส่เลขลำดับด้วย เช่น <code>/routine {word} 1</code>"
        record = fb_routine.by_index(int(rest))
        if record is None:
            return f"ไม่มีรายการที่ {rest}"
        if word in ("del", "delete", "rm"):
            fb_routine.remove(record["id"])
            append_log("publish", f"ลบโพสต์ประจำวัน {record['time']}")
            return f"🗑 ลบตาราง {record['time']} แล้ว\n" + \
                fb_routine.summary_text(label=_routine_label)
        if word in ("on", "off"):
            fb_routine.set_enabled(record["id"], word == "on")
            return (f"{'✅ เปิด' if word == 'on' else '⏸ พัก'}ตาราง "
                    f"{record['time']} แล้ว\n"
                    + fb_routine.summary_text(label=_routine_label))
        # run = สั่งลงเดี๋ยวนี้โดยไม่รอเวลา (ใช้ทดสอบว่าตารางตั้งถูกไหม)
        return _routine_fire(record, forced=True)

    return ("ใช้แบบนี้:\n"
            "<code>/routine</code> ดูตาราง\n"
            "<code>/routine add 9:00,10:00 &lt;รหัสงาน&gt;</code> เพิ่ม\n"
            "<code>/routine del 1</code> ลบ · <code>/routine off 1</code> พัก · "
            "<code>/routine on 1</code> เปิด\n"
            "<code>/routine run 1</code> ลงเดี๋ยวนี้เลย (ทดสอบ)")


def _fb_pending_text() -> str:
    """รายการโพสต์ที่ยังไม่ขึ้น (รอผู้ดูแลอนุมัติ)"""
    items = fb_pending.pending_items(fb_jobs.listing())
    return fb_pending.summary_text(items, label=fb_groups.label)


def _fb_pending_run(job_id: str = "") -> str:
    """ไล่ตามโพสต์ที่ยังไม่ขึ้น — ทีละงาน โดยใช้รอบตามเก็บที่มีอยู่แล้ว

    ระบุงานเองได้ (`/pending p123`) ซึ่งใช้ไล่งานที่ถูกยกเลิกไว้ได้ด้วย —
    ตัวไล่อัตโนมัติจะไม่แตะงานพวกนั้นเอง แต่ถ้าเจ้าของสั่งเองก็ทำให้
    """
    items = fb_pending.pending_items(fb_jobs.listing())
    if job_id:
        wanted = [x for x in items if x["job_id"] == job_id]
        if not wanted:
            return f"งาน {job_id} ไม่มีกลุ่มที่ค้างรออนุมัติ"
    else:
        job_id = fb_pending.next_job(items)
        if not job_id:
            return ("ยังไม่มีงานที่ถึงเวลาไล่\n" + _fb_pending_text())
        wanted = [x for x in items if x["job_id"] == job_id]
    note = _fb_followup(job_id=job_id)
    # **ตัดสินว่า “ลงมือแล้ว” จากตัวเดินงานจริง ไม่ใช่จากข้อความที่ได้กลับมา**
    #
    # `_fb_followup` คืนข้อความทุกกรณี — สำเร็จก็คืน “🔁 เริ่มตามเก็บ N กลุ่ม…”
    # ล้มก็คืนเหตุผล ไม่มีเคสไหนคืนค่าว่างเลยสักเคส โค้ดเดิมตรงนี้อ่านว่า
    # “มีข้อความ = เริ่มไม่ได้” จึง return ก่อนถึง mark_tried ทุกครั้งที่สำเร็จ
    # ตัวนับไม่ขยับ ตัวไล่อัตโนมัติจึงยิงซ้ำทุก 10 นาทีแทนที่จะเว้น 4 ชั่วโมง
    # (เกิดจริง 14 ส.ค. ยิง 23:22 แล้วยิงอีกที 23:32 — ห่างกันเป๊ะ 10 นาที)
    #
    # ถามตัวเดินงานว่า “ตอนนี้ถืองานนี้อยู่ไหม” เป็นหลักฐานตรง ไม่ต้องเดาจากสตริง
    # ที่เปลี่ยนถ้อยคำเมื่อไรก็พังเมื่อนั้น
    if not fb_runner.job_running(job_id):
        # ยังไม่ได้ลงมือ ห้ามนับเป็นหนึ่งครั้ง ไม่งั้นตัวนับจะเต็มทั้งที่ไม่เคยไล่จริง
        # แล้วกลุ่มนั้นจะถูกเลิกตามไปเฉยๆ
        return note or "เริ่มไล่ไม่ได้"
    fb_pending.mark_tried(job_id, [x["group_id"] for x in wanted])
    append_log("publish", f"[{job_id}] ไล่โพสต์ที่ยังไม่ขึ้น {len(wanted)} กลุ่ม")
    return note or f"🔄 เริ่มไล่โพสต์ที่ยังไม่ขึ้นของงาน {job_id} ({len(wanted)} กลุ่ม)"


def _fb_report_card(days: int = fb_report.DEFAULT_DAYS) -> tuple[str, dict | None]:
    """รายงาน + ปุ่มกดดูรูปของแต่ละโพสต์

    ปุ่มหนึ่งใบต่อหนึ่ง**งาน** ไม่ใช่ต่อกลุ่ม — งานเดียวลงหกกลุ่ม ถ้าทำปุ่มรายกลุ่ม
    จะได้ปุ่มซ้ำหกใบที่เปิดรูปชุดเดียวกัน
    """
    jobs = fb_jobs.listing()
    text = fb_report.build(jobs, days=days, label=fb_groups.label)
    rows = fb_report.post_report(jobs, days=days)
    if not rows:
        return text, None
    keyboard = {
        "inline_keyboard": [
            [
                {"text": fb_report.post_line(row),
                 "callback_data": f"fb:ri:{row['job_id']}"},
                {"text": "✏️", "callback_data": f"fb:ed:{row['job_id']}"},
            ]
            for row in rows
        ]
    }
    return text, keyboard


def _fb_preview(chat_id: str, job_id: str = "") -> str:
    """ส่งตัวอย่างว่างานนี้จะออกมาหน้าตายังไง — โพสต์ก่อน แล้วคอมเมนต์ทีละใบ

    **ส่งคอมเมนต์ทีละข้อความ ไม่รวมเป็นอัลบั้ม** — นี่คือหัวใจของฟังก์ชันนี้
    คำถามที่ต้องตอบคือ "รูปที่เพิ่งแนบไป มันไปอยู่คอมเมนต์ไหน" ซึ่งอัลบั้มตอบ
    ไม่ได้เลย เพราะ Telegram แสดงคำบรรยายรวมเป็นก้อนเดียวเหนือรูปทั้งชุด
    ตาเปล่าจึงจับคู่รูปกับข้อความไม่ได้

    (ปุ่ม 📷 ใน /report กับ /repost เป็นแบบอัลบั้ม ซึ่งดีสำหรับ "ดูภาพรวมโพสต์"
    แต่ใช้ตรวจการจับคู่ไม่ได้ — คนละงานกัน จึงต้องมีตัวนี้เพิ่ม)

    ส่งรูปเดี่ยวพร้อมคำบรรยายของช่องนั้น = เห็นคู่กันชัดในกรอบเดียว ตรงกับที่
    มันจะไปปรากฏบน Facebook จริง (คอมเมนต์หนึ่ง = รูปหนึ่ง + ข้อความหนึ่ง)
    """
    job = fb_jobs.get(job_id) if job_id else (
        fb_jobs.latest_open(chat_id)
        or next((j for j in fb_jobs.listing() if j.get("results")), None)
    )
    if job is None:
        return f"ไม่พบงาน {job_id}" if job_id else "ยังไม่มีงานให้ดู"
    token, default_chat = _fb_telegram()
    target = chat_id or default_chat
    if not token or not target:
        return "ยังไม่ได้ตั้งค่าบอท"

    job_id = job["id"]
    comments = _fb_comments(job)
    shots = _fb_comment_images(job)
    post_shots = [Path(p) for p in (job.get("images") or [job.get("image", "")]) if p]
    alive = [p for p in post_shots if p.is_file()]
    warns = []
    if len(alive) < len(post_shots):
        warns.append(f"⚠️ รูปโพสต์หายไปแล้ว {len(post_shots) - len(alive)} ใบ")

    head = (
        f"👁 <b>ตัวอย่างงาน {job_id}</b> — จะออกมาหน้าตาแบบนี้"
        "\n\n"
        f"📤 <b>ตัวโพสต์</b> · รูป {len(alive)} ใบ\n"
        + telegram_bot._escape((job.get("caption") or "(ยังไม่มีแคปชัน)")[:700])
    )
    try:
        if alive:
            telegram_bot.send_media_group(token, target, alive, head)
        else:
            telegram_bot.send_message(token, target, head + "\n\n⚠️ ยังไม่มีรูปโพสต์")

        # คอมเมนต์ทีละช่อง — ตรงนี้คือคำตอบของ "รูปเข้าคอมเมนต์ไหน"
        for order, text in enumerate(comments, 1):
            raw = shots[order - 1] if order <= len(shots) else ""
            clip = Path(raw) if raw else None
            body = (f"💬 <b>คอมเมนต์ที่ {order}</b>\n"
                    + telegram_bot._escape(text[:900]))
            if clip and clip.is_file():
                telegram_bot.send_photo(
                    token, target, clip, f"{body}\n\n📎 <code>{clip.name}</code>")
            elif clip:
                # ตั้งรูปไว้แต่ไฟล์หาย = โพสต์ออกไปจะไม่มีรูป ต้องรู้ก่อนโพสต์
                warns.append(f"⚠️ คอมเมนต์ที่ {order} ตั้งรูป "
                             f"<code>{clip.name}</code> ไว้แต่ไฟล์หายแล้ว "
                             "— จะโพสต์ออกไปแบบไม่มีรูป")
                telegram_bot.send_message(token, target, body + "\n\n📎 ไฟล์รูปหาย")
            else:
                telegram_bot.send_message(token, target, body + "\n\n(ช่องนี้ไม่มีรูป)")
    except telegram_bot.TelegramError as error:
        append_log("publish", f"ส่งตัวอย่างงาน {job_id} ไม่ได้: {error}")
        return "ส่งตัวอย่างไม่สำเร็จ"

    if not comments:
        warns.append("ยังไม่ได้ตั้งคอมเมนต์เลย — สั่ง /comment")
    # รูปที่ตั้งไว้เกินจำนวนข้อความ = รูปนั้นจะไม่ถูกใช้เลย ต้องบอก ไม่ใช่เงียบ
    extra = [x for index, x in enumerate(shots) if x and index >= len(comments)]
    if extra:
        warns.append(f"⚠️ มีรูปคอมเมนต์เกินมา {len(extra)} ใบ ที่ไม่มีข้อความคู่ "
                     "— รูปพวกนี้จะไม่ถูกใช้")
    with_photo = sum(1 for x in shots[:len(comments)] if x)
    tail = [f"✅ ตรวจแล้ว: คอมเมนต์ {len(comments)} ช่อง · มีรูป {with_photo} ช่อง"]
    tail += warns
    tail += ["", "แก้ข้อความ: <code>/comment 1 ข้อความ</code>",
             "เปลี่ยนรูป: ส่งรูปพร้อมพิมพ์ <code>/comment 2</code> ในคำบรรยาย"]
    _fb_say(target, "\n".join(tail))
    return f"ส่งตัวอย่างงาน {job_id} แล้ว"


def _fb_report_images(chat_id: str, job_id: str) -> str:
    """ส่งรูปของงานนั้นกลับเข้าแชท — ทั้งรูปในโพสต์และรูปในคอมเมนต์

    ส่งเป็น **อัลบั้มเดียว** ไม่ใช่ทีละใบ เพราะจุดประสงค์คือ "ดูว่าโพสต์นี้หน้าตา
    ยังไง" ซึ่งต้องเห็นครบในกรอบเดียวถึงจะเทียบกับโพสต์อื่นได้

    เรียงรูปโพสต์ก่อนแล้วค่อยรูปคอมเมนต์ ตรงกับลำดับที่มันไปปรากฏบน Facebook จริง
    """
    job = fb_jobs.get(job_id)
    if job is None:
        return "ไม่พบงานนี้แล้ว"
    post_shots = [Path(p) for p in (job.get("images") or [job.get("image", "")]) if p]
    comment_shots = [Path(p) for p in _fb_comment_images(job) if p]
    alive = [p for p in post_shots + comment_shots if p.is_file()]
    missing = len(post_shots) + len(comment_shots) - len(alive)

    results = job.get("results") or []
    posted = sum(1 for r in results if r.get("posted"))
    links = [r.get("link", "") for r in results if r.get("link")]
    comments = _fb_comments(job)
    when = job.get("finished_at") or job.get("started_at") or job.get("created_at") or ""
    head = [
        f"🧾 <b>งาน {job_id}</b>" + (f" · {_fb_when_text(when)}" if when else ""),
        telegram_bot._escape((job.get("caption") or "")[:400]),
    ]
    if comments:
        head += ["", "💬 <b>คอมเมนต์</b>"]
        head += [f"{index}. {telegram_bot._escape(text[:200])}"
                 for index, text in enumerate(comments, 1)]
    head += ["", f"📤 โพสต์สำเร็จ {posted}/{len(results) or len(job.get('groups') or [])} กลุ่ม"
             + (f" · เก็บลิงก์ได้ {len(links)}" if links else "")]
    if missing:
        # บอกตรงๆ ว่ารูปหาย ไม่ใช่ส่งเท่าที่มีแล้วให้เข้าใจว่าโพสต์มีแค่นี้
        head.append(f"⚠️ ไฟล์รูปหายไปแล้ว {missing} ใบ")
    caption = "\n".join(head)

    if not alive:
        _fb_say(chat_id, caption + "\n\n⚠️ ไม่เหลือไฟล์รูปให้แสดงเลย")
        return "ไฟล์รูปหายหมดแล้ว"
    token, default_chat = _fb_telegram()
    target = chat_id or default_chat
    if not token or not target:
        return "ยังไม่ได้ตั้งค่าบอท"
    try:
        telegram_bot.send_media_group(token, target, alive, caption)
    except telegram_bot.TelegramError as error:
        append_log("publish", f"ส่งรูปของงาน {job_id} ไม่ได้: {error}")
        return "ส่งรูปไม่สำเร็จ"
    return f"ส่งรูป {len(alive)} ใบแล้ว"


def _fb_routine_demand(now: datetime) -> tuple[list[dict], int]:
    """โพสต์ประจำวันที่ยังไม่ถึงคิววันนี้ ต้องใช้คอมเมนต์อีกกี่ครั้ง

    คืน (รายการที่รอ, จำนวนครั้งที่ต้องใช้) — ตารางที่ปิดไว้หรือยิงไปแล้ววันนี้
    ไม่นับ เพราะมันจะไม่กินโควตาอีกแล้ว

    **นับจากงานต้นทางที่ตารางจะหยิบมาลงจริง** ไม่ใช่เดาเอาว่ากลุ่มละ 2 ข้อความ
    ตารางหมุนเวียนได้หลายโพสต์ แต่ละใบตั้งกลุ่มกับจำนวนคอมเมนต์ไม่เท่ากัน
    เดาแล้วตัวเลขจะเพี้ยนพอดีตอนที่คนกำลังใช้มันตัดสินใจ
    """
    waiting = []
    total = 0
    for record in fb_routine.listing():
        if not record.get("enabled", True):
            continue
        try:
            hour, minute = (int(x) for x in record["time"].split(":"))
        except (KeyError, ValueError):
            continue
        when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if when <= now:
            continue                       # เลยเวลาไปแล้ว — วันนี้ไม่ยิงอีก
        source = fb_routine.current_source(record)
        job = fb_jobs.get(source) if source else None
        groups = len([g for g in (job.get("groups") or []) if g]) if job else 0
        per_post = len(_fb_comments(job)) if job else 0
        need = groups * per_post
        total += need
        waiting.append({"time": record["time"], "source": source,
                        "groups": groups, "per_post": per_post, "need": need,
                        "ok": bool(job)})
    waiting.sort(key=lambda x: x["time"])
    return waiting, total


def _fb_quota_text(now: datetime | None = None) -> str:
    """สรุปโควตาโพสต์/คอมเมนต์ — ตอบ /quotafb

    **ที่ต้องมีคือ "เหลือเท่าไร" คู่กับ "ค้างเท่าไร"** ดูอย่างเดียวว่าเหลือ 20
    ไม่ได้บอกอะไร ถ้าไม่รู้ว่าของค้างรอเติมอยู่ 24 ครั้ง — ตัวเลขสองตัวนี้ต้อง
    อยู่ในจอเดียวกันถึงจะตัดสินใจได้ว่า "เติมของเก่า" หรือ "เก็บไว้ให้ของใหม่"

    เจอจริง 19 ส.ค.: ของค้างโตจาก 4 เป็น 12 กลุ่มภายในสองชั่วโมง เพราะเลน post
    เติมได้ 4 กลุ่ม/ชั่วโมง แต่งานยิงชั่วโมงละ 6 กลุ่ม — ไล่เท่าไรก็ไม่ทัน
    ตัวเลข "ตามทันไหม" ข้างล่างจึงสำคัญกว่าโควตาที่เหลือด้วยซ้ำ
    """
    now = now or datetime.now()
    try:
        account = _fb_serial()
    except fb_auto_post.AutoPostError:
        account = ""
    today = now.date().isoformat()
    lines = [f"📊 <b>โควตาการโพสต์</b> · {now:%H:%M}"]

    # ---------------------------------------------------------- โพสต์วันนี้
    jobs = fb_jobs.listing()
    mine = [j for j in jobs
            if (j.get("finished_at") or j.get("created_at") or "").startswith(today)]
    posted = sum(1 for j in mine for r in (j.get("results") or []) if r.get("posted"))
    tried = sum(len(j.get("results") or []) for j in mine)
    lines += ["", f"📤 <b>โพสต์วันนี้</b> {len(mine)} งาน · "
                  f"ขึ้นจริง {posted}/{tried} กลุ่ม"]

    # ------------------------------------------------------- คอมเมนต์ชั่วโมงนี้
    lines += ["", "💬 <b>คอมเมนต์ — ชั่วโมงนี้</b>"]
    for lane, what in (("post", "งานโพสต์"), ("reply", "บอทตอบคอมเมนต์")):
        cap = facebook_group_post.comment_lane_limit(lane, account)
        free = facebook_group_post.comment_quota_left(lane, account)
        bar = "🟩" * free + "⬜" * max(0, cap - free)
        lines.append(f"   เลน {lane} ({what}) {bar} {free}/{cap}")
    lines.append(f"   เพดานรวมของบัญชี {facebook_group_post.comment_limit_per_hour(account)}/ชั่วโมง")
    wait = facebook_group_post.comment_quota_resets_in("post", account)
    if wait:
        lines.append(f"   ⏳ ว่างอีกช่องในอีก {wait / 60:.0f} นาที")

    # ---------------------------------------------------------- คอมเมนต์รายวัน
    used = fb_comment_guard.daily_used(now)
    cap_day = fb_comment_guard.daily_limit(account)
    left_day = fb_comment_guard.daily_left(now, account=account)
    lines += ["", f"💬 <b>คอมเมนต์ — วันนี้</b> {used}/{cap_day} → เหลือ {left_day}"]
    hold = fb_comment_guard.hold_reason(now, account=account)
    if hold:
        lines.append(f"   🛑 {hold}")

    # ------------------------------------------------------------- ของที่ค้าง
    waiting = []
    for job in jobs:
        per_post = len(_fb_comments(job))
        if not per_post or job["status"] in ("cancelled", "failed"):
            continue
        short = [r for r in (job.get("results") or [])
                 if r.get("posted") and not r.get("commented")]
        if short:
            when = (job.get("finished_at") or job.get("created_at") or "")
            waiting.append((job["id"], when, len(short), len(short) * per_post))
    # จำนวนข้อความต่อโพสต์ที่ใช้อยู่จริง — ใช้ทั้งตอนสรุปและตอนคิดว่าตามทันไหม
    per_post_now = max((len(_fb_comments(j)) for j in mine if _fb_comments(j)),
                       default=0)

    # **แยกของที่ยังคุ้มเติม ออกจากของที่เลยเวลาไปแล้ว**
    #
    # รวมกันเป็นก้อนเดียวจะอ่านผิด: เห็น "ค้าง 28 กลุ่ม" แล้วตกใจ ทั้งที่ครึ่งหนึ่ง
    # เป็นโพสต์อายุข้ามวันซึ่งคนเห็นไปแล้วไม่กลับมาดูคอมเมนต์ทีหลัง — เติมไปก็
    # แค่เผาโควตาที่ของใหม่ต้องใช้ (เกณฑ์เดียวกับ fb_pending.WINDOW_HOURS)
    fresh = [x for x in waiting
             if (now - datetime.fromisoformat(x[1])).total_seconds() < 3600 * 24]
    stale = [x for x in waiting if x not in fresh]
    need_fresh = sum(x[3] for x in fresh)
    if fresh:
        need = need_fresh
        lines += ["", f"⏳ <b>ค้างรอเติมคอมเมนต์</b> {sum(x[2] for x in fresh)} กลุ่ม "
                      f"({need} ครั้ง)"]
        for job_id, when, groups, times in fresh[:6]:
            lines.append(f"   <code>{job_id}</code> {when[11:16]} ขาด {groups} กลุ่ม")
        if len(fresh) > 6:
            lines.append(f"   …และอีก {len(fresh) - 6} งาน")
        if need > left_day:
            lines.append(f"   ⚠️ เกินโควตาที่เหลือวันนี้อยู่ {need - left_day} ครั้ง")
    else:
        lines += ["", "✅ ไม่มีงานใหม่ค้างรอเติมคอมเมนต์"]
    if stale:
        lines.append(f"   <i>(อีก {sum(x[2] for x in stale)} กลุ่มเป็นโพสต์เกิน 24 ชม. "
                     "— เติมไปคนคงไม่กลับมาเห็นแล้ว)</i>")

    # --------------------------------------------------- โพสต์ประจำวันที่จะมา
    routines, routine_need = _fb_routine_demand(now)
    if routines:
        lines += ["", f"🔁 <b>โพสต์ประจำวันที่ยังไม่ถึงคิว</b> "
                      f"{len(routines)} รอบ ({routine_need} ครั้ง)"]
        for item in routines:
            if not item["ok"]:
                lines.append(f"   {item['time']} ⚠️ ไม่พบงานต้นทาง "
                             f"<code>{item['source'] or '-'}</code>")
                continue
            lines.append(f"   {item['time']} {item['groups']} กลุ่ม × "
                         f"{item['per_post']} ข้อความ = {item['need']} ครั้ง")

    # ------------------------------------------------------- สรุปว่าจะเหลือเท่าไร
    #
    # **ตัวเลขที่ต้องใช้ตัดสินใจจริงคือบรรทัดนี้** — "เหลือ 20" ไม่ได้แปลว่าใช้ได้ 20
    # ถ้าอีกสองชั่วโมงข้างหน้ามีโพสต์ประจำวันรออยู่อีก 24 ครั้ง เอาไปเติมของเก่า
    # ตอนนี้คือไปแย่งโควตาของงานที่ยังไม่เกิด แล้วงานนั้นจะออกมาไม่มีคอมเมนต์
    committed = need_fresh + routine_need
    if committed:
        after = left_day - committed
        lines += ["", "🧮 <b>คิดรวมทั้งหมดแล้ว</b>",
                  f"   เหลือตอนนี้ {left_day} − ของค้าง {need_fresh} "
                  f"− โพสต์ประจำวัน {routine_need} = <b>{after}</b>"]
        if after < 0:
            lines.append(f"   ⚠️ ขาดอีก {-after} ครั้ง — ต้องเลือกว่าจะให้ใครได้ก่อน")
        elif after == 0:
            lines.append("   ⚠️ พอดีเป๊ะ ไม่เหลือเผื่องานที่สั่งเพิ่มระหว่างวัน")
        else:
            lines.append(f"   ✅ เหลือเผื่องานใหม่ได้อีก {after} ครั้ง "
                         f"(~{after // max(1, per_post_now)} กลุ่ม)")

    # --------------------------------------------------------- ตามทันไหม
    lane_cap = facebook_group_post.comment_lane_limit("post", account)
    per_post = per_post_now
    if per_post:
        groups_per_hour = lane_cap // per_post
        lines += ["", f"📐 <b>คอมเมนต์ตามงานทันไหม</b>",
                  f"   เติมได้ {groups_per_hour} กลุ่ม/ชม. "
                  f"(เลน {lane_cap} ครั้ง ÷ {per_post} ข้อความต่อโพสต์)"]
        if len(mine) >= 2:
            span = max(1.0, (now - datetime.fromisoformat(
                min(j.get("created_at") or now.isoformat() for j in mine)
            )).total_seconds() / 3600)
            rate = posted / span
            if groups_per_hour >= rate:
                mark = "✅ ตามทัน"
            else:
                mark = (f"⚠️ ตามไม่ทัน — ค้างเพิ่มราว "
                        f"{(rate - groups_per_hour) * 24:.0f} กลุ่ม/วัน")
            lines.append(f"   โพสต์จริง {rate:.1f} กลุ่ม/ชม. → {mark}")
    return "\n".join(lines)


def _fb_health_text() -> str:
    """ตรวจความพร้อมของเครื่องแบบไม่เริ่มงาน — ตอบ /health"""
    try:
        serial = _fb_serial()
    except fb_auto_post.AutoPostError as error:
        return f"🚫 {error}"
    report = fb_preflight.run_checks(
        serial, adb=ADB, jobs=fb_jobs.listing(),
        group_ids=fb_groups.enabled_ids(), label=fb_groups.label,
    )
    return (report.text() + "\n\n" + fb_comment_guard.summary_text()
            + "\n\n" + fb_phone_clean.summary_text()
            + "\n\n" + fb_backup.summary_text())


def _fb_collect(job_id: str = "", queued: bool = False) -> str:
    """เก็บยอด ถูกใจ/คอมเมนต์/แชร์ ของโพสต์ทุกกลุ่มในงานนี้

    ต่างจาก /followup ตรงที่**อ่านอย่างเดียว** ไม่กดถูกใจ ไม่คอมเมนต์ จึงเรียกซ้ำ
    ได้เรื่อยๆ ไม่กินโควตาคอมเมนต์ และไม่ต้องสลับคีย์บอร์ด

    เปิดโพสต์จากลิงก์ที่เก็บไว้เป็นทางแรก ถ้าไม่มีลิงก์ค่อยถอยไปแจ้งเตือน/ฟีด
    """
    job = fb_jobs.get(job_id) if job_id else \
        next((j for j in fb_jobs.listing() if j.get("results")), None)
    if job is None:
        return f"ไม่พบงาน {job_id}" if job_id else "ยังไม่มีงานที่โพสต์ไปแล้ว"
    serial, note = _fb_gate("collect", job, queued, str(job.get("serial") or ""))
    if note:
        return note
    # เก็บทุกกลุ่มที่โพสต์ขึ้นแล้ว — ไม่กรองว่ามีลิงก์ไหม เพราะกลุ่มที่ยังไม่มีลิงก์
    # ก็ยังเข้าถึงได้ทางแจ้งเตือน/ฟีด และจะได้เก็บลิงก์ติดมือกลับมาด้วยเลย
    targets = [
        {"group_id": r["group_id"], "name": fb_groups.label(r["group_id"]),
         "link": r.get("link", ""), "post_id": r.get("post_id", "")}
        for r in job["results"] if r.get("posted")
    ]
    if not targets:
        return f"งาน {job['id']} ไม่มีกลุ่มที่โพสต์สำเร็จ"

    job_id = job["id"]
    chat_id = job.get("chat_id", "")

    def on_log(line: str) -> None:
        append_log("publish", f"[{job_id}·เก็บยอด] {line}")
        fb_jobs.append_log(job_id, line)

    def on_result(entry: dict) -> None:
        _fb_stamp_post_id(entry)
        fb_jobs.upsert_result(job_id, entry)
        step = f"[{entry['index']}/{entry['total']}] " if entry.get("index") else ""
        _fb_say(chat_id, step + fb_auto_post.collect_line(entry, fb_groups.label))

    def on_done(results: list[dict], error: str) -> None:
        _fb_say(chat_id, (
            f"🏁 <b>เก็บยอดงาน {job_id} จบแล้ว</b>\n\n"
            + fb_auto_post.summarize_collect(results, fb_groups.label)
            + (f"\n\n⚠️ {telegram_bot._escape(error)}" if error else "")
        ))
        read = sum(1 for r in results if r.get("stats"))
        append_log("publish",
                   f"[{job_id}·เก็บยอด] จบ — อ่านได้ {read}/{len(results)} กลุ่ม")

    try:
        fb_runner.for_device(serial).start_collect(
            job_id=job_id, adb=ADB, serial=serial, caption=job["caption"],
            targets=targets, on_log=on_log, on_result=on_result,
            on_done=on_done, clipboard=_fb_clipboard(serial),
        )
    except fb_auto_post.AutoPostError as error:
        return str(error)
    append_log("publish", f"[{job_id}] เริ่มเก็บยอด {len(targets)} กลุ่ม")
    return f"📊 เริ่มเก็บยอด {len(targets)} กลุ่ม — ถูกใจ · คอมเมนต์ · แชร์"


def _fb_fiximage(job_id: str = "", queued: bool = False) -> str:
    """แก้รูปของโพสต์ที่ลงไปแล้วให้เป็นรูปที่ถูกต้อง

    ใช้ตอนโพสต์ขึ้นไปแล้วแต่รูปผิดใบ — เปิดโพสต์จากลิงก์ที่เก็บไว้ แล้วสั่ง
    "แก้ไขโพสต์ → ลบรูปภาพออก → เพิ่มสื่อ → บันทึก" ผ่านหน้าจอจริง

    ทำไมไม่ลบแล้วโพสต์ใหม่: ลิงก์ คอมเมนต์ และยอดถูกใจของเดิมจะหายหมด แถมการ
    ยิงเนื้อหาเดิมซ้ำลงกลุ่มเดิมยังเพิ่มสัญญาณสแปมให้ Facebook อีก

    ต้องมีลิงก์โพสต์ถึงจะแก้ได้ — กลุ่มที่ยังไม่เคยเก็บลิงก์ให้สั่ง /followup ก่อน
    """
    job = fb_jobs.get(job_id) if job_id else \
        next((j for j in fb_jobs.listing() if j.get("results")), None)
    if job is None:
        return f"ไม่พบงาน {job_id}" if job_id else "ยังไม่มีงานที่โพสต์ไปแล้ว"
    if not (job.get("images") or job.get("image")):
        return f"งาน {job['id']} ไม่มีรูป — ไม่มีอะไรให้แก้"
    serial, note = _fb_gate("fiximage", job, queued, str(job.get("serial") or ""))
    if note:
        return note
    targets = [
        {"group_id": r["group_id"], "name": fb_groups.label(r["group_id"]),
         "link": r.get("link", ""), "post_id": r.get("post_id", "")}
        for r in job["results"] if r.get("posted") and r.get("link")
    ]
    if not targets:
        return (f"งาน {job['id']} ยังไม่มีกลุ่มที่เก็บลิงก์ไว้ — "
                "สั่ง /followup เก็บลิงก์ก่อนแล้วค่อยแก้รูป")

    job_id = job["id"]
    chat_id = job.get("chat_id", "")
    images = [
        Path(p) for p in (job.get("images") or [job.get("image", "")]) if p
    ]

    def on_log(line: str) -> None:
        append_log("publish", f"[{job_id}·แก้รูป] {line}")
        fb_jobs.append_log(job_id, line)

    def on_result(entry: dict) -> None:
        fb_jobs.upsert_result(job_id, entry)
        step = f"[{entry['index']}/{entry['total']}] " if entry.get("index") else ""
        _fb_say(chat_id, step + fb_auto_post.fix_line(entry, fb_groups.label))

    def on_done(results: list[dict], error: str) -> None:
        _fb_say(chat_id, (
            f"🏁 <b>แก้รูปงาน {job_id} จบแล้ว</b>\n\n"
            + fb_auto_post.summarize_fix(results, fb_groups.label)
            + (f"\n\n⚠️ {telegram_bot._escape(error)}" if error else "")
        ))
        fixed = sum(1 for r in results if r.get("image_fixed"))
        append_log("publish",
                   f"[{job_id}·แก้รูป] จบ — สำเร็จ {fixed}/{len(results)} กลุ่ม")

    try:
        fb_runner.for_device(serial).start_fiximage(
            job_id=job_id, adb=ADB, serial=serial, caption=job["caption"],
            targets=targets, images=images, on_log=on_log,
            on_result=on_result, on_done=on_done,
        )
    except fb_auto_post.AutoPostError as error:
        return str(error)
    append_log("publish", f"[{job_id}] เริ่มแก้รูป {len(targets)} กลุ่ม")
    return f"🖼️ เริ่มแก้รูป {len(targets)} กลุ่ม — เปิดโพสต์เดิมแล้วเปลี่ยนรูปให้"


# รอก่อนไล่หาแจ้งเตือน — ผู้ดูแลบางกลุ่มอนุมัติภายในไม่กี่สิบวินาที
# รอสักหน่อยแล้วค่อยหาจะเจอมากกว่ายิงทันทีที่กดโพสต์เสร็จ
AUTO_FOLLOWUP_DELAY = 60.0
# ถ้ารอบโพสต์ "ไม่เห็นโพสต์ตัวเองเลยสักกลุ่ม" = ถูกกักรอผู้ดูแลอนุมัติ
# ยิงตามเก็บใน 60 วินาทีจึงเปล่าประโยชน์แน่นอน — แจ้งเตือนอนุมัติยังไม่มา
# และฟีดก็ยังไม่มีโพสต์ให้หา เสียเวลาจอกลุ่มละราวหนึ่งนาทีแล้วได้ 0/N
# (เจอจริง 12 ส.ค. งาน p545241529: 4 งานก่อนหน้าเห็นในฟีด 100% งานนี้ 0%
#  เพราะวันเดียวโพสต์ไปแล้วราว 26 โพสต์ลงกลุ่มเดิม Facebook เลยเริ่มตรวจก่อน)
AUTO_FOLLOWUP_SLOW_DELAY = 900.0


def _fb_followup_delay(results: list[dict]) -> float:
    """รอนานแค่ไหนก่อนตามเก็บ — ดูจากว่ารอบโพสต์เห็นโพสต์ตัวเองไหม"""
    visible = sum(
        1 for r in results
        if r.get("liked") or r.get("commented") or r.get("link")
    )
    return AUTO_FOLLOWUP_DELAY if visible else AUTO_FOLLOWUP_SLOW_DELAY


def _fb_auto_followup(job_id: str, delay: float = AUTO_FOLLOWUP_DELAY,
                      serial: str = "") -> None:
    """ต่อสายไป "หาโพสต์จากแจ้งเตือน" ทันทีที่รอบโพสต์จบ

    ทำไมต้องแยกเธรด: on_done ถูกเรียกจากในเธรดของตัวรันเอง ตอนนั้นตัวรัน
    **ของเครื่องนั้น** ยังนับว่ายุ่งอยู่ สั่ง start_followup ตรงๆ จะโดนตีกลับว่า
    "กำลังทำงานอยู่" จึงต้องรอให้เธรดเดิมปล่อยก่อน

    ทำไมต้องหน่วงก่อน: กลุ่มส่วนใหญ่ต้องรอผู้ดูแลอนุมัติ ยิงทันทีที่โพสต์เสร็จ
    จะยังไม่มีแจ้งเตือนให้หา เสียเวลาเปล่าราวหนึ่งนาทีต่อกลุ่ม

    **ต้องรู้ว่าเครื่องไหน** ไม่งั้นรอบตามเก็บจะไปเกิดบนเครื่องตัวหลักเสมอ ทั้งที่
    โพสต์ไปจากอีกเครื่อง — เปิดแอปผิดบัญชีแล้วหาโพสต์ไม่เจอสักกลุ่ม
    """
    def worker() -> None:
        deadline = time.time() + 180
        while fb_runner.busy_on(serial) and time.time() < deadline:
            time.sleep(2.0)
        if fb_runner.busy_on(serial):
            append_log("publish", f"[{job_id}] ตัวรันยังไม่ว่าง — ข้ามการตามเก็บอัตโนมัติ")
            return
        time.sleep(delay)
        append_log("publish", f"[{job_id}] โพสต์จบแล้ว — ไล่หาโพสต์จากแจ้งเตือนต่อ")
        try:
            note = _fb_followup(job_id=job_id)
        except Exception as error:      # ห้ามให้เธรดนี้ตายเงียบ
            append_log("publish", f"[{job_id}] ตามเก็บอัตโนมัติล้ม: {error}")
            return
        if note and not note.startswith("🔁"):
            append_log("publish", f"[{job_id}] ตามเก็บอัตโนมัติไม่ได้: {note}")

    threading.Thread(target=worker, daemon=True).start()


# ================================================ กล่องข้อความถึง Claude Code
#
# ส่งเข้า "เซสชันที่เปิดค้างอยู่" โดยตรงไม่ได้ — ไม่มี API ให้ยิงข้อความเข้าไป
# (เครื่องมือ send_message ของ Claude Code ส่งได้เฉพาะเซสชัน**อื่น** และเป็นของ
#  ฝั่ง Claude ไม่ใช่ฝั่งบอท · ในเครื่องก็ไม่มี claude CLI ให้เรียก)
# จึงพักไว้ในไฟล์แล้วให้ Claude มาอ่านเอง — ข้อความไม่หายและอ่านย้อนหลังได้
CLAUDE_INBOX = DATA_DIR / "claude_inbox.json"
_inbox_lock = threading.Lock()
INBOX_LIMIT = 200


def claude_inbox() -> list[dict]:
    if not CLAUDE_INBOX.is_file():
        return []
    try:
        items = json.loads(CLAUDE_INBOX.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return items if isinstance(items, list) else []


def claude_inbox_add(
    text: str, source: str = "telegram", channel: str = "post",
) -> dict:
    """ฝากข้อความไว้ให้ Claude — **แยกช่องทางตามสายงาน**

    ช่อง "post" = งานโพสต์/คอมเมนต์ Facebook (บอทหลักตัวนี้)
    ช่อง "clip" = สายเจนคลิป/สตอรีบอร์ด (บอท @ClipAiABot คนละโปรเซส)

    ถ้าไม่แยก ข้อความของสายหนึ่งจะไปโผล่ในเซสชันของอีกสาย แล้ว Claude ที่นั่ง
    อยู่คนละงานจะเห็นงานที่ไม่ใช่ของตัวเอง — เกิดจริงมาแล้ว 12 ส.ค.
    รายการเก่าที่ไม่มีฟิลด์นี้ถือเป็น "post" ตามต้นทางเดิม
    """
    entry = {
        "id": f"m{int(time.time() * 1000) % 1_000_000_000}",
        "text": text.strip(),
        "source": source,
        "channel": channel,
        "at": datetime.now().isoformat(timespec="seconds"),
        "read": False,
    }
    with _inbox_lock:
        items = claude_inbox()
        items.append(entry)
        CLAUDE_INBOX.write_text(
            json.dumps(items[-INBOX_LIMIT:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return entry


# เรียก Claude Code CLI แบบสั่งครั้งเดียวจบ (ไม่ใช่โหมดคุย)
CLAUDE_CLI = Path.home() / "AppData" / "Roaming" / "npm" / "claude.cmd"
CLAUDE_RUN_TIMEOUT = 600          # 10 นาที — งานจริงบางอย่างใช้เวลานาน
CLAUDE_REPLY_LIMIT = 3500         # กันข้อความ Telegram ล้นเพดาน 4096
# สิทธิ์ที่ยอมให้ Claude ใช้ตอนถูกสั่งจาก Telegram — **ประกาศตรงนี้ที่เดียว**
#
# ทำไมใส่เป็น flag ไม่ใช่ .claude/settings.json:
#   ทดสอบแล้วโหมด headless ไม่อ่านไฟล์ตั้งค่าของโปรเจกต์ (โฟลเดอร์ยังไม่ถูก trust)
#   แต่ flag ได้ผลแน่นอน และดีกว่าตรงที่เห็นชัดในโค้ดว่าอนุญาตอะไรไว้บ้าง
#
# รูปแบบต้องเว้นวรรค "Bash(adb *)" ไม่ใช่ "Bash(adb:*)" — แบบหลังไม่ตรงกับอะไรเลย
# (ตรวจจริง 11 ส.ค.: แบบ : ถูกปฏิเสธ · แบบเว้นวรรครันแล้วได้ผลกลับมา)
#
# จงใจให้แค่ adb: แตะมือถือได้ แต่แก้ไฟล์/รันสคริปต์อื่นไม่ได้
CLAUDE_ALLOWED_TOOLS = "Bash(adb *)"


def claude_cli_ready() -> bool:
    return CLAUDE_CLI.is_file()


def _claude_authorised(chat_id: str) -> bool:
    """รับคำสั่งจากแชทของเจ้าของเครื่องเท่านั้น

    คำสั่งนี้เปิดให้ "สั่งงาน Claude บนเครื่องนี้จากมือถือ" ได้เต็มรูปแบบ
    ใครยิงเข้าบอทได้ก็สั่งเครื่องนี้ได้ จึงต้องล็อกไว้กับ chat id ที่บันทึกไว้
    ยังไม่เคยบันทึก = ไม่รับ ดีกว่าปล่อยผ่านตอนยังไม่รู้ว่าเจ้าของคือใคร
    """
    known = str(load_config().get("telegram_chat_id") or "").strip()
    return bool(known) and str(chat_id).strip() == known


def claude_run(prompt: str, cwd: Path | None = None) -> tuple[bool, str]:
    """ยิง prompt เข้า Claude Code CLI แล้วคืน (สำเร็จไหม, คำตอบ)"""
    if not claude_cli_ready():
        return False, f"ไม่พบ Claude CLI ที่ {CLAUDE_CLI}"
    try:
        result = subprocess.run(
            [str(CLAUDE_CLI), "-p", prompt, "--allowedTools", CLAUDE_ALLOWED_TOOLS],
            cwd=str(cwd or BASE_DIR), capture_output=True,
            timeout=CLAUDE_RUN_TIMEOUT, creationflags=studio_shared.NO_WINDOW)
    except subprocess.TimeoutExpired:
        return False, f"Claude ทำงานเกิน {CLAUDE_RUN_TIMEOUT} วินาที — ตัดจบ"
    except OSError as error:
        return False, f"เรียก Claude ไม่ได้: {error}"
    out = result.stdout.decode("utf-8", errors="replace").strip()
    err = result.stderr.decode("utf-8", errors="replace").strip()
    if result.returncode != 0:
        return False, (err or out or f"Claude จบด้วยรหัส {result.returncode}")[:600]
    return True, out or "(Claude ไม่ได้ตอบอะไรกลับมา)"


# งานสำเร็จรูปที่สั่งจาก Telegram ได้ — **prompt เป็นข้อความคงที่ในโค้ดเท่านั้น**
#
# ตั้งใจไม่รับข้อความอิสระจากแชทมาต่อท้าย prompt: ถ้ารับ ข้อความ Telegram
# จะกลายเป็นคำสั่งที่เครื่องนี้ทำตามทันที ใครได้โทเคนบอทไปก็สั่งเครื่องได้
# แบบนี้ผู้ใช้เลือกได้แค่ "หมายเลขงาน" ส่วนเนื้อคำสั่งเราคุมเองทั้งหมด
CLAUDE_ACTIONS: dict[str, dict[str, str]] = {
    "status": {
        "label": "🩺 สุขภาพระบบ",
        "prompt": (
            "ตรวจสุขภาพระบบ pipeline studio แล้วสรุปสั้นๆ เป็นภาษาไทยไม่เกิน 15 บรรทัด "
            "สำหรับอ่านบนมือถือ: (1) เซิร์ฟเวอร์พอร์ต 8866 รันอยู่ไหม เวอร์ชันอะไร "
            "(2) adb devices เห็นมือถือไหม (3) มือถือต่อเน็ตได้ไหม แบตเท่าไร อุณหภูมิเท่าไร "
            "(4) คิวงานที่ยังไม่โพสต์มีกี่งาน "
            "ห้ามแก้ไฟล์ใดๆ ห้ามรีสตาร์ตอะไร อ่านอย่างเดียว "
            "ตอบเป็นข้อความล้วน ไม่ต้องใส่ตาราง markdown"
        ),
    },
    "phone": {
        "label": "📱 ตรวจมือถือ",
        "prompt": (
            "วินิจฉัยมือถือที่ต่อ adb อยู่ แล้วตอบภาษาไทยไม่เกิน 15 บรรทัด: "
            "เชื่อมต่ออยู่ไหม · เน็ตใช้ได้ไหม (ping จริง) · แบตกี่เปอร์เซ็นต์ กำลังชาร์จไหม "
            "· อุณหภูมิเท่าไร · คีย์บอร์ดค้างที่ ADBKeyboard หรือเปล่า "
            "ถ้าเจอปัญหาให้บอกสาเหตุที่น่าจะเป็นและวิธีแก้ที่ผู้ใช้ทำเองได้ "
            "ห้ามแก้ตั้งค่าเครื่องหรือแตะมือถือ อ่านสถานะอย่างเดียว "
            "ตอบเป็นข้อความล้วน ไม่ต้องใส่ตาราง markdown"
        ),
    },
    "log": {
        "label": "📜 สรุปงานล่าสุด",
        "prompt": (
            "อ่าน data/logs/publish.log เฉพาะงานล่าสุดงานเดียว แล้วสรุปภาษาไทย "
            "ไม่เกิน 15 บรรทัด: งานไหน · โพสต์ได้กี่กลุ่มจากกี่กลุ่ม · ถูกใจ/คอมเมนต์/ลิงก์ได้เท่าไร "
            "· มีขั้นไหนล้มบ้างและเพราะอะไร ถ้าทุกอย่างผ่านให้บอกสั้นๆ ว่าผ่านหมด "
            "ห้ามแก้ไฟล์ อ่านอย่างเดียว ตอบเป็นข้อความล้วน ไม่ต้องใส่ตาราง markdown"
        ),
    },
    "queue": {
        "label": "📋 คิวงานที่ค้าง",
        "prompt": (
            "อ่าน data/fb_jobs.json แล้วสรุปภาษาไทยไม่เกิน 15 บรรทัดว่ามีงานไหนบ้าง "
            "ที่ยังไม่ได้โพสต์หรือโพสต์ไม่ครบ พร้อมบอกว่าแต่ละงานขาดอะไร "
            "(ไม่มีรูป / ไม่มีแคปชัน / ตั้งเวลาไว้เมื่อไร / โพสต์ได้กี่กลุ่มจากกี่กลุ่ม) "
            "ห้ามแก้ไฟล์ อ่านอย่างเดียว ตอบเป็นข้อความล้วน ไม่ต้องใส่ตาราง markdown"
        ),
    },
}


def claude_inbox_mark_read(channel: str = "") -> int:
    """ปิดข้อความว่าอ่านแล้ว — ระบุ channel เพื่อปิด **เฉพาะสายงานของตัวเอง**

    ไม่ระบุแล้วสั่ง mark จะไปปิดของอีกสายด้วย ซึ่งทำให้เซสชันนั้นไม่เห็นงานที่
    ฝากไว้เลย (คนละคนละงานกัน)
    """
    def mine(item: dict) -> bool:
        return not channel or (item.get("channel") or "post") == channel

    with _inbox_lock:
        items = claude_inbox()
        count = sum(1 for i in items if not i.get("read") and mine(i))
        for item in items:
            if mine(item):
                item["read"] = True
        CLAUDE_INBOX.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return count


class PhoneGate:
    """คุมสิทธิ์ใช้จอมือถือ — **หนึ่งใบต่อหนึ่งเครื่อง** เจ้าเดียวต่อเครื่อง

    มือถือเครื่องหนึ่งมีจอเดียว ถ้างานโพสต์กับ Claude CLI สั่ง ADB ใส่เครื่อง
    เดียวกันพร้อมกันจะแตะทับกันเละทั้งคู่: กำลังพิมพ์แคปชันอยู่แล้วอีกฝั่งกด Back
    หรือ force-stop แอป

    **ของเดิมมีประตูใบเดียวทั้งระบบ** พอเครื่องแรกเข้าไปแล้ว เครื่องที่สองยืนรอ
    ข้างนอกทั้งที่จอตัวเองว่างสนิท — ต้นเหตุใหญ่ที่สุดที่ทำให้สั่งสองเครื่องพร้อมกัน
    ไม่ได้ ตอนนี้แจกกุญแจแยกรายเครื่อง จำนวนเครื่องเท่าไรก็ได้

    ออกแบบให้ไม่สมมาตรเพื่อกันเดดล็อก (เหมือนเดิม แต่คิดแยกรายเครื่อง):
      · งานโพสต์ของเครื่องนั้น ใช้ `fb_runner.busy_on(serial)` บอกว่าตัวเองยุ่ง
      · Claude ต้อง**รอให้งานโพสต์ของเครื่องนั้นว่างก่อน** แล้วค่อยจองประตู
      · งานโพสต์เช็คว่าประตูของเครื่องนั้นถูกจองอยู่ไหม ถ้าใช่ = ไม่เริ่ม
    ทั้งสองฝั่งจึงไม่มีทางรอกันวนไปมา และการรอของเครื่อง A ไม่ลามไปหยุดเครื่อง B
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: dict[str, tuple[str, float]] = {}   # serial -> (เจ้าของ, เวลา)

    @staticmethod
    def _key(serial: str) -> str:
        key = str(serial or "").strip()
        if not key:
            # ห้ามให้ผ่านแบบเงียบ — ประตูที่ไม่รู้ว่าเป็นของเครื่องไหน คือประตูใบเดียว
            # ทั้งระบบกลับมาอีกครั้ง ซึ่งคือบั๊กที่กำลังแก้อยู่พอดี
            raise ValueError("phone_gate ต้องระบุ serial ของมือถือ")
        return key

    def try_take(self, owner: str, serial: str) -> bool:
        key = self._key(serial)
        with self._lock:
            if self._held.get(key):
                return False
            self._held[key] = (owner, time.time())
            return True

    def wait_take(self, owner: str, serial: str, timeout: float = 900.0) -> bool:
        """รอจนจอ**เครื่องนั้น**ว่างแล้วจอง — คืน False ถ้ารอเกินเวลา"""
        key = self._key(serial)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not fb_runner.busy_on(key) and self.try_take(owner, key):
                return True
            time.sleep(3.0)
        return False

    def give_back(self, owner: str, serial: str) -> None:
        key = self._key(serial)
        with self._lock:
            if (self._held.get(key) or ("", 0.0))[0] == owner:
                self._held.pop(key, None)

    def held_by(self, serial: str) -> str:
        with self._lock:
            return (self._held.get(self._key(serial)) or ("", 0.0))[0]

    def held_for(self, serial: str) -> float:
        with self._lock:
            owner, since = self._held.get(self._key(serial)) or ("", 0.0)
        return (time.time() - since) if owner else 0.0

    def holders(self) -> dict:
        """{serial: เจ้าของ} ทุกเครื่องที่มีคนถืออยู่ — ใช้โชว์ในหน้าเว็บ/Telegram"""
        with self._lock:
            return {serial: owner for serial, (owner, _) in self._held.items() if owner}


phone_gate = PhoneGate()

# ข้อความเดียวใช้ทุกที่ที่ปฏิเสธเพราะจอไม่ว่าง — ตัวตั้งเวลาใช้ข้อความนี้
# เป็นตัวแยกว่า "รอจอ" (ไม่ล้างเวลา ลองใหม่ได้) กับ "ล้มจริง" (ล้างเวลา)
PHONE_BUSY_NOTE = "Claude กำลังใช้จอมือถืออยู่ — ยังเริ่มโพสต์ไม่ได้"
# ค่าคืนเฉพาะที่แปลว่า "จอยังไม่ว่าง ยังไม่ได้เริ่ม" — ตัวเดินคิวเทียบค่านี้ตรงๆ
# ห้ามเทียบด้วยการหาคำในข้อความ เพราะข้อความเปลี่ยนเมื่อไรตัวเดินคิวพังเงียบ
PHONE_WAIT_NOTE = "__phone_busy__"

# คิวรอใช้จอมือถือ — งานโพสต์/ตามเก็บที่สั่งมาตอนจอไม่ว่างจะมารอตรงนี้
#
# ของเดิมปฏิเสธไปเลยแล้วให้ผู้ใช้กดใหม่เอง ซึ่งไม่ต่างจากให้ไปนั่งเฝ้าหน้าจอ
# เข้าคิวแล้วเริ่มให้เองเมื่อจอว่างดีกว่า — ตัวตั้งเวลาที่วนอยู่แล้วทุก 20 วิ
# ทำหน้าที่เดินคิวให้ ไม่ต้องเพิ่มเธรดใหม่
_phone_waitlist: list[dict] = []
_waitlist_lock = threading.Lock()
PHONE_WAITLIST_LIMIT = 10


def phone_is_free(serial: str) -> bool:
    """จอ**เครื่องนี้**ว่างไหม — ต้องถามแยกรายเครื่องเสมอ

    ของเดิมถามว่า "จอว่างไหม" ลอยๆ ซึ่งพอมีสองเครื่องแปลว่า "ทุกเครื่องว่างพร้อมกัน
    ไหม" งานบนเครื่อง B เลยเริ่มไม่ได้ตราบใดที่เครื่อง A ยังทำงานอยู่
    """
    return not phone_gate.held_by(serial) and not fb_runner.busy_on(serial)


def phone_waitlist() -> list[dict]:
    with _waitlist_lock:
        return list(_phone_waitlist)


def _phone_wait_add(kind: str, job_id: str, chat_id: str = "", serial: str = "") -> int:
    """ต่อคิวรอจอ**เครื่องนั้น** คืนลำดับที่ (0 = มีอยู่ในคิวแล้ว · -1 = คิวเต็ม)

    ลำดับที่นับเฉพาะคิวของเครื่องเดียวกัน — บอกผู้ใช้ว่า "คิวที่ 3" ทั้งที่สองคิวแรก
    เป็นของอีกเครื่องซึ่งไม่เกี่ยวกันเลย จะทำให้เขานั่งรอเก้อ
    """
    serial = str(serial or "").strip()
    with _waitlist_lock:
        for item in _phone_waitlist:
            if (item["kind"] == kind and item["job_id"] == job_id
                    and item.get("serial", "") == serial):
                return 0
        if len(_phone_waitlist) >= PHONE_WAITLIST_LIMIT:
            return -1
        _phone_waitlist.append({"kind": kind, "job_id": job_id,
                                "chat_id": chat_id, "serial": serial})
        return sum(1 for i in _phone_waitlist if i.get("serial", "") == serial)


def _any_phone_free() -> bool:
    """มีเครื่องไหนว่างบ้างไหม — ด่านหยาบก่อนงานเบื้องหลังจะลงมือ

    งานเบื้องหลัง (ไล่โพสต์ที่ยังไม่ขึ้น · ล้างเครื่อง) ไม่ได้ผูกกับเครื่องใดเครื่องหนึ่ง
    ตั้งแต่ต้น ถามว่า "ทุกเครื่องว่างไหม" จะไม่ได้ลงมือเลยเมื่อมีหลายเครื่อง
    ส่วนขั้นลงมือจริงยังจองประตูรายเครื่องอยู่ดี ตรงนี้แค่กันไม่ให้เสียเวลาเปล่า
    """
    return any(phone_is_free(s) for s in device_book.enabled_serials())


# ชื่อไทยของแต่ละแบบงานที่ต้องใช้จอ — ใช้ทั้งในคิวและข้อความตอบกลับ
PHONE_JOB_NAMES = {"post": "", "followup": "ตามเก็บ", "collect": "เก็บยอด",
                   "fiximage": "แก้รูป"}


def _fb_gate(kind: str, job: dict, queued: bool, serial: str = "") -> tuple[str, str]:
    """ด่านเดียวก่อนสั่งงานมือถือ — คืน (เครื่องที่จะใช้, ข้อความที่ต้องตอบกลับ)

    ข้อความว่าง = ผ่านด่าน เริ่มงานได้เลย

    รวมของเดิมสี่ก้อนที่เขียนซ้ำกันคำต่อคำ (โพสต์ · ตามเก็บ · เก็บยอด · แก้รูป)
    ไว้ที่เดียว เพราะทั้งสี่ต้องเปลี่ยนพร้อมกันทุกครั้งที่กติกาเรื่องจอเปลี่ยน —
    ของเดิมแก้ไปสามที่ลืมที่หนึ่งเมื่อไรก็ได้บั๊กที่หาไม่เจอทันที

    **ต้องรู้ว่าเครื่องไหนก่อนถามว่าจอว่างไหม** ของเดิมถามว่า "จอว่างไหม" ลอยๆ
    แล้วค่อยไปเลือกเครื่องทีหลัง พอมีสองเครื่องคำถามนั้นจึงกลายเป็น "ทุกเครื่อง
    ว่างพร้อมกันไหม" ซึ่งตอบว่าไม่ว่างเกือบตลอดเวลา
    """
    try:
        picked = _fb_serial(serial)
    except fb_auto_post.AutoPostError as error:
        return "", str(error)
    if phone_is_free(picked):
        return picked, ""
    if queued:
        return picked, PHONE_WAIT_NOTE      # ตัวเดินคิวจะคืนกลับหัวคิวเอง
    place = _phone_wait_add(kind, job["id"], job.get("chat_id", ""), picked)
    if place < 0:
        return picked, f"คิวรอจอเต็ม ({PHONE_WAITLIST_LIMIT} งาน)"
    what = PHONE_JOB_NAMES.get(kind, kind)
    holder = (phone_gate.held_by(picked)
              or f"งานโพสต์ {fb_runner.running().get(picked, '')}".strip())
    return picked, (
        f"📥 {(what + ' ') if what else ''}{job['id']} เข้าคิวรอเครื่อง "
        f"{telegram_bot._escape(device_book.label(picked))} แล้ว — คิวที่ {place or 1}\n"
        f"<i>ตอนนี้ {telegram_bot._escape(holder)} ใช้เครื่องนั้นอยู่ · "
        f"ว่างเมื่อไรจะเริ่มให้เอง</i>"
    )


def _phone_wait_pump() -> None:
    """จอว่างแล้วหยิบงานแรกในคิว**ของเครื่องนั้น**มาเริ่ม — เรียกทุก 20 วินาที

    เดินคิวทีละเครื่อง ไม่ใช่ทีละคิวรวม เพราะงานหัวคิวอาจรอเครื่อง A อยู่ ส่วน
    เครื่อง B ว่าง — ของเดิมจะหยุดทั้งคิวเพราะหัวคิวยังไปไม่ได้ กลายเป็นเครื่อง
    ที่ว่างอยู่นั่งเฉยๆ ทั้งที่มีงานรอ
    """
    with _waitlist_lock:
        # รายการที่ไม่มี serial แปลว่ามีคนเรียก `_phone_wait_add` แบบเก่า — ทิ้ง
        # แล้วบอกให้เห็น ห้ามปล่อยให้มันไปทำ `phone_is_free("")` ระเบิดในลูป
        # ตัวตั้งเวลา เพราะ except ก้อนนอกจะกลืนไว้แล้วคิวจะค้างเงียบตลอดกาล
        orphan = [i for i in _phone_waitlist if not i.get("serial")]
        for bad in orphan:
            _phone_waitlist.remove(bad)
            append_log("publish", f"[{bad.get('job_id')}] คิวรอจอไม่ได้บอกว่าเครื่องไหน "
                                  f"— ทิ้งรายการนี้ ({bad.get('kind')})")
        item = next((i for i in _phone_waitlist if phone_is_free(i["serial"])), None)
        if item is None:
            return
        _phone_waitlist.remove(item)
    kind, job_id, chat_id = item["kind"], item["job_id"], item["chat_id"]
    append_log("publish", f"[{job_id}] จอว่างแล้ว — เริ่มงานที่รอคิวไว้ ({kind})")
    if kind == "followup":
        note = _fb_followup(job_id=job_id, queued=True)
    elif kind == "collect":
        note = _fb_collect(job_id=job_id, queued=True)
    elif kind == "fiximage":
        note = _fb_fiximage(job_id=job_id, queued=True)
    else:
        note = _fb_run_job(job_id, queued=True)
    # ยังเริ่มไม่ได้ (จอถูกแย่งไปใน 20 วินาทีที่ผ่านมา) — คืน**หัวคิว**
    # ไม่ใช่ต่อท้าย ไม่งั้นงานที่รอนานสุดโดนงานใหม่แซงตลอด
    if note == PHONE_WAIT_NOTE:
        with _waitlist_lock:
            _phone_waitlist.insert(0, item)
        return
    if note and chat_id:
        _fb_say(chat_id, note)


# คิวงานของ Claude — **ทำทีละงานเท่านั้น**
#
# ถ้าปล่อยให้แต่ละคำสั่งแยกเธรดของตัวเอง สั่งรัวๆ จะรันซ้อนกันหลายตัว
# แย่งกันแก้ไฟล์เดียวกันได้ และคำตอบจะทยอยกลับมาปนกันจนอ่านไม่รู้เรื่อง
_claude_jobs: list[dict] = []
_claude_queue_lock = threading.Lock()
_claude_worker: threading.Thread | None = None
_claude_running: dict | None = None
CLAUDE_QUEUE_LIMIT = 10


def claude_queue_state() -> tuple[dict | None, list[dict]]:
    """(งานที่กำลังทำ, งานที่รออยู่)"""
    with _claude_queue_lock:
        return _claude_running, list(_claude_jobs)


def _claude_pump() -> None:
    """ตัวเดินคิว — หยิบทีละงานจนคิวหมดแล้วค่อยจบเธรด"""
    global _claude_worker, _claude_running
    while True:
        with _claude_queue_lock:
            if not _claude_jobs:
                _claude_worker = None
                _claude_running = None
                return
            item = _claude_jobs.pop(0)
            _claude_running = item

        chat_id, label, prompt = item["chat_id"], item["label"], item["prompt"]
        # รอจนจอมือถือว่างก่อน — Claude สั่ง ADB ได้เหมือนกัน ถ้าชนกับงานโพสต์
        # จะแตะทับกันเละทั้งคู่ (กำลังพิมพ์แคปชันอยู่แล้วอีกฝั่ง force-stop แอป)
        #
        # จองเฉพาะเครื่องที่ Claude จะไปแตะ ไม่ใช่จองยกเซ็ต — เครื่องอื่นทำงาน
        # ของตัวเองต่อได้ตามปกติระหว่างที่ Claude ทำงานอยู่บนเครื่องนี้
        try:
            phone = _fb_serial()
        except fb_auto_post.AutoPostError as error:
            _fb_say(chat_id, f"⚠️ {telegram_bot._escape(label)} — "
                             f"{telegram_bot._escape(str(error))}")
            append_log("input", f"Claude [{label[:30]}] ไม่รู้ว่าจะใช้เครื่องไหน: {error}")
            continue
        phone_name = telegram_bot._escape(device_book.label(phone))
        if fb_runner.busy_on(phone):
            _fb_say(chat_id, f"⏳ รองานโพสต์บน {phone_name} ให้จบก่อน แล้วจะเริ่ม: "
                             f"{telegram_bot._escape(label)}")
        if not phone_gate.wait_take("claude", phone):
            _fb_say(chat_id, f"⚠️ {telegram_bot._escape(label)} — "
                             f"รอจอ {phone_name} ว่างเกิน 15 นาที ยกเลิกงานนี้")
            append_log("input", f"Claude [{label[:30]}] รอจอไม่ว่าง — ข้าม")
            continue
        _fb_say(chat_id, f"▶️ เริ่ม: {telegram_bot._escape(label)}")
        try:
            ok, reply = claude_run(prompt)
        finally:
            phone_gate.give_back("claude", phone)
        append_log("input", f"Claude [{label[:30]}] {'สำเร็จ' if ok else 'ล้ม'}: {reply[:90]}")
        head = f"🤖 <b>{telegram_bot._escape(label)}</b>" if ok else \
               f"⚠️ <b>{telegram_bot._escape(label)} — ทำไม่สำเร็จ</b>"
        body = telegram_bot._escape(reply[:CLAUDE_REPLY_LIMIT])
        if len(reply) > CLAUDE_REPLY_LIMIT:
            body += "\n…(ตัดท้าย)"
        with _claude_queue_lock:
            waiting = len(_claude_jobs)
        _fb_say(
            chat_id,
            f"{head}\n\n{body}"
            + (f"\n\n⏭ เหลือในคิวอีก {waiting} งาน" if waiting else ""),
        )


def claude_enqueue(chat_id: str, label: str, prompt: str) -> tuple[bool, str]:
    """ต่อคิวงานให้ Claude — คืน (รับไว้ไหม, ข้อความตอบผู้ใช้)"""
    global _claude_worker
    with _claude_queue_lock:
        if len(_claude_jobs) >= CLAUDE_QUEUE_LIMIT:
            return False, f"คิวเต็ม ({CLAUDE_QUEUE_LIMIT} งาน) — รอให้ทำเสร็จก่อน"
        _claude_jobs.append({"chat_id": chat_id, "label": label, "prompt": prompt})
        ahead = len(_claude_jobs) - 1
        busy = _claude_running is not None
        if _claude_worker is None or not _claude_worker.is_alive():
            _claude_worker = threading.Thread(target=_claude_pump, daemon=True)
            _claude_worker.start()
    if not busy and ahead == 0:
        return True, "🤖 ส่งให้ Claude แล้ว — กำลังทำงาน…"
    now = _claude_running or {}
    return True, (
        f"📥 เข้าคิวแล้ว — คิวที่ {ahead + 1}\n"
        f"<i>กำลังทำ: {telegram_bot._escape(str(now.get('label', '—'))[:60])}</i>"
    )


def _fb_claude_menu() -> tuple[str, dict | None]:
    """เมนูงานที่สั่งให้ Claude CLI ทำได้ พร้อมปุ่มกด"""
    waiting = [i for i in claude_inbox() if not i.get("read")]
    ready = claude_cli_ready()
    lines = [
        "🤖 <b>สั่งงาน Claude</b>",
        "",
        ("Claude CLI พร้อมใช้งาน" if ready else "⚠️ ยังไม่พบ Claude CLI ในเครื่อง"),
        "",
        "เลือกงานที่ต้องการ — แต่ละงานเป็นคำสั่งที่กำหนดไว้แล้ว อ่านอย่างเดียว ไม่แก้ไฟล์",
    ]
    # โชว์ทีละเครื่อง — บอกว่า "จอไม่ว่าง" ลอยๆ ตอนมีหลายเครื่องทำให้เข้าใจผิด
    # ว่าทั้งชุดติดหมด ทั้งที่ติดแค่เครื่องเดียว
    busy_lines = []
    for serial, owner in phone_gate.holders().items():
        busy_lines.append(f"📱 {device_book.label(serial)}: <b>{owner}</b> ใช้อยู่ "
                          f"({phone_gate.held_for(serial) / 60:.0f} นาที)")
    for serial, job_id in fb_runner.running().items():
        if serial not in phone_gate.holders():
            busy_lines.append(f"📱 {device_book.label(serial)}: งานโพสต์ "
                              f"<b>{job_id}</b> ใช้อยู่ — Claude จะรอจนจบ")
    if busy_lines:
        lines += [""] + busy_lines
    running, pending = claude_queue_state()
    if running or pending:
        lines += ["", "<b>สถานะคิว</b> — ทำทีละงาน"]
        if running:
            lines.append(f"▶️ กำลังทำ: {telegram_bot._escape(str(running.get('label'))[:55])}")
        for order, item in enumerate(pending, 1):
            lines.append(f"   {order}. {telegram_bot._escape(str(item.get('label'))[:55])}")
    if waiting:
        lines += ["", f"📮 มีข้อความฝากไว้ {len(waiting)} ข้อความรอ Claude อ่าน"]
    rows = [[{"text": item["label"], "callback_data": f"fb:cl:{key}"}]
            for key, item in CLAUDE_ACTIONS.items()] if ready else []
    return "\n".join(lines), ({"inline_keyboard": rows} if rows else None)


def _fb_claude_start(chat_id: str, key: str) -> str:
    """เริ่มงานสำเร็จรูปหนึ่งงาน — รันแยกเธรดแล้วส่งคำตอบกลับเข้าแชท"""
    action = CLAUDE_ACTIONS.get(key)
    if action is None:
        return "ไม่รู้จักงานนี้"
    if not _claude_authorised(chat_id):
        append_log("input", f"ปฏิเสธคำสั่ง Claude จาก chat {chat_id} (ไม่ใช่เจ้าของ)")
        _fb_say(chat_id, "🚫 แชทนี้ไม่มีสิทธิ์สั่งงาน Claude")
        return "ไม่มีสิทธิ์"
    if not claude_cli_ready():
        _fb_say(chat_id, f"⚠️ ไม่พบ Claude CLI ที่ {CLAUDE_CLI}")
        return "ไม่มี CLI"

    append_log("input", f"สั่งงาน Claude: {key}")
    taken, note = claude_enqueue(chat_id, action["label"], action["prompt"])
    _fb_say(chat_id, note)
    return "เข้าคิวแล้ว" if taken else "คิวเต็ม"


def _fb_stamp_post_id(entry: dict) -> dict:
    """เติม "รหัสโพสต์จริง" จากลิงก์ย่อที่เก็บมาได้

    ลิงก์ย่อ /share/p/<โทเคน> อ่านไม่ออกว่าเป็นโพสต์ไหน ตามไปหารหัสจริงเก็บไว้
    จะได้อ้างอิงโพสต์ได้แน่นอนโดยไม่ต้องเดาจากแคปชัน (แคปชันซ้ำกันได้ถ้าทำซ้ำ)

    รหัสนี้**เปิดโพสต์บนแอปไม่ได้** — ทดสอบครบทุกรูปแบบแล้วแอปเด้งไปฟีดหลัก
    เก็บไว้เพื่อตรวจสอบและอ้างอิงเท่านั้น
    """
    link = entry.get("link") or ""
    if not link or entry.get("post_id"):
        return entry
    try:
        group_id, post_id = fb_auto_post.resolve_post_link(link)
    except Exception as error:            # แปลงไม่ได้ต้องไม่ล้มทั้งงาน
        append_log("publish", f"แปลงลิงก์โพสต์ไม่ได้: {error}")
        return entry
    if post_id:
        entry["post_id"] = post_id
        entry.setdefault("link_group_id", group_id)
    return entry


def _fb_clipboard(serial: str):
    """ตัวอ่าน/เขียนคลิปบอร์ดมือถือของเครื่องนี้ (ผ่านช่อง scrcpy)

    `adb shell service call clipboard` ใช้ไม่ได้ตั้งแต่ Android 10 —
    คืนค่าว่างเสมอเมื่อแอปที่เรียกไม่ได้อยู่หน้าจอ จึงต้องผ่าน scrcpy
    """

    class Clipboard:
        @staticmethod
        def drain() -> None:
            scrcpy_control.drain_clipboard(ADB, serial)

        @staticmethod
        def wait_change(timeout: float = 8.0) -> str:
            return scrcpy_control.wait_clipboard(ADB, serial, timeout)

    return Clipboard


def _fb_parse_when(text: str) -> datetime | None:
    """อ่านเวลาที่ผู้ใช้พิมพ์ — รับ "20:30" หรือ "9/8 20:30" หรือ "+30" (อีกกี่นาที)

    เวลาที่ผ่านไปแล้วของวันนี้ ให้ถือว่าเป็นพรุ่งนี้ (ไม่ยิงย้อนหลังทันที)
    """
    value = (text or "").strip()
    if not value:
        return None
    now = datetime.now()
    if value.startswith("+"):
        try:
            return now + timedelta(minutes=int(value[1:]))
        except ValueError:
            return None
    found = re.match(r"^(?:(\d{1,2})[/-](\d{1,2})\s+)?(\d{1,2})[:.](\d{2})$", value)
    if not found:
        return None
    day, month, hour, minute = found.groups()
    when = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    if day and month:
        when = when.replace(day=int(day), month=int(month))
    elif when <= now:
        when += timedelta(days=1)       # เลยเวลาของวันนี้แล้ว = เอาพรุ่งนี้
    return when


# งานที่ถึงเวลาแล้วแต่จอไม่ว่าง — จำไว้เพื่อ log ครั้งเดียว ไม่ให้ท่วมทุก 20 วิ
_deferred_jobs: set[str] = set()


# เดินงานเบื้องหลังทุกๆ กี่วินาที — ไม่ต้องถี่ ทั้งสองงานเป็นงานรายชั่วโมง/รายวัน
HOUSEKEEPING_EVERY = 600.0
_housekeeping_at = 0.0


def _housekeeping() -> None:
    """งานประจำที่ควรทำเองโดยไม่ต้องมีใครสั่ง — สำรองข้อมูล + ไล่โพสต์ที่ยังไม่ขึ้น

    เกาะไปกับตัวตั้งเวลาที่วนอยู่แล้ว ไม่เพิ่มเธรดใหม่ — เธรดยิ่งเยอะยิ่งไล่ปัญหายาก
    และงานพวกนี้ช้าได้ ไม่ต้องตรงเป๊ะระดับวินาที

    **ห้ามไปแย่งจอมือถือกับงานของผู้ใช้เด็ดขาด** จึงลงมือต่อเมื่อจอว่างจริงเท่านั้น
    ถ้าไม่ว่างก็ข้ามไป รอบหน้าค่อยมาใหม่ (อีก 10 นาที)
    """
    global _housekeeping_at
    if time.time() - _housekeeping_at < HOUSEKEEPING_EVERY:
        return
    _housekeeping_at = time.time()

    # โดนพักคอมเมนต์แล้วต้อง**ดัง** ไม่ใช่รู้กันเองในไฟล์ log
    #
    # เรื่องเดิมที่พลาด: 16 ส.ค. คอมเมนต์ล้ม 32 ครั้งติดกัน 5 ชั่วโมงโดยไม่มี
    # ข้อความเข้าแชทสักบรรทัด ผู้ใช้รู้ตัวก็ต่อเมื่อมานั่งไล่ดูงานเองทีหลัง
    try:
        alert = fb_comment_guard.take_alert()
        if alert:
            _fb_say(_fb_telegram()[1], alert)
            append_log("publish", "แจ้งเตือน: พักคอมเมนต์ทั้งระบบ")
    except Exception as error:
        append_log("publish", f"แจ้งเตือนพักคอมเมนต์ไม่สำเร็จ: {error}")

    try:
        made = fb_backup.run_daily()
        if made:
            append_log("publish", f"สำรองข้อมูลรายวัน → {made['path'].name} "
                                  f"({made['files']} ไฟล์)")
            for name in made.get("pruned", []):
                append_log("publish", f"ลบไฟล์สำรองเก่า {name}")
    except Exception as error:
        append_log("publish", f"สำรองข้อมูลไม่สำเร็จ: {error}")

    try:
        jobs = fb_jobs.listing()
        fb_pending.cleanup(jobs)
        # ต้องมีเครื่องว่างสักเครื่อง และไม่มีงานตั้งเวลาใกล้ถึง — งานผู้ใช้มาก่อน
        if not _any_phone_free():
            return
        soon = datetime.now() + timedelta(minutes=15)
        for job in jobs:
            when = job.get("run_at") or ""
            if when and datetime.now() <= datetime.fromisoformat(when) <= soon:
                return
        items = fb_pending.pending_items(jobs)
        if not fb_pending.due_items(items):
            return
        note = _fb_pending_run()
        append_log("publish", f"ไล่โพสต์ที่ยังไม่ขึ้นเอง — {note[:80]}")
    except Exception as error:
        append_log("publish", f"ไล่โพสต์ที่ยังไม่ขึ้นไม่สำเร็จ: {error}")


PHONE_CLEAN_OWNER = "ล้างเครื่องประจำวัน"
SCREEN_OWNER = "ดูแลจอมือถือ"
_screen_at = 0.0
SCREEN_EVERY = 60.0


def _screen_shell(serial: str):
    return fb_screen.make_shell(serial, ADB)


def _job_due_within(seconds: float, now: datetime | None = None) -> bool:
    """มีงานตั้งเวลาจะถึงภายในกี่วินาทีนี้ไหม"""
    now = now or datetime.now()
    edge = now + timedelta(seconds=seconds)
    for job in fb_jobs.listing():
        when = job.get("run_at") or ""
        if not when or job["status"] != fb_auto_post.STATUS_READY:
            continue
        try:
            at = datetime.fromisoformat(when)
        except ValueError:
            continue
        if now <= at <= edge:
            return True
    return False


def _screen_pump(now: datetime | None = None) -> str:
    """ดูแลจอมือถือ — ปลุกก่อนงานถึง / ดับเมื่อไม่มีใครใช้

    **ทำไมต้องดับ** วัดเมื่อ 18 ส.ค.: จอเปิดค้าง 2 วัน 14 ชม. เพราะตั้ง
    `stay_on_while_plugged_in=15` ผลคือแบต 50 °C และค้างที่ 15% ทั้งที่เสียบ AC
    เกิน 45 °C ค้างนานๆ แบตเสื่อมถาวร

    **ตัวชี้ขาดว่า "ว่าง" คือ `lastUserActivityTime` ของเครื่องเอง** ซึ่งนับทั้ง
    นิ้วผู้ใช้และ `input tap` ของบอท — ตัวเดียวคุมได้ทั้งสองเรื่อง ไม่ต้องเดาว่า
    ผู้ใช้ถือเครื่องอยู่ไหม (มือถือเครื่องนี้เจ้าของใช้เองด้วย ดับใส่หน้าไม่ได้)
    """
    global _screen_at
    now = now or datetime.now()
    if time.time() - _screen_at < SCREEN_EVERY:
        return ""
    _screen_at = time.time()
    # ดูแล**ทุกเครื่องที่เปิดใช้** ไม่ใช่แค่เครื่องตัวหลัก — ของเดิมดูแลเครื่องเดียว
    # เครื่องที่สองจึงเปิดจอค้างตลอดกาลโดยไม่มีใครดับให้ ซึ่งคืออาการเดียวกับที่
    # วัดได้เมื่อ 18 ส.ค. (จอค้าง 2 วัน 14 ชม. · แบต 50 °C · เสื่อมถาวร)
    ready = {d["serial"] for d in list_devices() if d["ready"]}
    notes = []
    for serial in device_book.enabled_serials():
        if serial not in ready:
            continue
        try:
            note = _screen_pump_one(serial, now)
        except Exception as error:    # เครื่องเดียวพังต้องไม่ลามไปหยุดเครื่องอื่น
            append_log("publish", f"ดูแลจอ {device_book.label(serial)} ไม่สำเร็จ: {error}")
            continue
        if note:
            notes.append(f"{device_book.label(serial)}: {note}")
    return " · ".join(notes)


def _screen_pump_one(serial: str, now: datetime) -> str:
    """ดูแลจอของเครื่องเดียว — ค่าเปิด/ปิดอ่านจากค่าตั้งของเครื่องนั้น"""
    if not bool(device_book.setting(serial, "screen_saver", True)):
        return ""
    shell = _screen_shell(serial)

    # 1) ใกล้ถึงเวลางาน = ปลุกล่วงหน้า ให้แอปมีเวลาตั้งตัวก่อนบอทเริ่มกด
    if _job_due_within(fb_screen.PREWAKE_SECONDS, now):
        if not fb_screen.is_awake(shell):
            fb_screen.wake(shell, log=lambda x: append_log("publish", x))
            append_log("publish", f"ปลุกจอ {device_book.label(serial)} ก่อนงานตั้งเวลา")
        return "ปลุกล่วงหน้า"

    # 2) จะดับได้ต้องว่างจริงทุกด้าน — งานของ app.py · บอทคนละโปรเซส · นิ้วผู้ใช้
    #    **และต้องไม่มีคนนั่งดูจออยู่** ชั้นนี้เพิ่ง 22 ส.ค. 2569 เพราะของเดิม
    #    เช็คครบทุกอย่างยกเว้นเรื่องนี้ คนดูจอผ่านหน้าเว็บจึงโดนดับจอใส่ทุก 3 นาที
    #    (การนั่งดูไม่ได้แตะจอ มือถือเลยนับว่าไม่มีคนใช้)
    if someone_watching(serial):
        return ""
    if not phone_is_free(serial):
        return ""
    if _job_due_within(fb_screen.KEEP_AWAKE_BEFORE, now):
        return ""
    if not fb_screen.is_awake(shell):
        return ""
    try:
        # queue=False — งานหรี่จอเป็นงานจร ถ้าไม่ว่างให้ข้ามไปเลย
        # ห้ามเข้าแถวรอ ไม่งั้นไปแทรกหน้างานโพสต์ที่รอมาก่อน
        with studio_shared.phone_lock(serial, timeout=0.5, poll=0.2,
                                      label=SCREEN_OWNER, queue=False):
            idle = fb_screen.idle_seconds(shell)
            if idle < 0 or idle < fb_screen.IDLE_SECONDS:
                return ""
            fb_screen.sleep_screen(shell, log=lambda x: append_log("publish", x))
            return "ดับจอ"
    except studio_shared.PhoneBusy:
        return ""                     # บอทตัวอื่นใช้อยู่ ไม่ใช่เรื่องของเรา


def _phone_clean_pump(now: datetime | None = None) -> str:
    """ถึงเวลาล้างเครื่องประจำวันหรือยัง — ถึงแล้วล้างให้เลย

    **งานของผู้ใช้มาก่อนเสมอ** ด่านสามชั้นก่อนลงมือ:
      1. จอต้องว่างจริง (ไม่มีงานโพสต์ ไม่มีใครจองประตู)
      2. ต้องไม่มีงานตั้งเวลาใกล้ถึงใน 15 นาที
      3. ต้องจองประตูจอได้ — จองไม่ได้ก็ถอย รอบหน้า (อีก 20 วิ) ค่อยมาใหม่

    **จองสองชั้น** ประตูในโปรเซส (`phone_gate`) กันงานของ app.py เอง ส่วนล็อก
    ข้ามโปรเซส (`studio_shared.phone_lock`) กันบอทตัวอื่นที่รันแยกกันคนละโปรเซส
    (fb_engage_bot / fb_mass_bot) — ขาดชั้นไหนไปอีกฝั่งก็แตะจอทับได้

    **ADB หลุด/เครื่องดับกลางทางไม่ต้องกลัว** ทุกขั้นทำซ้ำได้ไม่เสียหาย และถ้า
    ไม่ได้ล้างสักเครื่องจะ**ไม่บันทึกว่าล้างแล้ว** รอบหน้าจึงกลับมาล้างใหม่เอง
    ส่วน `finally` คืนประตูเสมอ — ไม่งั้นล้มทีเดียวจอจะถูกล็อกค้างตลอดกาล
    """
    now = now or datetime.now()
    # เปิดไว้อย่างน้อยหนึ่งเครื่องก็พอ — สวิตช์จริงเป็นของแต่ละเครื่อง เช็คซ้ำ
    # ตอนวนล้างทีละเครื่องอีกที ตรงนี้แค่กันไม่ให้เสียเวลายิง adb เปล่าๆ
    if not any(bool(device_book.setting(s, "phone_clean", True))
               for s in device_book.enabled_serials()):
        return ""
    if not fb_phone_clean.due(now):
        return ""
    if not _any_phone_free():
        return ""
    soon = now + timedelta(minutes=15)
    for job in fb_jobs.listing():
        when = job.get("run_at") or ""
        if when and now <= datetime.fromisoformat(when) <= soon:
            return ""
    return _phone_clean_run(now)


# ใครล้างไปแล้วบ้างวันนี้ — เก็บแยกรายเครื่อง
#
# **จำเป็นเพราะ `fb_phone_clean` จดว่า "ล้างแล้ววันไหน" เป็นค่าเดียวทั้งระบบ**
# พอมีสองเครื่องแล้วเครื่องหนึ่งกำลังโพสต์อยู่ตอนถึงเวลาล้าง ของเดิมจะล้างเฉพาะ
# เครื่องที่ว่าง แล้วปั๊มว่า "ล้างแล้ววันนี้" — เครื่องที่ยุ่งจึงไม่ได้ล้างทั้งวัน
# โดยไม่มีอะไรบอก และจะไม่ได้ล้างไปเรื่อยๆ ทุกวันถ้ามันยุ่งเวลาเดิมประจำ
#
# จดในหน่วยความจำพอ — รีสตาร์ตแล้วลืมก็แค่ล้างซ้ำหนึ่งรอบ ซึ่งไม่เสียหายอะไร
# (ทุกขั้นของการล้างทำซ้ำได้) ดีกว่าเพิ่มไฟล์สถานะใหม่ที่ต้องมาดูแลอีกไฟล์
_clean_today: dict = {"date": "", "done": set(), "reports": []}


def _clean_ledger(now: datetime) -> dict:
    """สมุดรายวันของการล้างเครื่อง — ข้ามวันแล้วเริ่มนับใหม่"""
    today = now.date().isoformat()
    if _clean_today["date"] != today:
        _clean_today.update({"date": today, "done": set(), "reports": []})
    return _clean_today


def _phone_clean_run(now: datetime | None = None, force: bool = False) -> str:
    """ล้างเครื่องเดี๋ยวนี้ — ใช้ทั้งจากตัวตั้งเวลาและคำสั่ง /clean

    **จองประตูทีละเครื่อง ไม่ใช่จองยกเซ็ต** ของเดิมจองประตูใบเดียวทั้งระบบไว้
    ตลอดรอบล้าง ซึ่งแปลว่าระหว่างล้างเครื่อง A อยู่ เครื่อง B จะสั่งงานไม่ได้เลย
    ทั้งที่ยังไม่มีใครไปแตะมัน — ล้างเครื่องใช้เวลาเป็นนาที งานที่ตั้งเวลาไว้พอดี
    ตอนนั้นจะถูกเลื่อนออกไปฟรีๆ

    **เครื่องที่ยุ่งจะถูกข้ามแล้วกลับมาล้างทีหลัง ไม่ใช่ข้ามทั้งวัน** ตราบใดที่ยัง
    ล้างไม่ครบทุกเครื่อง จะยังไม่ปั๊มว่า "ล้างแล้ววันนี้" ตัวตั้งเวลาจึงวนกลับมา
    เก็บเครื่องที่เหลือให้เองทุก 20 วินาที และรายงานเข้า Telegram ครั้งเดียว
    ตอนครบทุกเครื่องแล้วเท่านั้น
    """
    now = now or datetime.now()
    serials = [d["serial"] for d in list_devices() if d["ready"]]
    if not serials:
        return "ไม่มีมือถือเชื่อมต่ออยู่"
    ledger = _clean_ledger(now)
    if force:
        ledger["done"], ledger["reports"] = set(), []
    fresh = []
    skipped = []
    for serial in serials:
        if serial in ledger["done"]:
            continue                              # ล้างไปแล้วรอบก่อนของวันนี้
        if not bool(device_book.setting(serial, "phone_clean", True)):
            ledger["done"].add(serial)            # ปิดไว้ = ถือว่าจบแล้ว ไม่ค้างคิว
            continue
        if not force and not phone_is_free(serial):
            skipped.append(device_book.label(serial))
            continue
        if not phone_gate.try_take(PHONE_CLEAN_OWNER, serial):
            skipped.append(device_book.label(serial))
            continue
        try:
            # queue=False — ล้างเครื่องตอนเที่ยงคืนเป็นงานจร ไม่ว่างก็ข้าม
            with studio_shared.phone_lock(serial, timeout=3.0, poll=0.5,
                                          label=PHONE_CLEAN_OWNER, queue=False):
                report = fb_phone_clean.clean(
                    serial, adb=ADB,
                    log=lambda line: append_log("publish", line),
                )
            fresh.append(report)
            ledger["done"].add(serial)
            ledger["reports"].append(report)
        except studio_shared.PhoneBusy:
            append_log("publish", f"ล้างเครื่อง {serial} ไม่ได้ — "
                                  f"{studio_shared.who_holds_phone(serial)}")
        except Exception as error:
            append_log("publish", f"ล้างเครื่อง {serial} ไม่สำเร็จ: {error}")
        finally:
            # ต้องคืนประตูของ **เครื่องนี้** ทุกทางออก ไม่งั้นล้มทีเดียว
            # เครื่องนั้นจะถูกล็อกค้างตลอดกาลจนกว่าจะรีสตาร์ตเซิร์ฟเวอร์
            phone_gate.give_back(PHONE_CLEAN_OWNER, serial)

    left = [s for s in serials if s not in ledger["done"]]
    if left:
        # ยังไม่ครบ = ยังไม่ปั๊มว่าทำแล้ว รอบหน้ามาเก็บที่เหลือ และเงียบไว้ก่อน
        # ไม่งั้นจะยิงรายงานเข้า Telegram ทุก 20 วินาทีจนกว่าเครื่องนั้นจะว่าง
        names = ", ".join(skipped) or ", ".join(device_book.label(s) for s in left)
        note = f"ล้างแล้ว {len(ledger['done'])}/{len(serials)} เครื่อง — รอ {names}"
        if fresh:
            append_log("publish", note)
        return note

    fb_phone_clean.mark_done(ledger["reports"], now)
    text = fb_phone_clean.report_text(ledger["reports"])
    _fb_say(_fb_telegram()[1], text)
    append_log("publish", f"ล้างเครื่องประจำวันแล้ว {len(ledger['reports'])} เครื่อง")
    return text


def _fb_scheduler() -> None:
    """เฝ้างานที่ตั้งเวลาไว้ ถึงเวลาแล้วเริ่มโพสต์ให้เอง

    เช็คทุก 20 วินาทีจากไฟล์งาน ไม่ได้ตั้ง timer ค้างไว้ในหน่วยความจำ —
    รีสตาร์ตเซิร์ฟเวอร์แล้วเวลาที่ตั้งไว้ต้องไม่หาย
    """
    while True:
        time.sleep(20)
        try:
            _phone_wait_pump()          # จอว่างแล้วเริ่มงานที่รอคิวไว้
            _routine_pump()             # ถึงเวลาของโพสต์ประจำวันหรือยัง
            _housekeeping()             # สำรองรายวัน + ไล่โพสต์ที่ยังไม่ขึ้น
            try:
                _phone_clean_pump()     # ล้างเครื่องตอนเที่ยงคืน
            except Exception as error:
                append_log("publish", f"ล้างเครื่องประจำวันไม่สำเร็จ: {error}")
            try:
                _screen_pump()          # ดับจอตอนว่าง / ปลุกก่อนงานถึง
            except Exception as error:
                append_log("publish", f"ดูแลจอมือถือไม่สำเร็จ: {error}")
            for job in fb_jobs.listing():
                if job["status"] != fb_auto_post.STATUS_READY:
                    continue
                when = job.get("run_at") or ""
                if not when or datetime.now() < datetime.fromisoformat(when):
                    continue
                # จอไม่ว่าง = **ยังไม่ล้างเวลา** ปล่อยให้รอบหน้า (อีก 20 วิ)
                # มาลองใหม่เอง กลายเป็นการรอคิว ไม่ใช่ความล้มเหลว
                #
                # ถ้าล้างเวลาไปก่อนแล้วถูกปฏิเสธ งานที่ตั้งเวลาไว้จะหายเงียบ
                # ผู้ใช้ตั้งโพสต์ 6 โมงเช้าแล้วไม่มีอะไรเกิดขึ้นโดยไม่รู้สาเหตุ
                #
                # ต้องถามถึง**เครื่องของงานนี้** ไม่ใช่ "มีเครื่องไหนถูกจองไหม"
                # ไม่งั้นงานบนเครื่อง B จะถูกเลื่อนทุกครั้งที่เครื่อง A ยุ่ง
                # และถ้ายังตอบไม่ได้ว่าจะใช้เครื่องไหน (ยังไม่เลือก / ถอดสายอยู่)
                # ก็ต้องเลื่อนเหมือนกัน ห้ามล้างเวลาทิ้งเด็ดขาด
                try:
                    _job_phone = _fb_serial(str(job.get("serial") or ""))
                except fb_auto_post.AutoPostError:
                    _job_phone = ""
                if not _job_phone or phone_gate.held_by(_job_phone):
                    if job["id"] not in _deferred_jobs:
                        _deferred_jobs.add(job["id"])
                        append_log(
                            "publish",
                            f"[{job['id']}] ถึงเวลาแล้วแต่จอไม่ว่าง — รอแล้วลองใหม่เอง",
                        )
                    continue
                _deferred_jobs.discard(job["id"])
                fb_jobs.update(job["id"], run_at="")   # กันยิงซ้ำถ้ารันไม่ผ่าน
                append_log("publish", f"[{job['id']}] ถึงเวลาที่ตั้งไว้ — เริ่มโพสต์")
                note = _fb_run_job(job["id"])
                # ต้องเขียนเหตุผลลง log ด้วย ไม่ใช่ส่งเข้าแชทอย่างเดียว
                #
                # เดิมส่งเข้า Telegram ทางเดียว พอเริ่มงานไม่ได้ log จะมีแค่บรรทัด
                # "ถึงเวลาที่ตั้งไว้" แล้วเงียบสนิท ไล่ย้อนไม่ได้เลยว่าติดอะไร
                # (เจอจริง 11 ส.ค. งาน p343003654: ยิงตอน 09:00 แล้วหายเงียบ)
                if note:
                    append_log("publish", f"[{job['id']}] เริ่มไม่ได้: {note}")
                _fb_say(job.get("chat_id", ""), note or f"⏰ ถึงเวลาโพสต์งาน {job['id']}")
        except Exception as error:      # ตัวเฝ้าต้องไม่ตายเพราะงานเดียวพัง
            append_log("publish", f"ตัวตั้งเวลาสะดุด: {error}")


def _fb_when_text(run_at: str) -> str:
    """เวลาที่ตั้งไว้ในรูปแบบอ่านง่าย — วัน/เดือน ชั่วโมง:นาที

    ของเดิมตัดสตริง ISO ตรงๆ ได้ "08-09 09:00" ซึ่งอ่านไม่ออกว่าวันไหนเดือนไหน
    """
    if not run_at:
        return ""
    try:
        return f"{datetime.fromisoformat(run_at):%d/%m %H:%M}"
    except ValueError:
        return run_at[:16].replace("T", " ")


# ข้อความที่รอให้เลือกงานก่อน — เก็บในหน่วยความจำพอ เพราะอายุแค่ไม่กี่วินาที
# {chat_id: {"kind": "comment"|"schedule", "text": "..."}}
_fb_pending_pick: dict[str, dict] = {}


def _fb_job_picker(chat_id: str, kind: str, text: str, jobs: list[dict]) -> None:
    """ส่งปุ่มให้กดเลือกว่าจะเอาคำสั่งนี้ไปลงงานไหน

    ดีกว่าให้พิมพ์รหัสงานเอง — รหัสเป็นเลขสุ่ม 9 หลัก พิมพ์ผิดง่ายและถ้าผิดจะไป
    ลงงานอื่นโดยไม่รู้ตัว
    """
    _fb_pending_pick[chat_id] = {"kind": kind, "text": text}
    label = {"comment": "คอมเมนต์", "schedule": "ตั้งเวลา"}.get(kind, "แก้ข้อความโพสต์")
    rows = []
    for job in jobs:
        caption = (job.get("caption", "") or "(ไม่มีแคปชัน)").splitlines()[0][:28]
        images = len(job.get("images") or ([job["image"]] if job.get("image") else []))
        rows.append([{
            "text": f"{caption} · 🖼{images}",
            "callback_data": f"fb:pick:{job['id']}",
        }])
    rows.append([{"text": "✖️ ยกเลิก", "callback_data": "fb:pickx:0"}])
    _fb_say(
        chat_id,
        f"มีงานในคิว {len(jobs)} งาน — แตะเลือกว่าจะ<b>{label}</b>ให้งานไหน\n"
        f"“{telegram_bot._escape(text[:60])}”",
        {"inline_keyboard": rows},
    )


def _fb_apply_pick(chat_id: str, job_id: str) -> str:
    """เอาคำสั่งที่ค้างอยู่ไปลงงานที่ผู้ใช้เพิ่งกดเลือก"""
    pending = _fb_pending_pick.pop(chat_id, None)
    if pending is None:
        return "คำสั่งนี้หมดอายุแล้ว — พิมพ์ใหม่อีกครั้ง"
    job = fb_jobs.get(job_id)
    if job is None:
        return "ไม่พบงานนี้แล้ว"
    if pending["kind"] == "caption":
        job = fb_jobs.update(job_id, caption=pending["text"]) or job
        append_log("publish", f"แก้แคปชันงาน {job_id}")
        _fb_show_card(job)
        return f"แก้ข้อความโพสต์ของ {job_id} แล้ว"
    if pending["kind"] == "comment":
        current = _fb_comments(job)
        if len(current) >= facebook_group_post.MAX_COMMENTS:
            return f"{job_id} มีคอมเมนต์ครบแล้ว — ใช้ /comment 1 หรือ 2 เพื่อแก้"
        current.append(pending["text"])
        job = _fb_set_comments(job_id, current) or job
        append_log("publish", f"ตั้งคอมเมนต์ของงาน {job_id}: {pending['text'][:60]}")
        _fb_show_card(job)
        return f"ใส่คอมเมนต์ช่อง {len(_fb_comments(job))} ให้ {job_id} แล้ว"
    when = _fb_parse_when(pending["text"])
    if when is None:
        return "อ่านเวลาไม่ออก — พิมพ์ /schedule ใหม่"
    job = fb_jobs.update(job_id, run_at=when.isoformat(timespec="seconds")) or job
    append_log("publish", f"ตั้งเวลาโพสต์งาน {job_id} เป็น {when:%d/%m %H:%M}")
    _fb_show_card(job)
    return f"ตั้งเวลา {when:%d/%m %H:%M} ให้ {job_id} แล้ว"


def _fb_pick_job(chat_id: str, argument: str) -> tuple[dict | None, str, str]:
    """เลือกงานที่คำสั่งจะไปลง คืน (งาน, ข้อความที่เหลือ, ข้อความบอกปัญหา)

    ระบุรหัสงานนำหน้าได้ เช่น <code>/comment p189874418 ข้อความ</code>
    ไม่ระบุแล้วมีงานค้างมากกว่าหนึ่ง = **ไม่เดา** ให้ตอบรายการกลับไปให้เลือก
    (เดาผิดแล้วคอมเมนต์ไปลงโพสต์อื่นเป็นเรื่องที่แก้คืนยาก)
    """
    first, _, rest = argument.partition(" ")
    first = first.strip()
    if re.fullmatch(r"p\d{4,}", first):
        job = fb_jobs.get(first)
        if job is None:
            return None, "", f"ไม่พบงาน {first}"
        if job["status"] not in fb_auto_post.OPEN_STATUSES and                 job["status"] != fb_auto_post.STATUS_RUNNING:
            return None, "", f"งาน {first} ไม่ได้อยู่ในคิวแล้ว (/queue ดูคิวปัจจุบัน)"
        return job, rest.strip(), ""

    active = [
        job for job in fb_jobs.listing()
        if (job["status"] in fb_auto_post.OPEN_STATUSES
            or job["status"] == fb_auto_post.STATUS_RUNNING)
        and (not chat_id or not job.get("chat_id") or job["chat_id"] == chat_id)
    ]
    if not active:
        return None, "", "ยังไม่มีงานที่ทำอยู่ — ส่งรูป + แคปชันเข้ามาก่อน"
    if len(active) > 1:
        # มีหลายงาน — ไม่เดา ส่งรหัสงานกลับไปให้ฝั่งเรียกทำปุ่มให้ผู้ใช้กดเลือก
        # ต้องคืน argument เดิมกลับไปด้วย ไม่งั้นข้อความที่ผู้ใช้พิมพ์มาหายทั้งก้อน
        return None, argument, "MANY:" + ",".join(job["id"] for job in active)
    return active[0], argument, ""


def _fb_comments(job: dict) -> list[str]:
    """คอมเมนต์ของงานเป็นรายการเสมอ — งานเก่าเก็บไว้เป็นข้อความเดียว"""
    items = job.get("comments")
    if isinstance(items, list) and items:
        return [str(x) for x in items][:facebook_group_post.MAX_COMMENTS]
    single = job.get("comment", "")
    return [single] if single else []


def _fb_set_comments(job_id: str, texts: list[str]) -> dict | None:
    """บันทึกคอมเมนต์ — เก็บทั้งรายการและช่องเดิมไว้ให้เข้ากันได้กับของเก่า"""
    clean = [t for t in texts if t.strip()][:facebook_group_post.MAX_COMMENTS]
    return fb_jobs.update(job_id, comments=clean, comment=clean[0] if clean else "")


def _fb_comment_images(job: dict) -> list[str]:
    """รูปแนบของคอมเมนต์ เรียงตรงช่องกับ _fb_comments() — ช่องที่ไม่มีรูปเป็น ""

    แยกจาก images ของโพสต์คนละชุด: รูปโพสต์ส่งมาตอนเปิดงาน ส่วนรูปคอมเมนต์
    ส่งมาพร้อมคำสั่ง /comment ทีหลัง
    """
    items = job.get("comment_images") or []
    out = [str(x or "") for x in items][:facebook_group_post.MAX_COMMENTS]
    while len(out) < len(_fb_comments(job)):
        out.append("")
    return out


def _fb_comment_lines(job: dict, limit: int = 150) -> list[str]:
    """บรรทัดคอมเมนต์สำหรับแสดงผล — ติด 📎 ให้ช่องที่มีรูปแนบ"""
    shots = _fb_comment_images(job)
    lines = []
    for order, text in enumerate(_fb_comments(job), 1):
        clip = shots[order - 1] if order <= len(shots) else ""
        mark = "📎" if clip else ""
        lines.append(f"💬{order}{mark} {telegram_bot._escape(text[:limit])}")
    return lines


def _fb_set_comment_image(job_id: str, slot: int, path: str) -> dict | None:
    """ผูกรูปเข้ากับคอมเมนต์ช่องที่ระบุ (slot เริ่มที่ 1)"""
    job = fb_jobs.get(job_id)
    if job is None:
        return None
    shots = _fb_comment_images(job)
    while len(shots) < slot:
        shots.append("")
    shots[slot - 1] = path
    return fb_jobs.update(job_id, comment_images=shots[:facebook_group_post.MAX_COMMENTS])


def _fb_block(prefix: str, text: str, suffix: str, limit: int = 600) -> list[str]:
    """จัดข้อความหลายบรรทัดให้อยู่ในคิวอย่างอ่านง่าย (คืน [] ถ้าไม่มีข้อความ)"""
    raw = (text or "").strip()
    if not raw:
        return []
    clipped = telegram_bot._escape(raw[:limit])
    if len(raw) > limit:
        clipped += "…"
    body = clipped.splitlines() or [clipped]
    out = [f"   {prefix}{body[0]}"]
    out += [f"   {line}" for line in body[1:]]
    out[-1] += suffix
    return out


def _fb_queue_text() -> str:
    """คิวงานที่ยังไม่ได้โพสต์ + งานที่กำลังโพสต์ — ใช้ตอบคำสั่ง /queue

    ต่างจาก /status ตรงที่ /status ดูงานล่าสุดงานเดียว ส่วนอันนี้ดูทุกงานที่ค้างอยู่
    เรียงตามคิวจริง: งานที่กำลังทำมาก่อน แล้วตามด้วยงานที่ตั้งเวลาไว้ (เวลาใกล้สุดก่อน)
    """
    pending = [
        job for job in fb_jobs.listing()
        if job["status"] in fb_auto_post.OPEN_STATUSES
        or job["status"] == fb_auto_post.STATUS_RUNNING
    ]
    if not pending:
        return (
            "📋 <b>คิวว่าง</b> — ไม่มีงานรออยู่\n"
            "ส่งรูป + แคปชันเข้ามาได้เลย"
        )

    def sort_key(job):
        running = job["status"] != fb_auto_post.STATUS_RUNNING
        return (running, job.get("run_at") or "9999", job.get("created_at", ""))

    lines = [f"📋 <b>คิวที่รออยู่</b> — {len(pending)} งาน", ""]
    for index, job in enumerate(sorted(pending, key=sort_key), 1):
        when = job.get("run_at", "")
        when_text = f" · ⏰ {_fb_when_text(when)}" if when else ""
        images = len(job.get("images") or ([job["image"]] if job.get("image") else []))
        groups = len(job.get("groups") or [])
        head = f"{index}. <b>{job['id']}</b> · "
        head += FB_STATUS_LABEL.get(job["status"], job["status"]).split(" —")[0]
        lines.append(head + when_text)
        # แคปชัน + คอมเมนต์โชว์เต็ม ไม่ตัดกลางประโยค — ตัดสั้นแล้วดูไม่ออกว่างานไหน
        # จำกัดที่ 600 ตัวอักษรต่อช่อง กันข้อความ Telegram ล้นเพดาน 4096
        lines += _fb_block("“", job.get("caption", ""), "”") or ["   (ยังไม่มีแคปชัน)"]
        detail = f"   🖼 {images} ใบ · 📦 {job.get('set') or 'ทั้งหมด'} · {groups} กลุ่ม"
        lines.append(detail)
        saved = _fb_comments(job)
        shots = _fb_comment_images(job)
        for order, item in enumerate(saved, 1):
            clip = "📎" if order <= len(shots) and shots[order - 1] else ""
            lines += _fb_block(f"💬{order}{clip} ", item, "")
        if not saved:
            lines.append("   💬 ยังไม่ได้ตั้งคอมเมนต์ (/comment)")
        if job["status"] == fb_auto_post.STATUS_RUNNING:
            lines.append(f"   ทำไปแล้ว {len(job.get('results') or [])}/{groups} กลุ่ม")
        lines.append("")
    lines.append("ยกเลิกงานที่ค้าง: /cancel · ตั้งเวลา: /schedule")
    text = "\n".join(lines)
    # Telegram รับข้อความละ 4096 ตัวอักษร — คิวยาวๆ พร้อมแคปชันเต็มมีสิทธิ์เกิน
    if len(text) > 3800:
        text = text[:3800] + "\n…(คิวยาว ตัดที่เหลือไว้ — ดูต่อในหน้าเว็บ)"
    return text


def _fb_status_text() -> str:
    """สรุปสถานะงานล่าสุด — ใช้ตอบคำสั่ง /status

    ดูจากไฟล์งานเป็นหลัก ไม่ใช่ตัวแปรในหน่วยความจำ จะได้ตรงกับของจริงแม้เพิ่งรีสตาร์ต
    """
    lines = ["📊 <b>สถานะล่าสุด</b>", ""]
    job = next(
        (j for j in fb_jobs.listing() if j.get("results") or j["status"] != "cancelled"),
        None,
    )
    if job is None:
        lines.append("ยังไม่มีงานเลย — ส่งรูป + แคปชันเข้ามาได้")
    else:
        caption = telegram_bot._escape(job.get("caption", "")[:60])
        lines.append(
            f"📮 <b>{job['id']}</b> · {FB_STATUS_LABEL.get(job['status'], job['status'])}"
        )
        lines.append(f"   “{caption}”")
        started = (job.get("started_at") or "")[11:16]
        finished = (job.get("finished_at") or "")[11:16]
        if started:
            lines.append(f"   เริ่ม {started}" + (f" · จบ {finished}" if finished else ""))
        results = job.get("results") or []
        planned = len(job.get("groups") or [])
        if job["status"] == fb_auto_post.STATUS_RUNNING:
            lines.append(f"   ทำไปแล้ว {len(results)}/{planned} กลุ่ม")
        if results:
            lines.append("")
            lines += [fb_auto_post.result_line(r, fb_groups.label) for r in results]
            total = len(results)
            counts = [
                ("โพสต์", sum(1 for r in results if r.get("posted"))),
                ("ถูกใจโพสต์", sum(1 for r in results if r.get("liked"))),
                ("คอมเมนต์", sum(1 for r in results if r.get("commented"))),
                ("ถูกใจคอมเมนต์", sum(1 for r in results if r.get("comment_liked"))),
            ]
            lines.append("")
            for label, value in counts:
                mark = "✅" if value == total else ("⚠️" if value else "❌")
                lines.append(f"{mark} {label} {value}/{total}")
            links = sum(1 for r in results if r.get("link"))
            lines.append(f"🔗 ลิงก์ที่เก็บได้ {links}/{total}")
        if job.get("comment"):
            lines.append(f"💬 คอมเมนต์ที่ตั้งไว้: {telegram_bot._escape(job['comment'][:80])}")

    lines.append("")
    lines.append("🔧 <b>เครื่อง</b>")
    live = fb_runner.running()
    lines.append("   งานที่กำลังทำ: " + (
        " · ".join(f"{device_book.label(s)} → {j}" for s, j in live.items())
        if live else "ไม่มี"))
    try:
        lines.append(f"   มือถือ: {_fb_serial()} พร้อม")
    except fb_auto_post.AutoPostError as error:
        lines.append(f"   มือถือ: ⚠️ {error}")
    enabled = len(fb_groups.enabled_ids())
    lines.append(f"   กลุ่มที่ติ๊กไว้: {enabled}/{len(fb_groups.listing())}")
    return "\n".join(lines)


def _telegram_command(chat_id: str, text: str) -> bool:
    """คืน True เมื่อจัดการคำสั่งนี้เองแล้ว"""
    command, _, argument = text.partition(" ")
    command = command.lower().split("@")[0]
    argument = argument.strip()

    if command in ("/start", "/help"):
        _fb_say(chat_id, FB_HELP)
        return True
    if command == "/caption":
        # แก้ข้อความโพสต์ของงานในคิว — เลือกงานด้วยปุ่มถ้ามีหลายคิว
        job, argument, problem = _fb_pick_job(chat_id, argument)
        if job is None:
            if problem.startswith("MANY:"):
                if not argument.strip():
                    _fb_say(chat_id, "พิมพ์ข้อความโพสต์ใหม่ต่อท้ายด้วย")
                    return True
                jobs = [fb_jobs.get(i) for i in problem[5:].split(",")]
                _fb_job_picker(chat_id, "caption", argument, [j for j in jobs if j])
                return True
            _fb_say(chat_id, problem)
            return True
        if not argument.strip():
            _fb_say(
                chat_id,
                "พิมพ์ข้อความโพสต์ใหม่ต่อท้ายด้วย เช่น\n"
                "<code>/caption ลดแรง 50% วันนี้วันเดียว</code>",
            )
            return True
        job = fb_jobs.update(job["id"], caption=argument.strip()) or job
        append_log("publish", f"แก้แคปชันงาน {job['id']}")
        _fb_show_card(job)
        _fb_say(
            chat_id,
            f"แก้ข้อความโพสต์ของงาน <b>{job['id']}</b> แล้ว\n"
            f"📝 “{telegram_bot._escape(job['caption'][:120])}”",
        )
        return True
    if command == "/comment":
        # ผูกกับงานที่ "ยังทำอยู่" เท่านั้น = ยังไม่ได้โพสต์ หรือกำลังโพสต์
        # ตั้งกลางคันได้ด้วย — กลุ่มที่เหลือจะใช้ข้อความที่เพิ่งตั้ง
        # (ตัวรันอ่านค่าใหม่ทุกกลุ่ม ไม่ได้จับค่าไว้ตั้งแต่เริ่มงาน)
        # มีหลายคิวก็ระบุได้ว่าจะเอางานไหน: /comment p189874418 ข้อความ
        job, argument, problem = _fb_pick_job(chat_id, argument)
        if job is None:
            if problem.startswith("MANY:"):
                if not argument.strip():
                    _fb_say(chat_id, "พิมพ์ข้อความที่จะคอมเมนต์ต่อท้ายด้วย")
                    return True
                jobs = [fb_jobs.get(i) for i in problem[5:].split(",")]
                _fb_job_picker(chat_id, "comment", argument, [j for j in jobs if j])
                return True
            if "ยังไม่มีงาน" in problem:
                problem += ("\nถ้าอยากคอมเมนต์โพสต์ที่ลงไปแล้ว ใช้ "
                            "<code>/followup ข้อความ</code>")
            _fb_say(chat_id, problem)
            return True
        posted_job = job["status"] == fb_auto_post.STATUS_RUNNING
        if not argument:
            _fb_say(
                chat_id,
                "พิมพ์ข้อความต่อท้ายด้วย เช่น\n"
                "<code>/comment สนใจทักแชทได้เลยค่ะ</code>\n"
                "ล้างคอมเมนต์: <code>/comment -</code>",
            )
            return True
        arg = argument.strip()
        current = _fb_comments(job)
        maximum = facebook_group_post.MAX_COMMENTS

        if arg == "-":
            job = _fb_set_comments(job["id"], []) or job
            note = "ล้างคอมเมนต์ทั้งหมดแล้ว จะไม่คอมเมนต์"
        else:
            # ระบุช่องได้: /comment 2 ข้อความ = แก้คอมเมนต์อันที่ 2
            slot_text, _, rest = arg.partition(" ")
            slot = int(slot_text) if slot_text.isdigit() and rest.strip() else 0
            text_value = rest.strip() if slot else arg
            if slot and not 1 <= slot <= maximum:
                _fb_say(chat_id, f"มีได้แค่ช่อง 1 ถึง {maximum}")
                return True
            if slot:
                while len(current) < slot:
                    current.append("")
                current[slot - 1] = text_value
                note = f"แก้คอมเมนต์ช่อง {slot} แล้ว"
            elif len(current) >= maximum:
                _fb_say(
                    chat_id,
                    f"งาน <b>{job['id']}</b> มีคอมเมนต์ครบ {maximum} ข้อความแล้ว\n"
                    "แก้ทีละช่อง: <code>/comment 1 ข้อความ</code> หรือ "
                    "<code>/comment 2 ข้อความ</code>\n"
                    "ล้างทั้งหมด: <code>/comment -</code>",
                )
                return True
            else:
                current.append(text_value)
                note = f"เพิ่มคอมเมนต์ช่อง {len(current)} แล้ว"
            job = _fb_set_comments(job["id"], current) or job

        saved = _fb_comments(job)
        append_log("publish", f"ตั้งคอมเมนต์ของงาน {job['id']}: {len(saved)} ข้อความ")
        if not posted_job:
            _fb_show_card(job)
        lines = [f"{note} — งาน <b>{job['id']}</b>"]
        lines.append(f"📝 “{telegram_bot._escape(job.get('caption', '')[:40])}…”")
        for order, item in enumerate(saved, 1):
            lines.append(f"💬{order} {telegram_bot._escape(item[:80])}")
        if posted_job:
            lines.append("(งานนี้กำลังโพสต์อยู่ — กลุ่มที่เหลือจะใช้ข้อความนี้)")
        _fb_say(chat_id, "\n".join(lines))
        return True
    if command == "/links":
        _fb_say(chat_id, _fb_links_text(argument))
        return True
    if command == "/groups":
        message, keyboard = _fb_groups_card()
        _fb_say(chat_id, message, keyboard)
        return True
    if command == "/name":
        group_id, _, name = argument.partition(" ")
        entry = fb_groups.update(parse_id := group_id.strip(), name=name.strip()[:60])
        _fb_say(
            chat_id,
            f"ตั้งชื่อกลุ่ม {parse_id} เป็น “{entry['name']}” แล้ว" if entry
            else f"ไม่พบกลุ่ม {parse_id} ในรายการ",
        )
        return True
    if command == "/sets":
        # ให้เลขลำดับคงที่ทั้งรายการ จะได้อ้างด้วยเลขตอนจัดชุด ไม่ต้องพิมพ์รหัสยาวๆ
        numbers = {g["group_id"]: i for i, g in enumerate(fb_groups.listing(), 1)}
        buckets = fb_groups.sets()
        lines = ["📦 <b>ชุดกลุ่ม</b> (ชุดละไม่เกิน "
                 f"{fb_auto_post.MAX_GROUPS_PER_POST} กลุ่ม)", ""]
        for order, (name, items) in enumerate(buckets.items(), 1):
            on = sum(1 for g in items if g.get("enabled", True))
            lines.append(
                f"📦 <b>{order}. {telegram_bot._escape(name)}</b> — "
                f"{len(items)} กลุ่ม (ติ๊กไว้ {on})"
            )
            for group in items:
                mark = "✅" if group.get("enabled", True) else "⬜"
                number = numbers.get(group["group_id"], "?")
                lines.append(
                    f"   <b>{number}.</b> {mark} {telegram_bot._escape(group['name'][:38])}"
                )
            lines.append("")
        lines.append(
            "จัดชุดใหม่ทีเดียวหลายกลุ่ม:\n"
            "<code>/newset A 1,2,3,4,5,6</code>  (ใช้เลขหน้าชื่อกลุ่ม)\n"
            "ย้ายทีละกลุ่ม: <code>/moveset &lt;เลขหรือรหัส&gt; &lt;ชื่อชุด&gt;</code>\n"
            "เปลี่ยนชื่อกลุ่มใหญ่: <code>/setname &lt;เลข📦&gt; &lt;ชื่อใหม่&gt;</code>\n"
            "หรือกดปุ่ม 📦 หน้าชื่อกลุ่มใน /groups เพื่อย้ายทีละกลุ่ม"
        )
        _fb_say(chat_id, "\n".join(lines))
        return True
    if command == "/setname":
        # อ้างกลุ่มใหญ่ด้วยเลข 📦 จาก /sets — ชื่อชุดเป็นไทยยาวๆ พิมพ์ซ้ำผิดง่าย
        number, _, new_name = argument.partition(" ")
        names = _fb_set_names()
        try:
            old = names[int(number.strip()) - 1]
        except (ValueError, IndexError):
            _fb_say(
                chat_id,
                "ใช้แบบนี้: <code>/setname 1 โปรโมชั่นเดือนนี้</code>\n"
                "เลข 📦 ดูได้จาก /sets",
            )
            return True
        try:
            moved = fb_groups.rename_set(old, new_name)
        except fb_auto_post.AutoPostError as error:
            _fb_say(chat_id, str(error))
            return True
        clean = new_name.strip()[:30]
        append_log("publish", f"เปลี่ยนชื่อกลุ่มใหญ่ “{old}” เป็น “{clean}”")
        _fb_say(
            chat_id,
            f"📦 เปลี่ยนชื่อ “{telegram_bot._escape(old)}” เป็น "
            f"<b>{telegram_bot._escape(clean)}</b> แล้ว — ย้ายตาม {moved} กลุ่มย่อย",
        )
        return True
    if command == "/newset":
        # จัดชุดทีเดียวหลายกลุ่ม: /newset A 1,2,3,4,5,6
        # อ้างด้วย "เลขลำดับ" ที่เห็นใน /sets เพราะรหัสกลุ่มยาว 15 หลัก พิมพ์ผิดง่าย
        set_name, _, picks = argument.partition(" ")
        set_name = set_name.strip()
        wanted = [p for p in re.split(r"[,\s]+", picks.strip()) if p]
        if not set_name or not wanted:
            _fb_say(
                chat_id,
                "ใช้แบบนี้: <code>/newset A 1,2,3,4,5,6</code>\n"
                f"ชุดหนึ่งใส่ได้ไม่เกิน {fb_auto_post.MAX_GROUPS_PER_POST} กลุ่ม "
                "(ดูเลขกลุ่มจาก /sets)",
            )
            return True
        if len(wanted) > fb_auto_post.MAX_GROUPS_PER_POST:
            _fb_say(
                chat_id,
                f"เลือกมา {len(wanted)} กลุ่ม — ชุดหนึ่งรับได้ไม่เกิน "
                f"{fb_auto_post.MAX_GROUPS_PER_POST} กลุ่ม",
            )
            return True

        listing = fb_groups.listing()
        done, failed = [], []
        for pick in wanted:
            group_id = ""
            if pick.isdigit() and 1 <= int(pick) <= len(listing):
                group_id = listing[int(pick) - 1]["group_id"]
            elif fb_groups.get(pick):
                group_id = pick               # พิมพ์รหัสกลุ่มมาตรงๆ ก็รับ
            if not group_id:
                failed.append(f"{pick} (ไม่พบ)")
                continue
            try:
                entry = fb_groups.assign_set(group_id, set_name)
                done.append(entry["name"][:24])
            except fb_auto_post.AutoPostError as error:
                failed.append(f"{pick} ({error})")

        lines = [f"📦 <b>ชุด {telegram_bot._escape(set_name)}</b>"]
        if done:
            lines += [f"   ✅ {telegram_bot._escape(name)}" for name in done]
        if failed:
            lines += [f"   ❌ {telegram_bot._escape(text)[:60]}" for text in failed]
        lines.append("")
        lines.append("ดูผลทั้งหมด: /sets")
        append_log("publish", f"จัดชุด {set_name}: สำเร็จ {len(done)} · พลาด {len(failed)}")
        _fb_say(chat_id, "\n".join(lines))
        return True
    if command == "/moveset":
        group_id, _, set_name = argument.partition(" ")
        try:
            entry = fb_groups.assign_set(group_id.strip(), set_name)
        except fb_auto_post.AutoPostError as error:
            _fb_say(chat_id, str(error))
            return True
        _fb_say(chat_id, f"ย้าย “{entry['name']}” ไปชุด “{entry['set']}” แล้ว")
        return True
    if command == "/schedule":
        # ระบุงานได้เหมือน /comment: /schedule p189874418 9/8 09:00
        job, argument, problem = _fb_pick_job(chat_id, argument)
        if job is None:
            if problem.startswith("MANY:"):
                if not argument.strip():
                    _fb_say(chat_id, "ใส่เวลาต่อท้ายด้วย เช่น <code>/schedule 20:30</code>")
                    return True
                jobs = [fb_jobs.get(i) for i in problem[5:].split(",")]
                _fb_job_picker(chat_id, "schedule", argument, [j for j in jobs if j])
                return True
            _fb_say(chat_id, problem)
            return True
        if argument.strip() == "-":
            fb_jobs.update(job["id"], run_at="")
            _fb_say(chat_id, "ยกเลิกเวลาที่ตั้งไว้แล้ว — ต้องกด 🚀 เอง")
            return True
        when = _fb_parse_when(argument)
        if when is None:
            _fb_say(
                chat_id,
                "ใส่เวลาแบบนี้:\n"
                "<code>/schedule 20:30</code> — วันนี้ (เลยแล้วเป็นพรุ่งนี้)\n"
                "<code>/schedule 9/8 20:30</code> — ระบุวัน\n"
                "<code>/schedule +30</code> — อีก 30 นาที\n"
                "<code>/schedule -</code> — ยกเลิก",
            )
            return True
        job = fb_jobs.update(job["id"], run_at=when.isoformat(timespec="seconds")) or job
        _fb_show_card(job)
        append_log("publish", f"ตั้งเวลาโพสต์งาน {job['id']} เป็น {when:%d/%m %H:%M}")
        _fb_say(
            chat_id,
            f"⏰ ตั้งเวลาโพสต์งาน <b>{job['id']}</b> เป็น {when:%d/%m %H:%M} แล้ว\n"
            f"ยกเลิก: <code>/schedule {job['id']} -</code>",
        )
        return True
    if command == "/queue":
        _fb_say(chat_id, _fb_queue_text())
        return True
    if command == "/claude":
        note = argument.strip()
        if not note:
            _fb_say(chat_id, *_fb_claude_menu())
            return True
        key = note.split()[0].lower()
        if key in CLAUDE_ACTIONS:
            _fb_claude_start(chat_id, key)
            return True
        # ข้อความอิสระ → ส่งเข้า Claude CLI จริง (ผู้ใช้เปิดช่องนี้เองโดยตั้งใจ)
        entry = claude_inbox_add(note)
        append_log("input", f"สั่งงาน Claude จาก Telegram: {note[:80]}")
        if not _claude_authorised(chat_id):
            _fb_say(chat_id, "🚫 แชทนี้ไม่มีสิทธิ์สั่งงาน Claude")
            return True
        if not claude_cli_ready():
            _fb_say(chat_id, f"📮 เก็บไว้ในกล่องแล้ว ({entry['id']}) — ไม่พบ Claude CLI")
            return True
        label = note.splitlines()[0][:60]
        _, reply = claude_enqueue(chat_id, label, note)
        _fb_say(chat_id, reply)
        return True
    if command == "/repost":
        # ไม่ระบุรหัส = เด้งรายการให้กดเลือก (ไม่เดาให้ — ทำซ้ำผิดโพสต์แก้คืนยาก)
        target = argument.strip()
        if not target:
            message, keyboard = _fb_repost_card()
            _fb_say(chat_id, message, keyboard)
            return True
        job, problem = _fb_clone_job(target, chat_id)
        if job is None:
            _fb_say(chat_id, problem)
            return True
        _fb_show_card(job)
        _fb_say(chat_id, f"🔁 ทำซ้ำงาน {target} → งานใหม่ <b>{job['id']}</b>")
        return True
    if command == "/status":
        _fb_say(chat_id, _fb_status_text())
        return True
    if command == "/followup":
        note = _fb_followup(argument)
        if note:
            _fb_say(chat_id, note)
        return True
    if command == "/collect":
        note = _fb_collect(argument.strip())
        if note:
            _fb_say(chat_id, note)
        return True
    if command == "/edit":
        _fb_say(chat_id, _fb_edit_command(chat_id, argument.strip()))
        return True
    if command == "/routine":
        _fb_say(chat_id, _fb_routine_command(chat_id, argument))
        return True
    if command == "/pending":
        note = argument.strip()
        if note.startswith("run"):
            _fb_say(chat_id, _fb_pending_run(note[3:].strip()))
        elif note.startswith("reset"):
            cleared = fb_pending.forget(note[5:].strip())
            _fb_say(chat_id, f"ล้างตัวนับการไล่แล้ว {cleared} รายการ")
        elif note:
            _fb_say(chat_id, _fb_pending_run(note))
        else:
            _fb_say(chat_id, _fb_pending_text())
        return True
    if command == "/report":
        days = argument.strip()
        message, keyboard = _fb_report_card(
            int(days) if days.isdigit() and 0 < int(days) <= 365
            else fb_report.DEFAULT_DAYS
        )
        _fb_say(chat_id, message, keyboard)
        return True
    if command == "/health":
        _fb_say(chat_id, _fb_health_text())
        return True
    if command == "/preview":
        # ดูตัวอย่างก่อนโพสต์ — ตอบคำถาม "รูปที่แนบไปเข้าคอมเมนต์ไหน"
        _fb_say(chat_id, _fb_preview(chat_id, argument.strip()))
        return True
    if command == "/quotafb":
        _fb_say(chat_id, _fb_quota_text())
        return True
    if command == "/clean":
        # สั่งล้างเดี๋ยวนี้โดยไม่ต้องรอเที่ยงคืน — ยังเคารพจอไม่ว่างเหมือนเดิม
        _fb_say(chat_id, _phone_clean_run() or "ล้างไม่สำเร็จ")
        return True
    if command == "/uncomment":
        # ปลดพักเอง — ไว้ใช้ตอนเปิดดูหลักฐานแล้วพบว่าไม่ได้โดนบล็อกจริง
        # (เช่น Facebook เปลี่ยนหน้าจอจนหาปุ่มส่งไม่เจอ ซึ่งต้องแก้คนละทาง)
        _fb_say(chat_id, fb_comment_guard.release() + "\n" +
                fb_comment_guard.summary_text())
        return True
    if command == "/backup":
        try:
            made = fb_backup.make_backup("manual")
            fb_backup.prune()
            _fb_say(chat_id, f"🗄 สำรองแล้ว {made['path'].name} "
                             f"({made['files']} ไฟล์ · {made['bytes'] / 1024:.0f} KB)")
        except Exception as error:
            _fb_say(chat_id, f"⚠️ สำรองไม่สำเร็จ: {telegram_bot._escape(str(error))}")
        return True
    if command == "/fiximage":
        note = _fb_fiximage(argument.strip())
        if note:
            _fb_say(chat_id, note)
        return True
    if command == "/cancel":
        # รวมงานที่ "กำลังโพสต์อยู่" ด้วย ไม่ใช่แค่งานที่ยังไม่เริ่ม —
        # ยกเลิกแล้วมือถือต้องหยุด ไม่ใช่ไล่โพสต์กลุ่มที่เหลือต่อจนครบ
        targets = [
            job["id"] for job in fb_jobs.listing()
            if job["status"] in fb_auto_post.OPEN_STATUSES
            or job["status"] == fb_auto_post.STATUS_RUNNING
        ]
        stopped = [job_id for job_id in targets if _fb_cancel_job(job_id).startswith("ยกเลิกแล้ว")]
        # ตัวรันอาจกำลังทำ "รอบตามเก็บ" ของงานที่สถานะเป็น done ไปแล้ว
        # ซึ่งไม่เข้าเงื่อนไขข้างบนเลย แต่ผู้ใช้สั่งยกเลิก = ต้องหยุดมือถือด้วย
        # (เจอจริง 11 ส.ค.: กดยกเลิกตอนรอบตามเก็บรันอยู่แล้วไม่มีอะไรเกิดขึ้น
        #  เพราะการ์ดของงาน done ไม่มีปุ่ม และ /cancel ก็มองไม่เห็นงานนี้)
        # หยุดให้ครบทุกเครื่อง ไม่ใช่แค่เครื่องเดียว — ผู้ใช้พิมพ์ /cancel
        # แปลว่า "หยุดทั้งหมด" ถ้าหยุดไปเครื่องเดียวอีกเครื่องจะโพสต์ต่อเงียบๆ
        halted = fb_runner.stop_all()
        for _serial, _job in halted:
            append_log("publish", f"[{_job}] ผู้ใช้สั่งยกเลิก — "
                                  f"สั่งหยุดตัวรันบน {device_book.label(_serial)}")
        _fb_say(
            chat_id,
            (f"ยกเลิกแล้ว {len(targets)} งาน" if targets else "ไม่มีงานค้างในคิว")
            + ("\n⏹ สั่งหยุดงานที่กำลังทำบนมือถือแล้ว — หยุดหลังกลุ่มที่ทำอยู่จบ"
               if (stopped or halted) else ""),
        )
        return True
    if command == "/stop":
        _fb_say(
            chat_id,
            (lambda done: f"สั่งหยุดแล้ว {len(done)} เครื่อง — "
                          "จะหยุดหลังกลุ่มที่กำลังทำอยู่จบ" if done
                          else "ตอนนี้ไม่มีงานกำลังโพสต์อยู่")(fb_runner.stop_all()),
        )
        return True
    return False


def _fb_brand_new_set() -> str:
    """ชื่อกลุ่มใหญ่ที่ยัง**ไม่มีอยู่เลย**

    ต่างจาก next_free_set() ที่คืนชุดที่ยังไม่เต็ม — ปุ่ม "กลุ่มใหญ่ใหม่" ต้องได้
    ชุดเปล่าจริงๆ ไม่ใช่ไปแทรกในชุดเดิมที่ยังมีที่ว่าง
    """
    used = set(fb_groups.sets().keys())
    index = 1
    while f"ชุด {index}" in used:
        index += 1
    return f"ชุด {index}"


def _fb_group_button(chat_id: str, action: str, rest: str, callback: dict) -> str:
    """ปุ่มทั้งหมดบนการ์ด /groups รวมช่องกลุ่มใหญ่ด้านหน้า

    ทุกทางจบด้วยการแก้ข้อความเดิมให้เป็นการ์ดล่าสุด ผู้ใช้จะได้ไม่ต้องพิมพ์
    /groups ใหม่ทุกครั้งที่กด
    """
    render, args, note = _fb_groups_card, (), ""
    if action == "gd":
        note = "ลบแล้ว" if fb_groups.remove(rest) else "ไม่พบกลุ่มนี้"
    elif action == "ge":
        entry = fb_groups.toggle(rest)
        note = ("เปิดใช้" if entry.get("enabled") else "ปิดไว้") if entry else "ไม่พบกลุ่มนี้"
    elif action == "gs":
        render, args, note = _fb_set_picker_card, (rest,), "เลือกกลุ่มใหญ่"
    elif action == "gsb":
        note = "กลับรายการกลุ่ม"
    elif action == "gsn":
        try:
            entry = fb_groups.assign_set(rest, _fb_brand_new_set())
            note = f"ย้ายไป “{entry.get('set')}” แล้ว"
        except fb_auto_post.AutoPostError as error:
            note = str(error)[:180]
    elif action == "gsm":
        group_id, _, number = rest.partition(":")
        names = _fb_set_names()
        try:
            target = names[int(number) - 1]
        except (ValueError, IndexError):
            return "กลุ่มใหญ่นี้หายไปแล้ว — กด /groups ใหม่"
        try:
            fb_groups.assign_set(group_id, target)
            note = f"ย้ายไป “{target}” แล้ว"
        except fb_auto_post.AutoPostError as error:
            note = str(error)[:180]

    text, keyboard = render(*args)
    message = callback.get("message") or {}
    token, _ = _fb_telegram()
    if token and message.get("message_id"):
        try:
            telegram_bot.edit_message(
                token, chat_id, message["message_id"], text, keyboard
            )
        except telegram_bot.TelegramError as error:
            append_log("publish", f"อัปเดตการ์ดกลุ่มไม่สำเร็จ: {error}")
    return note


def _telegram_callback(chat_id: str, data: str, callback: dict) -> str:
    """ปุ่มทั้งหมดที่ขึ้นต้นด้วย fb: — คืนข้อความสั้นๆ ให้เด้งบนปุ่ม"""
    action, _, rest = data.partition(":")

    if action in ("ge", "gd", "gs", "gsm", "gsn", "gsb"):
        return _fb_group_button(chat_id, action, rest, callback)

    if action == "cl":
        return _fb_claude_start(chat_id, rest)

    if action == "ri":
        return _fb_report_images(chat_id, rest)

    if action == "ed":
        note = _fb_edit_start(chat_id, rest)
        _fb_say(chat_id, note)
        return "เปิดแก้แล้ว"

    if action == "rp":
        job, problem = _fb_clone_job(rest, chat_id)
        if job is None:
            return problem[:180]
        _fb_show_card(job)
        return f"ทำซ้ำเป็นงาน {job['id']} แล้ว"

    if action == "pick":
        return _fb_apply_pick(chat_id, rest)
    if action == "pickx":
        _fb_pending_pick.pop(chat_id, None)
        return "ยกเลิกแล้ว"
    if action == "set":
        job_id, _, set_name = rest.partition(":")
        job = fb_jobs.get(job_id)
        if job is None:
            return "ไม่พบงานนี้แล้ว"
        picked = fb_groups.enabled_ids(set_name)
        job = fb_jobs.update(job_id, set=set_name, groups=picked) or job
        _fb_show_card(job)
        return f"ใช้ชุด “{set_name}” — {len(picked)} กลุ่ม"

    job_id, _, group_id = rest.partition(":")
    job = fb_jobs.get(job_id)
    if job is None:
        return "ไม่พบงานนี้แล้ว"
    # "x" (ยกเลิก) ต้องผ่านด่านนี้ด้วย — งานที่กำลังโพสต์อยู่ไม่ได้อยู่ใน
    # OPEN_STATUSES ถ้าตีกลับตรงนี้ ปุ่มยกเลิกจะใช้ไม่ได้ตอนที่จำเป็นที่สุด
    if job["status"] not in fb_auto_post.OPEN_STATUSES and action not in ("go", "x"):
        return "งานนี้ปิดไปแล้ว"

    note = ""
    if action == "t":
        selected = list(job.get("groups") or [])
        if group_id in selected:
            selected.remove(group_id)
            note = "ไม่โพสต์กลุ่มนี้"
        elif len(selected) >= fb_auto_post.MAX_GROUPS_PER_POST:
            return f"เลือกได้ไม่เกิน {fb_auto_post.MAX_GROUPS_PER_POST} กลุ่มต่อครั้ง"
        else:
            selected.append(group_id)
            note = "จะโพสต์กลุ่มนี้"
        job = fb_jobs.update(job_id, groups=selected) or job
    elif action == "all":
        picked = fb_groups.enabled_ids(job.get("set", ""))
        job = fb_jobs.update(job_id, groups=picked) or job
        note = f"เลือก {len(picked)} กลุ่ม (สูงสุด {fb_auto_post.MAX_GROUPS_PER_POST})"
    elif action == "none":
        job = fb_jobs.update(job_id, groups=[]) or job
        note = "ล้างการเลือกแล้ว"
    elif action == "x":
        note = _fb_cancel_job(job_id)
        job = fb_jobs.get(job_id) or job
    elif action == "go":
        note = _fb_run_job(job_id) or "เริ่มโพสต์แล้ว"
        job = fb_jobs.get(job_id) or job
    _fb_show_card(job)
    return note


# --------------------------------------------------------------- ลงมือโพสต์


def _fb_warn_comment_quota(job: dict, groups: list[str], serial: str = "") -> str:
    """เตือนถ้าโควตาคอมเมนต์ไม่พอสำหรับงานนี้ — เตือนอย่างเดียว ไม่ห้ามโพสต์

    **ต้องรับ serial ของเครื่องที่จะโพสต์จริง** โควตาคอมเมนต์นับแยกรายบัญชี และ
    หนึ่งเครื่อง = หนึ่งบัญชี ถ้าไปหยิบเครื่องตัวหลักมาเสมอ เครื่องที่สองจะถูกเตือน
    ด้วยโควตาของเครื่องแรก — เตือนผิดคนทั้งสองทาง (ห้ามทั้งที่ยังมีโควตา หรือ
    ปล่อยผ่านทั้งที่เต็มแล้ว)
    """
    per_post = len(_fb_comments(job))
    if not per_post:
        return ""
    account = str(serial or "").strip()
    if not account:
        try:
            account = _fb_serial()
        except fb_auto_post.AutoPostError:
            account = ""
    note = fb_comment_guard.plan_shortfall(len(groups) * per_post, account=account)
    if not note:
        return ""
    append_log("publish", f"[{job['id']}] {note}")
    _fb_say(job.get("chat_id", ""), note + "\n<i>เติมทีหลังได้ด้วย "
            f"<code>/followup {job['id']}</code></i>")
    return note


def _fb_run_job(job_id: str, queued: bool = False) -> str:
    """ตรวจความพร้อมแล้วสั่งรัน — คืนข้อความบอกผลการสั่ง (ว่าง = เริ่มแล้ว)"""
    job = fb_jobs.get(job_id)
    if job is None:
        return "ไม่พบงานนี้"
    if job["status"] == fb_auto_post.STATUS_RUNNING:
        return "งานนี้กำลังโพสต์อยู่แล้ว"
    # จอของเครื่องนั้นมีเจ้าเดียว — ไม่ว่างก็เข้าคิวรอ ไม่ปฏิเสธทิ้ง
    # (คิวแยกรายเครื่อง งานของเครื่องที่ว่างจึงไม่ต้องรอคิวของเครื่องที่ยุ่ง)
    serial, note = _fb_gate("post", job, queued, str(job.get("serial") or ""))
    if note:
        return note
    if not job.get("caption", "").strip():
        return "ยังไม่มีแคปชัน"
    images = [Path(p) for p in (job.get("images") or [job.get("image", "")]) if p]
    images = [p for p in images if p.is_file()][:facebook_group_post.MAX_PHOTOS]
    if not images:
        return "ยังไม่มีรูป หรือไฟล์รูปหาย"
    image = images if len(images) > 1 else images[0]
    groups = [g for g in (job.get("groups") or []) if g]
    if not groups:
        return "ยังไม่ได้เลือกกลุ่มสักกลุ่ม"
    # เตือนเรื่องโควตาคอมเมนต์ **ก่อนออกตัว** ไม่ใช่ไปตันทีละกลุ่มกลางทาง
    _fb_warn_comment_quota(job, groups, serial)
    if len(groups) > fb_auto_post.MAX_GROUPS_PER_POST:
        # โพสต์รัวหลายกลุ่มเกินไปเข้าข่ายสแปม — กันที่นี่อีกชั้นเผื่อเลือกมาเกิน
        return (
            f"เลือกไว้ {len(groups)} กลุ่ม — ครั้งเดียวโพสต์ได้ไม่เกิน "
            f"{fb_auto_post.MAX_GROUPS_PER_POST} กลุ่ม เอาออกก่อน"
        )

    chat_id = job.get("chat_id", "")

    # เตือนถ้าเพิ่งโพสต์กลุ่มเดิมไปไม่นาน — โพสต์ถี่คือทางตรงสู่การโดนตีธงสแปม
    #
    # **เตือนอย่างเดียว ไม่ห้าม** เพราะบางทีตั้งใจโพสต์ซ้ำจริง (แก้รูปผิดแล้วลงใหม่)
    # การข้ามกลุ่มให้เองเงียบๆ จะกลายเป็น "โพสต์ไม่ครบโดยไม่มีใครรู้" ซึ่งแย่กว่า
    duplicate = fb_preflight.check_duplicate(
        fb_jobs.listing(), groups, label=fb_groups.label, skip_job=job_id,
    )
    if not duplicate.ok:
        append_log("publish", f"[{job_id}] เตือนโพสต์ซ้ำ — {duplicate.detail}")
        _fb_say(chat_id, f"⚠️ <b>เพิ่งโพสต์กลุ่มนี้ไปไม่นาน</b>\n"
                         f"{telegram_bot._escape(duplicate.detail)}\n"
                         f"<i>โพสต์ถี่เกินเสี่ยงโดนตีธง — เริ่มให้ตามที่สั่ง</i>")

    def on_log(line: str) -> None:
        append_log("publish", f"[{job_id}] {line}")
        fb_jobs.append_log(job_id, line)

    def on_result(entry: dict) -> None:
        _fb_stamp_post_id(entry)
        fb_jobs.upsert_result(job_id, entry)
        changes = {
            "last_result": (
                "โพสต์แล้ว" if entry.get("posted") else entry.get("error", "ไม่สำเร็จ")
            ),
            "last_run": datetime.now().isoformat(timespec="seconds"),
        }
        if entry.get("link"):
            changes["last_link"] = entry["link"]
        fb_groups.update(entry.get("group_id", ""), **changes)
        current = fb_jobs.get(job_id)
        if current:
            _fb_show_card(current)      # การ์ดใบเดิมโชว์สถานะรวมล่าสุด
        # อัปเดตความคืบหน้าเข้าแชททันทีที่กลุ่มนี้จบ
        # รอบตรวจซ้ำ (final) ไม่ส่งซ้ำ — สรุปท้ายงานมีข้อมูลรอบนั้นครบอยู่แล้ว
        if entry.get("final"):
            return
        step = f"[{entry['index']}/{entry['total']}] " if entry.get("index") else ""
        _fb_say(chat_id, step + fb_auto_post.result_line(entry, fb_groups.label))

    def on_done(results: list[dict], error: str) -> None:
        status = fb_auto_post.STATUS_FAILED if error else fb_auto_post.STATUS_DONE
        current = fb_jobs.update(
            job_id, status=status, results=results,
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )
        if current:
            _fb_show_card(current)
        summary = fb_auto_post.summarize(results, fb_groups.label)
        posted = sum(1 for r in results if r.get("posted"))
        chain = bool(posted) and not fb_runner.for_device(serial).stop_flag.is_set()
        delay = _fb_followup_delay(results)
        held = delay > AUTO_FOLLOWUP_DELAY      # ไม่เห็นโพสต์เลย = รออนุมัติ
        _fb_say(chat_id, f"🏁 <b>งาน {job_id} จบแล้ว</b>\n{summary}" + (
            f"\n\n⚠️ {telegram_bot._escape(error)}" if error else ""
        ) + (
            (f"\n\n⏳ โพสต์ยังไม่ปรากฏในฟีดสักกลุ่ม — น่าจะรอผู้ดูแลอนุมัติ\n"
             f"จะไล่หาจากแจ้งเตือนอีกครั้งในอีก {delay / 60:.0f} นาที"
             if held else
             f"\n\n🔎 อีก {delay:.0f} วินาทีจะไล่หาโพสต์จากแจ้งเตือน "
             "แล้วกดถูกใจ/คอมเมนต์ให้เอง") if chain else ""
        ))
        append_log("publish", f"[{job_id}] จบงาน — {status}")
        # โพสต์ในฟีดหาโพสต์ตัวเองเจอยาก (ฟีดเรียงตามความเกี่ยวข้อง) ทางแจ้งเตือน
        # แม่นกว่ามาก จึงต่อสายไปทำต่อให้เลย ไม่ต้องรอผู้ใช้พิมพ์ /followup
        # ผู้ใช้สั่งหยุด/ยกเลิกไว้ = ไม่ต่อ
        if chain:
            _fb_auto_followup(job_id, delay, serial)

    class Clipboard:
        """อ่าน/เขียนคลิปบอร์ดมือถือผ่านช่อง scrcpy เดิมที่มีอยู่แล้ว

        `adb shell service call clipboard` ใช้ไม่ได้ตั้งแต่ Android 10
        (คืนค่าว่างเสมอเมื่อแอปที่เรียกไม่ได้อยู่หน้าจอ)
        เขียนได้ด้วยเพื่อวาง "ค่าเฝ้า" ก่อนกดคัดลอก — จะได้รู้ว่าคัดลอกติดจริงไหม
        """

        @staticmethod
        def drain() -> None:
            scrcpy_control.drain_clipboard(ADB, serial)

        @staticmethod
        def wait_change(timeout: float = 8.0) -> str:
            return scrcpy_control.wait_clipboard(ADB, serial, timeout)

        @staticmethod
        def read() -> str:
            return scrcpy_control.get_clipboard(ADB, serial)

    try:
        fb_runner.for_device(serial).start(
            job={**job, "groups": groups}, adb=ADB, serial=serial, image=image,
            gap_range=_fb_gap_range(serial), on_log=on_log, on_result=on_result,
            on_done=on_done, clipboard=Clipboard,
            # ส่งเป็นฟังก์ชัน ไม่ใช่ค่าคงที่ — ผู้ใช้พิมพ์ /comment กลางคันได้
            comment=lambda: _fb_comments(fb_jobs.get(job_id) or {}),
            comment_images=lambda: _fb_comment_images(fb_jobs.get(job_id) or {}),
        )
    except fb_auto_post.AutoPostError as error:
        return str(error)

    fb_jobs.update(
        job_id, status=fb_auto_post.STATUS_RUNNING, results=[], serial=serial,
        started_at=datetime.now().isoformat(timespec="seconds"),
    )
    append_log("publish", f"[{job_id}] เริ่มโพสต์ {len(groups)} กลุ่ม ด้วย {serial}")
    _fb_say(
        chat_id,
        f"🚀 <b>เริ่มโพสต์ {len(groups)} กลุ่ม</b>\n"
        f"เว้นระยะ {int(_fb_gap_range()[0])}–{int(_fb_gap_range()[1])} วินาทีต่อกลุ่ม "
        f"— จะรายงานทีละกลุ่มที่นี่",
    )
    return ""


approval_watcher.on_photo = _telegram_photo
approval_watcher.on_text = _telegram_text
approval_watcher.on_command = _telegram_command
approval_watcher.on_callback = _telegram_callback


# บอทเจนคลิปย้ายไปอยู่ที่ clip_app.py (พอร์ต 8877) แล้ว
#
# เหตุผล: งานสายคลิปกินเวลาเป็นนาทีและต้องรีสตาร์ตบ่อยตอนพัฒนา ทุกครั้งที่
# รีสตาร์ตรวมกัน บอทโพสต์ Facebook กับจอมือถือจะตายไปด้วยทั้งที่ไม่เกี่ยวกัน
#
# ไฟล์นี้ยังเก็บ clip_watcher ไว้ให้หน้าตั้งค่าใช้ตรวจ/บันทึกโทเคนบอทคลิปได้
# แต่ **ห้าม start()** เด็ดขาด — getUpdates ของหนึ่งโทเคนมีตัวอ่านได้ตัวเดียว
# ถ้าสองโปรเซสอ่านพร้อมกันจะได้ 409 Conflict แล้วข้อความหายสลับไปมา


@app.get("/api/fb/groups")
async def fb_list_groups() -> dict:
    settings = _fb_settings()
    # บอทหลักไม่มีโทเคน = งานจาก Telegram จะไม่เข้าเลย และจะ "เงียบ" แบบไม่มีอะไรฟ้อง
    # (เจอจริง: ผู้ใช้ส่งอัลบั้ม + /schedule ไปแล้วไม่มีอะไรตอบ เพราะไฟล์โทเคนหายไป)
    bot_ready = bool(_fb_telegram()[0] and _fb_telegram()[1])
    return {
        "ok": True,
        "bot_ready": bot_ready,
        "groups": fb_groups.listing(),
        "gap_min": settings.get("gap_min", 15),
        "gap_max": settings.get("gap_max", 20),
        "auto_start": bool(settings.get("auto_start")),
        # ค่าตั้งต้นเปิด — ไม่ได้ตั้งไว้ต้องแปลว่า "เปิด" ไม่ใช่ "ปิด"
        "phone_clean": bool(settings.get("phone_clean", True)),
        "screen_saver": bool(settings.get("screen_saver", True)),
        "serial": settings.get("serial", ""),
        "running": fb_runner.any_busy(),
        "running_on": fb_runner.running(),
    }


@app.post("/api/fb/groups")
async def fb_add_group(request: Request) -> dict:
    payload = await request.json()
    try:
        # ลิงก์ย่อต้องยิงเน็ตไปถามปลายทาง — ทำใน thread ห้ามบล็อก event loop
        entry = await asyncio.to_thread(
            fb_groups.add, str(payload.get("link", "")), str(payload.get("name", ""))
        )
    except fb_auto_post.AutoPostError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    append_log("publish", f"เพิ่มกลุ่ม {entry['group_id']} ({entry['name']})")
    return {"ok": True, "group": entry, "groups": fb_groups.listing()}


@app.post("/api/fb/groups/{group_id}")
async def fb_update_group(group_id: str, request: Request) -> dict:
    payload = await request.json()
    changes: dict = {}
    if "name" in payload:
        changes["name"] = str(payload["name"]).strip()[:60]
    if "enabled" in payload:
        changes["enabled"] = bool(payload["enabled"])
    entry = fb_groups.update(group_id, **changes)
    if entry is None:
        raise HTTPException(status_code=404, detail="ไม่พบกลุ่มนี้")
    return {"ok": True, "group": entry}


@app.delete("/api/fb/groups/{group_id}")
async def fb_delete_group(group_id: str) -> dict:
    if not fb_groups.remove(group_id):
        raise HTTPException(status_code=404, detail="ไม่พบกลุ่มนี้")
    append_log("publish", f"ลบกลุ่ม {group_id} ออกจากรายการ")
    return {"ok": True, "groups": fb_groups.listing()}


@app.get("/api/claude/inbox")
async def claude_inbox_read(
    unread_only: bool = True, mark: bool = False, channel: str = "",
) -> dict:
    """อ่านข้อความที่ฝากไว้ให้ Claude — ใช้ตอน Claude เข้ามาเช็คงานที่ค้าง

    ระบุ channel เพื่อเอาเฉพาะสายงานของตัวเอง (post / clip) ไม่ระบุ = เอาหมด
    """
    items = claude_inbox()
    if channel:
        items = [i for i in items if (i.get("channel") or "post") == channel]
    if unread_only:
        items = [i for i in items if not i.get("read")]
    marked = claude_inbox_mark_read(channel) if mark else 0
    return {"ok": True, "count": len(items), "marked": marked, "messages": items}


@app.post("/api/claude/inbox")
async def claude_inbox_write(request: Request) -> dict:
    payload = await request.json()
    text = str((payload or {}).get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="ต้องมีข้อความ")
    return {"ok": True, "entry": claude_inbox_add(
        text,
        str((payload or {}).get("source", "web")),
        str((payload or {}).get("channel", "post")),
    )}


@app.post("/api/fb/followup")
async def fb_followup(request: Request) -> dict:
    """สั่งรอบตามเก็บ (ถูกใจ + คอมเมนต์) แบบเดียวกับคำสั่ง /followup ในบอท

    มีไว้ให้หน้าเว็บและการทดสอบเรียกได้ ไม่ต้องพิมพ์ในแชทอย่างเดียว
    """
    payload = await request.json() if await request.body() else {}
    # รับรหัสงานได้ด้วย — ไม่งั้นสั่งตามเก็บงานที่ต้องการไม่ได้เลย
    # (ของเดิมเลือก "งานล่าสุดที่มีผลลัพธ์" ให้เสมอ ซึ่งมักไม่ใช่ใบที่ตั้งใจ)
    note = await asyncio.to_thread(
        _fb_followup, str((payload or {}).get("comment", "")),
        str((payload or {}).get("job_id", "")),
    )
    return {"ok": True, "note": note}


@app.post("/api/fb/settings")
async def fb_save_settings(request: Request) -> dict:
    """บันทึกค่าตั้งสายโพสต์ — ส่ง `serial` มาด้วย = บันทึกให้เครื่องนั้นเครื่องเดียว

    ไม่ส่ง serial = แก้ค่ากลางของระบบ ซึ่งเครื่องที่ยังไม่ได้ตั้งค่าเองจะใช้ตาม
    เครื่องที่ตั้งค่าเองไว้แล้วจะไม่ถูกกระทบ — เป็นกติกาเดียวกับที่ `devices.settings()`
    ใช้ ทำให้เพิ่มค่าตั้งใหม่ทีหลังแยกรายเครื่องได้เองโดยไม่ต้องแก้ตรงนี้อีก
    """
    payload = await request.json()
    serial = str(payload.get("serial") or "").strip()
    changes: dict = {}
    if "gap_min" in payload:
        changes["gap_min"] = max(5, int(payload.get("gap_min") or 15))
    if "gap_max" in payload:
        changes["gap_max"] = max(5, int(payload.get("gap_max") or 20))
    for key in ("auto_start", "phone_clean", "screen_saver"):
        if key in payload:
            changes[key] = bool(payload[key])

    if serial and payload.get("per_device"):
        # ค่าของเครื่องเดียว — ต้องเทียบเว้นระยะกับค่าที่เครื่องนั้นใช้จริง
        # ไม่ใช่ค่ากลาง ไม่งั้นตั้งขั้นต่ำ 30 บนเครื่องที่ขั้นสูงเป็น 20 แล้วผ่านไปได้
        merged = {**device_book.settings(serial), **changes}
        if merged.get("gap_min", 15) > merged.get("gap_max", 20):
            changes["gap_max"] = merged["gap_min"]
        try:
            live = await asyncio.to_thread(device_book.set_settings, serial, changes)
        except device_book.DeviceError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"ok": True, "serial": serial, **live}

    config = load_config()
    settings = config.get("facebook") or {}
    settings.update(changes)
    # เว้นระยะขั้นต่ำต้องไม่มากกว่าขั้นสูง ไม่งั้นสุ่มค่าไม่ได้
    if settings.get("gap_min", 15) > settings.get("gap_max", 20):
        settings["gap_max"] = settings["gap_min"]
    if "serial" in payload:
        # ของเดิมเก็บ "เครื่องตัวหลัก" ไว้ที่นี่ — ย้ายไปเป็นของทะเบียนแล้ว แต่ยัง
        # เขียนค่าเดิมไว้ด้วยจนกว่าจะแน่ใจว่าไม่มีใครอ่านที่เก่าอยู่
        settings["serial"] = serial
        if serial:
            try:
                await asyncio.to_thread(device_book.set_default, serial)
            except device_book.DeviceError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
    config["facebook"] = settings
    save_config(config)
    return {"ok": True, **settings}


@app.get("/api/fb/jobs")
async def fb_list_jobs() -> dict:
    jobs = fb_jobs.listing()[:10]
    return {
        "ok": True,
        "running": fb_runner.any_busy(),
        "running_on": fb_runner.running(),
        "jobs": [
            {
                **job,
                "has_image": bool(job.get("image")) and Path(job["image"]).is_file(),
                "group_names": [fb_groups.label(g) for g in (job.get("groups") or [])],
            }
            for job in jobs
        ],
    }


@app.get("/api/fb/jobs/{job_id}/image")
async def fb_job_image(job_id: str) -> FileResponse:
    # โชว์ใบแรกเป็นตัวแทนงาน — ใบที่เหลืออยู่ในโฟลเดอร์เดียวกัน
    job = fb_jobs.get(job_id)
    if job is None or not job.get("image"):
        raise HTTPException(status_code=404, detail="งานนี้ยังไม่มีรูป")
    path = Path(job["image"])
    # กันชี้ออกนอกโฟลเดอร์ที่เก็บรูปงาน — path มาจากไฟล์ที่แก้ด้วยมือได้
    if path.parent.resolve() != FB_POST_DIR.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์รูปของงานนี้")
    return FileResponse(path)


@app.post("/api/fb/jobs/{job_id}/run")
async def fb_run(job_id: str) -> dict:
    note = await asyncio.to_thread(_fb_run_job, job_id)
    if note:
        raise HTTPException(status_code=400, detail=note)
    return {"ok": True, "message": "เริ่มโพสต์แล้ว — ดูความคืบหน้าที่ log"}


@app.post("/api/fb/jobs/{job_id}/cancel")
async def fb_cancel(job_id: str) -> dict:
    # ใช้ตัวเดียวกับปุ่มยกเลิกใน Telegram — ตั้งสถานะ **และ** สั่งหยุดตัวรัน
    #
    # ของเดิมถ้าสถานะเป็น running จะสั่ง stop() แล้ว return ทันที ไม่เคยตั้งเป็น
    # cancelled เลย พองานที่ตัวรันตายไปแล้วแต่สถานะค้างที่ running จะยกเลิก
    # ยังไงก็ไม่หลุด ค้างตลอดกาล (เจอจริง 12 ส.ค. งาน p545241529)
    if fb_jobs.get(job_id) is None:
        raise HTTPException(status_code=404, detail="ไม่พบงานนี้")
    return {"ok": True, "message": _fb_cancel_job(job_id)}


# ดึงข้อมูลสินค้าจากลิงก์ Shopee — ใช้ร่วมกันทั้งหน้าเว็บและบอท Telegram
# หนึ่งเบราว์เซอร์หนึ่งโปรไฟล์ จึงทำได้ทีละงาน ไม่งั้นสองงานแย่งหน้าต่างกัน
# ตัวดึงข้อมูล Shopee ย้ายไป shopee_service.py แล้ว — ใช้ร่วมกับ clip_app.py
#
# และเปลี่ยนจาก threading.Lock มาเป็น studio_shared.browser_lock() ซึ่งเป็น
# ล็อกระดับไฟล์ กันข้ามโปรเซสได้จริง — พอแยกสายคลิปออกไปเป็นคนละโปรเซส
# ล็อกในโปรเซสเดียวกันไม่ได้ป้องกันอะไรอีกต่อไป ทั้งสองฝั่งจะเปิด Chrome
# โปรไฟล์เดียวกันพร้อมกันแล้วไล่หน้าต่างกันเอง


@app.post("/api/shopee/fetch")
async def shopee_fetch(request: Request) -> dict:
    """ดึงชื่อ + รายละเอียด + รูปทั้งหมด จากลิงก์สินค้า Shopee ที่ผู้ใช้วางมา

    เปิดเบราว์เซอร์จริงเพราะ Shopee ปิด API ภายในไว้ — งานนี้กินเวลาหลายสิบวินาที
    จึงทำใน thread แยก ไม่ให้บล็อก event loop ทั้งเซิร์ฟเวอร์
    """
    payload = await request.json()
    link = str(payload.get("link", "")).strip()
    if not link:
        raise HTTPException(status_code=400, detail="วางลิงก์ Shopee ก่อน")

    want_all = bool(payload.get("all_images", False))

    def work() -> dict:
        return shopee_collect(link, want_all)

    def send_for_approval(data: dict) -> dict:
        if not data.get("highlights"):
            return {}
        return request_approval(
            data["name"], data["highlights"],
            extra={"item_id": data["item_id"], "url": data["url"]},
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as error:
        # แยกกรณี "ยังไม่ล็อกอิน" ออกมาให้ชัด ผู้ใช้จะได้รู้ว่าต้องทำอะไรต่อ
        status = 409 if type(error).__name__ == "ShopeeNeedsLogin" else 502
        append_log("input", f"ดึงข้อมูล Shopee ไม่สำเร็จ: {error}")
        raise HTTPException(status_code=status, detail=str(error)) from error

    append_log(
        "input",
        f"ดึงข้อมูลสินค้าแล้ว: {result['name'][:60]} · รูป {len(result['saved_images'])} ใบ",
    )
    # ส่งไปขออนุมัติหลังตอบข้อมูลพร้อมแล้ว ถ้าส่งไม่ออกก็ยังได้ข้อมูลครบอยู่ดี
    if load_config().get("telegram_auto_send", True):
        result["approval"] = await asyncio.to_thread(send_for_approval, result)
    return {"ok": True, **result}


@app.post("/api/shopee/stock")
async def shopee_stock(request: Request) -> dict:
    """เช็คว่าสินค้าจากลิงก์ Shopee ยังมีของอยู่ไหม

    ส่ง links เป็นรายการได้ เช็คทีเดียวหลายตัว — เปิดเบราว์เซอร์รอบเดียวคุ้มกว่า
    """
    payload = await request.json()
    raw = payload.get("links") or payload.get("link") or ""
    links = [raw] if isinstance(raw, str) else list(raw)
    links = [str(item).strip() for item in links if str(item).strip()]
    if not links:
        raise HTTPException(status_code=400, detail="วางลิงก์ Shopee ก่อน")

    def work() -> list[dict]:
        import shopee_scrape
        from flow_worker import open_browser

        def say(message: str) -> None:
            append_log("input", message)

        results = []
        for link in links:
            try:
                results.append(shopee_scrape.read_stock(link, open_browser, log=say))
            except Exception as error:
                # ลิงก์เดียวพังต้องไม่ล้มทั้งชุด — บอกไปว่าตัวไหนอ่านไม่ได้
                results.append({
                    "url": link, "in_stock": None,
                    "reason": str(error), "error": type(error).__name__,
                })
        return results

    results = await asyncio.to_thread(work)
    gone = [r for r in results if r.get("in_stock") is False]
    if gone:
        append_log("input", f"ของหมด {len(gone)} รายการจาก {len(results)}")
    return {
        "ok": True,
        "items": results,
        "in_stock": sum(1 for r in results if r.get("in_stock") is True),
        "out_of_stock": len(gone),
        "unknown": sum(1 for r in results if r.get("in_stock") is None),
    }


@app.post("/api/chatgpt/prompts")
async def chatgpt_prompts(request: Request) -> dict:
    """ขั้นกลางของผัง — ส่งรูป + จุดขายเข้า ChatGPT แล้ว copy prompt ออกมา 2 ชุด

    ทำใน thread แยกเพราะขับเบราว์เซอร์ กินเวลาหลายนาที
    """
    payload = await request.json()
    product = str(payload.get("product", "")).strip()
    highlights = [str(h).strip() for h in payload.get("highlights", []) if str(h).strip()]
    images = [Path(p) for p in payload.get("images", []) if Path(p).is_file()]
    gpt_url = str(payload.get("gpt_url", "")).strip() or load_config().get("chatgpt_url", "")
    if not product or not highlights:
        raise HTTPException(status_code=400, detail="ต้องมีชื่อสินค้าและจุดขายก่อน")

    def work() -> dict:
        import chatgpt_driver
        from flow_worker import open_browser

        return chatgpt_driver.run_stage(
            open_browser, gpt_url, product, highlights, images,
            log=lambda message: append_log("gems", message),
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as error:
        status = 409 if type(error).__name__ == "ChatGPTNeedsLogin" else 502
        append_log("gems", f"ขั้น ChatGPT ไม่สำเร็จ: {error}")
        raise HTTPException(status_code=status, detail=str(error)) from error

    # "Copy prompt เก็บไว้" ในผัง — เก็บลงไฟล์ไว้ใช้ต่อ ไม่ให้หายไปกับหน้าเว็บ
    store = DATA_DIR / "prompts"
    store.mkdir(parents=True, exist_ok=True)
    target = store / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    target.write_text(
        json.dumps({"product": product, **result}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result["saved_to"] = str(target)
    append_log(
        "gems",
        f"เก็บ prompt แล้ว — เจนรูป {len(result['image_prompts'])} อัน "
        f"· เจนวิดีโอ {len(result['video_prompts'])} อัน",
    )
    return {"ok": True, **result}


@app.get("/api/shopee/image")
async def shopee_image(path: str) -> FileResponse:
    """เสิร์ฟรูปสินค้าที่โหลดเก็บไว้แล้ว — จำกัดให้อยู่ในโฟลเดอร์ของเราเท่านั้น

    **ต้องยอมทุกโฟลเดอร์งาน ไม่ใช่แค่ `shopee_products/`** ตั้งแต่ 27 ส.ค. 2569
    งานถูกแยกโฟลเดอร์ตามสถานะ (`clips/` `clipsfb/` `waitclips/` …) ตามที่เจ้าของ
    สั่ง ถ้ายังจำกัดไว้ที่เดียว **รูปของงานที่ย้ายแล้วจะขึ้น 404 ทั้งหมด**
    ซึ่งคือของส่วนใหญ่ แล้วหน้าเว็บจะโชว์กรอบว่างโดยไม่มีอะไรบอกว่าเพราะอะไร

    ด่านกัน path traversal ยังอยู่ครบ — ต้องอยู่ใต้โฟลเดอร์ใดโฟลเดอร์หนึ่งในรายการ
    ที่อนุญาตเท่านั้น ไม่ใช่ปล่อยให้อ่านอะไรก็ได้ใน `data/`
    """
    target = Path(path).resolve()
    allowed = ("shopee_products", "shopee_products_done", "clips", "clipsfb",
               "clipstiktok", "waitstory", "waitclips", "waitclipsfb",
               "waitclipstiktok")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="ไม่พบรูปนี้")
    parents = set(target.parents)
    if not any((DATA_DIR / name).resolve() in parents for name in allowed):
        raise HTTPException(status_code=404, detail="ไม่พบรูปนี้")
    return FileResponse(target)


# ---------------------------------------------------------------- ฟาร์มโปรไฟล์บอท
profile_farm = bot_profiles.ProfileFarm(DATA_DIR)


@app.get("/api/botfarm")
async def botfarm_list(request: Request) -> dict:
    require_admin(request)
    return {
        "ok": True,
        **profile_farm.list_profiles(),
        "chrome_profiles": profile_farm.chrome_profiles(),
    }


@app.post("/api/botfarm/import")
async def botfarm_import(request: Request) -> dict:
    require_admin(request)
    payload = await request.json()
    try:
        entry = profile_farm.import_profile(
            str(payload.get("source", "")), str(payload.get("name", "")))
    except bot_profiles.FarmError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "message": f"นำเข้า \"{entry['name']}\" แล้ว", "profile": entry}


@app.post("/api/botfarm/create")
async def botfarm_create(request: Request) -> dict:
    """สร้างโปรไฟล์บอทเปล่า — ล็อกอินเองในโปรไฟล์นั้นแล้วมันจำไว้ถาวร"""
    require_admin(request)
    payload = await request.json()
    try:
        entry = profile_farm.create_blank(str(payload.get("name", "")))
    except bot_profiles.FarmError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    append_log("publish", f"สร้างโปรไฟล์บอท \"{entry['name']}\"")
    return {"ok": True, "message": f"สร้าง \"{entry['name']}\" แล้ว", "profile": entry}


@app.post("/api/botfarm/ensure")
async def botfarm_ensure(request: Request) -> dict:
    """สร้างให้ครบ Bot1..BotN — ตัวที่มีอยู่แล้วไม่แตะ"""
    require_admin(request)
    payload = await request.json()
    try:
        result = await asyncio.to_thread(
            profile_farm.ensure_bots,
            int(payload.get("count", 10)),
            str(payload.get("prefix", "Bot")),
        )
    except bot_profiles.FarmError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    made = ", ".join(result["created"]) or "ไม่มีตัวใหม่"
    append_log("publish", f"เตรียมโปรไฟล์บอทครบ {result['total']} ตัว — สร้างใหม่: {made}")
    return {"ok": True, "message": f"พร้อมใช้ {result['total']} ตัว · สร้างใหม่: {made}", **result}


@app.post("/api/botfarm/settings")
async def botfarm_settings(request: Request) -> dict:
    require_admin(request)
    payload = await request.json()
    profile_farm.set_max_concurrent(payload.get("max_concurrent", 3))
    return {"ok": True, "message": "บันทึกเพดานแล้ว"}


@app.post("/api/botfarm/{profile_id}/launch")
async def botfarm_launch(profile_id: str, request: Request) -> dict:
    require_admin(request)
    payload = await request.json()
    try:
        result = profile_farm.launch(profile_id, str(payload.get("url", "")))
    except bot_profiles.FarmError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, **result}


@app.post("/api/botfarm/{profile_id}/stop")
async def botfarm_stop(profile_id: str, request: Request) -> dict:
    require_admin(request)
    return {"ok": True, **profile_farm.stop(profile_id)}


@app.post("/api/botfarm/{profile_id}/refresh")
async def botfarm_refresh(profile_id: str, request: Request) -> dict:
    require_admin(request)
    try:
        result = profile_farm.refresh_from_source(profile_id)
    except bot_profiles.FarmError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    msg = (f"รีเฟรชล็อกอินล่าสุดแล้ว ({result['at']})" if result["refreshed"]
           else "รีเฟรชไม่ได้ — โปรไฟล์ต้นทางเปิดค้างอยู่ ปิดหน้าต่างนั้นก่อน")
    return {"ok": True, "message": msg, **result}


@app.post("/api/botfarm/{profile_id}/auto-refresh")
async def botfarm_auto_refresh(profile_id: str, request: Request) -> dict:
    require_admin(request)
    payload = await request.json()
    profile_farm.set_auto_refresh(profile_id, bool(payload.get("value", True)))
    return {"ok": True}


@app.post("/api/botfarm/{profile_id}/backup")
async def botfarm_backup(profile_id: str, request: Request) -> dict:
    require_admin(request)
    try:
        result = profile_farm.backup_login(profile_id)
    except bot_profiles.FarmError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "message": f"สำรองล็อกอินแล้ว ({result['at']})", **result}


@app.post("/api/botfarm/{profile_id}/restore")
async def botfarm_restore(profile_id: str, request: Request) -> dict:
    require_admin(request)
    payload = await request.json()
    try:
        result = profile_farm.restore_login(profile_id, str(payload.get("stamp", "")))
    except bot_profiles.FarmError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "message": f"กู้ล็อกอินจากชุด {result['stamp']} แล้ว", **result}


@app.get("/api/botfarm/{profile_id}/backups")
async def botfarm_backups(profile_id: str, request: Request) -> dict:
    require_admin(request)
    return {"ok": True, "backups": profile_farm.list_backups(profile_id)}


@app.post("/api/botfarm/{profile_id}/rename")
async def botfarm_rename(profile_id: str, request: Request) -> dict:
    require_admin(request)
    payload = await request.json()
    try:
        result = profile_farm.rename(profile_id, str(payload.get("name", "")))
    except bot_profiles.FarmError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "message": f"เปลี่ยนชื่อเป็น \"{result['name']}\" แล้ว", **result}


@app.delete("/api/botfarm/{profile_id}")
async def botfarm_delete(profile_id: str, request: Request) -> dict:
    require_admin(request)
    try:
        return {"ok": True, **profile_farm.delete(profile_id)}
    except bot_profiles.FarmError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/qr.png")
async def qr_image(text: str, request: Request) -> Response:
    """QR ของลิงก์อะไรก็ได้ — ไว้ให้มือถือสแกนเปิดหน้าเว็บนี้โดยไม่ต้องพิมพ์ IP"""
    require_admin(request)
    content = text.strip()
    if not content:
        raise HTTPException(status_code=400, detail="ยังไม่ได้ใส่ลิงก์")
    try:
        image = qr_code.qr_png(content)
    except ValueError as error:
        raise HTTPException(
            status_code=400, detail="ข้อความยาวเกินกว่าที่ QR รองรับ"
        ) from error
    return Response(
        content=image, media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@atexit.register
def _close_scrcpy() -> None:
    """ปิด session ของ scrcpy ทั้งหมดตอนเซิร์ฟเวอร์ปิด — กันโปรเซสค้างบนมือถือ"""
    try:
        scrcpy_control.close_all()
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn

    print(f"Pipeline Studio v{APP_VERSION} — http://127.0.0.1:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
