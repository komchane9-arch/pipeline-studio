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
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import access_control
import bot_profiles
import studio_shared
import fb_auto_post
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
FB_POST_DIR = DATA_DIR / "fb_posts"          # รูปที่รับมาจาก Telegram

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
        run_adb=lambda *args: run_adb("-s", serial, *args, timeout=25).stdout,
        caption=(run or {}).get("caption") or clip_store.build_caption(run or {}),
        # ต้องเป็นลิงก์ที่ผู้ใช้ส่งมาทาง Telegram เท่านั้น — ลิงก์ที่ระบบแปลงเอง
        # ไม่มีรหัสผู้แนะนำ โพสต์ไปก็ไม่ได้ค่าคอม
        link=(run or {}).get("affiliate_url") or "",
        hashtags=list(plan.get("tags") or []),
        log=lambda message: append_log("publish", message),
        report=report,
    )


@app.post("/api/publish/flow/run")
async def publish_flow_run(request: Request) -> dict:
    """เดินผังทั้งชุด หรือทดลองทีละขั้น (ส่ง only มาเป็นเลขขั้น)"""
    payload = await request.json()
    serial = clean_serial(str(payload.get("serial", "")), True)
    target = _clean_target(payload.get("target"))
    item_id = str(payload.get("item_id", "")).strip()
    only = payload.get("only")

    if not _publish_run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="มีงานโพสต์รันอยู่แล้ว รอให้จบก่อน")

    def work() -> dict:
        try:
            context = _build_context(serial, target, item_id, lambda *a: None)
            if only:
                number = int(only)
                return publish_flow.run_flow(context, start_at=number, stop_after=number)
            return publish_flow.run_flow(context)
        finally:
            _publish_run_lock.release()

    try:
        result = await asyncio.to_thread(work)
    except publish_flow.StepError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    append_log(
        "publish",
        f"[{target}] เดินผัง {result['done']}/{result['total']} ขั้น — "
        f"{'สำเร็จ' if result['ok'] else 'ไม่สำเร็จ'}",
    )
    return {"ok": True, **result}


# ---------------------------------------------------------------- จอมือถือ (A)


@app.get("/api/devices")
async def devices() -> dict:
    found = await asyncio.to_thread(list_devices)
    names = load_config().get("device_names", {})
    for device in found:
        device["custom_name"] = names.get(device["serial"], "")
    return {"ok": True, "devices": found}


@app.post("/api/device-name")
async def set_device_name(request: Request) -> dict:
    """ตั้งชื่อเล่นให้มือถือ — โชว์แทนชื่อรุ่นใน dropdown (เก็บต่อ serial)"""
    payload = await request.json()
    serial = clean_serial(str(payload.get("serial", "")))
    name = str(payload.get("name", "")).strip()[:40]
    config = load_config()
    if name:
        config.setdefault("device_names", {})[serial] = name
    else:
        config.get("device_names", {}).pop(serial, None)   # ชื่อว่าง = ลบชื่อเล่นทิ้ง
    save_config(config)
    return {"ok": True, "serial": serial, "name": name}


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


@app.get("/api/screen")
async def screen(serial: str) -> Response:
    """ภาพหน้าจอปัจจุบัน — PNG นิ่งทีละเฟรม รีเฟรชจากฝั่งหน้าเว็บ

    จงใจไม่ใช้ screenrecord สตรีม: บทเรียนโปรเจกต์เดิมคือโปรเซสค้างสะสม
    จนสตรีมช้าจาก 0.5 วิเป็น 25 วิ ภาพนิ่งพอสำหรับดูสถานะ + เทรนตำแหน่ง
    """
    cleaned = await asyncio.to_thread(clean_serial, serial, True)

    def capture() -> bytes:
        # เคลียร์ screenrecord ที่อาจค้างจากโปรเจกต์เดิม/scrcpy ครั้งเดียวต่อเครื่อง
        # ของค้างพวกนี้กินตัวเข้ารหัสจนเครื่องหนัก (วัดจริง: ภาพแรก 0.5 วิ → 25 วิ)
        if cleaned not in _screenrecord_cleaned:
            run_adb("-s", cleaned, "shell", "pkill -f screenrecord", timeout=8)
            _screenrecord_cleaned.add(cleaned)
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


def _websocket_is_local(websocket: WebSocket) -> bool:
    host = websocket.client.host if websocket.client else ""
    return host in {"127.0.0.1", "::1", "localhost"}


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


@app.websocket("/ws/phone/input")
async def phone_input_socket(websocket: WebSocket, serial: str) -> None:
    """ช่องส่งการแตะ/ลากแบบต่อค้าง

    ยิง HTTP ทีละ event ได้แค่ ~50 ครั้ง/วินาที ต่ำกว่านิ้วจริงมาก (120-240)
    ช่องนี้ตัดค่าใช้จ่ายต่อ request ทิ้ง และ socket ขาดก็ปล่อยนิ้วทันที
    ไม่ต้องรอ watchdog 60 วินาที
    """
    if not _websocket_is_local(websocket):
        await websocket.close(code=1008, reason="อนุญาตเฉพาะเครื่องหลัก")
        return
    await websocket.accept()
    try:
        cleaned = await asyncio.to_thread(clean_serial, serial, True)
    except HTTPException as error:
        await websocket.send_json({"error": error.detail})
        await websocket.close(code=1008)
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


@app.websocket("/ws/phone/stream")
async def phone_stream(websocket: WebSocket, serial: str) -> None:
    """สตรีมหน้าจอ H.264 หน่วงต่ำ — ฝั่งหน้าเว็บถอดด้วย WebCodecs"""
    if not _websocket_is_local(websocket):
        await websocket.close(code=1008, reason="อนุญาตเฉพาะเครื่องหลัก")
        return
    await websocket.accept()
    try:
        cleaned = await asyncio.to_thread(clean_serial, serial, True)
    except HTTPException as error:
        await websocket.send_json({"error": error.detail})
        await websocket.close(code=1008)
        return

    stream_size = await asyncio.to_thread(device_stream_size, cleaned)
    size_arguments = ["--size", stream_size] if stream_size else []

    # ฆ่า screenrecord ที่ค้างบนมือถือก่อนเริ่มสตรีมใหม่เสมอ
    # ของค้างสะสมแย่งตัวเข้ารหัสกัน (วัดจริง: ค้าง 2 สตรีม → ภาพแรก 25 วิ,
    # ล้างแล้วเหลือ 0.5 วิ)
    await asyncio.to_thread(
        lambda: run_adb("-s", cleaned, "shell", "pkill -f screenrecord", timeout=8)
    )
    await asyncio.sleep(0.4)

    receive_task = asyncio.create_task(websocket.receive())
    process: subprocess.Popen | None = None
    try:
        while True:
            process = subprocess.Popen(
                [
                    ADB, "-s", cleaned, "exec-out", "screenrecord",
                    "--output-format=h264", *size_arguments,
                    "--bit-rate", "4000000", "--time-limit", "175", "-",
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
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
                read_task = asyncio.create_task(asyncio.to_thread(read_available))
                done, _ = await asyncio.wait(
                    {read_task, receive_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if receive_task in done:
                    read_task.cancel()
                    return
                chunk = read_task.result()
                if not chunk:
                    break
                buffer.extend(chunk)
                # ส่งทีละ NAL — ฝั่งหน้าเว็บป้อนเข้า VideoDecoder ได้ทันที
                starts = h264_start_codes(buffer)
                while len(starts) >= 2:
                    position = starts[0][0]
                    end = starts[1][0]
                    await websocket.send_bytes(bytes(buffer[position:end]))
                    del buffer[:end]
                    starts = [(s - end, size) for s, size in starts[1:]]

            if buffer:
                await websocket.send_bytes(bytes(buffer))
            process.wait(timeout=2)
            process = None
            await asyncio.sleep(0.15)
    except (WebSocketDisconnect, ConnectionError, RuntimeError):
        return
    finally:
        receive_task.cancel()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()


@app.post("/api/phone/key")
async def phone_key(request: Request) -> dict:
    payload = await request.json()
    key = str(payload.get("key", "")).strip().upper()
    code = ADB_KEY_EVENTS.get(key)
    if code is None:
        raise HTTPException(status_code=400, detail="ไม่รองรับปุ่มนี้")
    serial = await asyncio.to_thread(
        clean_serial, str(payload.get("serial", "")), True
    )
    await asyncio.to_thread(
        lambda: run_adb("-s", serial, "shell", "input", "keyevent", code)
    )
    return {"ok": True, "key": key}


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


def _mass_bot_keeper() -> None:
    """เฝ้าให้ fb_mass_bot รันอยู่เสมอ — ตายเมื่อไรปลุกใหม่ใน ≤60 วิ"""
    while True:
        try:
            ensure_mass_bot()
        except Exception as error:                              # noqa: BLE001
            append_log("input", f"keeper fb_mass_bot ผิดพลาด: {error}")
        time.sleep(60)


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
    # บอทหาโพสต์แมสเป็นโปรเซสแยก (role mass) — ให้ app.py ปลุกและเฝ้าให้ฟื้นเอง
    threading.Thread(target=_mass_bot_keeper, daemon=True).start()


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

fb_groups = fb_auto_post.GroupStore(DATA_DIR / "fb_groups.json")
fb_jobs = fb_auto_post.JobStore(DATA_DIR / "fb_jobs.json")
fb_runner = fb_auto_post.PostRunner()

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
    if (DATA_DIR / "fb_groups.json").is_file():
        return
    for group_id, name in FB_SEED_GROUPS:
        fb_groups.add(group_id, name)
    append_log("publish", f"ใส่กลุ่มตั้งต้นให้ {len(FB_SEED_GROUPS)} กลุ่ม (ลบได้)")


def _fb_settings() -> dict:
    return load_config().get("facebook") or {}


def _fb_gap_range() -> tuple[float, float]:
    settings = _fb_settings()
    low = float(settings.get("gap_min", 15) or 15)
    high = float(settings.get("gap_max", 20) or 20)
    return (min(low, high), max(low, high))


def _fb_serial() -> str:
    """เครื่องที่จะใช้โพสต์ — ที่ตั้งไว้ก่อน ถ้าไม่ได้ตั้งใช้เครื่องแรกที่พร้อม"""
    wanted = str(_fb_settings().get("serial", "")).strip()
    ready = [d["serial"] for d in list_devices() if d["ready"]]
    if wanted:
        if wanted not in ready:
            raise fb_auto_post.AutoPostError(
                f"มือถือ {wanted} ที่ตั้งไว้ไม่ได้เชื่อมต่ออยู่"
            )
        return wanted
    if not ready:
        raise fb_auto_post.AutoPostError("ไม่มีมือถือเชื่อมต่ออยู่ — เสียบสายแล้วลองใหม่")
    return ready[0]


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
        if fb_runner.busy and fb_runner.job_id == job["id"]:
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
    running = fb_runner.busy and fb_runner.job_id == job_id
    fb_jobs.update(job_id, status=fb_auto_post.STATUS_CANCELLED)
    if running and fb_runner.stop():
        append_log("publish", f"[{job_id}] ผู้ใช้สั่งยกเลิก — สั่งหยุดตัวรันแล้ว")
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
        rows.append([{
            "text": f"{order}. {head[:24]} · 🖼{shots} 💬{talk}",
            "callback_data": f"fb:rp:{job['id']}",
        }])
    lines += ["", "กดแล้วจะได้<b>งานใหม่</b> ที่ลอกแคปชัน รูป และคอมเมนต์มาให้ครบ",
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
    "• /schedule &lt;เวลา&gt; — ตั้งเวลาโพสต์ (20:30 / 9/8 20:30 / +30)\n"
    "• /followup — ตามเก็บ: เปิดโพสต์จากแจ้งเตือนแล้วกดถูกใจ/คอมเมนต์ให้\n"
    "• /collect — เก็บยอดถูกใจ/คอมเมนต์/แชร์ ของโพสต์ทุกกลุ่ม\n"
    "• /fiximage — แก้รูปของโพสต์ที่ลงไปแล้วให้เป็นรูปที่ถูก\n"
    "• /links — ลิงก์โพสต์ที่เก็บไว้ (ใส่ตัวเลขต่อท้ายเพื่อดูย้อนหลังมากขึ้น)\n"
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
    if not phone_is_free():
        if queued:
            return PHONE_WAIT_NOTE
        place = _phone_wait_add("followup", job["id"], job.get("chat_id", ""))
        if place < 0:
            return f"คิวรอจอเต็ม ({PHONE_WAITLIST_LIMIT} งาน)"
        holder = phone_gate.held_by() or f"งานโพสต์ {fb_runner.job_id}"
        return (
            f"📥 ตามเก็บ {job['id']} เข้าคิวรอจอแล้ว — คิวที่ {place or 1}\n"
            f"<i>ตอนนี้ {telegram_bot._escape(holder)} ใช้จออยู่</i>"
        )
    # ข้ามกลุ่มที่ "ครบแล้ว" — ไม่ใช่ไล่ทุกกลุ่มที่โพสต์สำเร็จ
    #
    # รอบโพสต์ทำถูกใจ/คอมเมนต์/เก็บลิงก์ให้เสร็จได้เลยถ้ากลุ่มนั้นไม่ต้องรออนุมัติ
    # ถ้ายังไล่ตามเก็บอีกจะหาโพสต์ไม่เจอ — แจ้งเตือน "ผู้ดูแลอนุมัติแล้ว" ไม่มีอยู่จริง
    # เพราะไม่เคยต้องอนุมัติ ส่วนฟีดก็จมไปแล้ว — จบด้วยรายงาน "ถูกใจ 0/5"
    # ซึ่งอ่านแล้วเหมือนล้มเหลว ทั้งที่ความจริงคือไม่มีอะไรต้องทำ
    # (เจอจริง 12 ส.ค. งาน p525306924: ครบทั้ง 5 กลุ่มตั้งแต่รอบโพสต์)
    want_comment = bool(_fb_comments(job))

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
        if done:
            return (f"✅ งาน {job['id']} ครบแล้วทั้ง {done} กลุ่ม — ถูกใจ คอมเมนต์ "
                    "และลิงก์เก็บครบตั้งแต่รอบโพสต์ ไม่ต้องตามเก็บ")
        return "งานล่าสุดไม่มีกลุ่มที่โพสต์สำเร็จ"
    try:
        serial = _fb_serial()
    except fb_auto_post.AutoPostError as error:
        return str(error)

    job_id = job["id"]
    chat_id = job.get("chat_id", "")
    # ใช้คอมเมนต์ทั้งรายการ ไม่ใช่แค่ข้อความแรก — ไม่งั้นงานที่ตั้งไว้ 2 ข้อความ
    # จะได้แค่ข้อความเดียว และรูปแนบที่เรียงตรงช่องกันจะเลื่อนไปผิดช่องด้วย
    override = comment_override.strip()
    comment = override or _fb_comments(job)
    comment_shots = [] if override else _fb_comment_images(job)

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
        fb_runner.start_followup(
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
    if not phone_is_free():
        if queued:
            return PHONE_WAIT_NOTE
        place = _phone_wait_add("collect", job["id"], job.get("chat_id", ""))
        if place < 0:
            return f"คิวรอจอเต็ม ({PHONE_WAITLIST_LIMIT} งาน)"
        holder = phone_gate.held_by() or f"งานโพสต์ {fb_runner.job_id}"
        return (
            f"📥 เก็บยอด {job['id']} เข้าคิวรอจอแล้ว — คิวที่ {place or 1}\n"
            f"<i>ตอนนี้ {telegram_bot._escape(holder)} ใช้จออยู่</i>"
        )
    # เก็บทุกกลุ่มที่โพสต์ขึ้นแล้ว — ไม่กรองว่ามีลิงก์ไหม เพราะกลุ่มที่ยังไม่มีลิงก์
    # ก็ยังเข้าถึงได้ทางแจ้งเตือน/ฟีด และจะได้เก็บลิงก์ติดมือกลับมาด้วยเลย
    targets = [
        {"group_id": r["group_id"], "name": fb_groups.label(r["group_id"]),
         "link": r.get("link", ""), "post_id": r.get("post_id", "")}
        for r in job["results"] if r.get("posted")
    ]
    if not targets:
        return f"งาน {job['id']} ไม่มีกลุ่มที่โพสต์สำเร็จ"
    try:
        serial = _fb_serial()
    except fb_auto_post.AutoPostError as error:
        return str(error)

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
        fb_runner.start_collect(
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
    if not phone_is_free():
        if queued:
            return PHONE_WAIT_NOTE
        place = _phone_wait_add("fiximage", job["id"], job.get("chat_id", ""))
        if place < 0:
            return f"คิวรอจอเต็ม ({PHONE_WAITLIST_LIMIT} งาน)"
        holder = phone_gate.held_by() or f"งานโพสต์ {fb_runner.job_id}"
        return (
            f"📥 แก้รูป {job['id']} เข้าคิวรอจอแล้ว — คิวที่ {place or 1}\n"
            f"<i>ตอนนี้ {telegram_bot._escape(holder)} ใช้จออยู่</i>"
        )
    targets = [
        {"group_id": r["group_id"], "name": fb_groups.label(r["group_id"]),
         "link": r.get("link", ""), "post_id": r.get("post_id", "")}
        for r in job["results"] if r.get("posted") and r.get("link")
    ]
    if not targets:
        return (f"งาน {job['id']} ยังไม่มีกลุ่มที่เก็บลิงก์ไว้ — "
                "สั่ง /followup เก็บลิงก์ก่อนแล้วค่อยแก้รูป")
    try:
        serial = _fb_serial()
    except fb_auto_post.AutoPostError as error:
        return str(error)

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
        fb_runner.start_fiximage(
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


def _fb_auto_followup(job_id: str, delay: float = AUTO_FOLLOWUP_DELAY) -> None:
    """ต่อสายไป "หาโพสต์จากแจ้งเตือน" ทันทีที่รอบโพสต์จบ

    ทำไมต้องแยกเธรด: on_done ถูกเรียกจากในเธรดของตัวรันเอง ตอนนั้น
    fb_runner.busy ยังเป็น True อยู่ สั่ง start_followup ตรงๆ จะโดนตีกลับว่า
    "กำลังทำงานอยู่" จึงต้องรอให้เธรดเดิมปล่อยก่อน

    ทำไมต้องหน่วงก่อน: กลุ่มส่วนใหญ่ต้องรอผู้ดูแลอนุมัติ ยิงทันทีที่โพสต์เสร็จ
    จะยังไม่มีแจ้งเตือนให้หา เสียเวลาเปล่าราวหนึ่งนาทีต่อกลุ่ม
    """
    def worker() -> None:
        deadline = time.time() + 180
        while fb_runner.busy and time.time() < deadline:
            time.sleep(2.0)
        if fb_runner.busy:
            append_log("publish", f"[{job_id}] ตัวรันยังไม่ว่าง — ข้ามการตามเก็บอัตโนมัติ")
            return
        time.sleep(delay)
        append_log("publish", f"[{job_id}] โพสต์จบแล้ว — ไล่หาโพสต์จากแจ้งเตือนต่อ")
        try:
            note = _fb_followup()
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
            timeout=CLAUDE_RUN_TIMEOUT,
        )
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
    """คุมสิทธิ์ใช้จอมือถือ — มีได้เจ้าเดียวในเวลาเดียว

    มือถือมีจอเดียว ถ้างานโพสต์กับ Claude CLI สั่ง ADB พร้อมกันจะแตะทับกัน
    เละทั้งคู่: กำลังพิมพ์แคปชันอยู่แล้วอีกฝั่งกด Back หรือ force-stop แอป

    ออกแบบให้ไม่สมมาตรเพื่อกันเดดล็อก:
      · งานโพสต์/ตามเก็บ ใช้ `fb_runner.busy` เป็นตัวบอกว่าตัวเองยุ่ง (ของเดิม)
      · Claude ต้อง**รอให้ fb_runner ว่างก่อน** แล้วค่อยจองประตูนี้
      · งานโพสต์เช็คว่าประตูถูกจองอยู่ไหม ถ้าใช่ = ไม่เริ่ม
    ทั้งสองฝั่งจึงไม่มีทางรอกันวนไปมา
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.owner = ""
        self.since = 0.0

    def try_take(self, owner: str) -> bool:
        with self._lock:
            if self.owner:
                return False
            self.owner, self.since = owner, time.time()
            return True

    def wait_take(self, owner: str, timeout: float = 900.0) -> bool:
        """รอจนจอว่างแล้วจอง — คืน False ถ้ารอเกินเวลา"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not fb_runner.busy and self.try_take(owner):
                return True
            time.sleep(3.0)
        return False

    def give_back(self, owner: str) -> None:
        with self._lock:
            if self.owner == owner:
                self.owner, self.since = "", 0.0

    def held_by(self) -> str:
        return self.owner

    def held_for(self) -> float:
        return (time.time() - self.since) if self.owner else 0.0


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


def phone_is_free() -> bool:
    return not phone_gate.held_by() and not fb_runner.busy


def phone_waitlist() -> list[dict]:
    with _waitlist_lock:
        return list(_phone_waitlist)


def _phone_wait_add(kind: str, job_id: str, chat_id: str = "") -> int:
    """ต่อคิวรอจอ คืนลำดับที่ (0 = มีอยู่ในคิวแล้ว · -1 = คิวเต็ม)"""
    with _waitlist_lock:
        for item in _phone_waitlist:
            if item["kind"] == kind and item["job_id"] == job_id:
                return 0
        if len(_phone_waitlist) >= PHONE_WAITLIST_LIMIT:
            return -1
        _phone_waitlist.append({"kind": kind, "job_id": job_id, "chat_id": chat_id})
        return len(_phone_waitlist)


def _phone_wait_pump() -> None:
    """จอว่างแล้วหยิบงานแรกในคิวมาเริ่ม — เรียกจากลูปตัวตั้งเวลาทุก 20 วินาที"""
    with _waitlist_lock:
        if not _phone_waitlist or not phone_is_free():
            return
        item = _phone_waitlist.pop(0)
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
        if fb_runner.busy:
            _fb_say(chat_id, f"⏳ รองานโพสต์ที่ทำอยู่ให้จบก่อน แล้วจะเริ่ม: "
                             f"{telegram_bot._escape(label)}")
        if not phone_gate.wait_take("claude"):
            _fb_say(chat_id, f"⚠️ {telegram_bot._escape(label)} — "
                             f"รอจอมือถือว่างเกิน 15 นาที ยกเลิกงานนี้")
            append_log("input", f"Claude [{label[:30]}] รอจอไม่ว่าง — ข้าม")
            continue
        _fb_say(chat_id, f"▶️ เริ่ม: {telegram_bot._escape(label)}")
        try:
            ok, reply = claude_run(prompt)
        finally:
            phone_gate.give_back("claude")
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
    holder = phone_gate.held_by()
    if holder:
        lines += ["", f"📱 จอมือถือ: <b>{holder}</b> ใช้อยู่ "
                      f"({phone_gate.held_for() / 60:.0f} นาที)"]
    elif fb_runner.busy:
        lines += ["", f"📱 จอมือถือ: งานโพสต์ <b>{fb_runner.job_id}</b> ใช้อยู่ "
                      "— Claude จะรอจนจบ"]
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


def _fb_scheduler() -> None:
    """เฝ้างานที่ตั้งเวลาไว้ ถึงเวลาแล้วเริ่มโพสต์ให้เอง

    เช็คทุก 20 วินาทีจากไฟล์งาน ไม่ได้ตั้ง timer ค้างไว้ในหน่วยความจำ —
    รีสตาร์ตเซิร์ฟเวอร์แล้วเวลาที่ตั้งไว้ต้องไม่หาย
    """
    while True:
        time.sleep(20)
        try:
            _phone_wait_pump()          # จอว่างแล้วเริ่มงานที่รอคิวไว้
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
                if phone_gate.held_by():
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
    lines.append("   งานที่กำลังทำ: " + ("มี" if fb_runner.busy else "ไม่มี"))
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
        halted = fb_runner.stop()
        if halted and fb_runner.job_id:
            append_log("publish", f"[{fb_runner.job_id}] ผู้ใช้สั่งยกเลิก — สั่งหยุดตัวรัน")
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
            "สั่งหยุดแล้ว — จะหยุดหลังกลุ่มที่กำลังทำอยู่จบ" if fb_runner.stop()
            else "ตอนนี้ไม่มีงานกำลังโพสต์อยู่",
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


def _fb_run_job(job_id: str, queued: bool = False) -> str:
    """ตรวจความพร้อมแล้วสั่งรัน — คืนข้อความบอกผลการสั่ง (ว่าง = เริ่มแล้ว)"""
    job = fb_jobs.get(job_id)
    if job is None:
        return "ไม่พบงานนี้"
    if job["status"] == fb_auto_post.STATUS_RUNNING:
        return "งานนี้กำลังโพสต์อยู่แล้ว"
    # จอมือถือมีเจ้าเดียว — ไม่ว่างก็เข้าคิวรอ ไม่ปฏิเสธทิ้ง
    if not phone_is_free():
        if queued:
            return PHONE_WAIT_NOTE          # ตัวเดินคิวจะคืนกลับหัวคิวเอง
        place = _phone_wait_add("post", job_id, job.get("chat_id", ""))
        if place < 0:
            return f"คิวรอจอเต็ม ({PHONE_WAITLIST_LIMIT} งาน)"
        holder = phone_gate.held_by() or f"งานโพสต์ {fb_runner.job_id}"
        return (
            f"📥 เข้าคิวรอจอแล้ว — คิวที่ {place or 1}\n"
            f"<i>ตอนนี้ {telegram_bot._escape(holder)} ใช้จออยู่ · "
            f"จอว่างเมื่อไรจะเริ่มให้เอง</i>"
        )
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
    if len(groups) > fb_auto_post.MAX_GROUPS_PER_POST:
        # โพสต์รัวหลายกลุ่มเกินไปเข้าข่ายสแปม — กันที่นี่อีกชั้นเผื่อเลือกมาเกิน
        return (
            f"เลือกไว้ {len(groups)} กลุ่ม — ครั้งเดียวโพสต์ได้ไม่เกิน "
            f"{fb_auto_post.MAX_GROUPS_PER_POST} กลุ่ม เอาออกก่อน"
        )

    try:
        serial = _fb_serial()
    except fb_auto_post.AutoPostError as error:
        return str(error)

    chat_id = job.get("chat_id", "")

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
        chain = bool(posted) and not fb_runner.stop_flag.is_set()
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
            _fb_auto_followup(job_id, delay)

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
        fb_runner.start(
            job={**job, "groups": groups}, adb=ADB, serial=serial, image=image,
            gap_range=_fb_gap_range(), on_log=on_log, on_result=on_result,
            on_done=on_done, clipboard=Clipboard,
            # ส่งเป็นฟังก์ชัน ไม่ใช่ค่าคงที่ — ผู้ใช้พิมพ์ /comment กลางคันได้
            comment=lambda: _fb_comments(fb_jobs.get(job_id) or {}),
            comment_images=lambda: _fb_comment_images(fb_jobs.get(job_id) or {}),
        )
    except fb_auto_post.AutoPostError as error:
        return str(error)

    fb_jobs.update(
        job_id, status=fb_auto_post.STATUS_RUNNING, results=[],
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
        "serial": settings.get("serial", ""),
        "running": fb_runner.busy,
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
    note = await asyncio.to_thread(
        _fb_followup, str((payload or {}).get("comment", ""))
    )
    return {"ok": True, "note": note}


@app.post("/api/fb/settings")
async def fb_save_settings(request: Request) -> dict:
    payload = await request.json()
    config = load_config()
    settings = config.get("facebook") or {}
    if "gap_min" in payload:
        settings["gap_min"] = max(5, int(payload.get("gap_min") or 15))
    if "gap_max" in payload:
        settings["gap_max"] = max(5, int(payload.get("gap_max") or 20))
    # เว้นระยะขั้นต่ำต้องไม่มากกว่าขั้นสูง ไม่งั้นสุ่มค่าไม่ได้
    if settings.get("gap_min", 15) > settings.get("gap_max", 20):
        settings["gap_max"] = settings["gap_min"]
    if "auto_start" in payload:
        settings["auto_start"] = bool(payload["auto_start"])
    if "serial" in payload:
        settings["serial"] = str(payload["serial"]).strip()
    config["facebook"] = settings
    save_config(config)
    return {"ok": True, **settings}


@app.get("/api/fb/jobs")
async def fb_list_jobs() -> dict:
    jobs = fb_jobs.listing()[:10]
    return {
        "ok": True,
        "running": fb_runner.busy,
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
    """เสิร์ฟรูปสินค้าที่โหลดเก็บไว้แล้ว — จำกัดให้อยู่ในโฟลเดอร์ของเราเท่านั้น"""
    target = Path(path).resolve()
    root = (DATA_DIR / "shopee_products").resolve()
    # กัน path traversal: ต้องอยู่ใต้ shopee_products เท่านั้น ไม่งั้นอ่านไฟล์อะไรก็ได้ในเครื่อง
    if not target.is_file() or root not in target.parents:
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
