"""worker เจนรูป/วิดีโอเบื้องหลัง — โปรแกรมแยกจากเว็บแอป

ทำไมต้องแยกโปรเซส (ไม่ใช่ thread ในเว็บแอป)
  1. เบราว์เซอร์ค้าง/แครช เว็บแอปไม่ล้มตาม งานถอดเสียงที่รันอยู่ไม่หาย
  2. Playwright แบบ sync ใช้ใน thread ที่มี asyncio loop ของ FastAPI ไม่ได้
  3. ปิด-เปิด worker ใหม่ตอนแก้ selector ได้ โดยไม่ต้องหยุดทั้งระบบ
  4. งานหนึ่งกินเวลาหลายนาที ถ้าไปรอใน request เว็บทั้งหน้าจะค้าง

คุยกับเว็บแอปผ่านไฟล์บนดิสก์เท่านั้น ไม่ต้องมี message queue:
    data/flow_jobs/<job_id>/state.json   ← สถานะและผลลัพธ์
    data/flow_jobs/<job_id>/image.png    ← ผลขั้นที่ 2
    data/flow_jobs/<job_id>/video.mp4    ← ผลขั้นที่ 3

วิธีใช้
    python flow_worker.py add --product "ครีมกันแดด" --detail "ขนาด 50ml กันน้ำ"
    python flow_worker.py run --demo     # พิสูจน์ลูปโดยไม่ต้องล็อกอิน Google
    python flow_worker.py run            # ของจริง เปิด Chrome ไปกด Flow
    python flow_worker.py list

หมายเหตุ: Google Flow ไม่มี API สาธารณะ ขั้นเจนรูป/วิดีโอจึงต้องขับเบราว์เซอร์
selector ทั้งหมดรวมไว้ที่ FLOW_SELECTORS ที่เดียว เวลา Flow เปลี่ยนหน้าตาแก้จุดเดียวจบ
"""

from __future__ import annotations

import argparse
import ctypes
import json
import re
import secrets
import sys
import threading
import time
import traceback
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import httpx
import gemini_quota

# Windows ตั้ง stdout เป็น cp1252 เมื่อไม่ได้ต่อกับ console (เช่นเขียนลงไฟล์ log)
# ข้อความไทยจะทำให้โปรแกรมตายทั้งตัว — บังคับ UTF-8 ไว้ตั้งแต่ต้น
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
JOBS_DIR = DATA_DIR / "flow_jobs"
GEMINI_KEY_FILE = DATA_DIR / "gemini_api_key.bin"
# โปรไฟล์ Chrome ถาวร ล็อกอิน Google ครั้งเดียวแล้วคุกกี้อยู่ยาว
PROFILE_DIR = DATA_DIR / "flow_browser_profile"

# ---- โปรไฟล์ของ Google Flow แยกออกมาแล้ว (เจ้าของสั่ง 28 ส.ค. 2569) ---------
#
# *"ให้ทำ storyboard ใน profile เดิม แล้วแยก google flow มาเจนต่อได้ใน profile ใหม่"*
#
# **ทำไมถึงคุ้ม** เดิมสตอรีบอร์ด (ChatGPT) กับเจนคลิป (Flow) ใช้โปรไฟล์เดียวกัน
# Chrome เปิดโปรไฟล์เดียวกันซ้อนกันไม่ได้ สองงานนี้จึงต้องผลัดกันทำทั้งที่เป็น
# คนละเว็บคนละบัญชี — 28 ส.ค. Flow ติดปัญหาแล้วงานสตอรีบอร์ดต้องรอไปด้วย
# ทั้งที่ไม่เกี่ยวกันเลย แยกแล้วเดินคู่กันได้
#
# ตั้งต้นด้วยการก๊อปโปรไฟล์เดิมมาทั้งก้อน ล็อกอิน Google จึงติดมาด้วย
# ไม่ต้องล็อกอินใหม่ (ก๊อปตอน Chrome ปิดสนิทเท่านั้น ไม่งั้นได้ไฟล์ครึ่งๆ กลางๆ)
#
# ⚠️ ใครแตะ Flow ต้องใช้ **สองตัวนี้คู่กันเสมอ** — โฟลเดอร์กับชื่อล็อก
# ใช้ผิดคู่ = Chrome สองตัวเปิดโปรไฟล์เดียวกัน งานตายกลางคัน
FLOW_GEN_PROFILE = DATA_DIR / "flow_gen_profile"
FLOW_LOCK = "flow-gen"

# ---- ที่นั่งของช่องที่ 2 ขึ้นไป (เจ้าของสั่ง 30 ส.ค. 2569) -------------------
#
# *"chrome profile 2 ผมจะ log-in google flow ไว้ด้วย ให้สามารถเจนคลิปจาก
# โปรไฟล์นั้นได้ด้วยนะ"* — โปรไฟล์ที่ 2 จึงล็อกอินไว้ **ทั้ง ChatGPT และ Flow**
# ช่องที่ 2 เลยใช้โฟลเดอร์เดียวทำทั้งสองอย่าง (ต่างจากช่องที่ 1 ที่แยกสองโฟลเดอร์)
#
# ผลที่ตามมาซึ่งต้องรู้: ภายในช่องที่ 2 การทำสตอรีบอร์ดกับการเจนคลิป
# **ผลัดกันใช้** ไม่เดินพร้อมกัน — ไม่เป็นไรเพราะตัวรันหนึ่งตัวทำได้ทีละงานอยู่แล้ว
#
# ⚠️ **ชื่อล็อกต้องมาคู่กับโฟลเดอร์เสมอ** (กติกาเดิมที่เขียนไว้ข้างบน) ตารางนี้
# จึงบอกทั้งสองอย่างในบรรทัดเดียวกัน ห้ามแยกไปเขียนคนละที่
FLOW_SEATS = [
    # ช่อง 1 — ของเดิมทุกอย่าง profile=None แปลว่าให้ flow_gen_profile_dir() ตัดสิน
    # (ซึ่งยังเคารพ flow_bot_profile ใน config.json เหมือนเดิม)
    {"profile": None, "lock": FLOW_LOCK},
    {"profile": "flow_browser_profile2", "lock": "flow_browser_profile2"},
]


# ---- โปรไฟล์เฉพาะของงานดึงลิงก์ Shopee (เจ้าของสั่ง 30 ส.ค. 2569) ----------
#
# *"profile 2 ใช้ เจน google flow ด้วยนิ ไม่ชนกันหรอ"* — ชนจริง เจ้าของจับได้เอง
# แล้วสั่งว่า *"แยก profile เพิ่มอีกอันนึงไปเลย"*
#
# ตอนนี้จึงเป็น **หนึ่งงานหนึ่งโปรไฟล์** ไม่มีใครใช้ร่วมกัน
#
#   flow_browser_profile    ChatGPT (ทำสตอรีบอร์ด)
#   flow_gen_profile        Google Flow ช่อง 1
#   flow_browser_profile2   Google Flow ช่อง 2
#   flow_browser_profile3   Shopee (ดึงลิงก์)          ← ตัวนี้
#
# ⚠️ โปรไฟล์นี้ **ต้องล็อกอิน Shopee ไว้ก่อน** ไม่งั้นเปิดหน้าสินค้าไม่ได้เลย
SHOPEE_PROFILE = "flow_browser_profile3"


def profile_named(name: str) -> Path:
    """โฟลเดอร์โปรไฟล์จากชื่อสั้น เช่น `flow_browser_profile2`

    ใส่พาธเต็มมาก็ได้ — จะคืนพาธนั้นเลย ไม่เอาไปต่อท้าย data/ ซ้ำ
    """
    name = str(name or "").strip()
    if not name:
        return PROFILE_DIR
    path = Path(name)
    return path if path.is_absolute() else DATA_DIR / name


def flow_seat(number: int = 1) -> dict:
    """โฟลเดอร์โปรไฟล์ + ชื่อล็อกของช่องที่ `number` (เริ่มที่ 1)

    เกินจำนวนช่องที่มี = ถอยกลับช่องแรก ไม่โยน error เพราะการถอยไปช่องแรก
    แค่ทำให้ช้าลง ส่วนการล้มทำให้งานทั้งใบหาย
    """
    index = max(1, int(number or 1)) - 1
    seat = FLOW_SEATS[index] if index < len(FLOW_SEATS) else FLOW_SEATS[0]
    folder = (profile_named(seat["profile"]) if seat["profile"]
              else flow_gen_profile_dir())
    lock = seat["lock"]

    # ---- ทุกช่องใช้โฟลเดอร์ของบัญชีที่กำลังใช้อยู่ (เจ้าของสั่ง 10 ก.ย. 2569)
    #
    # **สลับบัญชี = สลับโฟลเดอร์** ไม่ต้องล็อกอินใหม่ ไม่เจอ reCAPTCHA
    # (ลองของจริง 10 ก.ย. แล้ว Google เด้ง reCAPTCHA ทุกครั้งที่ล็อกอิน 3/3 รอบ)
    #
    # ⚠️ **ต้องใช้กับทุกช่อง ไม่ใช่แค่ช่อง 1** — ของเดิมผูกไว้กับช่อง 1
    # แต่ **การเจนคลิปวิ่งช่อง 2 เท่านั้น** (`CLIP_SLOT2_STAGES = {ready_flow}`)
    # ตัวสลับบัญชีจึงไม่มีผลกับเส้นทางจริงเลย เจอจริง 10 ก.ย. 14:26: ไปเปิด
    # `flow_browser_profile2` ที่หลุดล็อกอินไปแล้ว ทั้งที่เพิ่งตั้งค่าบัญชีไว้ 7 ใบ
    # และเจ้าของสั่งห้ามใช้ใบหลัก — ถูกข้ามทั้งคู่
    #
    # ℹ️ **ทุกช่องได้โฟลเดอร์เดียวกัน = ได้ชื่อล็อกเดียวกัน** จึงผลัดกันใช้
    # อย่างถูกต้อง ไม่ใช่เปิด Chrome ทับกันบนโปรไฟล์เดียว แลกกับการที่
    # สองช่องเจนพร้อมกันไม่ได้ — ยอมแลก เพราะเจนผิดบัญชีเสียเครดิตจริง
    # ส่วนเจนช้าลงแค่เสียเวลา
    #
    # ⚠️ **ใช้เฉพาะโฟลเดอร์ที่ล็อกอินค้างไว้จริงแล้ว** ยังไม่พร้อม = ถอยไปของเดิม
    # ไม่งั้นจะไปเปิด Chrome เปล่าๆ แล้วเจนไม่ได้ทั้งกองโดยไม่มีอะไรฟ้อง
    try:
        import flow_accounts                                 # noqa: PLC0415
        email = flow_accounts.current()
        if email and flow_accounts.is_ready(email):
            folder = flow_accounts.profile_dir_of(email)
    except Exception:                                        # noqa: BLE001
        pass                        # อ่านทะเบียนไม่ได้ = ใช้ของเดิม งานไม่ล้ม

    # ⚠️ **ชื่อล็อกต้องมาคู่กับโฟลเดอร์เสมอ** โฟลเดอร์คนละอันแต่ใช้ล็อกดอก
    # เดียวกัน = สองงานเปิด Chrome คนละตัวโดยคิดว่าตัวเองกันกันอยู่
    # ส่วนโฟลเดอร์เดียวกันแต่คนละชื่อล็อก = แย่งโปรไฟล์เดียวกันจน Chrome พัง
    # โฟลเดอร์เดิมจึงต้องได้ชื่อล็อกเดิมเป๊ะๆ ไม่ใช่ชื่อใหม่ที่แปลว่าที่เดียวกัน
    base = (profile_named(seat["profile"]) if seat["profile"]
            else flow_gen_profile_dir())
    if folder != base:
        lock = f"flow-acct-{folder.name}"

    return {"no": index + 1, "dir": folder, "lock": lock}


# ---- เว้นระยะระหว่างการยิง (เจ้าของสั่ง 30 ส.ค. 2569) -----------------------
#
# *"ให้ยิงต่างกัน เว้นอย่างน้อย 10 วิ หลังจากยิงตัวแรก"*
#
# **ทำไมต้องมี** สองช่องเริ่มงานพร้อมกันได้เป๊ะๆ แล้วจะเปิด Chrome สองตัวใน
# วินาทีเดียวกัน + ยิงเข้าเว็บเดียวกันพร้อมกัน ซึ่งเป็นจังหวะที่เครื่องหนักที่สุด
# และดูไม่เหมือนคนใช้งาน
#
# **จองคิวแล้วค่อยนอน** ไม่ใช่นอนทั้งที่ถือล็อก — ถ้าถือล็อกไว้ตอนนอน
# คนที่มาทีหลังจะรอซ้อนกันเป็นทอดๆ แล้วได้ระยะห่างเกินจริง
FIRE_GAP = 10.0
_FIRE_LOCK = threading.Lock()
_FIRE_AT: dict[str, float] = {}


def space_out(service: str, gap: float = FIRE_GAP, log=None) -> float:
    """รอจนกว่าจะห่างจากการยิงครั้งก่อนของบริการนี้อย่างน้อย `gap` วินาที

    คืนจำนวนวินาทีที่รอไป (0 = ยิงได้เลย) แยกตามบริการ — ChatGPT กับ Flow
    เป็นคนละเว็บ ไม่ต้องรอกัน
    """
    with _FIRE_LOCK:
        now = time.monotonic()
        when = max(now, _FIRE_AT.get(service, 0.0) + float(gap))
        _FIRE_AT[service] = when
        wait = when - now
    if wait > 0.05:
        if log:
            log(f"เว้นระยะจากการยิงครั้งก่อน {wait:.0f} วินาที ({service})")
        time.sleep(wait)
    return wait


def flow_gen_profile_dir():
    """โฟลเดอร์โปรไฟล์ที่ใช้เปิด Google Flow

    ตั้งโปรไฟล์บอทไว้ = ตัวนั้นชนะเหมือนเดิม (ยังใช้ร่วมกับ ChatGPT เหมือน
    ก่อนแยก — ตั้งใจ เพราะโปรไฟล์บอทเป็นเรื่องของ "ใช้บัญชีไหน" ไม่ใช่เรื่อง
    "เปิดเว็บไหน" ถ้าจะแยกด้วยต้องแก้ทั้ง bot_profiles ซึ่งเป็นคนละงาน)
    """
    try:
        import studio_shared as shared
        if str((shared.read_config() or {}).get("flow_bot_profile") or "").strip():
            return flow_profile_dir()
    except Exception:                                            # noqa: BLE001
        pass
    return FLOW_GEN_PROFILE

FLOW_URL = "https://labs.google/fx/tools/flow"

# ป้ายปุ่ม/พาธเป็นภาษาตามบัญชี Google ไม่ใช่ตาม URL — บัญชีนี้ตั้งไทยไว้
# (ลอง /fx/en/tools/flow แล้วเด้งกลับ /fx/th/ ทุกครั้ง) จึงต้องจับสองภาษา
# และพาธโปรเจกต์ต้องเผื่อรหัสภาษาคั่น: /fx/th/tools/flow/project/...
NEW_PROJECT_RE = re.compile(r"New project|Create new|โปรเจ็?กต์ใหม่", re.I)
# ⚠️ **Flow มีที่อยู่สองแบบ** (Google ย้ายโดเมนช่วง ก.ย. 2569)
#
#     เก่า  https://labs.google/fx/th/tools/flow/project/<รหัส 36 ตัว>
#     ใหม่  https://flow.google.com/project/<รหัส 36 ตัว>
#
# **ต้องรับทั้งคู่** ยึดแบบเดียวแล้วอีกแบบพังเงียบๆ — เจอจริง 10 ก.ย. 14:30
# เจนคลิปล้มด้วย TimeoutError 45 วินาที ทั้งที่เข้าหน้าโปรเจกต์ถูกต้องแล้ว
# แล้วขึ้นข้อความว่า "หักเครดิตแล้วแต่ไม่คืนคลิป" ซึ่งบอกผิด (เครดิต 50 → 50
# ไม่ได้หักสักหน่วย) ทำให้ไล่ผิดทางไปหาเรื่องแพ็กเกจบัญชีอยู่นาน
PROJECT_PATH_RE = re.compile(
    r"(?:/fx/(?:[a-z]{2}/)?tools/flow|flow\.google\.com)/project/")
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
POLL_SECONDS = 2.0
GENERATE_TIMEOUT_MS = 15 * 60 * 1000  # Flow เจนวิดีโอนานหลายนาที
STEPS = ("prompt", "image", "video")

# แก้ที่เดียวเมื่อ Flow เปลี่ยน UI — อย่ากระจาย selector ไปทั่วไฟล์
FLOW_SELECTORS = {
    # หน้า landing (ยังไม่เข้าแอป) — ใช้เป็นสัญญาณว่ายังไม่ได้ล็อกอิน
    "landing_button_probe": "button:has-text('Create with Google Flow')",
    "enter_app_buttons": ["Create with Google Flow", "Try in Google Flow"],
    # ป้ายไทย/อังกฤษ ดูที่ NEW_PROJECT_RE ด้านบน — ตรงนี้เหลือไว้ให้โค้ดเก่าที่ยังอ้างอยู่
    "new_project_button": "New project",
    # ห้ามใช้จับ URL ตรงๆ อีก: พาธจริงมีรหัสภาษาคั่น (/fx/th/tools/flow/project/)
    # ใช้ PROJECT_PATH_RE แทน
    "project_url_pattern": "tools/flow/project/",
    "prompt_box": "textarea",
    "generate_button": "Generate",
    "image_result": "img[src^='blob:'], img[src*='googleusercontent']",
    "video_result": "video",
    "download_button": "Download",
    "quota_hint": "out of credits",
}


class NeedsLogin(RuntimeError):
    """เจอหน้า login ของ Google — ต้องให้คนล็อกอินเองก่อน"""


class QuotaExhausted(RuntimeError):
    """โควตา Flow หมด ควรหยุดทั้งคิว ไม่ใช่ไล่ fail ทีละงาน"""


# ---------------------------------------------------------------- คีย์ Gemini


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


# ---- คีย์ Gemini หลายใบ (เจ้าของสั่ง 30 ส.ค. 2569) -------------------------
#
# *"ผมจะแอดเป็น 2 API key ทำได้เลยไหม"* — เดิมเก็บได้ใบเดียว พอเครดิตหมด
# ทั้งระบบหยุดทันที (เกิดจริงคืน 29 ส.ค.: Gemini ตอบ
# `Your prepayment credits are depleted` แล้วสายคลิปหยุดยาว)
#
# ⚠️ **คีย์ที่สองต้องอยู่คนละโปรเจกต์คนละบัญชี** เครดิตแบบเติมล่วงหน้าผูกกับ
# โปรเจกต์ ไม่ได้ผูกกับคีย์ — สร้างคีย์ใหม่ในโปรเจกต์เดิมจะกินถังเดียวกัน
# ไม่ช่วยอะไรเลย (เจ้าของยืนยันแล้วว่าเป็นคนละโปรเจกต์คนละบัญชี)
#
# **ทำที่ตัวจ่ายคีย์จุดเดียว** มี 9 ไฟล์ที่ยิงถาม Gemini ถ้าไปใส่ตรรกะสลับคีย์
# ทีละไฟล์จะมี 9 ที่ให้พลาด ตรงนี้เป็นประตูเดียวที่ทุกไฟล์ผ่าน จึงคุมได้ที่เดียว
#
# เก็บหลายใบใน**ไฟล์เดิม** คั่นด้วยขึ้นบรรทัด — ใบเดียวไม่มีขึ้นบรรทัด
# ของเก่าจึงอ่านได้เหมือนเดิมทุกประการ ไม่ต้องแปลงอะไร

# ใบที่ใช้ไม่ได้ชั่วคราว จดไว้ที่นี่ — **เก็บแค่ลายนิ้วมือ ไม่เก็บคีย์จริง**
# ไฟล์นี้ไม่ได้เข้ารหัส ถ้าเก็บคีย์จริงจะกลายเป็นรูรั่วที่เราสร้างเอง
GEMINI_STATE_FILE = GEMINI_KEY_FILE.parent / "gemini_key_state.json"

# พักใบที่มีปัญหานานแค่ไหน — แยกตามชนิดเพราะแก้คนละทาง
#
# **"credits" ลดจาก 12 ชั่วโมงเหลือ 45 นาที เมื่อ 31 ส.ค. 2569** หลังวัดของจริง
# แล้วพบว่าข้อความ "prepayment credits are depleted" **ไม่ได้แปลว่ารอไม่คืน**
#
#   23:41  gemini-3.1-flash-lite-preview · 3.5-flash-lite · 3.6-flash → 429 ทั้งสามตัว
#   01:00  ยิงจริงด้วยคีย์ใบเดิม → **สามตัวนั้นใช้ได้หมด** (5 จาก 9 โมเดลใช้ได้)
#
# คืนเองภายในราว 80 นาที แต่ระบบสั่งพักไว้ 12 ชั่วโมง = ปิดตัวเองทิ้งทั้งคืน
# ทั้งที่ใช้งานได้ ช่วงนั้นตัวเลือกรูปถอยไปใช้ "เลือกแบบกระจาย" ซึ่งไม่ได้ดูรูปเลย
# และตัวแต่งแฮชแท็กถอยไปใช้กฎเดา — กระทบงานทั้งคิว 198 ใบ
#
# **ยังมีจุดอ่อนที่ยังไม่ได้แก้: โทษถูกจดรายคีย์ แต่ปัญหาเกิดรายโมเดล**
# โมเดลหนึ่งเต็มโควตาแล้วทั้งคีย์โดนพัก ทั้งที่โมเดลอื่นบนคีย์เดียวกันยังยิงผ่าน
# (พิสูจน์แล้ว 31 ส.ค.) แก้ให้ถูกต้องคือจดเป็นคู่ (คีย์, โมเดล) ซึ่งต้องแก้
# ทั้ง _key_mark · mark_gemini_key_bad · clear_gemini_key · load_gemini_api_key
# และผู้เรียกทั้ง 3 ไฟล์ — ยังไม่ทำเพราะเสี่ยงทำ Gemini พังทั้งระบบ
GEMINI_REST = {
    "credits": 45 * 60.0,      # ข้อความบอกว่าเครดิตหมด แต่วัดแล้วคืนเองใน ~80 นาที
    "daily": 6 * 3600.0,       # โควตารายวันหมด — คืนข้ามวัน
    "rate": 120.0,             # ยิงถี่เกินไป — เดี๋ยวเดียวก็หาย
}


def _key_mark(key: str) -> str:
    """ลายนิ้วมือของคีย์ ไว้จดสถานะโดยไม่ต้องเก็บคีย์จริง"""
    import hashlib                                            # noqa: PLC0415

    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()[:12]


def _key_state() -> dict:
    import json                                               # noqa: PLC0415

    try:
        return json.loads(GEMINI_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:                                         # noqa: BLE001
        return {}


def _read_key_file() -> str:
    """ถอดรหัสไฟล์คีย์ — คืนข้อความดิบ (อาจมีหลายบรรทัด)"""
    if not GEMINI_KEY_FILE.is_file():
        return ""
    encrypted = GEMINI_KEY_FILE.read_bytes()
    buffer = ctypes.create_string_buffer(encrypted, len(encrypted))
    source = _DataBlob(
        len(encrypted), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
    )
    destination = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(destination)
    )
    if not ok:
        return ""
    try:
        return ctypes.string_at(destination.pbData, destination.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(
            ctypes.cast(destination.pbData, wintypes.HLOCAL)
        )


def load_gemini_keys() -> list[str]:
    """คีย์ทุกใบที่เก็บไว้ เรียงตามลำดับที่ใส่"""
    return [line.strip() for line in _read_key_file().splitlines() if line.strip()]


def gemini_key_board() -> list[dict]:
    """สถานะคีย์ทุกใบให้คนอ่าน — ใบไหนใช้ได้ ใบไหนพักอยู่ เพราะอะไร"""
    import time                                               # noqa: PLC0415

    state = _key_state()
    now = time.time()
    rows = []
    for index, key in enumerate(load_gemini_keys(), 1):
        note = state.get(_key_mark(key)) or {}
        until = float(note.get("until") or 0)
        rows.append({
            "no": index,
            "tail": key[-6:],                 # ปลายคีย์พอให้แยกออกว่าใบไหน
            "ok": until <= now,
            "why": str(note.get("why") or ""),
            "wait_min": max(0, round((until - now) / 60)),
        })
    return rows


def mark_gemini_key_bad(key: str, why: str = "", kind: str = "rate") -> None:
    """จดว่าคีย์ใบนี้ใช้ไม่ได้ชั่วคราว — ครั้งหน้าตัวจ่ายจะข้ามไปใบถัดไปเอง

    `kind` = credits (เครดิตหมด) · daily (โควตารายวัน) · rate (ยิงถี่)
    """
    import json                                               # noqa: PLC0415
    import time                                               # noqa: PLC0415

    if not key:
        return
    # เก็บ **เฉพาะข้อความที่คนอ่านรู้เรื่อง** ไม่ใช่ JSON ดิบทั้งก้อน
    # ไม่งั้นกระดานสถานะจะอ่านไม่ออกเลย
    note = str(why or "")
    if note.lstrip().startswith("{"):
        try:
            note = json.loads(note).get("error", {}).get("message", "") or note
        except Exception:                                     # noqa: BLE001
            pass
    state = _key_state()
    state[_key_mark(key)] = {
        "until": time.time() + GEMINI_REST.get(kind, GEMINI_REST["rate"]),
        "why": note[:200],
        "kind": kind,
    }
    try:
        GEMINI_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def gemini_trouble_kind(body: str) -> str:
    """อ่านคำตอบของ Google แล้วบอกว่าเป็นปัญหาชนิดไหน — ว่างแปลว่าไม่ใช่เรื่องโควตา

    **ต้องแยกให้ออก เพราะแก้คนละทางสิ้นเชิง**
      · เครดิตหมด    รอเท่าไรก็ไม่คืน ต้องเติมเงินหรือสลับคีย์
      · โควตารายวัน  คืนข้ามวัน
      · ยิงถี่        รอไม่กี่วินาทีก็หาย
    ของเดิมจดแค่เลข 429 ทำให้แยกไม่ออก แล้วไปนั่งรอโควตาที่ไม่มีวันคืน
    (เกิดจริง 29 ส.ค. 2569 — เข้าใจผิดว่ารอถึงเที่ยงคืนแล้วจะใช้ได้)
    """
    low = (body or "").lower()
    if "prepayment credits" in low or "credits are depleted" in low:
        return "credits"
    if "billing" in low and "quota" in low:
        return "credits"
    if "perday" in low.replace("_", "").replace(" ", "") or "per day" in low:
        return "daily"
    if "resource_exhausted" in low or "quota" in low:
        return "rate"
    return ""


def clear_gemini_key(key: str) -> None:
    """ปลดโทษคีย์ใบนี้ — เรียกเองได้ หรือถูกเรียกอัตโนมัติเมื่อยิงผ่าน"""
    import json                                               # noqa: PLC0415

    if not key:
        return
    state = _key_state()
    if state.pop(_key_mark(key), None) is None:
        return
    try:
        GEMINI_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def note_gemini_response(key: str, status: int, body: str) -> str:
    """ให้ตัวเรียกส่งคำตอบที่ได้จาก Gemini มาที่นี่ — คืนชนิดปัญหาที่เจอ

    เรียกได้ทุกครั้งไม่ว่าจะสำเร็จหรือไม่ ราคาถูกและปลอดภัย
    """
    if status == 200:
        # **ยิงผ่านเมื่อไร ต้องปลดโทษทันที** ไม่งั้นเติมเงินแล้วคีย์ยังถูกพักต่อ
        # อีก 12 ชั่วโมงโดยไม่มีเหตุผล แล้วเจ้าของจะนึกว่าเติมไปไม่ได้ผล
        clear_gemini_key(key)
        return ""
    kind = gemini_trouble_kind(body)
    if kind:
        # **ส่งข้อความเต็มไป ห้ามตัดก่อน** — ตัวรับต้องแปลง JSON เพื่อดึง
        # ประโยคที่คนอ่านรู้เรื่องออกมา ตัดก่อนแปลงแล้ว JSON จะไม่ครบ
        # แปลงไม่ได้ แล้วหน้าเว็บจะโชว์วงเล็บปีกกาดิบๆ (เจ้าของเห็นเอง 30 ส.ค.)
        mark_gemini_key_bad(key, body or "", kind)
    return kind


def load_gemini_api_key() -> str | None:
    """คีย์ที่ **ใช้ได้ตอนนี้** — มีหลายใบจะข้ามใบที่เพิ่งมีปัญหาให้เอง

    ทุกไฟล์ที่ยิงถาม Gemini เรียกตัวนี้ ไม่ต้องรู้ว่ามีกี่ใบ
    ถ้าทุกใบติดปัญหาหมด **คืนใบที่จะพ้นโทษเร็วที่สุด ไม่คืนค่าว่าง** เพราะ
    "ไม่มีคีย์" กับ "คีย์ติดโควตา" เป็นคนละอาการ ถ้าคืนว่างผู้เรียกจะรายงานว่า
    ยังไม่ได้ตั้งคีย์ ซึ่งพาไปแก้ผิดที่
    """
    import time                                               # noqa: PLC0415

    keys = load_gemini_keys()
    if not keys:
        return None
    if len(keys) == 1:
        return keys[0]
    state, now = _key_state(), time.time()
    ready = [k for k in keys if float((state.get(_key_mark(k)) or {}).get("until") or 0) <= now]
    if ready:
        return ready[0]
    return min(keys, key=lambda k: float((state.get(_key_mark(k)) or {}).get("until") or 0))


def _load_gemini_api_key_single() -> str | None:
    """ตัวอ่านแบบเดิม เก็บไว้เผื่อต้องเทียบ — ไม่ได้ใช้ในสายงานปกติ"""
    if not GEMINI_KEY_FILE.is_file():
        return None
    encrypted = GEMINI_KEY_FILE.read_bytes()
    buffer = ctypes.create_string_buffer(encrypted, len(encrypted))
    source = _DataBlob(
        len(encrypted), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
    )
    destination = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(destination)
    )
    if not ok:
        return None
    try:
        return ctypes.string_at(destination.pbData, destination.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(
            ctypes.cast(destination.pbData, wintypes.HLOCAL)
        )


# ------------------------------------------------------------------- ตัวคิว


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def job_state_path(job_dir: Path) -> Path:
    return job_dir / "state.json"


def read_state(job_dir: Path) -> dict:
    try:
        return json.loads(job_state_path(job_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(job_dir: Path, state: dict) -> None:
    """เขียนแบบ atomic ทุกครั้งที่สถานะเปลี่ยน — ปิดเครื่องกลางคันแล้วทำต่อได้"""
    state["updated_at"] = _now()
    temporary = job_dir / "state.json.tmp"
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(job_state_path(job_dir))


def add_job(
    product: str, detail: str, image: str = "",
    post_tiktok: bool = False, tags: str = "",
) -> Path:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir()
    write_state(
        job_dir,
        {
            "id": job_id,
            "created_at": _now(),
            "status": "pending",
            "done_steps": [],
            "input": {
                "product": product, "detail": detail, "image": image,
                "post_tiktok": post_tiktok, "tags": tags,
            },
            "artifacts": {},
            "error": None,
        },
    )
    return job_dir


def claim_next_job() -> Path | None:
    """หยิบงานที่ยังไม่เสร็จอันเก่าสุด (เรียงตามชื่อโฟลเดอร์ = เวลาสร้าง)"""
    if not JOBS_DIR.is_dir():
        return None
    for job_dir in sorted(JOBS_DIR.iterdir()):
        if not job_dir.is_dir():
            continue
        state = read_state(job_dir)
        # running ค้างจากรอบก่อน (worker ถูกปิดกลางคัน) ให้หยิบมาทำต่อได้
        if state.get("status") in {"pending", "running"}:
            return job_dir
    return None


# ------------------------------------------------------- ขั้นที่ 1: gen prompt


def step_prompt(job_dir: Path, state: dict, demo: bool) -> None:
    product = state["input"]["product"]
    detail = state["input"]["detail"]
    if demo:
        prompt = f"[demo] วิดีโอโฆษณา {product} — {detail}"
    else:
        api_key = load_gemini_api_key()
        if not api_key:
            raise RuntimeError(
                "ยังไม่ได้ใส่ API key ของ Gemini ในเว็บแอป (หน้าตั้งค่า)"
            )
        instruction = (
            "เขียน prompt ภาษาอังกฤษสำหรับสร้างวิดีโอโฆษณาสินค้าความยาว 8 วินาที "
            "บรรยายภาพ มุมกล้อง แสง และอารมณ์ ให้เห็นภาพชัด ตอบกลับเป็น prompt ล้วนๆ "
            f"ไม่ต้องอธิบายเพิ่ม\n\nสินค้า: {product}\nรายละเอียด: {detail}"
        )
        response = httpx.post(
            f"{GEMINI_ENDPOINT}/{GEMINI_MODEL}:generateContent",
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": instruction}]}]},
            timeout=60.0,
        )
        gemini_quota.record(GEMINI_MODEL, ok=response.status_code == 200,
                            response=response)
        if response.status_code != 200:
            raise RuntimeError(f"Gemini ตอบ {response.status_code}: {response.text[:200]}")
        payload = response.json()
        try:
            prompt = payload["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as error:
            raise RuntimeError(f"อ่านคำตอบของ Gemini ไม่ได้: {payload}") from error

    (job_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    state["artifacts"]["prompt"] = "prompt.txt"
    state["prompt"] = prompt


# -------------------------------------------------- ขั้นที่ 2-3: Flow (เบราว์เซอร์)


def _check_page_health(page) -> None:
    body = page.content()
    if FLOW_SELECTORS["quota_hint"].lower() in body.lower():
        raise QuotaExhausted("Flow แจ้งว่าโควตาหมด")
    if page.url.startswith("https://accounts.google.com"):
        # เด้งมาโดเมนนี้ไม่ได้แปลว่าหลุดล็อกอินเสมอไป — ส่วนใหญ่คือหน้าเลือก
        # บัญชีที่รอให้กด เลือกให้ได้ก็ไปต่อได้เลย ไม่ต้องหยุดทั้งงาน
        if _pick_account(page):
            return
        raise NeedsLogin("Flow เด้งไปหน้าล็อกอิน Google")


def _choose_settings(page, kind: str, aspect: str) -> None:
    """ตั้งชนิดผลลัพธ์ (Image/Video) สัดส่วน และจำนวนชิ้น ก่อนสั่งสร้าง

    ปุ่มตั้งค่าไม่มีชื่อคงที่ (ชื่อเปลี่ยนตามโมเดลที่เลือกอยู่ เช่น "🍌 Nano Banana 2")
    จึงจับจากไอคอนสัดส่วนที่ติดมาในชื่อปุ่มเสมอ (crop_16_9 / crop_9_16 ...)
    """
    page.get_by_role("button", name=re.compile(r"crop_", re.I)).first.click()
    page.get_by_role(
        "tab", name=re.compile("Video" if kind == "video" else "Image", re.I)
    ).first.click()
    page.get_by_role("tab", name=re.compile(re.escape(aspect))).first.click()
    # x1 = สร้างชิ้นเดียว ประหยัดเครดิต
    page.get_by_role("tab", name=re.compile(r"^x1$")).first.click()
    page.keyboard.press("Escape")
    time.sleep(1)


def _submit_prompt(page, prompt: str) -> None:
    box = page.locator(FLOW_SELECTORS["prompt_box"]).first
    box.wait_for(state="visible", timeout=30_000)
    box.click()
    box.fill(prompt)
    time.sleep(1)  # ปุ่มส่งเพิ่งเลิก disabled หลังมีข้อความ
    page.get_by_role(
        "button", name=re.compile(r"arrow_forward\s*Create", re.I)
    ).first.click()


def _save_result(page, selector: str, target: Path) -> None:
    """ดึงไฟล์ผลลัพธ์ออกมา

    ลองปุ่มดาวน์โหลดก่อน ถ้าไม่มีค่อยอ่าน src ของ media แล้วโหลดผ่าน
    request ของเบราว์เซอร์ (ติดคุกกี้ไปด้วย ไม่งั้นจะโดนปฏิเสธ)
    """
    element = page.locator(selector).first
    try:
        with page.expect_download(timeout=60_000) as download:
            page.get_by_role(
                "button", name=re.compile(FLOW_SELECTORS["download_button"], re.I)
            ).first.click()
        download.value.save_as(str(target))
        return
    except Exception:
        pass

    source = element.get_attribute("src") or ""
    if not source or source.startswith("blob:"):
        raise RuntimeError(
            f"ดาวน์โหลดผลลัพธ์ไม่ได้ (src={source[:60]!r}) "
            "— ดูโครงหน้าที่ data/flow_failed_dump.txt แล้วแก้ FLOW_SELECTORS"
        )
    response = page.request.get(source)
    if not response.ok:
        raise RuntimeError(f"โหลดไฟล์ผลลัพธ์ไม่สำเร็จ: HTTP {response.status}")
    target.write_bytes(response.body())


def _flow_generate(page, prompt: str, kind: str, target: Path, aspect: str) -> None:
    """ขั้นตอนเดียวกันทั้งรูปและวิดีโอ ต่างกันแค่ชนิดที่เลือกและผลลัพธ์ที่รอ"""
    page = open_project(page)
    _check_page_health(page)
    _choose_settings(page, kind, aspect)
    _submit_prompt(page, prompt)

    selector = (
        FLOW_SELECTORS["video_result"] if kind == "video"
        else FLOW_SELECTORS["image_result"]
    )
    try:
        # รอผลนานได้ แต่ต้องมีเพดาน ไม่งั้นงานเดียวค้างทั้งคิว
        page.locator(selector).first.wait_for(
            state="visible", timeout=GENERATE_TIMEOUT_MS
        )
        _check_page_health(page)
        _save_result(page, selector, target)
    except Exception:
        # เก็บโครงหน้าไว้ให้ไล่แก้ selector ได้ โดยไม่ต้องเจนใหม่ให้เปลืองเครดิต
        try:
            dump_page(page, DATA_DIR / "flow_failed_dump.txt")
        except Exception:
            pass
        raise


def _demo_artifacts(target: Path, kind: str) -> None:
    """โหมด demo: สร้างไฟล์จริงที่เปิดดูได้ เพื่อพิสูจน์ว่าลูปครบวง
    (ใช้ av ที่โปรเจกต์มีอยู่แล้ว ไม่ต้องพึ่ง Flow)"""
    import av

    if kind == "image":
        with av.open(str(target), "w") as container:
            stream = container.add_stream("png")
            stream.width, stream.height = 640, 640
            stream.pix_fmt = "rgb24"
            frame = av.VideoFrame(640, 640, "rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        return

    with av.open(str(target), "w") as container:
        stream = container.add_stream("libx264", rate=24)
        stream.width, stream.height = 640, 640
        stream.pix_fmt = "yuv420p"
        for index in range(48):  # 2 วินาที
            frame = av.VideoFrame(640, 640, "rgb24")
            frame.pts = index
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def step_image(job_dir: Path, state: dict, demo: bool, page) -> None:
    target = job_dir / "image.png"
    if demo:
        _demo_artifacts(target, "image")
    else:
        _flow_generate(page, state["prompt"], FLOW_SELECTORS["image_result"], target)
    state["artifacts"]["image"] = target.name


def step_video(job_dir: Path, state: dict, demo: bool, page) -> None:
    target = job_dir / "video.mp4"
    if demo:
        _demo_artifacts(target, "video")
    else:
        _flow_generate(
            page,
            state["prompt"] + "\n(animate the generated image)",
            FLOW_SELECTORS["video_result"],
            target,
        )
    state["artifacts"]["video"] = target.name


# --------------------------------------------------------------- ลูปของ worker


def run_job(job_dir: Path, page, demo: bool) -> None:
    state = read_state(job_dir)
    state["status"] = "running"
    write_state(job_dir, state)
    print(f"  งาน {state['id']} — {state['input']['product']}")

    if not demo:
        # ของจริงใช้ pipeline 4 ซีนที่พอร์ตมาจากระบบเดิมทั้งชุด
        import flow_pipeline

        api_key = load_gemini_api_key()
        if not api_key:
            raise RuntimeError("ยังไม่ได้ใส่ API key ของ Gemini ในเว็บแอป (หน้าตั้งค่า)")
        summary = flow_pipeline.run_pipeline(
            page,
            api_key,
            GEMINI_MODEL,
            state["input"]["product"],
            state["input"].get("detail", ""),
            job_dir,
            project_url=state.get("project_url", ""),
            projects=state.get("projects") or {},
            product_image=(
                Path(state["input"]["image"])
                if state["input"].get("image") else None
            ),
            scenes=state.get("scenes"),
            only_missing=bool(state.get("done_steps")),
            post_tiktok=bool(state["input"].get("post_tiktok")),
            tiktok_tags=[t for t in state["input"].get("tags", "").split() if t],
            log=lambda message: print(f"    {message}", flush=True),
        )
        state["scenes"] = summary.get("scenes")
        state["project_url"] = summary.get("project_url", "")
        state["projects"] = summary.get("projects") or {}
        state["artifacts"]["video"] = summary.get("video")
        state["errors"] = summary.get("errors") or {}
        state["done_steps"] = ["prompt", "image", "video"]
        state["status"] = "done" if not state["errors"] else "failed"
        state["error"] = None if not state["errors"] else str(state["errors"])
        write_state(job_dir, state)
        print(f"  {'✅' if state['status'] == 'done' else '⚠️'} {job_dir}")
        return

    handlers = {"prompt": step_prompt, "image": step_image, "video": step_video}
    for step in STEPS:
        if step in state.get("done_steps", []):
            print(f"    ข้าม {step} (ทำไว้แล้ว)")
            continue
        print(f"    {step}…", end="", flush=True)
        started = time.perf_counter()
        if step == "prompt":
            handlers[step](job_dir, state, demo)
        else:
            handlers[step](job_dir, state, demo, page)
        state.setdefault("done_steps", []).append(step)
        # เซฟทุกขั้น ไม่ใช่ตอนจบ — พังขั้นถัดไปก็ไม่ต้องทำขั้นนี้ซ้ำ
        write_state(job_dir, state)
        print(f" เสร็จ ({time.perf_counter() - started:.1f} วิ)")

    state["status"] = "done"
    state["error"] = None
    write_state(job_dir, state)
    print(f"  ✅ เสร็จทั้งงาน → {job_dir}")


# ---- ด่านตรวจแพ็กเกจบัญชี Flow (เจ้าของสั่ง 30 ส.ค. 2569) ------------------
#
# *"ก่อนใช้ google flow ให้เช็คว่า profile ต้องขึ้น ultra แบบนี้เสมอ
# ถ้าไม่มีให้แจ้งเตือน ว่าต้องเปลี่ยนบัญชี"*
#
# **ทำไมต้องตรวจ** โปรไฟล์หนึ่งล็อกอินได้หลายบัญชี และ Chrome เลือกบัญชีล่าสุด
# ให้เอง ถ้าเผลอไปอยู่บัญชีที่ไม่ใช่ Ultra งานจะเดินต่อจนถึงขั้นกดเจน แล้วค่อยล้ม
# หรือแย่กว่านั้นคือ **เจนด้วยบัญชีผิด** ซึ่งถอนไม่ได้
#
# **ตรวจของที่มีเฉพาะตอนถูก ไม่ใช่ของที่แปลว่าผิด** (กติกาข้อ 2.3.1) —
# มองหาป้ายคำว่า ULTRA บนแถบบนสุดจริงๆ ไม่ใช่ "ไม่เจอคำว่า Free"
#
# **ห้ามยึดชื่อคลาส** ของจริงเป็น `div.sc-355d1ae3-8.ktpcbJ` ซึ่งเป็นรหัสสุ่มที่
# เปลี่ยนทุกครั้งที่ Google ปล่อยเวอร์ชันใหม่ — ยึดตำแหน่ง (แถบบนสุด) กับข้อความ
# ที่ตรงเป๊ะทั้งคำแทน วัดของจริง 30 ส.ค.: ป้ายอยู่ที่ y=28 สูง 24 กว้าง 53
_BADGE_JS = """() => {
  const out = [];
  for (const el of document.querySelectorAll('div, span, button, a, p')) {
    if (el.children.length) continue;
    const text = (el.textContent || '').trim();
    if (!text || text.length > 12) continue;
    const box = el.getBoundingClientRect();
    // เฉพาะแถบบนสุด และต้องมองเห็นจริง (กว้าง/สูงมากกว่าศูนย์)
    if (box.top < 0 || box.top > 140) continue;
    if (box.width < 16 || box.width > 220 || box.height < 8) continue;
    out.push(text);
  }
  return out;
}"""

# แพ็กเกจที่ยอมให้ใช้เจนคลิปได้ — เจ้าของสั่งไว้ว่าต้องเป็น Ultra เท่านั้น
FLOW_PLAN_REQUIRED = "ULTRA"


class WrongFlowPlan(RuntimeError):
    """บัญชีที่ล็อกอินอยู่ไม่ใช่แพ็กเกจที่ต้องใช้ — ต้องเปลี่ยนบัญชีก่อน"""


def flow_plan_badge(page, tries: int = 5, gap: float = 2.0) -> str:
    """อ่านป้ายแพ็กเกจบนแถบบนของหน้า Flow — คืน "ULTRA" / "PRO" / "" ถ้าไม่เจอ

    ลองซ้ำหลายรอบเพราะแถบบนโหลดช้ากว่าตัวหน้า — ตัดสินจากรอบเดียวจะได้ค่าว่าง
    ทั้งที่ป้ายกำลังจะขึ้น แล้วไปฟ้องว่าบัญชีผิดทั้งที่ถูก
    """
    known = ("ULTRA", "PRO", "PREMIUM", "FREE", "BASIC")
    for attempt in range(max(1, tries)):
        try:
            words = page.evaluate(_BADGE_JS) or []
        except Exception:                                        # noqa: BLE001
            words = []
        for word in words:
            up = str(word).strip().upper()
            if up in known:
                return up
        if attempt < tries - 1:
            time.sleep(gap)
    return ""


def require_flow_plan(page, seat_name: str = "", log=print) -> str:
    """บอกว่าบัญชีที่ล็อกอินอยู่เป็นแพ็กเกจอะไร — **ไม่หยุดงานแล้ว**

    **เจ้าของสั่งปลดด่านนี้ 10 ก.ย. 2569** — *"ลบเงื่อนไข ultra ออก"*

    ที่มาของด่านเดิม: ใส่ไว้ 30 ส.ค. ตอนมีบัญชี ULTRA ใบเดียว การเจนด้วย
    บัญชีอื่นจึงเป็นความผิดพลาดเสมอ **ตอนนี้คนละสถานการณ์** — มีบัญชีสำรอง
    6 ใบที่ตั้งใจเอามาใช้จริง และเจ้าของสั่งห้ามใช้ใบ ULTRA ด่านเดิมจึงกลาย
    เป็นตัวขวางคำสั่งแทนที่จะกันความผิดพลาด

    ตรวจของจริง 10 ก.ย. ก่อนปลด
        ko…e9  ULTRA          1,103 เครดิต   ← ใบเดียวที่เป็น ULTRA
        ko…c9  (ไม่เจอป้าย)      50 เครดิต   ← แพ็กเกจฟรี

    ⚠️ **ยังอ่านป้ายแล้วเขียน log อยู่ แค่ไม่หยุดงาน** (กติกาข้อ 2.4 ห้ามเงียบ)
    คลิปออกมาไม่ดีเมื่อไร จะได้ย้อนดูได้ว่ารอบนั้นใช้แพ็กเกจอะไร ส่วนด่านตรวจ
    ความละเอียดไฟล์ที่ได้จริงยังทำงานตามเดิม — คลิป 360p ยังถูกจับได้อยู่
    """
    badge = flow_plan_badge(page)
    where = f" ({seat_name})" if seat_name else ""
    if badge == FLOW_PLAN_REQUIRED:
        log(f"บัญชี Flow{where}: {badge} ✅")
    elif badge:
        log(f"บัญชี Flow{where}: แพ็กเกจ {badge} (ไม่ใช่ {FLOW_PLAN_REQUIRED}) "
            f"— เจ้าของสั่งให้เจนต่อได้ ไม่หยุด")
    else:
        log(f"บัญชี Flow{where}: อ่านป้ายแพ็กเกจไม่ได้ "
            f"— เจ้าของสั่งให้เจนต่อได้ ไม่หยุด")
    return badge


def flow_profile_dir() -> Path:
    """โฟลเดอร์โปรไฟล์ที่สาย Flow จะใช้

    ตั้ง `flow_bot_profile` ใน config.json เป็น id ของโปรไฟล์บอทได้ —
    จะได้ใช้ล็อกอินจากฟาร์มโปรไฟล์ (bot_profiles.py) แทนโปรไฟล์เดี่ยวตัวเดิม
    ข้อดีคือคนละโฟลเดอร์ = คนละโปรเซส รันขนานกับงานอื่นได้

    ก่อนใช้จะดึงไฟล์ล็อกอินล่าสุดจากโปรไฟล์ Chrome ต้นทางมาทับให้ (ถ้าเปิด
    auto_refresh) เพราะคุกกี้ Google หมดอายุเร็ว ถ้าใช้ของที่ก๊อปไว้วันก่อน
    จะเด้งหน้าล็อกอินแล้วงานทั้งคิวหยุด

    ตั้งค่าไม่ได้/หาโปรไฟล์ไม่เจอ → ถอยไปใช้โปรไฟล์เดิม ไม่ทำให้ทั้งงานล้ม
    """
    try:
        import studio_shared as shared
        bot_id = str((shared.read_config() or {}).get("flow_bot_profile") or "").strip()
    except Exception:
        bot_id = ""
    if not bot_id:
        return PROFILE_DIR
    try:
        import bot_profiles

        farm = bot_profiles.ProfileFarm(DATA_DIR)
        path = farm.user_data_dir(bot_id)
        entry = next(
            (item for item in farm.list_profiles()["profiles"] if item["id"] == bot_id),
            None,
        )
        if entry and entry.get("running"):
            raise RuntimeError(
                f"โปรไฟล์บอท {entry['name']} เปิดอยู่ — ปิดก่อนแล้วค่อยสั่งใหม่"
            )
        if entry and entry.get("auto_refresh"):
            result = farm.refresh_from_source(bot_id)
            if not result.get("refreshed"):
                print(
                    f"  ⚠ ดึงล็อกอินล่าสุดของ {entry['name']} ไม่ได้"
                    f" ({result.get('reason', 'ไม่ทราบสาเหตุ')}) — ใช้ของที่ก๊อปไว้เดิม",
                    flush=True,
                )
        print(f"  ใช้โปรไฟล์บอท: {entry['name'] if entry else bot_id}", flush=True)
        return path
    except RuntimeError:
        raise
    except Exception as error:
        # ห้ามถอยไปโปรไฟล์อื่นเงียบๆ — คนละโปรไฟล์ = คนละบัญชี Google =
        # ไปตัดเครดิต Flow ของบัญชีที่ไม่ได้ตั้งใจ
        #
        # เจอจริง: config ชี้ไป b7e2355d ซึ่งถูกลบไปตอนสร้างฟาร์มโปรไฟล์ใหม่
        # ระบบถอยไปใช้โปรไฟล์เดิมโดยบอกแค่ทาง stdout ที่ไม่มีใครเห็น แล้วไป
        # โผล่เป็นอาการ "Flow ยังไม่ได้ล็อกอิน" ให้ไล่หาสาเหตุกันคนละทาง
        raise RuntimeError(
            f"โปรไฟล์บอทที่ตั้งไว้ ({bot_id}) ใช้ไม่ได้: {error} — "
            "ไปตั้ง flow_bot_profile ใหม่ที่หน้าตั้งค่า "
            "(เว้นว่าง = ใช้โปรไฟล์ Flow เดี่ยวตัวเดิม)"
        ) from error


def open_browser(playwright, hidden: bool = False, profile_dir=None,
                 position=None):
    """เปิด Chrome ตัวจริงพร้อมโปรไฟล์ถาวร

    - headless=False จำเป็น Google ตรวจจับ headless แล้วบล็อก
    - channel="chrome" ใช้ Chrome ที่ติดตั้งในเครื่อง ไม่ใช่ Chromium ของ Playwright
      เพราะหน้าล็อกอิน Google มักปฏิเสธ Chromium ด้วยข้อความ
      "This browser or app may not be secure"
    - ปิด flag ที่ประกาศตัวว่าเป็นระบบอัตโนมัติ ลดโอกาสโดนสกัด
    """
    # ไม่ระบุมา = โปรไฟล์เดิม (ChatGPT · TikTok · Shopee) ของเดิมจึงไม่เปลี่ยน
    profile_dir = Path(profile_dir) if profile_dir else flow_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    args = [
        "--disable-blink-features=AutomationControlled",
        # ปิดเสียง — คลิปที่ Flow เจนเสร็จเล่นตัวอย่างเองพร้อมเสียง
        "--mute-audio",
        # บังคับโฟลเดอร์โปรไฟล์ให้ชัด ไม่ปล่อยให้ Chrome เลือกเองจาก Local State
        #
        # เจอจริง: โปรไฟล์บอทก๊อป Local State ของเครื่องต้นทางมาทั้งก้อน ซึ่งมี
        # info_cache/profiles_order ที่พูดถึงโฟลเดอร์อย่าง "Profile 15" ที่ไม่มี
        # อยู่ในสำเนา ถ้าไม่ระบุตรงนี้ Chrome อาจไปเปิดโฟลเดอร์อื่นหรือสร้างใหม่
        # แล้วได้หน้าต่างที่ไม่มีล็อกอินโดยไม่มีอะไรฟ้อง
        "--profile-directory=Default",
    ]
    if hidden:
        # ซ่อนไปนอกจอ ใช้ตอนรันคิวยาวๆ ที่ไม่ต้องดู (ห้ามใช้ตอนล็อกอิน)
        args.append("--window-position=-32000,-32000")
    else:
        # **ต้องบังคับตำแหน่งกลับมาในจอ ไม่ใช่แค่ไม่ใส่ค่าซ่อน**
        #
        # เจอจริง 28 ส.ค. 2569: หน้าต่างที่เปิดให้เจ้าของล็อกอินไปโผล่ที่
        # x=-1570 ซึ่งอยู่นอกจอทุกจอ เจ้าของมองไม่เห็นเลยทั้งที่ระบบขึ้นว่า
        # "เปิดหน้าต่างให้แล้ว" — เพราะ Chrome **จำตำแหน่งหน้าต่างล่าสุด**
        # ของโปรไฟล์นั้นไว้ ซึ่งคือตำแหน่งซ่อนจากรอบก่อน
        #
        # ตั้งแต่ตำแหน่งอย่างเดียว **ไม่ตั้งขนาด** — ขนาดหน้าต่างเปลี่ยน
        # การจัดหน้าของเว็บ ซึ่งอาจทำให้ตัวหาปุ่มที่ใช้ได้อยู่แล้วหาไม่เจอ
        #
        # ระบุ `position` มาได้ตอนเปิดหลายหน้าต่างพร้อมกัน — ไม่งั้นทุกใบ
        # ไปกองซ้อนกันที่จุดเดียว เจ้าของเห็นแค่ใบบนสุดใบเดียว
        # (เจ้าของสั่ง 10 ก.ย. 2569 — *"เด้ง chrome มา 7 หน้าเลย"*)
        left, top = position if position else (80, 60)
        args.append(f"--window-position={int(left)},{int(top)}")
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        channel="chrome",
        headless=False,
        args=args,
        accept_downloads=True,
        no_viewport=True,
    )


def _is_signed_in(page) -> bool:
    """ตรวจจาก "มีหน้าแอปจริงหรือยัง" ไม่ใช่จาก "ไม่มีปุ่ม Sign in"

    หน้า landing ของ Flow ไม่มีปุ่ม Sign in เลย (มีแค่ Create with Google Flow)
    ถ้าตรวจแบบหลังจะเข้าใจผิดว่าล็อกอินแล้วตั้งแต่ยังไม่ได้ล็อกอิน
    """
    if "accounts.google.com" in page.url:
        return False
    try:
        if page.locator(FLOW_SELECTORS["landing_button_probe"]).count() > 0:
            return False
        # อยู่ในโปรเจกต์แล้ว = เข้าแอปได้แน่นอน
        if PROJECT_PATH_RE.search(page.url):
            return True
        # ต้องเจอ **สัญญาณของแอปจริง** เท่านั้น
        #
        # เดิมเจอ textarea หรือ contenteditable ที่ไหนก็ตัดสินว่าล็อกอินแล้ว —
        # หน้า landing ก็มีของพวกนี้ ผลคือรายงาน "LOGIN OK" ทั้งที่ยังไม่ได้เข้าแอป
        # เลยสักครั้ง (เจอจริง: ตอบ LOGIN OK แต่พอเปิดจริงเด้งไป accountchooser)
        # ตัวเช็คที่บอกว่า "ผ่าน" ทั้งที่ยังไม่ผ่าน อันตรายกว่าไม่มีตัวเช็คเลย
        if page.get_by_role("button", name=NEW_PROJECT_RE).count() > 0:
            return True
        return False
    except Exception:
        return False


def flow_account() -> str:
    """อีเมลบัญชี Google ที่สาย Flow ต้องใช้ (ตั้งที่ `flow_account` ใน config)"""
    try:
        import studio_shared as shared

        return str((shared.read_config() or {}).get("flow_account") or "").strip()
    except Exception:
        return ""


def _account_rows(page) -> dict:
    """รายชื่อบัญชีบนหน้า "Choose an account" → {อีเมล: ตัวกด}"""
    rows = {}
    found = page.locator("[data-identifier]")
    for index in range(found.count()):
        item = found.nth(index)
        email = (item.get_attribute("data-identifier") or "").strip()
        if email:
            rows[email] = item
    return rows


def _pick_account(page) -> bool:
    """อยู่หน้า "เลือกบัญชี" ของ Google → กดเลือกให้เอง คืน True ถ้ากดไปแล้ว

    ล็อกอินไว้หลายบัญชีในโปรไฟล์เดียว Google จะไม่ปล่อยผ่าน แต่หยุดถามก่อนว่า
    จะใช้บัญชีไหน หน้านั้นอยู่บนโดเมน accounts.google.com ตัวเช็คล็อกอินเลย
    ตัดสินว่า "ยังไม่ได้ล็อกอิน" ทั้งที่ล็อกอินครบทุกบัญชี — เจอจริง 3 บัญชี
    (milk0650361448 / komchand9 / komchane9) แล้วคิวหยุดค้างโดยข้อความบอกผิดทาง

    ไม่เดาบัญชีเองเมื่อมีให้เลือกหลายตัว เพราะแต่ละบัญชีมีเครดิต Flow แยกกัน
    กดผิดตัว = ไปตัดเครดิตของบัญชีที่ไม่ได้ตั้งใจ
    """
    if "accounts.google.com" not in page.url:
        return False
    try:
        rows = _account_rows(page)
    except Exception:
        return False
    if not rows:
        return False

    wanted = flow_account()
    if wanted and wanted not in rows:
        raise NeedsLogin(
            f"หน้าเลือกบัญชีไม่มี {wanted} — ที่มีให้เลือกคือ {', '.join(rows)}"
        )
    if not wanted:
        if len(rows) > 1:
            raise NeedsLogin(
                f"โปรไฟล์นี้ล็อกอิน Google ไว้ {len(rows)} บัญชี "
                f"({', '.join(rows)}) เลยค้างที่หน้าเลือกบัญชี — "
                "ตั้ง flow_account ว่าจะใช้บัญชีไหน"
            )
        wanted = next(iter(rows))

    print(f"  เลือกบัญชี Google: {wanted}", flush=True)
    rows[wanted].click()
    page.wait_for_load_state("domcontentloaded", timeout=60_000)
    time.sleep(3)
    return True


def _enter_app(page) -> None:
    """หน้า landing ต้องกดเข้าแอปก่อน ถึงจะเจอหน้าล็อกอิน/หน้าทำงาน"""
    for name in FLOW_SELECTORS["enter_app_buttons"]:
        button = page.get_by_role("button", name=name, exact=False).first
        try:
            if button.count() and button.is_visible():
                button.click()
                page.wait_for_load_state("domcontentloaded", timeout=60_000)
                return
        except Exception:
            continue


def _app_page(browser, fallback):
    """คืนแท็บที่เป็นหน้าแอปจริง — ปุ่มเข้าแอปของ Flow เปิดแท็บใหม่
    ถ้าไปยึดแท็บแรกไว้จะเฝ้าหน้าที่ไม่มีอะไรเกิดขึ้น"""
    for _ in range(12):
        pages = [item for item in browser.pages if not item.is_closed()]
        signed = next((item for item in pages if _is_signed_in(item)), None)
        if signed is not None:
            return signed
        # ค้างที่หน้าเลือกบัญชี = รอให้กดเฉยๆ ไม่ใช่หลุดล็อกอิน กดให้แล้ววนต่อ
        if any(_pick_account(item) for item in pages):
            continue
        if any(
            item.locator(FLOW_SELECTORS["landing_button_probe"]).count()
            for item in pages
        ):
            _enter_app(pages[-1])
        time.sleep(2)
    return fallback


def dump_page(page, target: Path) -> None:
    """ดูดโครงหน้าจริงมาเก็บไว้ ใช้เขียน/ซ่อม selector เวลา Flow เปลี่ยน UI"""
    lines = [f"URL: {page.url}", f"TITLE: {page.title()}", ""]
    try:
        lines.append("=== ARIA SNAPSHOT ===")
        lines.append(page.locator("body").aria_snapshot())
    except Exception as error:
        lines.append(f"(aria_snapshot ใช้ไม่ได้: {error})")

    lines.append("\n=== ปุ่มทั้งหมด ===")
    for index in range(min(page.get_by_role("button").count(), 60)):
        button = page.get_by_role("button").nth(index)
        try:
            name = (button.get_attribute("aria-label") or button.inner_text() or "").strip()
            lines.append(f"[{index}] {name[:80]!r} visible={button.is_visible()}")
        except Exception:
            continue

    lines.append("\n=== ช่องกรอกข้อความ ===")
    for selector in ("textarea", "input[type=text]", "[contenteditable=true]"):
        found = page.locator(selector)
        for index in range(min(found.count(), 15)):
            item = found.nth(index)
            try:
                lines.append(
                    f"{selector}[{index}] placeholder="
                    f"{item.get_attribute('placeholder')!r} "
                    f"aria-label={item.get_attribute('aria-label')!r} "
                    f"visible={item.is_visible()}"
                )
            except Exception:
                continue

    target.write_text("\n".join(lines), encoding="utf-8")


def login_flow(wait_minutes: int) -> int:
    """เปิดหน้าต่างให้ผู้ใช้ล็อกอิน Google เอง แล้วรอจนล็อกอินเสร็จ

    ผู้ใช้เป็นคนกรอกรหัสเองเท่านั้น worker แค่เปิดหน้าต่างและรอ
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=False,
                                 profile_dir=flow_gen_profile_dir())
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=90_000)
        _enter_app(page)
        print("เปิดหน้าต่าง Chrome แล้ว — กรุณาล็อกอิน Google ในหน้าต่างนั้น", flush=True)
        print(f"(รอสูงสุด {wait_minutes} นาที ตรวจสถานะทุก 5 วินาที)", flush=True)

        deadline = time.time() + wait_minutes * 60
        reported = ""
        while time.time() < deadline:
            # ปุ่มเข้าแอปเปิดแท็บใหม่ ต้องดูทุกแท็บ ไม่ใช่แค่ตัวที่เปิดตอนแรก
            pages = [item for item in browser.pages if not item.is_closed()]
            urls = " | ".join(item.url[:70] for item in pages)
            if urls != reported:
                reported = urls
                print(f"  แท็บ: {urls}", flush=True)
            for item in pages:
                try:
                    if _pick_account(item):
                        break
                except NeedsLogin as error:
                    # ตั้งบัญชีไว้ผิด/ไม่ได้ตั้ง — บอกให้รู้ทันที ไม่ปล่อยรอจนหมดเวลา
                    print(f"หยุดรอ — {error}", flush=True)
                    browser.close()
                    return 1
            signed = next((item for item in pages if _is_signed_in(item)), None)
            if signed is not None:
                print(f"LOGIN OK — url={signed.url}", flush=True)
                time.sleep(3)  # เผื่อหน้าโหลดส่วนที่เหลือ
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                dump_page(signed, DATA_DIR / "flow_page_dump.txt")
                print(f"บันทึกโครงหน้าไว้ที่ {DATA_DIR / 'flow_page_dump.txt'}", flush=True)
                browser.close()
                return 0
            time.sleep(5)
        print("TIMEOUT — ยังไม่ได้ล็อกอิน", flush=True)
        browser.close()
        return 1


def open_project(page):
    """เข้าโปรเจกต์ใหม่ — ที่ทำงานจริงของ Flow อยู่ข้างในโปรเจกต์
    หน้าแดชบอร์ดมีแค่รายการโปรเจกต์ ไม่มีช่องพิมพ์ prompt"""
    if FLOW_SELECTORS["project_url_pattern"] in page.url:
        return page
    page.get_by_role(
        "button", name=NEW_PROJECT_RE
    ).first.click()
    page.wait_for_url(f"**{FLOW_SELECTORS['project_url_pattern']}**", timeout=60_000)
    page.wait_for_load_state("domcontentloaded", timeout=60_000)
    time.sleep(4)  # ตัวแก้ไขโหลดต่อหลัง DOM พร้อม
    return page


def inspect_flow(click: str = "", name: str = "project") -> int:
    """เปิดโปรเจกต์จริงแล้วดูดโครงหน้า ใช้เขียน/ซ่อม selector ของขั้นเจน
    --click ใช้กดปุ่มก่อนดูด เช่นเปิดเมนูเลือกโมเดลแล้วดูว่ามีอะไรบ้าง"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=False,
                                 profile_dir=flow_gen_profile_dir())
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=90_000)
        page = _app_page(browser, page)
        if not _is_signed_in(page):
            print("ยังไม่ได้ล็อกอิน — รัน login ก่อน", flush=True)
            browser.close()
            return 1
        page = open_project(page)
        print(f"เข้าโปรเจกต์แล้ว: {page.url}", flush=True)
        if click:
            page.get_by_role("button", name=click, exact=False).first.click()
            time.sleep(2)
            print(f"กดปุ่ม {click!r} แล้ว", flush=True)
        target = DATA_DIR / f"flow_{name}_dump.txt"
        dump_page(page, target)
        print(f"บันทึกโครงหน้าไว้ที่ {target}", flush=True)
        browser.close()
        return 0


def login_tiktok(wait_minutes: int) -> int:
    """เปิดหน้าต่างให้ผู้ใช้ล็อกอิน TikTok เองในโปรไฟล์เดียวกับ Flow

    ใช้โปรไฟล์เดียวกันได้เพราะคนละเว็บ คุกกี้อยู่ร่วมกันไม่ชนกัน
    ล็อกอินครั้งเดียวใช้ได้ยาว เหมือน Google
    """
    from playwright.sync_api import sync_playwright

    import tiktok_post

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=False)
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(tiktok_post.UPLOAD_URL, wait_until="domcontentloaded", timeout=90_000)
        print("เปิดหน้าต่างแล้ว — กรุณาล็อกอิน TikTok ในหน้าต่างนั้น", flush=True)
        print(f"(รอสูงสุด {wait_minutes} นาที)", flush=True)
        poster = tiktok_post.TikTokPoster(page, log=lambda m: print("   ", m, flush=True))
        deadline = time.time() + wait_minutes * 60
        reported = ""
        while time.time() < deadline:
            state = poster.state()
            if state["url"] != reported:
                reported = state["url"]
                print(f"  อยู่ที่: {reported[:90]}", flush=True)
            if not state["signedOut"] and "/tiktokstudio" in state["url"]:
                print("LOGIN OK — พร้อมโพสต์แล้ว", flush=True)
                browser.close()
                return 0
            time.sleep(5)
        print("TIMEOUT — ยังไม่ได้ล็อกอิน", flush=True)
        browser.close()
        return 1


def login_chatgpt(wait_minutes: int) -> int:
    """เปิดหน้าต่างให้ล็อกอิน ChatGPT เอง เก็บคุกกี้ไว้ในโปรไฟล์เดียวกับตัวอื่น"""
    from playwright.sync_api import sync_playwright

    import chatgpt_driver

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=False)
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(chatgpt_driver.CHATGPT_HOME, wait_until="domcontentloaded", timeout=90_000)
        print("เปิดหน้าต่างแล้ว — ล็อกอิน ChatGPT ในหน้าต่างนั้น", flush=True)
        print(f"(รอสูงสุด {wait_minutes} นาที)", flush=True)
        session = chatgpt_driver.ChatGPTSession(page, log=lambda m: print("   ", m, flush=True))
        deadline = time.time() + wait_minutes * 60
        while time.time() < deadline:
            # อ่านสถานะพลาดระหว่างล็อกอินเป็นเรื่องปกติ ห้ามให้ล้มทั้งคำสั่ง:
            #   "Execution context was destroyed" = หน้าเปลี่ยนพอดีตอนอ่าน
            #       เกิดทุกครั้งที่กดปุ่มล็อกอิน → รอแล้วอ่านใหม่
            #   "Target ... closed"              = ผู้ใช้ปิดหน้าต่างเอง → จบพร้อมบอกเหตุ
            # (เจอจริง: กดล็อกอินแล้วคำสั่งพังทิ้ง traceback หน้าต่างปิดหายไปเลย)
            try:
                state = session.state()
            except Exception as error:
                if "closed" in str(error).lower():
                    print("หน้าต่างถูกปิด — ยังไม่ได้ล็อกอิน", flush=True)
                    return 1
                time.sleep(3)
                continue
            if not state["signedOut"] and state["hasBox"]:
                print("LOGIN OK — ใช้ขั้น ChatGPT ได้แล้ว", flush=True)
                browser.close()
                return 0
            time.sleep(5)
        print("TIMEOUT — ยังไม่ได้ล็อกอิน", flush=True)
        browser.close()
        return 1


def clone_profile(source: str, target: str) -> int:
    """ก๊อปโปรไฟล์ Chrome ทั้งก้อน — **ล็อกอินเดิมติดไปด้วย ไม่ต้องล็อกอินใหม่**

    **เจ้าของถาม 30 ส.ค. 2569** — *"ดึงล้อคอินเดิมมาไม่ได้หรอ"* ได้ และเป็นวิธี
    ที่โปรเจกต์นี้ใช้ตอนสร้าง `flow_gen_profile` มาแล้ว (ดูคำอธิบายหัวไฟล์)
    แต่ตอนนั้นทำด้วยมือ ครั้งนี้ทำเป็นคำสั่งถาวรจะได้ทำซ้ำได้และไม่พลาดขั้นตอน

    **ขั้นตอนที่ห้ามข้าม**
      1. ต้องถือล็อกของ **ทั้งต้นทางและปลายทาง** — ก๊อปตอน Chrome ยังเปิดอยู่
         จะได้ไฟล์ครึ่งๆ กลางๆ แล้วโปรไฟล์ใหม่เปิดไม่ขึ้นหรือคุกกี้ใช้ไม่ได้
      2. ข้ามไฟล์ล็อกของ Chrome เอง (`Singleton*` · `*.lock` · `Crashpad`)
         พวกนี้ผูกกับโปรเซสเดิม ก๊อปไปแล้วโปรไฟล์ใหม่จะนึกว่ามีคนใช้อยู่
      3. ปลายทางที่มีของอยู่แล้วต้อง **ลบทิ้งก่อน** ไม่ใช่ทับทีละไฟล์ —
         ของเก่าที่ค้างอยู่จะทำให้คุกกี้สองชุดปนกัน
    """
    import shutil                                               # noqa: PLC0415

    import studio_shared                                        # noqa: PLC0415

    src = profile_named(source)
    dst = profile_named(target)
    if not src.is_dir():
        print(f"ไม่มีโปรไฟล์ต้นทาง {src}", flush=True)
        return 1
    if src == dst:
        print("ต้นทางกับปลายทางเป็นตัวเดียวกัน", flush=True)
        return 1
    skip = shutil.ignore_patterns("Singleton*", "*.lock", "Crashpad",
                                  "*.tmp", "GPUCache", "ShaderCache")
    print(f"ก๊อป {src.name} → {dst.name}", flush=True)
    with studio_shared.browser_lock(label=f"ก๊อปโปรไฟล์ {source}", profile=source):
        with studio_shared.browser_lock(label=f"ก๊อปโปรไฟล์ {target}", profile=target):
            if dst.exists():
                print(f"  ลบของเดิมใน {dst.name} ก่อน", flush=True)
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst, ignore=skip, dirs_exist_ok=True)
    size = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file())
    print(f"เสร็จ — {dst.name} ขนาด {size / 1024 / 1024:,.0f} MB", flush=True)
    print("ล็อกอินเดิมติดมาด้วยแล้ว ไม่ต้องล็อกอินใหม่", flush=True)
    return 0


def login_slot(wait_minutes: int, slot: int = 2) -> int:
    """เปิดหน้าต่างโปรไฟล์ของช่องนั้นให้ล็อกอินเอง **ทั้ง ChatGPT และ Google Flow**

    **เจ้าของสั่ง 30 ส.ค. 2569** — *"chrome profile 2 ผมจะ log-in google flow
    ไว้ด้วย ให้สามารถเจนคลิปจากโปรไฟล์นั้นได้ด้วยนะ"*

    ช่องที่ 2 ขึ้นไปใช้โฟลเดอร์เดียวทำทั้งสองเว็บ จึงเปิดทีเดียวล็อกอินได้ทั้งคู่
    ส่วนช่องที่ 1 แยกเป็นสองโฟลเดอร์ ต้องใช้คำสั่ง `login` กับ `login-chatgpt`
    ตามเดิม — ตัวนี้จึงปฏิเสธช่องที่ 1 แทนที่จะเปิดโปรไฟล์ผิดตัวให้

    **ตัวตรวจดูของที่มีเฉพาะตอนสำเร็จ** (กติกาข้อ 2.3.1) — ChatGPT ต้องมีช่องพิมพ์
    ให้ใช้จริง · Flow ต้องเข้าถึงหน้าแอปได้จริง ไม่ใช่แค่ไม่เจอปุ่มล็อกอิน
    """
    from playwright.sync_api import sync_playwright

    import chatgpt_driver

    if int(slot) < 2:
        print("ช่องที่ 1 แยกสองโปรไฟล์ — ใช้ `login` (Flow) กับ `login-chatgpt` แทน",
              flush=True)
        return 1
    folder = flow_seat(slot)["dir"]
    folder.mkdir(parents=True, exist_ok=True)
    print(f"ช่อง {slot} · โปรไฟล์ {folder}", flush=True)
    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=False, profile_dir=folder)
        gpt_page = browser.pages[0] if browser.pages else browser.new_page()
        gpt_page.goto(chatgpt_driver.CHATGPT_HOME,
                      wait_until="domcontentloaded", timeout=90_000)
        flow_page = browser.new_page()
        flow_page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=90_000)
        try:
            _enter_app(flow_page)
        except Exception as error:                               # noqa: BLE001
            print(f"  (กดเข้าแอป Flow ยังไม่ได้: {error} — ล็อกอินก่อนได้เลย)",
                  flush=True)
        # แท็บที่สาม: Shopee — ช่องที่ดึงลิงก์ต้องล็อกอิน Shopee ด้วย
        # (Shopee ไทยปิดหน้าสินค้าไม่ให้คนที่ยังไม่ล็อกอินดู)
        try:
            shop_page = browser.new_page()
            shop_page.goto("https://shopee.co.th/",
                           wait_until="domcontentloaded", timeout=90_000)
        except Exception as error:                               # noqa: BLE001
            print(f"  (เปิดแท็บ Shopee ไม่ได้: {error})", flush=True)
        print("เปิดหน้าต่างแล้ว 3 แท็บ — ChatGPT · Google Flow · Shopee",
              flush=True)
        print(f"(รอสูงสุด {wait_minutes} นาที · ล็อกอินครบทั้งคู่แล้วปิดให้เอง)",
              flush=True)
        session = chatgpt_driver.ChatGPTSession(
            gpt_page, log=lambda m: print("   ", m, flush=True))
        deadline = time.time() + wait_minutes * 60
        said = ""
        passes = 0                 # ผ่านติดกันกี่รอบแล้ว (ต้องครบ 3 ถึงจะเชื่อ)
        announced = False
        while time.time() < deadline:
            # ระหว่างล็อกอินหน้าเปลี่ยนตลอด อ่านพลาดเป็นเรื่องปกติ ห้ามล้มทั้งคำสั่ง
            gpt_ok = flow_ok = False
            try:
                state = session.state()
                gpt_ok = bool(not state["signedOut"] and state["hasBox"])
            except Exception as error:                           # noqa: BLE001
                if "closed" in str(error).lower():
                    print("หน้าต่างถูกปิด — ยังล็อกอินไม่ครบ", flush=True)
                    return 1
            try:
                # ต้องเป็นแท็บที่อยู่บนเว็บ Flow จริงๆ — เดิมนับทุกแท็บที่ไม่ใช่
                # ChatGPT ซึ่งรวมแท็บล็อกอิน Google ที่กำลังกรอกรหัสอยู่ด้วย
                pages = [x for x in browser.pages
                         if not x.is_closed() and "labs.google" in x.url]
                flow_ok = any(_is_signed_in(x) for x in pages)
            except Exception:                                    # noqa: BLE001
                pass
            now = f"ChatGPT {'✅' if gpt_ok else '⏳'} · Google Flow {'✅' if flow_ok else '⏳'}"
            if now != said:
                said = now
                print(f"  {now}", flush=True)
            # ---- ห้ามปิดหน้าต่างเองตอนคนยังใช้อยู่ (30 ส.ค. 2569) --------
            #
            # **เจอจริงในนาทีเดียวกับที่เขียนตัวนี้เสร็จ** ตัวตรวจตัดสินว่า
            # "ล็อกอินครบแล้ว" ตอนเจ้าของยังกรอกรหัสค้างอยู่ แล้วปิดหน้าต่างทิ้ง
            # กลางมือ — เจ้าของต้องทักมาว่า *"จอหายไปไหนผมกำลังล้อคอิน"*
            #
            # รากคือตัวตรวจตอบ "ใช่" ได้ทั้งตอนล็อกอินเสร็จและตอนหน้ากำลังเปลี่ยน
            # (กติกาข้อ 2.3.1) แก้สองชั้น:
            #   1. ต้องผ่านติดกัน 3 รอบ ไม่ใช่รอบเดียวจบ — จังหวะที่หน้าเปลี่ยน
            #      ผ่านมาแวบเดียว ไม่มีทางผ่านติดกันสามรอบ
            #   2. **ผ่านแล้วก็ยังไม่ปิด** ปล่อยให้เจ้าของปิดเอง เพราะ
            #      "ปิดเร็วไป" เสียงานจริง ส่วน "ค้างไว้" เสียแค่หน้าต่างเปล่า
            if gpt_ok and flow_ok:
                passes += 1
            else:
                passes = 0
            if passes == 3 and not announced:
                announced = True
                print(f"LOGIN OK ทั้งคู่ — ช่อง {slot} ใช้งานได้แล้ว", flush=True)
                # บอกแพ็กเกจตั้งแต่ตอนนี้ จะได้สลับบัญชีทันทีถ้าเลือกผิด
                # ไม่ใช่ไปรู้ตอนคิวเดินแล้วล้มทั้งแถว
                try:
                    badge = flow_plan_badge(pages[0] if pages else flow_page, tries=3)
                except Exception:                                # noqa: BLE001
                    badge = ""
                if badge == FLOW_PLAN_REQUIRED:
                    print(f"บัญชี Flow: {badge} ✅ ใช้เจนคลิปได้", flush=True)
                else:
                    print(f"⚠️ บัญชี Flow ขึ้นว่า {badge or 'ไม่มีป้ายแพ็กเกจ'} "
                          f"ไม่ใช่ {FLOW_PLAN_REQUIRED} — ต้องสลับบัญชีก่อน",
                          flush=True)
                print("หน้าต่างยังเปิดค้างไว้ ปิดเองได้เลยเมื่อเสร็จ", flush=True)
            time.sleep(5)
        if announced:
            print("จบเวลารอ — ล็อกอินไว้เรียบร้อยแล้ว", flush=True)
            browser.close()
            return 0
        print(f"TIMEOUT — ยังล็อกอินไม่ครบ ({said})", flush=True)
        browser.close()
        return 1


def login_shopee(wait_minutes: int, profile: str = "") -> int:
    """เปิดหน้าต่างให้ล็อกอิน Shopee เอง เก็บคุกกี้ไว้ในโปรไฟล์เดียวกับ Flow/TikTok

    Shopee ไทยปิดหน้าสินค้าไม่ให้คนที่ยังไม่ล็อกอินดู จึงต้องล็อกอินครั้งเดียว
    ก่อนใช้ปุ่มดึงข้อมูลจากลิงก์ในหน้า Input
    """
    from playwright.sync_api import sync_playwright

    import shopee_scrape

    folder = profile_named(profile) if profile else None
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)
        print(f"โปรไฟล์ {folder.name}", flush=True)
    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=False, profile_dir=folder)
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(shopee_scrape.SHOPEE_HOME, wait_until="domcontentloaded", timeout=90_000)
        print("เปิดหน้าต่างแล้ว — ล็อกอิน Shopee ในหน้าต่างนั้น", flush=True)
        print(f"(รอสูงสุด {wait_minutes} นาที)", flush=True)
        deadline = time.time() + wait_minutes * 60
        while time.time() < deadline:
            # คุกกี้ SPC_ST ออกให้เฉพาะ session ที่ล็อกอินแล้ว ใช้เป็นสัญญาณได้
            names = {cookie["name"] for cookie in browser.cookies()}
            if any(name.startswith("SPC_ST") for name in names):
                print("LOGIN OK — ดึงข้อมูลสินค้าได้แล้ว", flush=True)
                browser.close()
                return 0
            time.sleep(5)
        print("TIMEOUT — ยังไม่ได้ล็อกอิน", flush=True)
        browser.close()
        return 1


def post_tiktok_folder(
    folder: str, tags: str, caption: str, pid: str, ptxt: str,
    delay: float, day_limit: int, move_to: str, no_cover: bool,
    schedule_from: str, schedule_step: int, hidden: bool,
) -> int:
    """โพสต์คลิปทั้งโฟลเดอร์ขึ้น TikTok ทีละคลิป (ลูปเดียวกับ extension เดิม)

    เรียงตามเวลาที่แก้ไขไฟล์ = คลิปที่เจนก่อนได้โพสต์ก่อน
    """
    from playwright.sync_api import sync_playwright

    import tiktok_post

    source = Path(folder)
    if not source.is_dir():
        print(f"ไม่พบโฟลเดอร์ {source}")
        return 1
    videos = sorted(
        (p for p in source.iterdir() if p.suffix.lower() in {".mp4", ".mov", ".webm"}),
        key=lambda p: p.stat().st_mtime,
    )
    if not videos:
        print(f"ไม่มีไฟล์วิดีโอใน {source}")
        return 1
    print(f"เจอ {len(videos)} คลิปใน {source}", flush=True)

    when = None
    if schedule_from:
        try:
            when = datetime.fromisoformat(schedule_from)
        except ValueError:
            print("รูปแบบเวลาไม่ถูก ต้องเป็น 2026-08-09T19:30")
            return 1

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=hidden)
        page = browser.pages[0] if browser.pages else browser.new_page()
        try:
            outcome = tiktok_post.post_batch(
                page,
                videos,
                caption=caption,
                tags=[t for t in tags.split() if t],
                pid=pid,
                ptxt=ptxt,
                delay_seconds=delay,
                day_limit=day_limit,
                move_to=Path(move_to) if move_to else None,
                schedule_from=when,
                schedule_step_minutes=schedule_step,
                edit_cover=not no_cover,
                log=lambda message: print(" ", message, flush=True),
            )
        except tiktok_post.TikTokNeedsLogin as error:
            print(f"ยังไม่ได้ล็อกอิน: {error}")
            browser.close()
            return 2
        browser.close()
    return 0 if outcome["done"] else 1


def delete_tiktok_posts(count: int, hidden: bool) -> int:
    """ลบคลิปล่าสุด N อันออกจาก TikTok (ข้ามคลิปที่ปักหมุดเสมอ)"""
    from playwright.sync_api import sync_playwright

    import tiktok_post

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=hidden)
        page = browser.pages[0] if browser.pages else browser.new_page()
        outcome = tiktok_post.delete_recent_posts(
            page, count, log=lambda message: print(" ", message, flush=True)
        )
        browser.close()
    if outcome.get("error"):
        print(outcome["error"])
        return 1
    return 0 if outcome["ok"] else 1


def worker_loop(demo: bool, once: bool, hidden: bool = False) -> int:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    page = None
    browser = None
    playwright = None

    if not demo:
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        browser = open_browser(playwright, hidden=hidden,
                                 profile_dir=flow_gen_profile_dir())
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=90_000)
        page = _app_page(browser, page)

    print("worker พร้อมทำงาน" + (" (โหมด demo)" if demo else ""))
    try:
        while True:
            job_dir = claim_next_job()
            if job_dir is None:
                if once:
                    print("ไม่มีงานค้างในคิว")
                    return 0
                time.sleep(POLL_SECONDS)
                continue
            try:
                run_job(job_dir, page, demo)
            except NeedsLogin as error:
                state = read_state(job_dir)
                state["status"] = "needs_login"
                state["error"] = str(error)
                write_state(job_dir, state)
                print(f"  ⛔ {error} — ล็อกอินในหน้าต่างที่เปิดอยู่ แล้วสั่ง run ใหม่")
                return 2
            except QuotaExhausted as error:
                state = read_state(job_dir)
                state["status"] = "pending"
                state["error"] = str(error)
                write_state(job_dir, state)
                print(f"  ⛔ {error} — หยุดคิวไว้ก่อน ไม่ไล่ทำงานที่เหลือให้เสียเปล่า")
                return 3
            except Exception as error:  # งานเดียวพังต้องไม่ล้มทั้งคิว
                state = read_state(job_dir)
                state["status"] = "failed"
                state["error"] = f"{type(error).__name__}: {error}"
                write_state(job_dir, state)
                print(f"  ❌ พัง: {state['error']}")
                traceback.print_exc()
            if once:
                return 0
    except KeyboardInterrupt:
        print("\nหยุด worker แล้ว")
        return 0
    finally:
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()


def manage_slots(args) -> int:
    """ดู/แก้ 5 ช่อง — โครงเดียวกับ S.models ของ extension เดิม"""
    import tiktok_post

    slots = tiktok_post.load_slots()
    if args.set:
        index = args.set - 1
        if not 0 <= index < tiktok_post.SLOT_COUNT:
            print(f"ช่องต้องอยู่ระหว่าง 1-{tiktok_post.SLOT_COUNT}")
            return 1
        if args.code is not None:
            slots[index]["code"] = args.code
        if args.tags is not None:
            slots[index]["tags"] = args.tags
        if args.pid is not None:
            slots[index]["pid"] = args.pid
        if args.ptxt is not None:
            slots[index]["ptxt"] = args.ptxt
        slots[index]["on"] = not args.off
        tiktok_post.save_slots(slots)
        print(f"บันทึกช่อง {args.set} แล้ว")
    for number, slot in enumerate(slots, start=1):
        mark = "เปิด" if slot["on"] else "ปิด "
        print(
            f"  ช่อง {number} [{mark}] code={slot['code'] or '-':<14}"
            f" pid={slot['pid'] or '-':<18} ptxt={slot['ptxt'] or '-':<14}"
            f" tags={slot['tags'] or '-'}"
        )
    return 0


def list_jobs() -> int:
    if not JOBS_DIR.is_dir():
        print("ยังไม่มีคิว")
        return 0
    for job_dir in sorted(JOBS_DIR.iterdir()):
        if not job_dir.is_dir():
            continue
        state = read_state(job_dir)
        steps = ",".join(state.get("done_steps", [])) or "-"
        print(
            f"{state.get('id', job_dir.name):<28} {state.get('status', '?'):<12}"
            f" ขั้นที่เสร็จ: {steps:<20} {state.get('error') or ''}"
        )
    return 0


def retry_jobs(job_id: str) -> int:
    """คืนงานที่ failed/needs_login กลับเป็น pending
    ขั้นที่ทำเสร็จแล้วยังอยู่ใน done_steps จึงทำต่อจากจุดที่ค้าง ไม่เริ่มใหม่หมด"""
    if not JOBS_DIR.is_dir():
        print("ยังไม่มีคิว")
        return 0
    count = 0
    for job_dir in sorted(JOBS_DIR.iterdir()):
        if not job_dir.is_dir():
            continue
        state = read_state(job_dir)
        if job_id and state.get("id") != job_id:
            continue
        if state.get("status") not in {"failed", "needs_login"}:
            continue
        state["status"] = "pending"
        state["error"] = None
        write_state(job_dir, state)
        print(f"คืนคิวแล้ว: {state['id']} (ทำต่อจาก {state.get('done_steps') or 'ขั้นแรก'})")
        count += 1
    if not count:
        print("ไม่มีงานที่ต้องคืนคิว")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="เพิ่มงานเข้าคิว")
    add.add_argument("--product", required=True)
    add.add_argument("--detail", default="")
    add.add_argument("--image", default="", help="ไฟล์รูปสินค้าต้นฉบับ (แนบทั้งให้ Gemini และตอนเจนรูป)")
    add.add_argument("--post-tiktok", action="store_true", help="โพสต์ขึ้น TikTok หลังรวม/ตัดคลิปเสร็จ")
    add.add_argument("--tags", default="", help="แฮชแท็ก คั่นด้วยช่องว่าง เช่น \"รีวิวมือถือ ของดีบอกต่อ\"")

    run = sub.add_parser("run", help="เริ่ม worker")
    run.add_argument("--demo", action="store_true", help="ไม่เปิดเบราว์เซอร์ ใช้พิสูจน์ลูป")
    run.add_argument("--once", action="store_true", help="ทำงานเดียวแล้วออก")
    run.add_argument("--hidden", action="store_true", help="ซ่อนหน้าต่างไปนอกจอ")

    login = sub.add_parser("login", help="เปิดหน้าต่างให้ล็อกอิน Google เอง")
    login.add_argument("--wait-minutes", type=int, default=15)

    tiktok = sub.add_parser("login-tiktok", help="เปิดหน้าต่างให้ล็อกอิน TikTok เอง")
    tiktok.add_argument("--wait-minutes", type=int, default=15)

    shopee = sub.add_parser("login-shopee", help="เปิดหน้าต่างให้ล็อกอิน Shopee เอง")
    shopee.add_argument("--wait-minutes", type=int, default=15)
    # โปรไฟล์เฉพาะของงานดึงลิงก์ — ใส่ --profile flow_browser_profile3
    shopee.add_argument("--profile", default="",
                        help="ชื่อโปรไฟล์ Chrome (ว่าง = โปรไฟล์เดิม)")

    gpt = sub.add_parser("login-chatgpt", help="เปิดหน้าต่างให้ล็อกอิน ChatGPT เอง")
    gpt.add_argument("--wait-minutes", type=int, default=15)

    seat = sub.add_parser("login-slot",
                          help="เปิดโปรไฟล์ของช่องที่ 2 ขึ้นไป ล็อกอิน ChatGPT + Flow ทีเดียว")
    seat.add_argument("--slot", type=int, default=2)
    seat.add_argument("--wait-minutes", type=int, default=20)

    clone = sub.add_parser("clone-profile",
                           help="ก๊อปโปรไฟล์ Chrome ทั้งก้อน (ล็อกอินเดิมติดไปด้วย)")
    clone.add_argument("--from", dest="source", required=True)
    clone.add_argument("--to", dest="target", required=True)

    inspect = sub.add_parser("inspect", help="ดูดโครงหน้าโปรเจกต์จริง ไว้เขียน selector")
    inspect.add_argument("--click", default="", help="กดปุ่มชื่อนี้ก่อนดูด")
    inspect.add_argument("--name", default="project", help="ชื่อไฟล์ผลลัพธ์")

    slots = sub.add_parser("slots", help="ดู/ตั้งค่า 5 ช่อง (แฮชแท็ก + product id)")
    slots.add_argument("--set", type=int, metavar="N", help="ตั้งค่าช่องที่ N (1-5)")
    slots.add_argument("--code", default=None, help="โค้ด/ชื่อรุ่นที่ใช้จับคู่")
    slots.add_argument("--tags", default=None, help="แฮชแท็ก คั่นด้วยช่องว่าง")
    slots.add_argument("--pid", default=None, help="Product ID ของ TikTok Shop")
    slots.add_argument("--ptxt", default=None, help="ข้อความบนป้ายสินค้า (ไว้ยืนยันว่าเพิ่มสำเร็จ)")
    slots.add_argument("--off", action="store_true", help="ปิดช่องนี้")

    post = sub.add_parser("post-tiktok", help="โพสต์คลิปทั้งโฟลเดอร์ขึ้น TikTok ทีละคลิป")
    post.add_argument("folder", help="โฟลเดอร์ที่มีคลิป (.mp4/.mov/.webm)")
    post.add_argument("--tags", default="", help="แฮชแท็ก คั่นด้วยช่องว่าง")
    post.add_argument("--caption", default="", help="ข้อความแคปชันนำหน้าแฮชแท็ก")
    post.add_argument("--pid", default="", help="Product ID ของ TikTok Shop")
    post.add_argument("--ptxt", default="", help="ข้อความบนป้ายสินค้า ไว้ยืนยันว่าเพิ่มสำเร็จ")
    post.add_argument("--delay", type=float, default=20, help="เว้นระยะระหว่างคลิป (วินาที)")
    post.add_argument("--day-limit", type=int, default=150, help="ลิมิตคลิปต่อ 24 ชม.")
    post.add_argument("--move-to", default="", help="ย้ายคลิปที่โพสต์แล้วไปโฟลเดอร์นี้")
    post.add_argument("--no-cover", action="store_true", help="ไม่ต้องแก้ไขปก")
    post.add_argument("--schedule-from", default="", help="ตั้งเวลาเริ่ม เช่น 2026-08-09T19:30")
    post.add_argument("--schedule-step", type=int, default=60, help="ห่างกันกี่นาทีต่อคลิป")
    post.add_argument("--hidden", action="store_true", help="ซ่อนหน้าต่างไปนอกจอ")

    delete = sub.add_parser("delete-tiktok", help="ลบคลิปล่าสุด N อัน (ข้ามคลิปที่ปักหมุด)")
    delete.add_argument("count", type=int, help="จำนวนคลิปที่จะลบ")
    delete.add_argument("--hidden", action="store_true", help="ซ่อนหน้าต่างไปนอกจอ")

    sub.add_parser("list", help="ดูสถานะคิว")
    retry = sub.add_parser("retry", help="เอางานที่พังกลับเข้าคิว (ทำต่อจากขั้นที่ค้าง)")
    retry.add_argument("job_id", nargs="?", default="", help="ว่างไว้ = ทุกงานที่พัง")

    args = parser.parse_args()
    if args.command == "add":
        job_dir = add_job(
            args.product, args.detail, args.image,
            post_tiktok=args.post_tiktok, tags=args.tags,
        )
        print(f"เพิ่มงานแล้ว: {job_dir.name}")
        return 0
    if args.command == "slots":
        return manage_slots(args)
    if args.command == "list":
        return list_jobs()
    if args.command == "retry":
        return retry_jobs(args.job_id)
    # คำสั่งล็อกอินทุกตัวเปิดโปรไฟล์ Chrome ตัวเดียวกับที่คิวงานใช้ ต้องถือล็อก
    # เดียวกัน ไม่งั้นงานในคิวจะเปิดซ้อนแล้ว **ไล่หน้าต่างล็อกอินทิ้งกลางคัน**
    # (เจอมาแล้วทั้งกับหน้าต่างล็อกอินและกับงานที่กำลังทำอยู่)
    if args.command == "clone-profile":
        return clone_profile(args.source, args.target)
    if args.command == "login-slot":
        import studio_shared

        # ล็อกดอกเดียวกับที่ช่องนั้นใช้ตอนทำงานจริง ไม่งั้นคิวจะเปิดโปรไฟล์
        # เดียวกันซ้อนแล้วไล่หน้าต่างล็อกอินทิ้งกลางคัน
        with studio_shared.browser_lock(
                label=f"ล็อกอินช่อง {args.slot}",
                profile=flow_seat(args.slot)["lock"]):
            return login_slot(args.wait_minutes, args.slot)
    logins = {
        "login": login_flow, "login-tiktok": login_tiktok,
        "login-shopee": login_shopee, "login-chatgpt": login_chatgpt,
    }
    if args.command in logins:
        import studio_shared

        # **ล็อกต้องตรงกับโปรไฟล์ที่จะเปิด** — ล็อกอิน Flow เปิดโปรไฟล์ Flow
        # ที่เหลือ (TikTok · ChatGPT · Shopee) ยังอยู่โปรไฟล์เดิม
        # จับผิดดอก = Chrome สองตัวเปิดโปรไฟล์เดียวกัน งานตายกลางคัน
        want = getattr(args, "profile", "") or ""
        lock = want or (FLOW_LOCK if args.command == "login" else "")
        with studio_shared.browser_lock(
                label=f"ล็อกอิน ({args.command})", profile=lock):
            if args.command == "login-shopee":
                return login_shopee(args.wait_minutes, want)
            return logins[args.command](args.wait_minutes)
    if args.command == "post-tiktok":
        return post_tiktok_folder(
            args.folder, args.tags, args.caption, args.pid, args.ptxt,
            args.delay, args.day_limit, args.move_to, args.no_cover,
            args.schedule_from, args.schedule_step, args.hidden,
        )
    if args.command == "delete-tiktok":
        return delete_tiktok_posts(args.count, args.hidden)
    if args.command == "inspect":
        return inspect_flow(args.click, args.name)
    return worker_loop(demo=args.demo, once=args.once, hidden=args.hidden)


if __name__ == "__main__":
    sys.exit(main())
