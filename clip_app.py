"""เซิร์ฟเวอร์สายเจนคลิป — แยกโปรเซสจาก app.py

    app.py       พอร์ต 8866   งานมือถือ + โพสต์ Facebook + บอทหลัก
    clip_app.py  พอร์ต 8877   สายเจนคลิป + บอท @ClipAiABot   ← ไฟล์นี้

**ทำไมต้องแยกโปรเซส** งานสายคลิปกินเวลาเป็นนาที (เปิดเบราว์เซอร์ คุยกับ ChatGPT
เจนวิดีโอใน Flow) และต้องแก้/รีสตาร์ตบ่อยระหว่างพัฒนา ทุกครั้งที่รีสตาร์ตรวมกัน
บอทโพสต์ Facebook กับจอมือถือจะตายไปด้วยทั้งที่ไม่เกี่ยวอะไรเลย

**สิ่งที่ยังใช้ร่วมกันและต้องระวัง** โปรไฟล์ Chrome มีตัวเดียว เปิดซ้อนกันไม่ได้
แยกโปรเซสแล้ว threading.Lock เดิมกันไม่ได้อีกต่อไป จึงคุมด้วย
`studio_shared.browser_lock()` ซึ่งเป็นล็อกระดับไฟล์ของ Windows — กันข้ามโปรเซสได้
และปล่อยเองเมื่อโปรเซสตาย
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

import chatgpt_driver
import clip_board
import clip_check
import clip_claims
import clip_queue
import clip_store
import publish_order
import clip_rules

# ขึ้นบรรทัดใหม่ — ประกาศเป็นค่าคงที่ให้อ่านง่ายเวลาต่อสตริงยาวๆ
NEWLINE = chr(10)
import hashtag
import policy_fix
import shopee_scrape
import studio_shared as shared
import telegram_bot
import thai_speech
import tiktok_repost
import tiktok_source
from shopee_service import shopee_collect

APP_VERSION = "1"
# app.py ส่ง STUDIO_CLIP_PORT มาให้ตอนสั่งเปิด — สำเนาโค้ดอีกชุด (git worktree)
# จะได้เปิดสายคลิปของตัวเองคนละพอร์ต ไม่ไปชนกับตัวจริง
PORT = int(os.environ.get("STUDIO_CLIP_PORT", "") or 8877)
# เซิร์ฟเวอร์หลักอยู่ต่ำกว่าสายคลิป 11 พอร์ตเสมอ (app.py: CLIP_PORT = PORT + 11)
# คิดกลับแบบนี้แทนที่จะฝัง 8866 ตรงๆ ไม่งั้นสำเนาที่รันบน 8966/8977 จะไปถาม
# สถานะของตัวจริงแทนตัวเอง
MAIN_PORT = PORT - 11

DATA_DIR = shared.DATA_DIR
WEB_DIR = shared.WEB_DIR

app = FastAPI(title="Pipeline Studio — สายเจนคลิป")


def append_log(tab: str, message: str) -> None:
    """log ของสายคลิปไปที่แท็บ clip เสมอ ไม่ปนกับ log ของงานโพสต์

    รับพารามิเตอร์ tab ไว้ให้โค้ดที่ย้ายมาจาก app.py เรียกได้เหมือนเดิม
    แต่ **บังคับลง clip.log** — สองโปรเซสเขียนไฟล์เดียวกันแล้วไล่ log ยากมาก
    """
    shared.append_log("clip", message)


def load_config() -> dict:
    return shared.read_config()


load_clip_token = shared.load_clip_token


# บอทของสายคลิป — คนละโทเคนกับบอทโพสต์ เพราะ getUpdates ของหนึ่งโทเคน
# มีตัวอ่านได้ตัวเดียว ถ้าใช้โทเคนเดียวกันสองโปรเซสจะได้ 409 Conflict ทันที
approval_store = telegram_bot.ApprovalStore(DATA_DIR / "approvals.json")
clip_watcher = telegram_bot.ApprovalWatcher(
    approval_store,
    get_token=load_clip_token,
    log=lambda message: append_log("clip", f"[บอทคลิป] {message}"),
)


def set_config(key: str, value) -> bool:
    """แก้ค่าเดียวใน config.json — อ่าน-แก้-เขียน จบเป็นชิ้นเดียวใต้ล็อกข้ามโปรเซส

    ของเดิมอ่านสดแล้วเขียนทับตรงๆ โดยไม่มีล็อก คอมเมนต์เดิมเขียนไว้เองว่าแค่
    "ลดโอกาส" ทับค่าที่ app.py เพิ่งใส่ — คือรู้ว่ามีช่องแต่ยอมรับไว้ ตอนนี้ปิดแล้ว

    สองอย่างที่เปลี่ยน: (1) ถือล็อกไฟล์ตลอดช่วงอ่านถึงเขียน อีกฝั่งจึงแทรกกลาง
    ไม่ได้ (2) เขียนแบบ temp+replace อีกฝั่งไม่มีวันอ่านเจอไฟล์ครึ่งๆ ซึ่งเดิม
    จะทำให้ app.py อ่านไม่ออกแล้วถอยไปใช้ค่าปริยาย = ตั้งค่าผู้ใช้หายทั้งชุด
    """
    if shared.read_config().get(key) == value:
        return True
    try:
        shared.update_json(
            shared.CONFIG_FILE,
            lambda stored: stored.__setitem__(key, value),
            default={},
            label=f"บอทคลิปแก้ {key}",
        )
    except (OSError, shared.DataBusy) as error:
        append_log("clip", f"บันทึกตั้งค่า {key} ไม่ได้: {error}")
        return False
    return True


# ตอนนี้ยังไล่แก้ขั้นเจนใน Google Flow อยู่ จึงตั้งค่าปริยายให้ **หยุดที่บทพูด**
#
# ปิดไว้เพื่อไม่ให้ทุกครั้งที่กดอนุมัติแล้วไปเปิด Flow ทิ้งไว้ 5 ฉาก ฉากละ ~50 วินาที
# โดยไม่ได้อะไรกลับมา — ของที่ทำเสร็จแล้ว (สตอรีบอร์ด/คำสั่ง/บทพูด) ถูกเก็บครบทุกครั้ง
# อยู่แล้ว เปิดกลับด้วย /flow on ในแชทเมื่อขั้นเจนพร้อม
FLOW_ENABLED_KEY = "clip_flow_enabled"

# เจนทุกฉากรวมเป็น **คลิปเดียว** หรือแยกฉากละคลิป
#
# รวมคลิปเดียว = เจนครั้งเดียว ใช้เครดิตครั้งเดียว ได้คลิปที่เล่นต่อเนื่องเลย
#   แต่ Flow ตั้งไว้ 8 วินาทีต่อการเจนหนึ่งครั้ง ทุกฉากจึงถูกอัดอยู่ในนั้น
# แยกฉาก = ได้ไฟล์ละฉาก คุมรายละเอียดได้ดีกว่า แต่เสียเครดิตเท่าจำนวนฉาก
#   และต้องเอาไปต่อกันเองทีหลัง
FLOW_ONE_CLIP_KEY = "clip_flow_one_clip"

# prompt รวมยาวเกินนี้จะถูกตัด — ช่อง prompt ของ Flow ไม่ได้รับไม่จำกัด
# และ prompt ที่ยาวเกินไปทำให้โมเดลไล่ทำไม่ครบทุกฉากอยู่ดี
FLOW_PROMPT_LIMIT = 4000

# ความยาวคลิปเป็นวินาที — Flow ให้เลือก 4 / 6 / 8 / 10
#
# สตอรีบอร์ดที่ GPT เขียนวางไว้เป็นคลิป 10 วินาที (SCENE 1 = 0–2 วิ … SCENE 5 = 8–10 วิ)
# ต้องตั้งให้ตรงกัน ไม่งั้นฉากท้ายถูกตัดทิ้ง — เดิมไม่ได้ตั้งเลย ได้ 8 วินาทีตามค่า
# ที่ค้างอยู่ใน UI ของ Flow
# โมเดลวิดีโอที่ใช้ — ผู้ใช้เลือก Omni Flash
#
# การ์ดกันเครดิตใน select_video_model จะทำงานเฉพาะเมื่อชื่อโมเดลมีคำว่า "Lite"
# (= รุ่นฟรี Lower Priority) Omni Flash ไม่เข้าเงื่อนไขนั้น จึงเลือกได้ตรงๆ
# **แต่แปลว่ารอบนี้เสียเครดิตจริง** แผงตั้งค่าขึ้นว่าใช้ 12 เครดิตต่อการสร้าง
FLOW_MODEL_KEY = "clip_flow_model"
FLOW_SECONDS_KEY = "clip_flow_seconds"
FLOW_SECONDS_CHOICES = (4, 6, 8, 10)


def flow_model() -> str:
    return str(shared.read_config().get(FLOW_MODEL_KEY) or "Omni Flash")


def flow_seconds() -> int:
    value = shared.read_config().get(FLOW_SECONDS_KEY, 10)
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 10
    return value if value in FLOW_SECONDS_CHOICES else 10


# ยอดเครดิตที่อ่านได้ล่าสุด + เวลาที่อ่าน
#
# **ทำไมต้องจำ** อ่านยอดสดต้องเปิดเบราว์เซอร์ กดเมนูบัญชี ~15 วินาที และเปิด
# ซ้อนตอนคิวกำลังเจนอยู่ไม่ได้ (โปรไฟล์เดียวกัน) แต่ทุกครั้งที่เจนก็อ่านยอด
# อยู่แล้วทั้งก่อนและหลัง — เก็บค่านั้นไว้เลย จะได้ตอบ /credits ได้ทันทีและ
# เอาไปกันพลาดตอน /genall ได้โดยไม่ต้องเปิดเบราว์เซอร์
FLOW_CREDITS_KEY = "flow_credits_last"
FLOW_CREDITS_AT_KEY = "flow_credits_at"

# เครดิตต่อการเจนหนึ่งครั้ง — **ตัวเลขประมาณการ**
#
# แผงตั้งค่าของ Flow ขึ้นว่า 12 เครดิตต่อการสร้าง แต่ที่วัดได้จริงจากส่วนต่าง
# ก่อน-หลังคือรอบละ 15 จึงใช้ 15 เป็นฐานคิด (ประเมินสูงไว้ดีกว่าประเมินต่ำ
# แล้วเครดิตหมดกลางคิว) ยอดจริงยังรายงานจากส่วนต่างที่วัดได้ทุกรอบเหมือนเดิม
FLOW_CREDIT_PER_CLIP = 15


def flow_enabled() -> bool:
    return bool(shared.read_config().get(FLOW_ENABLED_KEY, False))


def _remember_credits(value: int | None) -> None:
    """จดยอดเครดิตที่เพิ่งอ่านได้ — None แปลว่าอ่านไม่ได้ ไม่ต้องเขียนทับของเดิม"""
    if value is None:
        return
    set_config(FLOW_CREDITS_KEY, int(value))
    set_config(FLOW_CREDITS_AT_KEY, time.time())


def known_credits() -> tuple[int | None, float]:
    """ยอดเครดิตที่จำไว้ + อายุเป็นวินาที (อายุ -1 = ยังไม่เคยอ่านได้เลย)"""
    config = shared.read_config()
    value = config.get(FLOW_CREDITS_KEY)
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None, -1.0
    try:
        stamp = float(config.get(FLOW_CREDITS_AT_KEY) or 0)
    except (TypeError, ValueError):
        stamp = 0.0
    return value, (time.time() - stamp if stamp else -1.0)


def _age_text(seconds: float) -> str:
    """อายุของตัวเลขเป็นภาษาคน — ต้องบอกเสมอว่าเลขนี้เก่าแค่ไหน
    ยอดเครดิตที่อ่านมาเมื่อวานอาจไม่ตรงกับตอนนี้ ผู้ใช้ต้องรู้ว่าเชื่อได้แค่ไหน"""
    if seconds < 0:
        return "ยังไม่เคยอ่านได้"
    if seconds < 90:
        return "เมื่อครู่นี้"
    if seconds < 3600:
        return f"{int(seconds // 60)} นาทีที่แล้ว"
    if seconds < 86400:
        return f"{int(seconds // 3600)} ชั่วโมงที่แล้ว"
    return f"{int(seconds // 86400)} วันที่แล้ว"


def _credit_estimate(run: dict) -> int:
    """เดาว่างานชิ้นนี้จะใช้เครดิตเท่าไร ตามโหมดที่ตั้งไว้ตอนนี้

    โหมดรวม = เจนครั้งเดียว · โหมดแยกฉาก = เจนเท่าจำนวนคำสั่ง Flow
    """
    if one_clip_mode():
        return FLOW_CREDIT_PER_CLIP
    scenes = int(run.get("flow_prompt_count") or 1)
    return max(1, scenes) * FLOW_CREDIT_PER_CLIP


def one_clip_mode() -> bool:
    return bool(shared.read_config().get(FLOW_ONE_CLIP_KEY, True))


# บรรทัดสั่งเสียงพูดในคำสั่งของแต่ละฉาก — GPT เขียนมาแบบนี้เสมอ
# ตัวอย่างจริง: `Audio: Generate Thai voice-over narration: "แก จอนี้ภาพสวยเกินเรื่องมาก!"`
AUDIO_LINE_RE = re.compile(r"^\s*(audio|voice-?over|narration)\s*[:：]", re.I)


def split_audio_line(text: str) -> tuple[str, str]:
    """แยก **บรรทัดสั่งเสียงพูด** ออกจากคำบรรยายภาพ — คืน (ภาพ, เสียง)

    ต้องแยกเพราะเวลาคำสั่งยาวเกินเพดานแล้วต้องย่อ **ห้ามย่อบรรทัดเสียง**
    (ดูเหตุผลเต็มใน `build_one_clip_prompt`)
    """
    visual, audio = [], []
    for line in (text or "").strip().splitlines():
        (audio if AUDIO_LINE_RE.match(line) else visual).append(line)
    return "\n".join(visual).strip(), "\n".join(audio).strip()


def build_one_clip_prompt(prompts: list[str], seconds: int = 8) -> str:
    """รวม prompt ทุกฉากเป็นก้อนเดียวสำหรับเจนคลิปเดียวจบ

    ต้องบอกให้ชัดว่า **คลิปเดียวต่อเนื่อง** ไม่ใช่หลายคลิป ไม่งั้นโมเดลจะตีความว่า
    ให้ทำฉากแรกอย่างเดียว (แต่ละก้อนเดิมเขียนไว้แบบ "เจนทีละฉาก")

    **บรรทัดสั่งเสียงพูดห้ามโดนตัดเด็ดขาด** (แก้ 26 ส.ค. 2026)
    ------------------------------------------------------------------
    ของเดิมย่อทุกฉากเท่าๆ กันด้วยการ **ตัดท้ายทิ้ง** ซึ่งเป็นที่ที่ GPT วางบรรทัด
    `Audio: Generate Thai voice-over narration: "…"` ไว้พอดี ผลคือคำสั่งเสียง
    เป็นสิ่งแรกที่หายทุกครั้งที่คำสั่งยาวเกิน

    วัดกับของจริง — คลิปจอ 25 นิ้ว (43351917391):
        คำสั่ง 6 ชุดรวม 6,599 ตัวอักษร → ย่อเหลือ 3,984 (เพดาน 4,000)
        คำสั่งเรื่องเสียงในต้นฉบับ 22 จุด → **ส่งถึง Flow 0 จุด**
    คลิปที่ได้จึงมีแต่ดนตรี ไม่มีเสียงพูดเลย และ**กดเจนใหม่พร้อมคอมเมนต์
    "ใส่บทพูดตามสคริป" ก็ไม่ช่วย** เพราะคำสั่งที่แก้แล้วก็โดนตัดที่เดิมซ้ำ

    ตอนนี้จึงกันที่ว่างให้บรรทัดเสียงไว้ก่อน แล้วค่อยเอาที่เหลือไปเฉลี่ยให้
    คำบรรยายภาพ — ภาพย่อได้ (ได้ฉากที่บรรยายสั้นลง) แต่เสียงย่อไม่ได้
    (ได้คลิปเงียบ ซึ่งใช้ไม่ได้เลยและต้องเจนใหม่ = เสียเครดิตฟรี)
    """
    header = (
        f"Create ONE continuous {seconds}-second vertical 9:16 video that plays "
        f"through ALL {len(prompts)} scenes below in order, as a single seamless clip. "
        "Divide the time evenly between scenes with smooth cuts. "
        "Keep the same product, colours and lighting style across every scene.\n\n"
    )
    parts = [split_audio_line(text) for text in prompts]

    def join(rows: list[tuple[str, str]]) -> str:
        blocks = []
        for index, (visual, audio) in enumerate(rows, 1):
            block = f"--- SCENE {index} ---\n{visual}"
            if audio:
                block += f"\n{audio}"
            blocks.append(block)
        return header + "\n\n".join(blocks)

    combined = join(parts)
    if len(combined) <= FLOW_PROMPT_LIMIT:
        return combined

    # กันที่ให้บรรทัดเสียงก่อน แล้วเอาที่เหลือหารเฉลี่ยให้คำบรรยายภาพ
    reserved = sum(len(audio) + 1 for _, audio in parts if audio)
    frame = len(header) + sum(len(f"--- SCENE {i} ---\n\n\n") for i in range(1, len(parts) + 1))
    room = (FLOW_PROMPT_LIMIT - reserved - frame) // max(1, len(parts))
    # ต่ำกว่านี้คำบรรยายภาพจะสั้นจนไม่เหลือความหมาย — ยอมเกินเพดานดีกว่าส่งของที่
    # อ่านไม่รู้เรื่อง แล้วให้บรรทัดตัดท้ายชั้นสุดท้ายจัดการ (ซึ่งยังไม่โดนเสียง
    # เพราะเสียงถูกกันที่ไว้แล้ว)
    room = max(150, room)
    combined = join([(visual[:room].rstrip(), audio) for visual, audio in parts])
    if len(combined) <= FLOW_PROMPT_LIMIT:
        return combined
    # ยังยาวอยู่ = บรรทัดเสียงเองยาวมากผิดปกติ ตัดท้ายเป็นทางสุดท้าย
    # **ขึ้น log ด้วย** ไม่ปล่อยให้เสียงหายเงียบๆ อีก
    _clip_log(f"⚠️ คำสั่งยังยาว {len(combined)} เกินเพดาน {FLOW_PROMPT_LIMIT} "
              "แม้ย่อคำบรรยายภาพจนสุดแล้ว — บรรทัดสั่งเสียงอาจถูกตัดบางส่วน")
    return combined[:FLOW_PROMPT_LIMIT]


def _remember_clip_chat_id(chat_id: str) -> None:
    """จำ chat id ให้เอง ผู้ใช้ไม่ต้องกดบันทึก"""
    if set_config("telegram_clip_chat_id", chat_id):
        append_log("clip", f"จำ chat id ของบอทคลิปแล้ว ({chat_id})")


clip_watcher.on_chat_seen = _remember_clip_chat_id


SHOPEE_LINK_RE = re.compile(r"https?://\S*shopee\S+", re.I)

# สาย TikTok repost — ตัวจับลิงก์อยู่ใน tiktok_source เพื่อให้ทดสอบแยกได้โดยไม่ต้อง
# โหลดทั้งเซิร์ฟเวอร์ **ต้องเช็ค TikTok ก่อน Shopee เสมอ** เพราะ SHOPEE_LINK_RE
# กว้างมาก (`\S*shopee\S+`) ลิงก์ TikTok ที่มีคำว่า shopee ในพารามิเตอร์จะโดนจับผิดฝั่ง
TIKTOK_LINK_RE = tiktok_source.TIKTOK_LINK_RE

CLIP_HELP = (
    "🎬 <b>บอทเจนคลิป</b>\n\n"
    "ส่ง <b>ลิงก์สินค้า Shopee</b> มาในแชทนี้ได้เลย เดี๋ยวจะ:\n"
    "1) เปิดหน้าสินค้า โหลดรูปทั้งหมดมาเป็นคลัง แล้วคัดชุดเริ่มต้นให้\n"
    "2) คัดลอกชื่อสินค้า\n"
    "3) สรุปคุณสมบัติเด่น 3 ข้อ\n"
    "4) ส่ง <b>ชุดรูป</b> + <b>จุดเด่น</b> มาให้ตรวจก่อน\n"
    "     รูป — ➕ เพิ่ม · 🗑 ลบ · 🔄 เปลี่ยน\n"
    "     จุดเด่น — ✏️ แก้ข้อความ · 🗑 ลบ · ➕ เพิ่ม\n"
    "5) ทำ <b>สตอรีบอร์ด</b> กับ <b>บทพูด</b> ส่งมาให้อนุมัติ\n"
    "6) อนุมัติครบแล้วเจนคลิปใน Google Flow ส่งมาให้อนุมัติอีกรอบ\n\n"
    "\n<b>หรือส่งลิงก์คลิป TikTok</b> เพื่อทำคลิปใหม่จากคลิปนั้น:\n"
    "1) โหลดคลิป + แคปชัน + แฮชแท็ก\n"
    "2) ให้ Gemini ดูคลิปแล้วเขียน <b>คำสั่งสร้างคลิป</b> + <b>ถอดบทพูด</b> (แยกผู้พูดให้)\n"
    "3) ตรวจ 3 อย่าง: รูป · คำสั่ง · บทพูด → เจนคลิป → ยืนยันอีกครั้งก่อนโพสต์\n"
    "4) โพสต์ขึ้น TikTok พร้อม Product ID · แฮชแท็ก · คำพูดบนตะกร้า\n\n"
    "<b>วางหลายลิงก์รวดเดียวได้</b> — เข้าคิวทำทีละงานตามลำดับ\n"
    "ทุกชิ้นต้องผ่านการอนุมัติก่อนไปขั้นถัดไปเสมอ\n"
    "กด ✏️ แล้วพิมพ์บอกว่าจะแก้ตรงไหน แก้สตอรีบอร์ดกับบทพูดแยกกันได้\n\n"
    "<b>คำสั่ง</b>\n"
    "/queue — คิวงานตอนนี้\n"
    "/pending — <b>งานที่จอดรออนุมัติ</b> (กดเรียกมาอนุมัติได้เลย)\n"
    "/approveall — <b>อนุมัติงานค้างรวดเดียว</b> (ขั้นก่อนโพสต์เท่านั้น · มีหน้ายืนยัน)\n"
    "/recheck — ตรวจคลิปว่า <b>1080p</b> และ <b>มีเสียงพูด</b> จริงไหม\n"
    "/features &lt;รหัส&gt; — <b>คัดจุดเด่นใหม่</b> (ไล่ให้ครบแล้วเลือก 3 ข้อที่ว้าวสุด)\n"
    "     <code>/pending &lt;เลข&gt;</code> เรียกงานนั้น · <code>/pending all</code> เรียกมาทีละชุด\n"
    "/cancel [เลข] — ยกเลิกงาน (ไม่ใส่เลข = ยกเลิกทั้งหมด)\n"
    "/flow on | off — เปิด/ปิดขั้นเจนคลิปใน Google Flow\n"
    "/mode รวม | แยก — เจนคลิปเดียวจบทุกฉาก หรือแยกฉากละคลิป\n"
    "/clips — <b>คลิปที่พร้อมลง Shopee Video</b> (เจนเสร็จแล้ว ยังไม่ได้ลง)\n"
    "/clipsfb — <b>คลิปที่พร้อมลง Facebook Reels</b> (ลง Shopee แล้ว) · <code>/clipfb &lt;เลข&gt;</code> เปิดดู\n"
    "/clipstiktok — <b>คลิปที่พร้อมลง TikTok</b> (ลง Facebook แล้ว) · <code>/cliptiktok &lt;เลข&gt;</code> เปิดดู\n"
    "/archive — งานที่ติ๊กว่าทำแล้ว (เก็บออกจากรายการไปแล้ว)\n"
    "/posted &lt;เลข&gt; — <b>ติ๊กว่าคลิปนั้นลงไปแล้ว</b> (สำหรับคลิปที่โพสต์เองด้วยมือ)\n"
    "     ไม่ติ๊ก = ระบบไม่รู้ว่าลงแล้ว → /clipsfb กับ /clipstiktok จะว่างตลอด\n"
    "/history — <b>สมุดบันทึกการลง</b> ลงอะไรไปแล้วบ้าง ที่ไหน เมื่อไร (แยกตามวัน)\n"
    "/wait — <b>งานที่พักไว้รอแก้ทั้งหมด</b> · <code>/wait &lt;เลข&gt;</code> เอากลับเข้าขั้นเดิม\n"
    "     แยกรายขั้น: <code>/waitstoryboard</code> · <code>/waitclip</code> · <code>/waitclips</code> · <code>/waitclipsfb</code> · <code>/waitclipstiktok</code>\n"
    "/clip &lt;เลข&gt; — เปิดดูงานนั้น (สตอรีบอร์ด + บทพูด)\n"
    "/gen &lt;เลข&gt; — <b>เจนคลิปต่อ</b>จากสตอรีบอร์ดที่ทำไว้แล้ว\n"
    "/genall — <b>ไล่เจนวิดีโอทุกงานที่ยังไม่มีคลิป</b> (ต้องมีสตอรีบอร์ด + บทพูดครบ)\n"
    "/genall sb — ไล่ทำสตอรีบอร์ดทุกงานที่ยังไม่มี (<code>/genall all</code> = ทำใหม่ทั้งหมด)\n"
    "/storyboard — สตอรีบอร์ดที่ทำแล้วแต่<b>ยังไม่ได้เจนคลิป</b>\n"
    "/genall ลอง — <b>ดูก่อนว่าจะทำอะไรบ้าง ใช้เครดิตเท่าไร</b> (ไม่เข้าคิวจริง)\n"
    "/credits — <b>เครดิต Flow ที่เหลือ</b> (<code>/credits สด</code> = ไปอ่านของจริง)\n"
    "/failed — <b>งานที่ล้ม</b> พร้อมเหตุผล และปุ่มสั่งทำต่อ\n"
    "/retry &lt;เลข&gt; — สั่งงานที่ล้ม<b>ทำต่อจากขั้นที่ค้าง</b> (<code>/retry all</code> = ทุกชิ้น)\n"
    "/health — <b>สถานะระบบทุกสาย</b> (<code>/health สด</code> = เช็ค Flow ด้วย)\n"
    "/flow check — <b>ตรวจว่า Flow พร้อมเจนไหม</b> (ไม่เสียเครดิต)\n"
    "/digest — <b>สรุป 24 ชม.ที่ผ่านมา</b> (ส่งเองทุกวัน · "
    "<code>/digest 09:00</code> ตั้งเวลา · <code>/digest off</code> ปิด)\n"
    "/trash — <b>งานที่ลบไปแล้ว</b> ยังกู้ได้ 7 วัน\n"
    "/undo &lt;เลข&gt; — <b>กู้งานกลับ</b> (ไม่ใส่เลข = ใบที่ลบล่าสุด)\n"
    "/videos — <b>คลิปที่เจนไว้แล้วทั้งหมด</b> กดดูย้อนหลังได้\n"
    "/video &lt;เลข&gt; — ส่งคลิปของงานนั้นมาดูในแชท\n"
    "/basket &lt;ข้อความ&gt; — คำพูดบนปุ่มตะกร้าตอนโพสต์ TikTok"
)


# ยาวเกินกี่บรรทัดถึงควรพับเก็บ — สั้นกว่านี้กางไว้เลยอ่านง่ายกว่า
FOLD_MIN_LINES = 4


def fold(title: str, body: str, always: bool = False) -> str:
    """ทำข้อความยาวให้เป็น **บล็อกพับได้** — เห็นหัวข้อก่อน แตะแล้วค่อยกางเต็ม
    (ผู้ใช้สั่ง 23 ส.ค. 2026: "ใน telegram ดูยากมาก ทำเป็น drop down ได้ไหม")

    Telegram ไม่มีเมนู drop-down ในข้อความบอท แต่มี **บล็อกอ้างอิงแบบกางได้**
    (`<blockquote expandable>`) ซึ่งให้ผลเหมือนกัน: ย่อเหลือไม่กี่บรรทัดพร้อมปุ่ม
    กาง แตะแล้วขยายในที่เดิม ไม่ต้องยิงข้อความใหม่ ไม่ต้องรอเน็ต

    พับเฉพาะของที่ยาวจริง — ของสั้นพับแล้วกลายเป็นต้องแตะเพิ่มโดยไม่ได้อะไร
    """
    lines = [line for line in body.splitlines() if line.strip()]
    if not lines:
        return ""
    if not always and len(lines) < FOLD_MIN_LINES:
        return f"{title}\n" + "\n".join(lines) if title else "\n".join(lines)
    head = f"{title}\n" if title else ""
    return f"{head}<blockquote expandable>" + "\n".join(lines) + "</blockquote>"


# ร่องรอยว่า Telegram อ่านแท็กไม่ออก — ไม่ใช่ปัญหาเครือข่าย ส่งซ้ำเฉยๆ ไม่หาย
_TAG_ERROR = ("can't parse entities", "unsupported start tag",
              "unclosed start tag", "wrong end tag")


def _strip_fold(text: str) -> str:
    """ถอดแท็กบล็อกพับออก เหลือข้อความล้วน — ใช้เป็นทางถอยเมื่อ Telegram ไม่รับ"""
    return (text.replace("<blockquote expandable>", "")
                .replace("<blockquote>", "").replace("</blockquote>", ""))


def _clip_say(chat_id: str, text: str, keyboard=None, preview: bool = True) -> int:
    token = load_clip_token() or ""
    target = chat_id or load_config().get("telegram_clip_chat_id", "")
    if not token or not target:
        return 0
    try:
        return telegram_bot.send_message(token, target, text, keyboard, preview=preview)
    except telegram_bot.TelegramError as error:
        # **ห้ามให้ของสวยงามทำให้ข้อความหายไปทั้งอัน**
        # ถ้า Telegram รุ่นนี้ไม่รู้จักบล็อกพับ ให้ส่งแบบข้อความล้วนแทน
        # ผู้ใช้ยังได้เนื้อหาครบ แค่ไม่ได้พับ — ดีกว่าเงียบหายไปเฉยๆ
        if "<blockquote" in text and any(m in str(error).lower() for m in _TAG_ERROR):
            append_log("input", f"[บอทคลิป] Telegram ไม่รับบล็อกพับ ({error}) — ส่งแบบธรรมดาแทน")
            try:
                return telegram_bot.send_message(
                    token, target, _strip_fold(text), keyboard, preview=preview)
            except telegram_bot.TelegramError as second:
                error = second
        append_log("input", f"[บอทคลิป] ส่งข้อความไม่ได้: {error}")
        _explain_send_failure(error)
        return 0


# ผลการถามชื่อบอท/สถานะแชท — ถามทุกครั้งช้าและกินโควตา จึงจำไว้ชั่วคราว
_clip_bot_cache: dict = {"at": 0.0, "username": "", "chat_ok": None, "reason": ""}
CLIP_BOT_CACHE_SECONDS = 300


def clip_bot_status(force: bool = False) -> dict:
    """บอทคลิปตอนนี้คือตัวไหน และส่งหา chat ที่ตั้งไว้ได้จริงไหม

    มีไว้ให้เห็นปัญหา **ก่อน** งานจะวิ่ง — เจอจริง 11 ส.ค.: ระบบเจนคลิปจนจบแล้ว
    ค่อยขึ้น "chat not found" ซึ่งไม่ได้บอกว่าบอทตัวไหนหรือต้องทำอะไรต่อ
    """
    now = time.time()
    if not force and now - _clip_bot_cache["at"] < CLIP_BOT_CACHE_SECONDS:
        return dict(_clip_bot_cache)
    token = load_clip_token() or ""
    target = str(load_config().get("telegram_clip_chat_id", "") or "")
    info = {"at": now, "username": "", "chat_ok": None, "reason": ""}
    if not token:
        info["reason"] = "ยังไม่ได้ตั้งโทเคนบอทคลิป"
    else:
        try:
            info["username"] = telegram_bot.describe_bot(token).get("username", "")
        except telegram_bot.TelegramError as error:
            info["reason"] = f"โทเคนใช้ไม่ได้: {error}"
        if info["username"] and target:
            try:
                telegram_bot.call(token, "getChat", {"chat_id": target})
                info["chat_ok"] = True
            except telegram_bot.TelegramError as error:
                info["chat_ok"] = False
                info["reason"] = str(error)
        elif info["username"]:
            info["reason"] = "ยังไม่รู้ chat id — ทักบอทหนึ่งครั้งแล้วระบบจะจำให้เอง"
    _clip_bot_cache.update(info)
    return dict(info)


def _explain_send_failure(error) -> None:
    """แปลง error ดิบของ Telegram เป็นสิ่งที่ลงมือแก้ได้

    "chat not found" ไม่ได้แปลว่า chat id ผิด — id ของแชทส่วนตัวคือ id ผู้ใช้
    ซึ่งเหมือนกันทุกบอท แต่ **Telegram ห้ามบอททักคนก่อน** ถ้ายังไม่เคยมีใคร
    กด Start กับบอทตัวนั้น บอทจะส่งหาไม่ได้เลย
    """
    if "chat not found" not in str(error).lower():
        return
    status = clip_bot_status(force=True)
    name = f"@{status['username']}" if status["username"] else "บอทคลิป"
    append_log(
        "clip",
        f"บอทคลิปที่ตั้งไว้ตอนนี้คือ {name} แต่ยังไม่เคยมีใครเริ่มแชทกับบอทตัวนี้ "
        f"— เปิด Telegram หา {name} แล้วกด Start หนึ่งครั้ง "
        "หรือเปลี่ยนโทเคนกลับเป็นบอทเดิมในหน้าตั้งค่า",
    )


def _clip_keep(action, what: str) -> None:
    """เก็บข้อมูลลงดิสก์แบบ "ล้มแล้วไม่ลากงานหลักล้มตาม"

    การเก็บบันทึกเป็นงานรอง — ถ้าเขียนไฟล์ไม่ได้ (ดิสก์เต็ม สิทธิ์ไม่พอ) ก็ไม่ควร
    ทำให้ผู้ใช้ไม่ได้สตอรีบอร์ดที่ GPT วาดเสร็จแล้ว แต่ต้อง **เขียน log ไว้เสมอ**
    ไม่ใช่กลืนเงียบ ไม่งั้นข้อมูลหายโดยไม่มีใครรู้
    """
    try:
        action()
    except Exception as error:
        append_log("input", f"[บอทคลิป] เก็บ{what}ไม่สำเร็จ: {type(error).__name__}: {error}")


def _clip_send_product(chat_id: str, data: dict) -> None:
    """ส่งผลกลับเข้าแชท — รูปก่อน แล้วตามด้วยชื่อ + จุดเด่น"""
    token = load_clip_token() or ""
    escape = telegram_bot._escape
    files = [Path(path) for path in data.get("saved_images", [])]
    for index, path in enumerate(files, 1):
        if not path.is_file():
            continue
        try:
            telegram_bot.send_photo(
                token, chat_id, path, f"รูปที่ {index}/{len(files)}"
            )
        except telegram_bot.TelegramError as error:
            append_log("input", f"[บอทคลิป] ส่งรูปไม่ได้: {error}")
    lines = [
        f"🛍 <b>{escape(data.get('name', '')[:200])}</b>",
        "",
        f"🖼 รูปที่คัดมา {len(files)} ใบ (สีละ 1 + ภาพรวม 1)",
    ]
    highlights = data.get("highlights") or []
    if highlights:
        lines += ["", "✨ <b>คุณสมบัติเด่น</b>"]
        lines += [f"{i}. {escape(text)}" for i, text in enumerate(highlights, 1)]
    # ต้องเป็น **ลิงก์ที่ผู้ใช้ส่งมา** เพราะนั่นคือลิงก์ affiliate ที่ได้ค่าคอม
    # ลิงก์ที่ระบบแปลงเองตอนเปิดหน้า (data["url"]) ไม่มีรหัสผู้แนะนำติดไปด้วย
    affiliate = data.get("affiliate_url") or data.get("url", "")
    lines += ["", "🔗 <b>ลิงก์ affiliate</b>", escape(affiliate)]
    _clip_say(chat_id, "\n".join(lines))


# --------------------------------------- คิวงานเจนคลิป + จุดหยุดรออนุมัติ

clip_jobs = clip_queue.ClipQueue(DATA_DIR / "clip_queue.json")

# ---- บอกที่เก็บงานว่า "ชิ้นนี้ยังมีใบงานเปิดอยู่ในคิวที่ขั้นไหน" -----------
#
# ที่เก็บงาน (`clip_store`) ต้องรู้ตอนย้ายโฟลเดอร์ ไม่งั้นงานที่เจนคลิปเสร็จแล้ว
# แต่ยังรอคนอนุมัติจะถูกย้ายไป `clips/` ทั้งที่กระดานยังจัดไว้กอง "รออนุมัติคลิป"
# แล้วโฟลเดอร์กับกระดานจะบอกไม่ตรงกัน (วัดจริง 27 ส.ค. 2569: โฟลเดอร์ 37 กระดาน 31)
#
# เสียบเป็นฟังก์ชันแทนที่จะให้ `clip_store` เรียกคิวเอง เพราะที่เก็บงานไม่ควร
# รู้จักคิว — ใครเอา `clip_store` ไปใช้ที่อื่นจะได้ไม่ต้องลากคิวไปด้วย
def _open_stage_of(item_id: str) -> str:
    """ขั้นของใบงานที่ยังเปิดอยู่ของสินค้าชิ้นนี้ — คืน "" ถ้าไม่มีใบงานเปิดอยู่"""
    job = next((j for j in clip_jobs.all()
                if str(j.get("item_id")) == str(item_id)
                and j.get("stage") in clip_queue.OPEN_STAGES), None)
    return (job or {}).get("stage") or ""

clip_store.stage_lookup = _open_stage_of


def _clip_log(message: str) -> None:
    append_log("input", f"[คลิป] {message}")


def _clip_buttons(job_id: str, kind: str) -> dict:
    """ปุ่มอนุมัติ/สั่งแก้/พักไว้ — คำนำหน้า clip: จองไว้ให้ on_callback ของบอทคลิป

    **แถวที่สองคือปุ่มพักไว้รอแก้** (ผู้ใช้สั่ง 27 ส.ค. 2026)

    ของเดิมมีสองทางคือ "ผ่าน" กับ "สั่งแก้" ซึ่งทั้งคู่บังคับให้ทำอะไรสักอย่าง
    เดี๋ยวนั้น แต่บางใบยังตัดสินใจไม่ได้ (ต้องไปหารูปมาเพิ่ม · รอถามร้าน ·
    ยังไม่ว่างดู) พอไม่กดอะไรเลย ใบนั้นก็ค้างปนกับงานที่เดินได้จริงจนนับไม่ถูก

    แยกเป็นแถวล่างเพราะเป็น **ทางออกคนละชนิด** — สองปุ่มบนคือเดินหน้าต่อ
    ส่วนปุ่มนี้คือหยุดไว้ก่อน วางแถวเดียวกันจะกดพลาดได้ง่ายบนมือถือ
    """
    labels = {
        "storyboard": ("✅ อนุมัติสตอรีบอร์ด", "✏️ สั่งแก้สตอรีบอร์ด", "sb"),
        "script": ("✅ อนุมัติบทพูด", "✏️ สั่งแก้บทพูด", "sc"),
        "video": ("✅ อนุมัติคลิป", "🔄 เจนใหม่", "vid"),
    }
    ok_text, edit_text, tag = labels[kind]
    return {"inline_keyboard": [
        [
            {"text": ok_text, "callback_data": f"clip:{tag}_ok:{job_id}"},
            {"text": edit_text, "callback_data": f"clip:{tag}_edit:{job_id}"},
        ],
        [
            {"text": "🅿 พักไว้รอแก้", "callback_data": f"clip:park:{job_id}:"},
        ],
    ]}


# เริ่มต้นด้วยกี่ใบ — ส่งเข้า GPT มากกว่านี้รูปจะซ้ำกันเองและกินเพดานอัปโหลด
CLIP_START_IMAGES = 3
# สินค้าที่ปรับเปลี่ยนรูปทรงได้ต้องใช้รูปมากกว่า — อย่างน้อยท่าละใบ
CLIP_TRANSFORM_IMAGES = 5
CLIP_MAX_IMAGES = 8


def _clip_send_images(job: dict) -> None:
    """ส่งชุดรูปให้ตรวจ พร้อมปุ่ม เพิ่ม / ลบ / เปลี่ยน รายใบ

    รูปที่ส่งเข้า GPT เป็นตัวกำหนดหน้าตาของทั้งคลิป — ตัวคัดอัตโนมัติเลือกผิดได้
    (เลือกรูปที่มีตัวหนังสือเต็มใบ หรือรูปซ้ำ) ถ้าไม่ให้แก้ตรงนี้ พอรู้ตัวทีหลัง
    ต้องทำใหม่ทั้งงาน
    """
    chat_id = job["chat_id"]
    item_id = job.get("item_id", "")
    run = clip_store.load_run(DATA_DIR, item_id)
    base = Path(run.get("folder") or clip_store.run_dir(DATA_DIR, item_id))
    images = run.get("images") or []
    pool = run.get("image_pool") or []
    token = load_clip_token() or ""

    for index, name in enumerate(images, 1):
        path = base / name
        if not path.is_file():
            continue
        try:
            telegram_bot.send_photo(token, chat_id, path, f"รูปที่ {index}/{len(images)}")
        except telegram_bot.TelegramError as error:
            _clip_log(f"ส่งรูปที่ {index} ไม่ได้: {error}")

    rows = []
    for index in range(1, len(images) + 1):
        row = []
        # เหลือใบเดียวแล้วห้ามลบ — ส่งเข้า GPT โดยไม่มีรูปเลยไม่ได้
        if len(images) > 1:
            row.append({"text": f"🗑 ลบรูป {index}",
                        "callback_data": f"clip:img_del:{job['id']}:{index}"})
        if pool:
            row.append({"text": f"🔄 เปลี่ยนรูป {index}",
                        "callback_data": f"clip:img_swap:{job['id']}:{index}"})
        if row:
            rows.append(row)

    last = []
    if pool and len(images) < CLIP_MAX_IMAGES:
        last.append({"text": f"➕ เพิ่มรูป (คลังเหลือ {len(pool)})",
                     "callback_data": f"clip:img_add:{job['id']}:"})
    last.append({"text": "✅ ใช้ชุดนี้ ทำสตอรีบอร์ดต่อ",
                 "callback_data": f"clip:img_ok:{job['id']}:"})
    rows.append(last)
    # 🅿 พักไว้รอแก้ — **ต้องมีในทุกการ์ดที่ต้องตัดสินใจ** (ผู้ใช้สั่ง 27 ส.ค. 2569)
    # ค้างที่ชุดรูปคือ "ต้องไปหารูปมาเพิ่ม" ซึ่งทำเดี๋ยวนั้นไม่ได้เสมอไป
    rows.append([{"text": "🅿 รอแก้",
                  "callback_data": f"clip:park:{job['id']}:"}])

    note = (
        f"🖼 <b>ชุดรูปที่จะส่งเข้า GPT</b> — {len(images)} ใบ "
        f"(คลังสำรอง {len(pool)} ใบ)\n"
        "แก้ได้ก่อนทำสตอรีบอร์ด · รูปที่ลบไม่ได้หายไปไหน กลับมาเลือกใหม่ได้"
    )
    _clip_say(chat_id, note, {"inline_keyboard": rows})


CLIP_MAX_HIGHLIGHTS = 6

# สินค้าที่ "ปรับเปลี่ยนรูปทรงได้" ต้องมีรูปอ้างอิง**ทุกท่า** ไม่ใช่ท่าเดียวหลายใบ
#
# โซฟาเบดที่จุดเด่นเขียนว่า "ปรับนั่ง–นอนได้" แต่ส่งเข้า GPT แต่รูปตอนเป็นโซฟา
# สตอรีบอร์ดจะเดาท่าตอนกางเองทั้งหมด แล้วคลิปจะออกมาไม่ตรงสินค้าจริง
TRANSFORM_RE = re.compile(
    r"ปรับ(?:ได้|เป็น|นั่ง|นอน|เอน|ระดับ|ท่า|มุม|องศา)"
    # ถอด/พับ/กาง มีคำคั่นได้ เช่น "ถอดซักได้" "ถอดปลอกได้" "พับเก็บได้"
    r"|ปรับเปลี่ยน|เปลี่ยนรูปทรง|แปลงร่าง|กางออก|ยืดได้"
    r"|ถอด\S{0,8}ได้|พับ\S{0,8}ได้|พับเก็บ|กาง\S{0,8}ได้"
    r"|นั่ง[–\-]นอน|นอน[–\-]นั่ง|\d+\s*in\s*1|2in1|3in1|multi[- ]?function",
    re.I,
)

# เกณฑ์เพิ่มที่ส่งให้ Gemini ตอนคัดรูป เมื่อเจอว่าสินค้าปรับเปลี่ยนได้
TRANSFORM_JUDGE_RULE = (
    "**สินค้านี้ปรับเปลี่ยนรูปทรงได้** — ต้องเลือกรูปที่แสดง **ทุกท่า/ทุกสถานะ** "
    "อย่างน้อยท่าละ 1 รูป (เช่น ตอนเป็นโซฟา กับ ตอนกางเป็นเตียง / ตอนพับ กับ ตอนกาง) "
    "สำคัญกว่าการเลือกรูปสวย ถ้าต้องเลือกระหว่างรูปสวยท่าเดิม กับรูปธรรมดาท่าใหม่ "
    "ให้เอารูปท่าใหม่"
)

# ข้อความที่ส่งเข้า GPT ตอนทำสตอรีบอร์ด เมื่อสินค้าปรับเปลี่ยนรูปทรงได้
#
# ต้องสั่งให้ชัดว่า **ฉากที่โชว์การเปลี่ยนต้องอ้างอิงรูปที่แนบไป ห้ามวาดท่าเอง**
# ไม่งั้น GPT จะเดารูปทรงตอนกางออกเอง แล้วคลิปที่ได้ไม่ตรงสินค้าจริง
# (ตรงกับบั๊กที่ KVID เคยเจอ: รูปอ้างอิงหลุด → โมเดลมั่วสินค้าเอง)
TRANSFORM_STORYBOARD_ASK = (
    "สินค้านี้ **ปรับเปลี่ยนรูปทรงได้** และรูปที่แนบมามีครบทุกท่าแล้ว\n"
    "ข้อบังคับ: ฉากไหนที่โชว์การปรับเปลี่ยน ให้ยึดรูปทรงจาก **รูปที่แนบมาของท่านั้น** "
    "ห้ามวาดท่าขึ้นเอง และให้ระบุกำกับในแต่ละฉากด้วยว่าใช้รูปที่เท่าไร\n"
    "ควรมีฉากที่ให้เห็นการเปลี่ยนจากท่าหนึ่งไปอีกท่าอย่างน้อย 1 ฉาก"
)


def transform_hint(highlights: list[str], name: str = "") -> str:
    """คืนเกณฑ์เพิ่มสำหรับคัดรูป ถ้าจุดเด่นบอกว่าสินค้าปรับเปลี่ยนได้"""
    blob = " ".join(list(highlights or []) + [name or ""])
    return TRANSFORM_JUDGE_RULE if TRANSFORM_RE.search(blob) else ""





def _clip_send_worksheet(job: dict) -> None:
    """ส่ง **ใบงานเดียวจบ** ให้ตรวจ — รูป + จุดเด่น + ลิงก์ + ปุ่มทั้งหมดในที่เดียว

    ของเดิมส่งกระจายเป็น 3–8 ข้อความ (รูปทีละใบ · ข้อความสินค้า · การ์ดรูป ·
    การ์ดจุดเด่น) ผู้ใช้ต้องเลื่อนขึ้นลงเทียบเอง แล้วยังต้องกดผ่านสองครั้ง
    แยกกันอีก — ตามผังที่ผู้ใช้เขียน (12 ส.ค.) เปลี่ยนเป็นใบงานเดียว
    **กด Approve ทีเดียวจบทั้งใบ**

    สิ่งที่จงใจไม่โชว์: รายละเอียดสินค้ายาวๆ และการ์ดตัวอย่างลิงก์ — สองอย่างนี้
    ดันของที่ต้องตรวจจริงตกจอ
    """
    chat_id = job["chat_id"]
    token = load_clip_token() or ""
    job_id = job["id"]
    run = clip_store.load_run(DATA_DIR, job.get("item_id", ""))
    base = Path(run.get("folder") or clip_store.run_dir(DATA_DIR, job.get("item_id", "")))
    images = run.get("images") or []
    highlights = run.get("highlights") or []
    pool = run.get("image_pool") or []
    escape = telegram_bot._escape

    # 1) รูปที่คัดมา — ไปเป็นอัลบั้มเดียว เห็นครบในกรอบเดียว เทียบกันได้ทันที
    files = [base / name for name in images]
    if token and files:
        try:
            telegram_bot.send_media_group(
                token, chat_id, files,
                caption=f"🛍 <b>{escape(run.get('name', '')[:180])}</b>\n"
                        f"🖼 รูปที่คัดมา {len(files)} ใบ",
            )
        except telegram_bot.TelegramError as error:
            append_log("input", f"[บอทคลิป] ส่งอัลบั้มรูปไม่ได้: {error}")

    # 2) เนื้อใบงาน + ปุ่มทั้งหมด — ข้อความเดียว
    lines = ["✨ <b>คุณสมบัติเด่น</b>"]
    lines += [f"<b>{i}.</b> {escape(text)}" for i, text in enumerate(highlights, 1)]
    if not highlights:
        lines.append("<i>— ยังไม่มี —</i>")
    affiliate = run.get("affiliate_url") or run.get("product_url") or ""
    lines += ["", "🔗 <b>ลิงก์ affiliate</b>", f"<code>{escape(affiliate)}</code>"]

    rows: list[list[dict]] = []
    for index in range(1, len(images) + 1):
        row = []
        if len(images) > 1:
            row.append({"text": f"🗑 รูป {index}",
                        "callback_data": f"clip:img_del:{job_id}:{index}"})
        if pool:
            row.append({"text": f"🔄 รูป {index}",
                        "callback_data": f"clip:img_swap:{job_id}:{index}"})
        if row:
            rows.append(row)
    if pool and len(images) < CLIP_MAX_IMAGES:
        rows.append([{"text": "➕ เพิ่มรูป",
                      "callback_data": f"clip:img_add:{job_id}:"}])
    # 🖼 ดูรูปทั้งหมด (ผู้ใช้สั่ง 22 ส.ค. 2026) — ใบงานโชว์แค่ 3 ใบที่ AI คัดให้
    # ที่เหลืออยู่ในคลังโดยไม่มีใครเห็น เลือกรูปโดยไม่ได้ดูของก็เลือกไม่ถูก
    if pool:
        rows.append([{
            "text": f"🖼 ดูรูปทั้งหมด {len(images) + len(pool)} ใบ",
            "callback_data": f"clip:img_all:{job_id}:",
        }])

    for index in range(1, len(highlights) + 1):
        row = [{"text": f"✏️ ข้อ {index}",
                "callback_data": f"clip:hl_edit:{job_id}:{index}"}]
        if len(highlights) > 1:
            row.append({"text": f"🗑 ข้อ {index}",
                        "callback_data": f"clip:hl_del:{job_id}:{index}"})
        rows.append(row)
    if len(highlights) < CLIP_MAX_HIGHLIGHTS:
        rows.append([{"text": "➕ เพิ่มจุดเด่น",
                      "callback_data": f"clip:hl_add:{job_id}:"}])

    # ปุ่มตัดสินอยู่ล่างสุดเสมอ — กดทีเดียวผ่านทั้งใบ
    #
    # **สามทางเลือก ไม่ใช่สอง** (ผู้ใช้สั่งเพิ่ม 27 ส.ค. 2026)
    # ของเดิมมีแค่ผ่านกับยกเลิก ซึ่งบังคับให้ตัดสินใจเดี๋ยวนั้นทั้งที่บางใบ
    # ยังไม่พร้อม (รูปไม่ครบ · จุดเด่นยังไม่ถูก) ทิ้งไว้เฉยๆ ก็ปนกับงานที่เดินได้
    # ส่วนยกเลิกก็แรงเกินไปเพราะของที่ทำไว้แล้วหายหมด
    #
    # 🅿 = "ยังเอาอยู่ แต่ยังไม่พร้อม" เครื่องหยุดแตะ ของยังอยู่ครบ กลับมาแก้เมื่อไรก็ได้
    rows.append([
        {"text": "✅ Approve", "callback_data": f"clip:sheet_ok:{job_id}:"},
        {"text": "🅿 รอแก้", "callback_data": f"clip:park:{job_id}:"},
        {"text": "✖️ Cancel", "callback_data": f"clip:sheet_cancel:{job_id}:"},
    ])
    _clip_say(chat_id, "\n".join(lines), {"inline_keyboard": rows}, preview=False)


def _clip_send_highlights(job: dict) -> None:
    """ส่งจุดเด่นให้ตรวจ พร้อมปุ่ม แก้ / ลบ / เพิ่ม รายข้อ

    จุดเด่นถูกส่งเข้า GPT คู่กับรูป เป็นตัวกำหนดว่าคลิปจะพูดถึงอะไร — ตัวสกัด
    อัตโนมัติหยิบผิดได้บ่อย (ได้เงื่อนไขร้าน/โปรโมชันแทนคุณสมบัติสินค้า)
    """
    escape = telegram_bot._escape
    chat_id = job["chat_id"]
    run = clip_store.load_run(DATA_DIR, job.get("item_id", ""))
    highlights = run.get("highlights") or []

    rows = []
    for index in range(1, len(highlights) + 1):
        row = [{"text": f"✏️ แก้ข้อ {index}",
                "callback_data": f"clip:hl_edit:{job['id']}:{index}"}]
        # เหลือข้อเดียวห้ามลบ — ส่งเข้า GPT โดยไม่มีจุดเด่นเลยไม่ได้
        if len(highlights) > 1:
            row.append({"text": f"🗑 ลบข้อ {index}",
                        "callback_data": f"clip:hl_del:{job['id']}:{index}"})
        rows.append(row)
    last = []
    if len(highlights) < CLIP_MAX_HIGHLIGHTS:
        last.append({"text": "➕ เพิ่มจุดเด่น",
                     "callback_data": f"clip:hl_add:{job['id']}:"})
    last.append({"text": "✅ ใช้จุดเด่นชุดนี้",
                 "callback_data": f"clip:hl_ok:{job['id']}:"})
    rows.append(last)
    rows.append([{"text": "🅿 รอแก้",
                  "callback_data": f"clip:park:{job['id']}:"}])

    lines = [f"✨ <b>คุณสมบัติเด่น</b> — {len(highlights)} ข้อ", ""]
    lines += [f"<b>{i}.</b> {escape(text)}" for i, text in enumerate(highlights, 1)]
    lines.append("")
    lines.append("แก้ได้ก่อนส่งเข้า GPT · กด ✏️ แล้วพิมพ์ข้อความใหม่")
    _clip_say(chat_id, "\n".join(lines), {"inline_keyboard": rows})


def _clip_edit_highlights(job_id: str, chat_id: str, action: str, arg: str) -> str:
    """ลบ / เพิ่ม จุดเด่น (การแก้ข้อความรอผู้ใช้พิมพ์ ดู _clip_take_edit)"""
    job = clip_jobs.get(job_id) or {}
    item_id = job.get("item_id", "")
    run = clip_store.load_run(DATA_DIR, item_id)
    if not run:
        return "ไม่พบงานนี้แล้ว"
    highlights = list(run.get("highlights") or [])
    index = int(arg) - 1 if arg.isdigit() else -1

    if action == "hl_edit":
        if not 0 <= index < len(highlights):
            return "ข้อนั้นไม่มีแล้ว"
        clip_jobs.update(job_id, awaiting=f"highlight:{index}")
        _clip_say(
            chat_id,
            f"✏️ <b>พิมพ์ข้อความใหม่ของข้อ {index + 1}</b>\n"
            f"ของเดิม: <i>{telegram_bot._escape(highlights[index])}</i>",
        )
        return f"พิมพ์จุดเด่นข้อ {index + 1} ใหม่มาได้เลย"

    if action == "hl_del":
        if not 0 <= index < len(highlights):
            return "ข้อนั้นไม่มีแล้ว"
        if len(highlights) <= 1:
            return "เหลือข้อเดียว ลบไม่ได้"
        highlights.pop(index)
        note = "ลบแล้ว"
    elif action == "hl_add":
        if len(highlights) >= CLIP_MAX_HIGHLIGHTS:
            return f"เพิ่มได้สูงสุด {CLIP_MAX_HIGHLIGHTS} ข้อ"
        clip_jobs.update(job_id, awaiting=f"highlight:{len(highlights)}")
        _clip_say(chat_id, "➕ <b>พิมพ์จุดเด่นข้อใหม่</b>ได้เลย")
        return "พิมพ์จุดเด่นข้อใหม่มาได้เลย"
    else:
        return f"ไม่รู้จักปุ่ม {action}"

    _clip_keep(
        lambda: clip_store.set_highlights(DATA_DIR, item_id, highlights), "จุดเด่น"
    )
    # เหตุผลเดียวกับฝั่งรูป — สั่งจากเว็บไม่ต้องยิงการ์ดเข้าแชท
    # การ์ดนี้อัปโหลดรูปทั้งอัลบั้มขึ้น Telegram ใหม่ ทั้งที่แก้แค่ข้อความหนึ่งบรรทัด
    if not _web_call():
        _clip_send_worksheet(clip_jobs.get(job_id))
    return note


# รูปหนึ่งอัลบั้มของ Telegram ใส่ได้มากสุด 10 ใบ — เกินนั้นต้องแยกอัลบั้ม
ALBUM_LIMIT = 10


def _clip_send_all_images(job_id: str, chat_id: str) -> str:
    """ส่ง **รูปสินค้าทุกใบที่โหลดมา** พร้อมเลขกำกับ + ปุ่มเลือกใบที่ชอบ

    **ทำไมต้องมี** ระบบโหลดรูปมาเก็บไว้ครบ (ทีวีเครื่องหนึ่ง 19 ใบ) แต่ใบงานโชว์
    แค่ 3 ใบที่ AI คัดให้ ที่เหลืออยู่ในคลังโดยไม่มีใครเห็น เวลาอยากเปลี่ยนรูป
    ทำได้แค่กด 🔄 แล้วมันหยิบใบถัดไปในคลังมาให้แบบสุ่มไล่ — เหมือนเลือกของโดย
    ไม่ได้ดูของ ต้องกดวนจนกว่าจะบังเอิญเจอใบที่ชอบ

    เห็นครบแล้วแตะเลขที่ต้องการได้เลย จบในสองแตะ
    """
    job = clip_jobs.get(job_id) or {}
    item_id = str(job.get("item_id") or "")
    run = clip_store.load_run(DATA_DIR, item_id)
    if not run:
        return "ไม่พบงานนี้แล้ว"

    base = Path(run.get("folder") or clip_store.run_dir(DATA_DIR, item_id))
    images = list(run.get("images") or [])
    pool = list(run.get("image_pool") or [])
    token = load_clip_token() or ""
    escape = telegram_bot._escape

    # เรียง "ใบที่ใช้อยู่" ไว้ก่อนเสมอ เลข 1..N จึงตรงกับปุ่มในใบงานพอดี
    every = images + pool
    files = [base / name for name in every if (base / name).is_file()]
    if not files:
        return "งานนี้ไม่มีไฟล์รูปเก็บไว้"

    used = len(images)
    for start in range(0, len(files), ALBUM_LIMIT):
        chunk = files[start:start + ALBUM_LIMIT]
        head = start + 1
        tail = start + len(chunk)
        note = (f"🖼 รูปที่ {head}–{tail} จากทั้งหมด {len(files)} ใบ"
                if len(files) > ALBUM_LIMIT else f"🖼 รูปทั้งหมด {len(files)} ใบ")
        if start == 0:
            note = (f"🛍 <b>{escape((run.get('name') or '')[:120])}</b>\n{note}\n"
                    f"✅ ใบที่ใช้อยู่ตอนนี้: <b>1–{used}</b>")
        try:
            telegram_bot.send_media_group(token, chat_id, chunk, caption=note)
        except telegram_bot.TelegramError as error:
            append_log("input", f"[บอทคลิป] ส่งอัลบั้มรูปไม่ได้: {error}")
            return f"ส่งรูปไม่สำเร็จ: {error}"

    # ปุ่มเลือกเฉพาะใบที่ **ยังไม่ได้ใช้** — ใบที่ใช้อยู่แล้วกดไปก็ไม่มีอะไรเกิดขึ้น
    rows, row = [], []
    for offset in range(len(pool)):
        number = used + offset + 1
        row.append({"text": f"➕ {number}",
                    "callback_data": f"clip:img_use:{job_id}:{number}"})
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if len(images) >= CLIP_MAX_IMAGES:
        tip = (f"ตอนนี้ใช้ครบ {CLIP_MAX_IMAGES} ใบแล้ว — "
               "กด 🗑 ลบใบที่ไม่เอาออกก่อน แล้วค่อยกดเลือกใบใหม่")
    elif rows:
        tip = "แตะเลขข้างล่างเพื่อเอารูปใบนั้นมาใช้"
    else:
        tip = "ใช้ครบทุกใบที่โหลดมาแล้ว"
    _clip_say(chat_id, tip, {"inline_keyboard": rows} if rows else None, preview=False)
    return f"ส่งรูปครบ {len(files)} ใบแล้ว"


def _clip_edit_images(job_id: str, chat_id: str, action: str, arg: str) -> str:
    """เพิ่ม / ลบ / เปลี่ยน รูปหนึ่งใบ แล้วส่งชุดใหม่ให้ดู"""
    job = clip_jobs.get(job_id) or {}
    item_id = job.get("item_id", "")
    run = clip_store.load_run(DATA_DIR, item_id)
    if not run:
        return "ไม่พบงานนี้แล้ว"
    images = list(run.get("images") or [])
    pool = list(run.get("image_pool") or [])

    index = int(arg) - 1 if arg.isdigit() else -1
    if action in ("img_del", "img_swap") and not 0 <= index < len(images):
        return "รูปนั้นไม่มีแล้ว"

    if action == "img_del":
        if len(images) <= 1:
            return "เหลือใบเดียว ลบไม่ได้"
        # ย้ายไปคลัง ไม่ลบไฟล์ — กดเอากลับมาได้
        pool.append(images.pop(index))
        note = "ลบแล้ว"
    elif action == "img_swap":
        if not pool:
            return "คลังหมดแล้ว ไม่มีรูปให้เปลี่ยน"
        pool.append(images[index])
        images[index] = pool.pop(0)
        note = "เปลี่ยนรูปแล้ว"
    elif action == "img_add":
        if not pool:
            return "คลังหมดแล้ว"
        if len(images) >= CLIP_MAX_IMAGES:
            return f"เพิ่มได้สูงสุด {CLIP_MAX_IMAGES} ใบ"
        images.append(pool.pop(0))
        note = "เพิ่มรูปแล้ว"
    elif action == "img_use":
        # เลือกใบเจาะจงจากรายการ "ดูรูปทั้งหมด" — เลขที่ส่งมานับต่อจากใบที่ใช้อยู่
        if len(images) >= CLIP_MAX_IMAGES:
            return f"ใช้ครบ {CLIP_MAX_IMAGES} ใบแล้ว — ลบใบที่ไม่เอาออกก่อน"
        spot = index - len(images)          # index คือเลข-1 มาแล้วจากด้านบน
        if not 0 <= spot < len(pool):
            return "ไม่มีรูปเลขนั้นในคลัง (รายการอาจเปลี่ยนไปแล้ว กดดูรูปทั้งหมดใหม่)"
        images.append(pool.pop(spot))
        note = f"เอารูปที่ {index + 1} มาใช้แล้ว"
    else:
        return f"ไม่รู้จักปุ่ม {action}"

    _clip_keep(
        lambda: clip_store.set_images(DATA_DIR, item_id, images, pool), "ชุดรูป"
    )
    # **สั่งจากหน้าเว็บไม่ต้องยิงการ์ดเข้าแชท** — หน้าเว็บวาดของใหม่ให้เองอยู่แล้ว
    #
    # การ์ดนี้คือการ **อัปโหลดอัลบั้มรูปทั้งชุดขึ้น Telegram ใหม่ทุกครั้ง**
    # กดลบ/เพิ่มรูปหนึ่งใบจึงกินเวลาหลายวินาที ทั้งที่งานจริงคือเขียนไฟล์ json
    # (25 ส.ค. 2026 ผู้ใช้ถามว่า "ทำไมตอนลบรูปกว่าจะลบช้ามาก")
    #
    # แชทยังได้การ์ดครบตอนกด "ใช้ชุดรูปนี้" ซึ่งเป็นจังหวะที่ต้องเห็นของจริง
    if not _web_call():
        _clip_send_worksheet(clip_jobs.get(job_id))
    return note


def _clip_send_storyboard(job: dict, run: dict) -> None:
    """ส่งภาพสตอรีบอร์ดให้ผู้ใช้ตรวจ พร้อมปุ่มอนุมัติ/สั่งแก้"""
    chat_id = job["chat_id"]
    token = load_clip_token() or ""
    folder = Path(run.get("folder") or clip_store.run_dir(DATA_DIR, job["item_id"]))
    frames = [folder / name for name in run.get("storyboard", [])]
    frames = [path for path in frames if path.is_file()]

    if not frames:
        note = "⚠️ ยังไม่ได้ภาพสตอรีบอร์ด"
        if run.get("refused"):
            # ตัวกรองของ ChatGPT ปฏิเสธ — คนละเรื่องกับระบบเราพัง ต้องบอกให้ชัด
            note = (
                "⚠️ <b>ChatGPT ปฏิเสธการสร้างภาพ</b> (ตัวกรองเนื้อหาของเขาเอง)\n"
                f"<i>{telegram_bot._escape(run.get('refusal_text', '')[:200])}</i>"
            )
        _clip_say(chat_id, f"{note}\n\nกด ✏️ เพื่อสั่งแก้แล้วลองใหม่ได้",
                  _clip_buttons(job["id"], "storyboard"))
        return

    for index, path in enumerate(frames, 1):
        last = index == len(frames)
        caption = f"🎬 สตอรีบอร์ด {index}/{len(frames)} — {run.get('name', '')[:60]}"
        try:
            telegram_bot.send_photo(
                token, chat_id, path, caption,
                # ปุ่มติดกับใบสุดท้ายใบเดียว ไม่งั้นทุกใบมีปุ่มแล้วกดผิดใบได้
                _clip_buttons(job["id"], "storyboard") if last else None,
            )
        except telegram_bot.TelegramError as error:
            _clip_log(f"ส่งสตอรีบอร์ดไม่ได้: {error}")


def _clip_send_script(job: dict, run: dict) -> None:
    """ส่ง **บทพูด** ให้ตรวจ — ไม่ส่งคำสั่งเจนวิดีโอ

    คำสั่งสำหรับ Google Flow ยาวหลายพันตัวและเป็นศัพท์เทคนิคล้วน ผู้ใช้ไม่ได้อยาก
    อ่านในแชท — เก็บไว้ในเครื่องแล้วเอาไปใช้ตอนเจนเอง ส่วนสิ่งที่ต้องให้คนตรวจคือ
    คำพูดที่จะได้ยินในคลิป
    """
    escape = telegram_bot._escape
    script = run.get("script") or []
    if not script:
        _clip_say(
            job["chat_id"],
            "⚠️ ยังไม่ได้บทพูดจาก GPT — กด ✏️ เพื่อสั่งขอใหม่",
            _clip_buttons(job["id"], "script"),
        )
        return
    # โชว์จำนวนคำให้เห็นทันที — เพดานคือ 25–35 คำสำหรับคลิป 10 วินาที
    # เกินแล้วเสียงจะล้นคลิป ต้องเห็นตั้งแต่ตอนตรวจ ไม่ใช่ไปรู้ตอนคลิปออกมาแล้ว
    words = chatgpt_driver.count_words(script)
    low, high = chatgpt_driver.SCRIPT_MIN_WORDS, chatgpt_driver.SCRIPT_MAX_WORDS
    mark = "✅" if low <= words <= high else ("⚠️ ยาวเกิน" if words > high else "⚠️ สั้นไป")
    body = fold(
        f"🗣 <b>บทพูดในคลิป</b> — ราว {words} คำ {mark} (เกณฑ์ {low}–{high})",
        "\n".join(f"<b>{i}.</b> {escape(text)}" for i, text in enumerate(script, 1)),
    )
    parts = _split_text(body, TELEGRAM_TEXT_LIMIT)
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        _clip_say(job["chat_id"], part,
                  _clip_buttons(job["id"], "script") if last else None)


def _clip_collect(job: dict) -> None:
    """ขั้นแรก: ดึงสินค้า → เก็บ → ส่งชุดรูปให้ผู้ใช้ตรวจ/แก้ก่อนส่งเข้า GPT"""
    chat_id = job["chat_id"]
    _clip_say(chat_id, "🔎 กำลังเปิดหน้าสินค้า… รอสักครู่")
    try:
        # โหลด **รูปทั้งหมด** ไม่ใช่เฉพาะที่คัดแล้ว — ต้องมีคลังไว้ให้กดเปลี่ยน/เพิ่ม
        # ในแชท ถ้าโหลดแต่ที่คัดไว้ (บางสินค้าเหลือใบเดียว) จะไม่มีอะไรให้สลับเลย
        data = shopee_collect(job["link"], want_all=True)
    except Exception as error:
        hint = ""
        if type(error).__name__ == "ShopeeNeedsLogin":
            hint = (
                "\n\nยังไม่ได้ล็อกอิน Shopee — รันคำสั่งนี้ที่เครื่อง:\n"
                "<code>python flow_worker.py login-shopee</code>"
            )
        _clip_say(chat_id, f"❌ ดึงข้อมูลไม่สำเร็จ: "
                           f"{telegram_bot._escape(str(error)[:200])}{hint}")
        raise
    data["affiliate_url"] = job["link"]      # ลิงก์ที่ผู้ใช้ส่งมา = ลิงก์ affiliate

    # want_all=True ทำให้ saved_images กลายเป็นรูปทุกใบ ต้องคัดเองอีกชั้น
    # ไม่งั้นจะส่งเข้า GPT ทั้ง 20 ใบ (เกินเพดานที่รับได้ และรูปซ้ำกันเอง)
    import shopee_scrape

    paired = data.get("candidates") or []
    hint = transform_hint(data.get("highlights") or [], data.get("name", ""))
    want = CLIP_TRANSFORM_IMAGES if hint else CLIP_START_IMAGES

    picked = []
    if len(paired) > want:
        if hint:
            # จุดเด่นบอกว่าปรับเปลี่ยนได้ → ให้ Gemini ดูรูปจริงแล้วเลือกให้ครบทุกท่า
            # เลือกแบบกระจายเฉยๆ ไม่การันตีว่าจะได้ท่าที่ต่างกัน
            _clip_log("จุดเด่นบอกว่าสินค้าปรับเปลี่ยนได้ — คัดรูปให้ครบทุกท่า")
            from flow_worker import load_gemini_api_key

            indexes = shopee_scrape.judge_images(
                [item["file"] for item in paired], load_gemini_api_key(),
                count=want, log=_clip_log, extra_rule=hint,
            )
            picked = [paired[i] for i in indexes if 0 <= i < len(paired)]
        if not picked:
            picked = shopee_scrape.spread_pick(paired)
    else:
        picked = paired
    picked = picked[:want]
    data["picked"] = picked
    data["saved_images"] = [item["file"] for item in picked]

    clip_jobs.update(job["id"], item_id=data["item_id"], name=data.get("name", "")[:80])
    _clip_log(
        f"ดึงสินค้าแล้ว: {data['name'][:50]} · "
        f"โหลดรูป {len(paired)} ใบ · เริ่มด้วย {len(picked)} ใบ"
        + (" (สินค้าปรับเปลี่ยนได้)" if hint else "")
    )
    _clip_keep(lambda: clip_store.save_product(DATA_DIR, data), "ข้อมูลสินค้า")

    if not data.get("highlights") or not data.get("saved_images"):
        _clip_say(chat_id, "❌ ยังไม่มีรูปหรือจุดเด่นครบ ทำต่อไม่ได้")
        raise RuntimeError("ไม่มีรูปหรือจุดเด่นครบ")

    clip_jobs.update(
        job["id"], stage=clip_queue.STAGE_IMAGE_REVIEW,
        images_ok=False, highlights_ok=False,
    )
    _clip_send_worksheet(clip_jobs.get(job["id"]))


def _clip_make(job: dict) -> None:
    """ขั้นสอง: เอาชุดรูปที่ผู้ใช้อนุมัติแล้วส่งเข้า GPT → สตอรีบอร์ด + คำสั่ง + บทพูด"""
    # import อยู่ในบล็อกกันพลาดด้วย — ถ้า import ล้ม (เช่นไม่มี playwright)
    # แล้วปล่อยหลุดออกไป thread จะตายเงียบ ไม่มี log ไม่มีข้อความเข้าแชทเลย
    try:
        from flow_worker import open_browser
    except Exception as error:
        raise RuntimeError(f"โหลดโมดูลไม่ได้: {error}") from error

    chat_id = job["chat_id"]
    item_id = job.get("item_id", "")
    run = clip_store.load_run(DATA_DIR, item_id)
    if not run:
        raise RuntimeError(f"ไม่พบข้อมูลสินค้า {item_id}")

    base = Path(run["folder"])
    data = {
        "item_id": item_id,
        "name": run.get("name", ""),
        "highlights": run.get("highlights", []),
        "folder": run["folder"],
    }
    highlights = data["highlights"]
    images = [base / name for name in run.get("images", [])]
    images = [p for p in images if p.is_file()]
    if not highlights or not images:
        _clip_say(chat_id, "❌ ข้ามขั้นสตอรีบอร์ด — ยังไม่มีรูปหรือจุดเด่นครบ")
        raise RuntimeError("ไม่มีรูปหรือจุดเด่นครบ")

    # กติกาเพิ่มที่แนบไปกับคำขอสตอรีบอร์ด — ใส่ในช่องเดิมจุดเดิม (`extra_ask`)
    #   · ระบบเดาให้ : สินค้าปรับเปลี่ยนรูปทรงได้ → ให้ยึดรูปที่แนบไป
    #   · ผู้ใช้เลือก : แนวการวางกล้อง (ซูมดูดีเทล / เห็นสินค้าเต็มทุกฉาก)
    #
    # ที่ต้องให้เลือกเองเพราะ **GPT ตัวที่วาดสตอรีบอร์ดมีคำสั่งประจำตัวของมันเอง**
    # อยู่ฝั่ง OpenAI ซึ่งสั่งมุมกล้องแบบ Close Up / Slow Zoom มาเอง เราแก้ไม่ได้
    # ทำได้แค่ส่งข้อบังคับไปทับให้ชนะ (ไล่ตรวจ 26 ส.ค. 2026 แล้ว — คำสั่งฝั่งเรา
    # ไม่มีที่ไหนสั่งให้ซูมเลยสักจุด)
    rules = []
    # ห้ามของมีลิขสิทธิ์บนหน้าจอสินค้า — **แนบทุกครั้ง ไม่มีเงื่อนไข**
    # (คลิปทีวี 85 นิ้วโดนลบเพราะข้อนี้ 26 ส.ค. 2026 — ดู clip_rules.py)
    rules.append((clip_rules.NO_THIRD_PARTY_LABEL, clip_rules.NO_THIRD_PARTY_ASK))
    if transform_hint(highlights, data.get("name", "")):
        rules.append(("สินค้าปรับเปลี่ยนได้", TRANSFORM_STORYBOARD_ASK))
    frame_label, frame_ask = clip_rules.ask_of(run)
    if frame_ask:
        rules.append((frame_label, frame_ask))
    extra_ask = (NEWLINE + NEWLINE).join(text for _, text in rules)
    _clip_say(
        chat_id,
        f"🎬 ส่งรูป {len(images)} ใบเข้า GPT นักสร้างสตอรีบอร์ด… ใช้เวลาสักพัก"
        + (NEWLINE + "(กติกาที่แนบไปด้วย: "
           + " · ".join(tag for tag, _ in rules) + ")" if rules else ""),
    )
    if rules:
        # บอกให้ชัดว่าใบนี้ใช้กติกาไหน — กติกาที่มองไม่เห็นจะไล่ยากมากเวลา
        # สตอรีบอร์ดออกมาไม่เหมือนใบอื่นแล้วไม่รู้ว่าเพราะอะไร
        _clip_log("กติกาที่แนบไปกับคำขอสตอรีบอร์ด: "
                  + " · ".join(tag for tag, _ in rules))
    folder = base / "storyboard"
    try:
        with shared.browser_lock(label="ทำสตอรีบอร์ด"):
            result = chatgpt_driver.make_storyboard(
                open_browser, data.get("name", ""), highlights, images, folder,
                log=_clip_log, extra_ask=extra_ask,
                avoid_openers=_clip_recent_openers(data.get("item_id", "")),
            )
    except Exception as error:
        hint = ""
        if type(error).__name__ == "ChatGPTNeedsLogin":
            hint = (
                "\n\nยังไม่ได้ล็อกอิน ChatGPT — รันคำสั่งนี้ที่เครื่อง:\n"
                "<code>python flow_worker.py login-chatgpt</code>"
            )
        _clip_say(chat_id, f"❌ ทำสตอรีบอร์ดไม่สำเร็จ: "
                           f"{telegram_bot._escape(str(error)[:200])}{hint}")
        raise

    # เก็บก่อนส่ง — ส่ง Telegram ล้มได้ (เน็ตหลุด ไฟล์ใหญ่เกิน) แต่ของต้องอยู่ครบ
    _clip_keep(lambda: clip_store.save_storyboard(DATA_DIR, data, result), "สตอรีบอร์ด")
    _clip_log(
        f"ได้ภาพ {len(result.get('frames', []))} ใบ · "
        f"คำสั่ง {len(result.get('flow_prompts', []))} ชุด · "
        f"บทพูด {len(result.get('script', []))} ฉาก"
    )

    # ได้ของไม่ครบต้อง **บอกให้รู้ตัว** ไม่ใช่ส่งของที่ขาดไปเงียบๆ แล้วให้ไปเจอเอง
    # ตอนกดอนุมัติ — ผู้ใช้จะไม่รู้ว่าต้องสั่งแก้หรือรอ
    warnings = result.get("warnings") or []
    if warnings:
        lines = "\n".join(f"• {telegram_bot._escape(w[:180])}" for w in warnings)
        _clip_say(
            chat_id,
            "⚠️ <b>ทำได้ไม่ครบ แต่เก็บของที่ได้ไว้แล้ว</b>\n" + lines +
            "\n\nกด ✏️ สั่งแก้เพื่อขอส่วนที่ขาดใหม่ในแชทเดิมได้เลย",
        )

    run = clip_store.load_run(DATA_DIR, item_id)
    # ส่งสตอรีบอร์ดกับบทพูด **ติดกันในรอบเดียว** แต่ปุ่มแยกกันคนละชุด
    # ผู้ใช้จะได้เห็นภาพคู่กับคำพูดแล้วตัดสินทีเดียว ไม่ต้องกดผ่านทีละขั้น
    # ส่วนการอนุมัติยังแยกกันจริง — จะกดผ่านอันหนึ่งแล้วสั่งแก้อีกอันก็ได้
    clip_jobs.update(
        job["id"], stage=clip_queue.STAGE_STORYBOARD_REVIEW, sent_script=True,
    )
    fresh = clip_jobs.get(job["id"])
    _clip_send_storyboard(fresh, run)
    _clip_send_script(fresh, run)


def _clip_revise(job: dict) -> None:
    """สั่งแก้ตามที่ผู้ใช้พิมพ์มา แล้วส่งของใหม่กลับไปให้ตรวจอีกรอบ"""
    from flow_worker import open_browser

    edit = job.get("pending_edit") or {}
    target = edit.get("target") or "storyboard"
    instruction = edit.get("instruction") or ""
    chat_id = job["chat_id"]

    # สาย TikTok ไม่ได้คุยกับ GPT จึงไม่มีแชทให้กลับไปสั่งแก้ — ⛔ ยังไม่ได้ทำ
    # (ดู "ช่องที่เว้นไว้" ใน TIKTOK-REPOST.md) ห้ามปล่อยให้ตกไปเข้าเงื่อนไข
    # chat_url ว่างข้างล่าง เพราะอันนั้น raise แล้วงานจะกลายเป็น failed ทั้งงาน
    if _job_kind(job) == "tiktok":
        clip_jobs.update(
            job["id"], stage=clip_queue.STAGE_STORYBOARD_REVIEW,
            pending_edit=None, awaiting="",
        )
        _clip_say(
            chat_id,
            "⛔ สายคลิป TikTok ยังสั่งแก้ด้วยข้อความไม่ได้\n"
            "ตอนนี้กด ✅ อนุมัติ หรือ /cancel แล้วส่งลิงก์ใหม่ได้",
        )
        return

    run = clip_store.load_run(DATA_DIR, job.get("item_id", ""))
    chat_url = run.get("chat_url", "")
    if not chat_url:
        _clip_say(chat_id, "❌ ไม่มีลิงก์แชทเดิม สั่งแก้ต่อไม่ได้ — ส่งลิงก์สินค้าใหม่อีกครั้ง")
        raise RuntimeError("ไม่มี chat_url")

    _clip_say(chat_id, f"✏️ กำลังสั่งแก้{'สตอรีบอร์ด' if target == 'storyboard' else 'บทพูด'}…")
    folder = Path(run["folder"]) / "storyboard"
    with shared.browser_lock(label="สั่งแก้สตอรีบอร์ด/บทพูด"):
        result = chatgpt_driver.revise(
            open_browser, chat_url, instruction, target, folder, log=_clip_log,
        )

    # เขียนทับเฉพาะส่วนที่แก้ ไม่แตะของอีกฝั่ง — สั่งแก้บทพูดต้องไม่ทำสตอรีบอร์ดหาย
    patch = dict(run)
    if target == "storyboard":
        frames = result.get("frames") or []
        if frames:
            patch["frames"] = frames
        patch.update({
            "flow_prompts": run.get("flow_prompts", []),
            "flow_reply": run.get("gpt_flow_reply", ""),
            "reply": result.get("reply", ""),
            "script": run.get("script", []),
            "script_reply": run.get("gpt_script_reply", ""),
            "refused": bool(result.get("refused")),
            "refusal_text": result.get("refusal_text", ""),
            "chat_url": chat_url,
        })
    else:
        patch.update({
            "frames": [str(Path(run["folder"]) / n) for n in run.get("storyboard", [])],
            "flow_prompts": run.get("flow_prompts", []),
            "flow_reply": run.get("gpt_flow_reply", ""),
            "reply": run.get("gpt_storyboard_reply", ""),
            "script": result.get("script", []),
            "script_reply": result.get("reply", ""),
            "chat_url": chat_url,
        })
    _clip_keep(
        lambda: clip_store.save_storyboard(DATA_DIR, {"item_id": job["item_id"]}, patch),
        "ผลการแก้",
    )

    fresh = clip_store.load_run(DATA_DIR, job["item_id"])
    if target == "storyboard":
        clip_jobs.update(
            job["id"], stage=clip_queue.STAGE_STORYBOARD_REVIEW,
            pending_edit=None, storyboard_ok=False,
        )
        _clip_send_storyboard(clip_jobs.get(job["id"]), fresh)
    else:
        # กลับมาที่สถานะตรวจร่วมอันเดิม แล้วล้างเฉพาะ "ผ่าน" ของบทพูด
        # สตอรีบอร์ดที่อนุมัติไปแล้วต้องไม่ถูกล้างตาม ไม่งั้นต้องกดผ่านซ้ำทุกครั้ง
        clip_jobs.update(
            job["id"], stage=clip_queue.STAGE_STORYBOARD_REVIEW,
            pending_edit=None, script_ok=False,
        )
        _clip_send_script(clip_jobs.get(job["id"]), fresh)


def _clip_send_video(job: dict, run: dict) -> None:
    """ส่งคลิปที่เจนได้เข้าแชทให้ตรวจ พร้อมปุ่มอนุมัติ/เจนใหม่"""
    chat_id = job["chat_id"]
    token = load_clip_token() or ""
    folder = Path(run.get("folder") or clip_store.run_dir(DATA_DIR, job["item_id"]))
    videos = [folder / name for name in run.get("videos", [])]
    videos = [path for path in videos if path.is_file()]
    if not videos:
        _clip_say(chat_id, "⚠️ เจนคลิปแล้วแต่ไม่พบไฟล์",
                  _clip_buttons(job["id"], "video"))
        return
    # ตรวจ **ก่อน**ส่งการ์ด ผู้ใช้จะได้เห็นผลตรวจตอนตัดสินใจกดอนุมัติ ไม่ใช่หลังกดไปแล้ว
    run = _clip_ensure_check(run)
    entry = {"id": job["id"], "product": run.get("name", "")}
    buttons = _clip_buttons(job["id"], "video")
    for index, path in enumerate(videos, 1):
        try:
            # ปุ่มติดชิ้นสุดท้ายชิ้นเดียว ไม่งั้นมีปุ่มทุกชิ้นแล้วกดผิดชิ้นได้
            telegram_bot.send_video_approval(
                token, chat_id, entry, path,
                buttons if index == len(videos) else {"inline_keyboard": []},
            )
        except telegram_bot.TelegramError as error:
            _clip_log(f"ส่งคลิปไม่ได้: {error}")
    _clip_say(chat_id, _clip_check_text(run))


def _speech_retry(prompt: str, attempt: int, error) -> str:
    """ปรับจังหวะบทพูดก่อนลองใหม่ — ใช้เมื่อ Veo สร้างเสียงไทยไม่ผ่าน

    KVID เจอมาก่อนว่าเสียงไทยล้มเพราะประโยคยาวติดกันไม่มีจังหวะพัก retry ด้วยบท
    เดิมจึงได้ผลเดิม ต้องเปลี่ยนจังหวะคำก่อน
    """
    level = min(attempt, thai_speech.MAX_LEVEL)
    _clip_log(f"  ปรับจังหวะบทพูดเป็นระดับ {level} ก่อนลองใหม่")
    return thai_speech.speech_ready(prompt, level)


def _clip_policy_recover(
    job: dict, index: int, prompt: str, target: Path, driver, start_image,
    model: str, seconds, reason: str, label: str,
):
    """โดน Flow ปฏิเสธเพราะนโยบาย → ให้ Gemini แก้คำสั่ง+บทพูด แล้วเจนใหม่

    คืน `True` เมื่อได้คลิป · คืนข้อความบอกเหตุเมื่อยังไม่ได้

    **ส่งให้ Gemini ครบชุดตามที่ผู้ใช้กำหนด**: ภาพสตอรีบอร์ด + รูปสินค้า ·
    คำสั่งเดิม · บทพูดเดิม · ข้อความ error จริงจาก Flow · ชื่อโมเดลที่ใช้เจน
    ยิ่ง Gemini เห็นบริบทครบ ยิ่งแก้ตรงจุด ไม่ใช่เดาจากตัวหนังสืออย่างเดียว

    **ปลอดภัยเรื่องเงิน**: รอบที่โดนปฏิเสธ Google ไม่คิดเครดิต จึงวนแก้ได้
    ถึง `policy_fix.MAX_ROUNDS` รอบ เสียแค่เวลา
    """
    from flow_worker import load_gemini_api_key

    api_key = load_gemini_api_key()
    if not api_key:
        return "ไม่มีคีย์ Gemini — แก้คำสั่งอัตโนมัติไม่ได้"

    run = clip_store.load_run(DATA_DIR, job.get("item_id", "")) or {}
    folder = Path(run.get("folder") or clip_store.run_dir(DATA_DIR, job.get("item_id", "")))
    # รูปที่ส่งไปให้ดู — ภาพสตอรีบอร์ดก่อน (ตรงกับฉากที่สุด) แล้วตามด้วยรูปสินค้า
    images = [folder / name for name in (run.get("storyboard") or [])]
    images += [folder / name for name in (run.get("images") or [])]
    images = [p for p in images if p.is_file()]
    script = list(run.get("script") or [])

    current = prompt
    for round_no in range(1, policy_fix.MAX_ROUNDS + 1):
        _clip_log(f"{label}: โดนปฏิเสธ — ให้ Gemini แก้คำสั่ง (รอบ {round_no}/"
                  f"{policy_fix.MAX_ROUNDS})")
        try:
            fixed = policy_fix.rewrite(
                current, reason, api_key, script=script, images=images,
                model=model, log=_clip_log,
            )
        except policy_fix.PolicyFixError as error:
            _clip_log(f"{label}: Gemini แก้ไม่ผ่าน — {error}")
            return f"Gemini แก้คำสั่งไม่ผ่าน ({error})"

        current = fixed["prompt"]
        if fixed.get("script"):
            script = fixed["script"]
        # เก็บของที่แก้แล้วทันที — ถ้าเจนล้มทีหลังยังได้คำสั่งที่ผ่านนโยบายไว้ใช้ต่อ
        _clip_keep(
            lambda p=current, s=script, i=index: clip_store.save_fixed_prompt(
                DATA_DIR, job["item_id"], i, p, s
            ),
            "คำสั่งที่ Gemini แก้แล้ว",
        )
        try:
            driver.new_project()
            driver.generate(
                thai_speech.speech_ready(current, 1), "video", target,
                start_image=start_image, on_retry=_speech_retry,
                seconds=seconds, video_model=model,
            )
            return True
        except flow_driver.PolicyBlocked as error:
            reason = str(error)          # เหตุผลใหม่ ส่งกลับให้ Gemini รอบถัดไป
            continue
        except flow_driver.FlowError as error:
            return f"เจนใหม่แล้วล้มด้วยเหตุอื่น ({str(error)[:70]})"
    return f"ลองแก้ครบ {policy_fix.MAX_ROUNDS} รอบแล้วยังไม่ผ่าน"


def _rescue_pending_video(driver, folder: Path) -> Path | None:
    """ตามเก็บคลิปที่ Flow ยังเรนเดอร์ค้างอยู่ ก่อนจะปิดเบราว์เซอร์

    ใช้ตอนรอบเจนจบแบบไม่ได้ไฟล์ — ถ้าไทล์ยังปั่นอยู่แปลว่าเครดิตถูกใช้ไปแล้ว
    ปิดหน้าต่างทิ้งตอนนี้คือจ่ายเงินแล้วไม่ได้ของ

    รอไม่เกิน 5 นาที และคืน None เงียบๆ ถ้าไม่มีอะไรค้างจริง
    """
    snap = driver.snapshot()
    if not (snap.get("active") or snap.get("pct") is not None):
        return None
    _clip_log("ยังมีไทล์เรนเดอร์ค้างอยู่ — รอเก็บก่อนปิดเบราว์เซอร์")
    before = set(snap.get("videoUrls") or [])
    url = driver.wait_result("video", before, 300, 10)
    target = folder / "clip.mp4"
    driver.download(url, target)
    return target


# ส่งประโยคเปิดของคลิปก่อนหน้าไปกี่ประโยค — มากไปคำสั่งยาวจน GPT สนใจข้ออื่นน้อยลง
RECENT_OPENERS = 8


def _clip_recent_openers(skip_item: str = "") -> list[str]:
    """ประโยคเปิดของคลิปที่ทำไปแล้ว — ส่งไปบอก GPT ว่าห้ามเขียนซ้ำแนวนี้

    **ทำไมต้องมี** วัดจริง 23 ส.ค. 2026: บทพูด 27 ชิ้นในคลัง 22 ชิ้นขึ้นต้นด้วย
    คำว่า "แก" (81%) และสินค้าตระกูลเดียวกันบทพูดซ้ำกัน 34–52% เพราะสเปกเหมือนกัน
    จุดเด่นจึงถูกคัดมาชุดเดียวกัน แล้ว GPT ก็เขียนตามสูตรประจำของมัน
    คนดูเลื่อนเจอคลิปเราติดกันสามคลิปแล้วรู้สึกว่าเป็นอันเดิม = เลื่อนผ่าน

    **เอาของใหม่สุดก่อน** เพราะคลิปที่คนจะเห็นติดกันคือคลิปที่โพสต์ไล่ๆ กัน
    """
    openers: list[str] = []
    runs = clip_store.list_runs(DATA_DIR)
    for run in runs:
        if str(run.get("item_id") or "") == str(skip_item):
            continue
        script = run.get("script") or []
        if script and str(script[0]).strip():
            openers.append(str(script[0]).strip())
        if len(openers) >= RECENT_OPENERS:
            break
    return openers


def _clip_make_hashtags(item_id: str) -> dict:
    """สร้างแฮชแท็ก 5 ตัวของสินค้าชิ้นนี้แล้วเก็บลง run.json

    สูตรตามที่ผู้ใช้สั่ง: ยี่ห้อ · ชนิดสินค้า · จุดเด่น 3 ตัว (ตัวละ 2-5 พยางค์)
    ตัวแยกส่วนประกอบอยู่ใน hashtag.py — ไม่มีคีย์ Gemini ก็ยังทำงานได้ด้วยกฎ
    """
    from flow_worker import load_gemini_api_key

    run = clip_store.load_run(DATA_DIR, item_id)
    if not run:
        raise RuntimeError(f"ไม่พบงาน {item_id}")
    plan = hashtag.plan_for_run(run, load_gemini_api_key(), log=_clip_log)
    saved = clip_store.save_hashtags(DATA_DIR, item_id, plan)
    tags = saved.get("hashtags") or []
    _clip_log(
        f"แฮชแท็ก {len(tags)}/{hashtag.TAG_COUNT} ตัว: "
        + " ".join(f"#{tag}" for tag in tags)
    )
    return saved


# ============================================ ตรวจคลิปที่ได้มา (ผู้ใช้สั่ง 22 ส.ค. 2026)
#
# ตรวจ **สองข้อ** ตามที่ผู้ใช้กำหนด: คลิปเป็น 1080p ไหม · มีเสียงพูดไหม
# แล้วแนบผลไปกับคลิปทุกครั้งที่ส่งเข้าแชท (ทั้งการ์ดขออนุมัติ และ /clips /clipsfb)
#
# **ตรวจตอนเจนเสร็จ เก็บผลไว้ ไม่ตรวจสดตอนเปิดดู** — ชั้นที่ฟังเสียงต้องยิงไปหา
# Gemini ทุกครั้ง ถ้าตรวจสดทุกครั้งที่กด /clips คนเปิดดูงานเดิมสิบรอบก็ยิงสิบครั้ง
# แล้วโดนตัดโควตา (วัดจริง 22 ส.ค.: ยิงรวด 15 ครั้งใน 27 วิ โดน 429 ตั้งแต่ครั้งที่ 4)


def _clip_video_paths(run: dict) -> list:
    """คลิปของงานนี้ที่มีไฟล์อยู่จริง"""
    folder = Path(run.get("folder") or "")
    return [folder / name for name in (run.get("videos") or [])
            if (folder / name).is_file()]


def _clip_check_stale(run: dict) -> bool:
    """ผลตรวจที่เก็บไว้ยังใช้กับไฟล์ตอนนี้ได้ไหม

    ผลผูกกับ **ไฟล์** ไม่ใช่กับงาน — โหลดคลิปใหม่ทับ (เช่นอัปจาก 720p เป็น 1080p)
    แล้วยังโชว์ผลเก่าว่า "720p" คือโกหกผู้ใช้ เทียบขนาดไฟล์จึงจับได้ทันที
    """
    old = run.get("video_check") or {}
    if not old:
        return True
    paths = _clip_video_paths(run)
    if not paths:
        return True
    now_mb = round(paths[0].stat().st_size / 1048576, 1)
    return abs(float(old.get("size_mb") or 0) - now_mb) > 0.05


def _clip_check_videos(item_id: str, force: bool = False) -> dict:
    """ตรวจคลิปของงานนี้แล้วเก็บผล — คืน dict ผลตรวจ (ของไฟล์แรก)

    มีผลเก่าที่ยังตรงกับไฟล์อยู่ก็ใช้ของเก่า ไม่ยิง Gemini ซ้ำ เว้นแต่สั่ง force
    """
    from flow_worker import load_gemini_api_key

    run = clip_store.load_run(DATA_DIR, item_id)
    if not run:
        raise RuntimeError(f"ไม่พบงาน {item_id}")
    paths = _clip_video_paths(run)
    if not paths:
        raise RuntimeError("งานนี้ยังไม่มีไฟล์คลิป")
    if not force and not _clip_check_stale(run):
        return run.get("video_check") or {}

    result = clip_check.check(
        paths[0], load_gemini_api_key(), run.get("script"), log=_clip_log,
    )
    # ---- คำอ้างที่ไม่มีในหน้าสินค้า (ผู้ใช้สั่ง 26 ส.ค. 2026) ----------------
    #
    # **ไม่ต้องยิง AI เลย** เป็นการเทียบข้อความกับข้อความล้วน จึงไม่กินโควตา
    # ไม่มีทางล้มเพราะ 503 และให้คำตอบเดิมทุกครั้ง — ต่างจากด่านอื่นในไฟล์นี้
    #
    # เจอจริงตอนไล่ตรวจ 27 ใบ: คลิป TCL Monitor 27 นิ้ว พูดว่า "DC Dimming"
    # ซึ่งสินค้าไม่มีฟีเจอร์นี้ (หน้าสินค้ามีแต่ "Precise Dimming Zones")
    # เข้าข่ายอ้างสรรพคุณเกินจริง = 3 คะแนน หนักกว่าละเมิดลิขสิทธิ์ 3 เท่า
    try:
        claims = clip_claims.check(run, clip_store.target_dir(DATA_DIR, item_id))
    except Exception as error:                               # noqa: BLE001
        # ด่านเสริมล้มห้ามลากผลตรวจหลักตายตาม แต่ต้องไม่เงียบด้วย
        _clip_log(f"ตรวจคำอ้างของ {item_id} ไม่สำเร็จ: {error}")
        claims = []
    result["claims"] = claims
    if claims:
        spots = ", ".join(f"ฉาก {c['scene']} “{c['value']}”" for c in claims[:3])
        result.setdefault("problems", []).append(
            f"⚠️ พูดถึงของที่ไม่มีในหน้าสินค้า ({spots}) — เข้าข่ายอ้างเกินจริง")
        _clip_log(f"คำอ้างที่ไม่มีในหน้าสินค้าของ {item_id}: {spots}")
    clip_store.save_video_check(DATA_DIR, item_id, result)
    # แยกสามทางในบันทึก ไม่ใช่สองทาง — "ตรวจไม่ได้" ต้องไม่ถูกเขียนว่า "ไม่มีเสียงพูด"
    # ไม่งั้นวันหลังย้อนอ่าน log จะเข้าใจผิดว่าคลิปเสีย ทั้งที่แค่ยังไม่ได้ฟัง
    said = {True: "มีเสียงพูด", False: "ไม่มีเสียงพูด"}.get(
        result.get("has_speech"), "ยังตรวจเสียงไม่ได้")
    _clip_log(
        f"ตรวจคลิป {item_id}: {result.get('resolution')} · {said}"
        + (" · ผ่าน" if result.get("ok") else " · " + " / ".join(result.get("problems") or []))
    )
    return result


def _clip_ensure_check(run: dict) -> dict:
    """มีผลตรวจแล้วคืนของเดิม ยังไม่มี/ล้าสมัยก็ตรวจให้ก่อน แล้วคืน run ที่อัปเดตแล้ว

    ครอบด้วย _clip_keep เพราะผลตรวจเป็น **ของแถมข้างคลิป** ตรวจไม่ได้ก็ต้องยังส่ง
    คลิปให้ผู้ใช้ดูได้ตามปกติ ไม่ใช่ทำให้ทั้งการ์ดหายไป
    """
    if not (run.get("videos") and _clip_check_stale(run)):
        return run
    item_id = str(run.get("item_id") or "")
    if not item_id:
        return run

    # **สมุดบันทึกบอกว่ามีคลิป แต่ไฟล์หายไป** = สถานะไม่ตรงกัน ซ่อมตรงนี้เลย
    #
    # เกิดได้เมื่อไฟล์ถูกลบนอกเส้นทางปกติ (ลบด้วยมือ · ดิสก์เต็ม · ปุ่มเจนใหม่รุ่นเก่า
    # ที่ลบไฟล์แต่ไม่ลบรายการ) ปล่อยไว้จะขึ้น error "งานนี้ยังไม่มีไฟล์คลิป" ทุกครั้ง
    # ที่เปิดดู ซึ่งชี้สาเหตุผิดทาง — ฟังดูเหมือนยังไม่เคยเจน ทั้งที่เจนแล้วไฟล์หาย
    if not _clip_video_paths(run):
        _clip_log(f"งาน {item_id}: สมุดบันทึกบอกว่ามีคลิปแต่ไฟล์หาย — ล้างรายการให้ตรงกับของจริง")
        _clip_keep(lambda: clip_store.clear_videos(DATA_DIR, item_id), "ล้างรายการคลิปที่ไฟล์หาย")
        return clip_store.load_run(DATA_DIR, item_id) or run

    done = []
    _clip_keep(lambda: done.append(_clip_check_videos(item_id)), "ผลตรวจคลิป")
    return clip_store.load_run(DATA_DIR, item_id) if done else run


def _clip_check_text(run: dict) -> str:
    """ข้อความยืนยันผลตรวจที่แนบไปกับคลิปในแชท

    เขียนเป็นข้อความสั้นที่อ่านแล้วรู้ผลทันที ไม่ต้องตีความตัวเลขเอง — และถ้ายัง
    ไม่เคยตรวจต้องบอกตรงๆ ว่ายังไม่ได้ตรวจ ไม่ใช่เงียบจนดูเหมือนผ่าน
    """
    escape = telegram_bot._escape
    result = run.get("video_check") or {}
    item = escape(str(run.get("item_id") or ""))
    if not result:
        return ("🔍 <b>ผลตรวจคลิป</b>\n"
                f"⚠️ ยังไม่ได้ตรวจ — สั่ง <code>/recheck {item}</code> ให้ตรวจได้")
    if _clip_check_stale(run):
        return ("🔍 <b>ผลตรวจคลิป</b>\n"
                f"⚠️ ไฟล์เปลี่ยนไปหลังตรวจ — สั่ง <code>/recheck {item}</code> ให้ตรวจใหม่")

    lines = ["🔍 <b>ผลตรวจคลิป</b>", escape(clip_check.badge(result))]
    said = (result.get("transcript") or "").strip()
    if said:
        # สิ่งที่ได้ยินยาวได้หลายบรรทัด — พับไว้ ให้ผลผ่าน/ไม่ผ่านเด่นกว่า
        lines.append(fold("🗣 <i>ได้ยินว่าอะไรบ้าง (แตะเพื่อกาง)</i>",
                          escape(said[:600]), always=True))
    left = [p for p in (result.get("problems") or []) if p]
    if left:
        lines.append("⚠️ " + escape(" · ".join(left))[:300])
    return "\n".join(lines)


def _clip_generate(job: dict) -> None:
    """เอาคำสั่งที่อนุมัติแล้วไปเจนคลิปใน Google Flow

    ต้องอนุมัติทั้งสตอรีบอร์ดและบทพูดก่อนถึงจะมาถึงตรงนี้ — ตัวรันจะไม่หยิบงาน
    ที่ยังไม่ผ่านมาทำ เพราะสถานะยังไม่ใช่ ready_flow
    """
    import flow_driver
    from flow_worker import FLOW_URL, open_browser, _app_page, _enter_app
    from playwright.sync_api import sync_playwright

    chat_id = job["chat_id"]
    run = clip_store.load_run(DATA_DIR, job.get("item_id", ""))
    prompts = run.get("flow_prompts") or []
    if not prompts:
        _clip_say(chat_id, "❌ ไม่มีคำสั่งสำหรับ Google Flow เจนต่อไม่ได้")
        raise RuntimeError("ไม่มี flow_prompts")

    folder = Path(run["folder"]) / clip_store.VIDEO_DIR
    folder.mkdir(parents=True, exist_ok=True)
    # เฟรมตั้งต้น: ใช้ **ภาพสตอรีบอร์ด** ก่อน (ผู้ใช้สั่งเปลี่ยน 11 ส.ค.)
    #
    # เดิมใช้รูปสินค้าจริงเพราะกลัวได้ "แผ่นสตอรีบอร์ดขยับ" — ภาพสตอรีบอร์ดเป็น
    # แผ่นรวมหลายช่องพร้อมตัวหนังสือกำกับ ข้อกังวลนั้นยังจริงอยู่ ถ้าคลิปที่ได้
    # ออกมาเป็นภาพแผ่นให้ย้อนกลับมาใช้รูปสินค้า (สลับลำดับสองบรรทัดล่าง)
    #
    # ไม่มีภาพสตอรีบอร์ด → ถอยไปใช้รูปสินค้า ไม่ปล่อยให้ไม่มีเฟรมตั้งต้นเลย
    # เพราะบัญชีนี้ Flow ปฏิเสธงานที่ไม่แนบรูปอ้างอิง
    storyboard_dir = Path(run["folder"]) / clip_store.STORYBOARD_DIR
    frames = sorted(storyboard_dir.glob("*.png")) + sorted(storyboard_dir.glob("*.jpg"))
    product_images = [Path(run["folder"]) / name for name in run.get("images", [])]
    start_image = next(
        (p for p in [*frames, *product_images] if p.is_file()), None
    )
    if start_image is not None:
        kind = "ภาพสตอรีบอร์ด" if start_image.parent.name == clip_store.STORYBOARD_DIR else "รูปสินค้า"
        _clip_log(f"เฟรมตั้งต้น: {kind} — {start_image.name}")

    one_clip = one_clip_mode()
    seconds = flow_seconds()
    model = flow_model()
    _clip_say(
        chat_id,
        f"🎥 เริ่มเจนใน Google Flow — {len(prompts)} ฉาก · ยาว {seconds} วินาที · {model}"
        + ("\nรวมเป็น <b>คลิปเดียว</b> เจนครั้งเดียว (เปลี่ยนด้วย /mode แยก)"
           if one_clip else
           "\nแยก <b>ฉากละคลิป</b> (เปลี่ยนด้วย /mode รวม)")
        + "\nหน้าต่าง Flow เปิดให้ดูบนจอแล้ว",
    )
    made: list[Path] = []
    failed: list[str] = []

    def attempt() -> bool:
        """เจนทุกฉากหนึ่งรอบ — คืน True ถ้าติดที่ยังไม่ได้ล็อกอิน

        ไม่เขียนตัวเช็คล็อกอินเอง: `new_project()` เปิดหน้า Flow แล้วเช็ค signedOut
        ให้อยู่แล้วและโยน NeedsLogin ออกมา ตัวเช็คที่ผมเขียนเองเคยตัดสินผิดมาแล้ว
        (บอกว่ายังไม่ล็อกอินทั้งที่คุกกี้อยู่ครบ) — ใช้ของที่พิสูจน์แล้วดีกว่า

        เปิดหน้าต่างให้เห็น (hidden=False) ตามที่ผู้ใช้ขอ จะได้ดูว่ากำลังทำอะไรอยู่
        """
        with sync_playwright() as playwright:
            browser = open_browser(playwright, hidden=False)
            page = browser.pages[0] if browser.pages else browser.new_page()
            driver = None                 # อาจล้มก่อนสร้าง — finally ต้องเช็คได้
            credits_before = None
            try:
                page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=90_000)
                # หน้า landing ต้องกดเข้าแอปก่อน และปุ่มนั้น **เปิดแท็บใหม่**
                # ถ้ายึดแท็บแรกไว้จะไปขับหน้าที่ไม่มีอะไรเกิดขึ้น
                # (พลาดมาแล้ว: สร้างตัวขับบนหน้าเปล่า แล้วล้มทุกฉากใน 3 วินาที)
                _enter_app(page)
                page = _app_page(browser, page)
                # ดึงแท็บขึ้นหน้าให้ผู้ใช้เห็นตอนทำงาน (ผู้ใช้ขอไว้)
                try:
                    page.bring_to_front()
                except Exception:
                    pass
                # จดว่าลงเอยที่หน้าไหน — ตอนล้มจะได้รู้ว่าอยู่หน้าถูกหรือเปล่า
                _clip_log(f"เปิดหน้า Flow แล้ว: {page.url[:80]}")
                driver = flow_driver.FlowDriver(page, log=_clip_log)

                # อ่านเครดิตก่อนเริ่ม เพื่อบอกได้ว่ารอบนี้ใช้ไปเท่าไรและเหลือเท่าไร
                # ต้องรู้ตัวเลขจริง ไม่งั้นเจนซ้ำโดยไม่รู้ว่ากำลังเผาเครดิตอยู่
                credits_before = driver.read_credits()
                _remember_credits(credits_before)
                if credits_before is not None:
                    _clip_log(f"เครดิตก่อนเริ่ม: {credits_before:,}")
                else:
                    _clip_log("อ่านเครดิตก่อนเริ่มไม่ได้ — รอบนี้จะบอกยอดใช้ไม่ได้")

                # หนึ่งคลิปจบทุกฉาก = เจนครั้งเดียว เสียเครดิตครั้งเดียว
                jobs = (
                    [(0, build_one_clip_prompt(prompts, seconds), folder / "clip.mp4")]
                    if one_clip
                    else [
                        (i, p, folder / f"scene-{i:02d}.mp4")
                        for i, p in enumerate(prompts, 1)
                    ]
                )

                for index, prompt, target in jobs:
                    label = "คลิปรวม" if one_clip else f"ฉาก {index}/{len(prompts)}"
                    if target.is_file():
                        made.append(target)
                        _clip_log(f"{label}: มีคลิปอยู่แล้ว ข้าม")
                        continue
                    _clip_log(f"{label}: เจนคลิป ({len(prompt)} ตัวอักษร)")
                    try:
                        # เก็บลิงก์โปรเจกต์ไว้เสมอ (ผู้ใช้สั่ง 22 ส.ค. 2026)
                        #
                        # ก่อนหน้านี้ทิ้งค่าที่ new_project() คืนมา ทำให้ไม่มีใครรู้ว่า
                        # คลิปไหนอยู่โปรเจกต์ไหนใน Flow — พอจะกลับไปโหลดไฟล์
                        # ความละเอียดสูงกว่าเดิมจึงทำไม่ได้ ต้องเปิดไล่หาเอง
                        # (ตรวจ 22 ส.ค.: run.json 26 ไฟล์ ไม่มีลิงก์โปรเจกต์เลยสักไฟล์)
                        project_url = driver.new_project()
                        if project_url:
                            _clip_keep(
                                lambda url=project_url, i=index: clip_store.save_project_url(
                                    DATA_DIR, job["item_id"], url, i
                                ),
                                "ลิงก์โปรเจกต์ Flow",
                            )
                        driver.generate(
                            # เตรียมบทให้ Veo อ่านออกตั้งแต่รอบแรก ไม่รอให้ล้มก่อน
                            thai_speech.speech_ready(prompt, 1),
                            "video", target, start_image=start_image,
                            on_retry=_speech_retry, seconds=seconds,
                            video_model=model,
                        )
                        made.append(target)
                        _clip_log(f"{label}: ได้คลิปแล้ว")
                    except flow_driver.NeedsLogin:
                        return True
                    except flow_driver.PolicyBlocked as error:
                        # ห้ามลองซ้ำด้วย prompt **เดิม** — แต่ให้ Gemini แก้ก่อนแล้ว
                        # ลองใหม่ได้ (ผู้ใช้สั่ง 22 ส.ค. 2026) เพราะรอบที่โดนปฏิเสธ
                        # Google ไม่คิดเครดิต (log 18:46:47 "รอบนี้ใช้ไป 0")
                        # การวนแก้จึงเสียแค่เวลา ไม่เสียเงิน
                        note = _clip_policy_recover(
                            job, index, prompt, target, driver, start_image,
                            model, seconds, str(error), label,
                        )
                        if note is True:
                            made.append(target)
                            _clip_log(f"{label}: ได้คลิปแล้ว (หลังให้ Gemini แก้คำสั่ง)")
                        else:
                            failed.append(f"{label}: ขัดนโยบาย ({str(note)[:80]})")
                            _clip_log(f"{label}: ขัดนโยบาย — {str(error)[:250]}")
                    except flow_driver.FlowError as error:
                        failed.append(f"{label}: {str(error)[:80]}")
                        # ต้องลง log ด้วย ไม่ใช่ส่งเข้าแชทอย่างเดียว — เวลาไล่สาเหตุ
                        # ทีหลังจะได้เห็นว่าล้มตรงไหน (พลาดมาแล้ว: log เงียบ 50 วินาที
                        # แล้วขึ้นแค่ "เจนคลิปไม่สำเร็จสักฉาก" ซึ่งบอกอะไรไม่ได้เลย)
                        _clip_log(f"{label}: ล้มเหลว — {str(error)[:250]}")
                    except Exception as error:
                        failed.append(f"{label}: {type(error).__name__}")
                        _clip_log(
                            f"{label}: ล้มด้วย {type(error).__name__} — {str(error)[:250]}"
                        )
            finally:
                # **ห้ามปิด Chrome ทิ้งขณะที่ Flow ยังเรนเดอร์อยู่**
                #
                # เจอจริง 11 ส.ค.: ตัวจับ Failed ยิงลวง งานเลยจบรอบแล้วปิดเบราว์เซอร์
                # ทั้งที่ไทล์ยังปั่นอยู่ — เครดิตจ่ายไปแล้วแต่ไม่ได้ไฟล์ เสียเปล่า
                #
                # ตรงนี้จึงรอให้ไทล์ที่ค้างอยู่เรนเดอร์จบก่อน แล้วเก็บไฟล์ให้ครบ
                try:
                    if driver is not None and not made:
                        rescued = _rescue_pending_video(driver, folder)
                        if rescued:
                            made.append(rescued)
                            failed.clear()
                            _clip_log(f"เก็บคลิปที่ยังเจนค้างอยู่ได้: {rescued.name}")
                except Exception as error:                       # noqa: BLE001
                    _clip_log(f"ตามเก็บคลิปที่ค้างไม่สำเร็จ: {type(error).__name__}: {error}")

                # อ่านเครดิตหลังจบรอบ แล้วรายงานส่วนต่าง — ทำใน finally เพื่อให้
                # รู้ยอดแม้รอบนั้นล้ม (รอบที่ล้มก็เผาเครดิตได้ถ้ากด Create ไปแล้ว)
                try:
                    after = driver.read_credits() if driver is not None else None
                except Exception:                                # noqa: BLE001
                    after = None
                _remember_credits(after)
                if after is not None:
                    if credits_before is not None:
                        used = credits_before - after
                        _clip_log(
                            f"เครดิตหลังจบรอบ: {after:,} · รอบนี้ใช้ไป {used:,}"
                        )
                    else:
                        _clip_log(f"เครดิตหลังจบรอบ: {after:,}")
                browser.close()
        return False

    with shared.browser_lock(label="เจนคลิปใน Google Flow"):
        if attempt():
            # ผู้ใช้สั่งไว้: ถ้าต้องล็อกอิน ให้เด้งหน้าต่างขึ้นมาให้ล็อกอินเอง
            # ต้องเรียก **นอกบล็อก Playwright** — เปิดซ้อนกันไม่ได้
            # (เจอจริง: "Sync API inside the asyncio loop" ล้มทั้ง 3 งานรวด)
            _clip_say(
                chat_id,
                "🔐 <b>Google Flow ยังไม่ได้ล็อกอิน</b>\n"
                "เปิดหน้าต่างขึ้นมาบนเครื่องแล้ว — ล็อกอินในหน้าต่างนั้นได้เลย\n"
                "ล็อกอินเสร็จระบบจะเจนต่อให้เอง (รอสูงสุด 15 นาที)",
            )
            _clip_log("Google Flow ยังไม่ล็อกอิน — เปิดหน้าต่างให้ผู้ใช้")
            from flow_worker import login_flow
            if login_flow(15) != 0:
                _clip_say(chat_id, "❌ ยังไม่ได้ล็อกอิน Google Flow — สั่งเจนใหม่ได้ทีหลัง")
                raise RuntimeError("ยังไม่ได้ล็อกอิน Google Flow")
            if attempt():
                raise RuntimeError("ล็อกอินแล้วแต่ Flow ยังบอกว่ายังไม่ได้ล็อกอิน")

    _clip_keep(
        lambda: clip_store.save_video(
            DATA_DIR, job["item_id"], made, "; ".join(failed)
        ),
        "คลิปที่เจนได้",
    )
    if failed:
        _clip_say(chat_id, "⚠️ บางฉากเจนไม่ผ่าน\n" +
                  telegram_bot._escape("\n".join(failed))[:800])
    if not made:
        _clip_say(chat_id, "❌ ไม่ได้คลิปสักฉาก")
        raise RuntimeError("เจนคลิปไม่สำเร็จสักฉาก")

    # ผู้ใช้สั่ง 22 ส.ค. 2026: เจนคลิปเสร็จให้ทำแฮชแท็ก 5 ตัวเก็บไว้เลย
    # (ยี่ห้อ · ชนิดสินค้า · จุดเด่น 3 ตัว ตัวละ 2-5 พยางค์)
    #
    # ทำ**หลัง**คลิปเสร็จ ไม่ใช่ตอนดึงสินค้า เพราะจะได้ไม่เสียโควตา Gemini กับ
    # งานที่สุดท้ายเจนคลิปไม่ผ่าน · และครอบด้วย _clip_keep เพราะแท็กเป็นของรอง
    # ทำไม่ได้ก็ไม่ควรทำให้คลิปที่จ่ายเครดิตไปแล้วถูกรายงานว่าล้มเหลว
    _clip_keep(lambda: _clip_make_hashtags(job["item_id"]), "แฮชแท็ก")

    # ผู้ใช้สั่ง 22 ส.ค. 2026: ได้คลิปมาแล้วให้ตรวจซ้ำว่า **1080p จริง** และ
    # **มีเสียงพูดจริง** แล้วแนบผลไปกับคลิปตอนส่งเข้าแชท
    #
    # ตรวจตรงนี้ (ไม่ใช่ตอนเปิดดู) เพราะเป็นจุดเดียวที่รู้แน่ว่าไฟล์เพิ่งเปลี่ยน
    # และเป็นจุดที่ผู้ใช้กำลังจะเห็นคลิปครั้งแรก — ตรวจไม่ได้ก็ไม่ทำให้คลิปที่จ่าย
    # เครดิตไปแล้วถูกรายงานว่าล้มเหลว จึงครอบด้วย _clip_keep เหมือนแฮชแท็ก
    _clip_keep(lambda: _clip_check_videos(job["item_id"]), "ผลตรวจคลิป")

    fresh = clip_store.load_run(DATA_DIR, job["item_id"])
    # งานที่สั่งเจนตรง (ไม่ผ่านคิว) ไม่มีรายการในคิวให้อัปเดต — ปล่อยให้พังตรงนี้
    # จะทำให้งานที่ **เจนคลิปสำเร็จแล้ว** ถูกรายงานว่าล้มเหลว (เจอจริง 11 ส.ค.)
    if clip_jobs.get(job["id"]):
        clip_jobs.update(job["id"], stage=clip_queue.STAGE_VIDEO_REVIEW)
        _clip_send_video(clip_jobs.get(job["id"]), fresh)
    else:
        _clip_send_video(job, fresh)


# ======================================================= สาย TikTok repost
#
# ต่างจากสาย Shopee แค่ **สองขั้นแรก** เท่านั้น:
#     ขั้นดึงของ    Shopee: เปิดหน้าสินค้า     TikTok: โหลดคลิป + แคปชัน + แท็ก
#     ขั้นคิดงาน    Shopee: GPT ทำสตอรีบอร์ด  TikTok: Gemini ดูคลิปแล้วเขียน prompt
# ตั้งแต่ขั้นอนุมัติเป็นต้นไปใช้ของเดิมทั้งหมด เพราะทุกขั้นอ่านของจาก run.json
# ไม่ได้แตะลิงก์ต้นทางเลย


def _job_kind(job: dict) -> str:
    """สายงานของงานนี้ — งานเก่าในไฟล์คิวไม่มีฟิลด์นี้ ให้ถือว่าเป็น Shopee"""
    return job.get("kind") or "shopee"


def _tiktok_collect(job: dict) -> None:
    """ขั้นแรกของสาย TikTok: โหลดคลิป + แคปชัน + แฮชแท็ก แล้วส่งให้ตรวจ

    ยังไม่ได้ Product ID กับรูปสินค้าจริง (ดู tiktok_source.fetch_product) —
    บอกผู้ใช้ตรงๆ ว่ายังขาด ไม่เงียบแล้วปล่อยให้ไปเจอตอนโพสต์
    """
    chat_id = job["chat_id"]
    link = job["link"]
    _clip_say(chat_id, "🎬 กำลังโหลดคลิปจาก TikTok… รอสักครู่")

    # ยังไม่รู้รหัสคลิปจนกว่าจะอ่าน metadata (ลิงก์ย่อไม่มีรหัสอยู่ในตัว)
    # จึงโหลดลงโฟลเดอร์ชั่วคราวก่อน แล้วค่อยเปลี่ยนชื่อเป็นรหัสจริง
    staging = clip_store.run_dir(DATA_DIR, f"tt_tmp_{job['id']}")
    source = tiktok_source.collect(link, staging, want_product=True, log=_clip_log)

    video_id = source.get("video_id") or job["id"]
    item_id = tiktok_repost.item_id_for(video_id)
    final = clip_store.run_dir(DATA_DIR, item_id)
    if final.resolve() != staging.resolve():
        if final.exists():
            shutil.rmtree(final, ignore_errors=True)   # ทับของเก่าตามกติกาเดิม
        staging.rename(final)
    video = final / Path(source["video"]).name
    cover = final / Path(source["cover"]).name if source.get("cover") else None

    caption = source.get("caption") or ""
    name = (caption.splitlines()[0] if caption else "") or f"คลิป TikTok {video_id}"

    # แฮชแท็กทำหน้าที่เดียวกับ "จุดเด่น" ของสาย Shopee — เป็นของที่ต้องให้ผู้ใช้
    # ตรวจ/แก้ก่อนใช้ และเป็นข้อ ③ ของการยืนยันก่อนโพสต์ด้วย จึงใช้ช่องเดียวกัน
    tags = source.get("hashtags") or ["#รีวิวสินค้า"]

    images = [cover] if cover and cover.is_file() else []
    if not images:
        _clip_say(
            chat_id,
            "❌ ไม่ได้รูปปกคลิปมาเลย — ยังไม่มีรูปให้ใช้เป็นเฟรมตั้งต้น ทำต่อไม่ได้",
        )
        raise RuntimeError("ไม่มีรูปจากคลิป TikTok")

    data = {
        "item_id": item_id,
        "shop_id": "",
        "name": name[:120],
        "highlights": tags,
        "saved_images": images,
        "candidates": [],
        "affiliate_url": link,       # ลิงก์ที่ผู้ใช้ส่งมา ไม่ใช่ที่ระบบแปลงเอง
        "url": source.get("webpage_url", link),
        "detail": caption,
    }
    clip_jobs.update(
        job["id"], item_id=item_id, name=name[:80],
        source_video=str(video), tiktok_caption=caption,
    )
    _clip_keep(lambda: clip_store.save_product(DATA_DIR, data), "ข้อมูลคลิป TikTok")

    _clip_say(chat_id, telegram_bot._escape(tiktok_repost.summarize_source(source)))
    product = source.get("product") or {}
    if not product.get("ready"):
        _clip_say(
            chat_id,
            "⚠️ <b>ยังดึง Product ID กับรูปสินค้าจริงไม่ได้</b>\n"
            "ตอนนี้ใช้รูปปกคลิปแทนไปก่อน และตอนโพสต์จะยังไม่ผูกสินค้าให้\n"
            "ต้องเติม selector ของการ์ดสินค้าก่อน (ดู TIKTOK-REPOST.md)",
        )

    clip_jobs.update(
        job["id"], stage=clip_queue.STAGE_IMAGE_REVIEW,
        images_ok=False, highlights_ok=False,
    )
    _clip_send_worksheet(clip_jobs.get(job["id"]))


def _tiktok_analyze(job: dict) -> None:
    """ขั้นสองของสาย TikTok: ให้ Gemini ดูคลิปแล้วเขียน prompt + ถอดบทพูด

    แทนที่ `_clip_make` (ที่คุย GPT ทำสตอรีบอร์ด) — สายนี้มีคลิปต้นฉบับเป็นตัวอ้างอิง
    อยู่แล้ว ไม่ต้องวาดสตอรีบอร์ดขึ้นมาใหม่

    **ไม่ต้องถือ browser_lock** เพราะไม่ได้เปิดเบราว์เซอร์เลย ยิง Gemini API ตรง
    """
    chat_id = job["chat_id"]
    item_id = job.get("item_id", "")
    run = clip_store.load_run(DATA_DIR, item_id)
    video = Path(job.get("source_video") or "")
    if not video.is_file():
        # เผื่องานเก่าที่ยังไม่มีฟิลด์นี้ หรือไฟล์ถูกย้าย — หาในโฟลเดอร์งาน
        folder = Path(run.get("folder") or clip_store.run_dir(DATA_DIR, item_id))
        video = next((p for p in folder.glob("source.*")
                      if p.suffix.lower() in tiktok_source.VIDEO_SUFFIXES), video)
    if not video.is_file():
        _clip_say(chat_id, "❌ หาไฟล์คลิปต้นฉบับไม่เจอ วิเคราะห์ต่อไม่ได้")
        raise RuntimeError(f"ไม่พบคลิปต้นฉบับของงาน {item_id}")

    _clip_say(chat_id, "🧠 กำลังให้ Gemini ดูคลิปแล้วเขียนคำสั่ง + ถอดบทพูด…")
    analysis = tiktok_repost.analyze_clip(video, log=_clip_log)
    result = tiktok_repost.build_result(analysis, {"item_id": item_id})
    _clip_keep(
        lambda: clip_store.save_storyboard(DATA_DIR, {"item_id": item_id}, result),
        "ผลวิเคราะห์คลิป",
    )

    clip_jobs.update(
        job["id"], stage=clip_queue.STAGE_STORYBOARD_REVIEW,
        storyboard_ok=False, script_ok=False,
    )
    fresh = clip_jobs.get(job["id"])
    _tiktok_send_prompts(fresh, result["flow_prompts"], analysis)
    _clip_send_script(fresh)


def _tiktok_send_prompts(job: dict, prompts: list[str], analysis: dict) -> None:
    """ส่งคำสั่งสร้างคลิปให้ตรวจ — ใช้ปุ่มชุดเดียวกับสตอรีบอร์ดของสายเดิม

    สายนี้ไม่มีภาพสตอรีบอร์ดให้ดู จึงส่งเป็นข้อความ แต่ยังใช้ปุ่ม storyboard เดิม
    เพื่อให้ธง storyboard_ok และกลไก ✏️ สั่งแก้ ทำงานได้เหมือนกันทุกอย่าง
    """
    head = (
        f"🎯 <b>คำสั่งสร้างคลิป</b> — {len(prompts)} ฉาก\n"
        f"<i>{telegram_bot._escape(str(analysis.get('summary') or '')[:300])}</i>\n"
    )
    body = "\n\n".join(
        f"<b>ฉาก {index}</b>\n{telegram_bot._escape(prompt)}"
        for index, prompt in enumerate(prompts, 1)
    )
    parts = _split_text(head + "\n" + body, TELEGRAM_TEXT_LIMIT)
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        _clip_say(
            job["chat_id"], part,
            _clip_buttons(job["id"], "storyboard") if last else None,
        )


def _tiktok_send_post_review(job: dict) -> None:
    """การ์ดยืนยันก่อนโพสต์ — ข้อ ①②③④ ของผัง

    ต้องเห็นครบทั้ง 4 อย่างในที่เดียวก่อนกดโพสต์ เพราะโพสต์ TikTok แล้วลบทีหลัง
    ก็ยังเหลือร่องรอย (ยอดวิว/แจ้งเตือนผู้ติดตาม) ถือว่าเรียกคืนไม่ได้
    """
    run = clip_store.load_run(DATA_DIR, job.get("item_id", ""))
    videos = run.get("videos") or []
    tags = run.get("highlights") or []
    product_id = run.get("tiktok_product_id") or ""
    basket = tiktok_repost.basket_text()

    lines = [
        "🚀 <b>ยืนยันก่อนโพสต์ขึ้น TikTok</b>",
        "",
        f"① 🎥 คลิป — {len(videos)} ไฟล์",
        *[f"    {telegram_bot._escape(str(v))}" for v in videos[:4]],
        f"② 🛒 Product ID — {telegram_bot._escape(product_id) if product_id else '⛔ ยังไม่มี (จะโพสต์โดยไม่ผูกสินค้า)'}",
        f"③ 🏷 แฮชแท็ก {len(tags)} อัน — {telegram_bot._escape(' '.join(tags)) or '-'}",
        f"④ 💬 คำพูดบนตะกร้า — {telegram_bot._escape(basket)}",
        "",
        f"แคปชันที่จะใช้: <i>{telegram_bot._escape(tiktok_repost.build_post_caption(run))}</i>",
        "",
        "แก้แฮชแท็กได้ที่การ์ดจุดเด่นด้านบน · แก้คำพูดบนตะกร้าด้วย /basket &lt;ข้อความ&gt;",
    ]
    keyboard = {"inline_keyboard": [
        [
            {"text": "🚀 โพสต์เลย", "callback_data": f"clip:tt_post:{job['id']}"},
            {"text": "🗑 ไม่โพสต์", "callback_data": f"clip:tt_skip:{job['id']}"},
        ],
        # 🅿 ค้างตอนจะโพสต์ = "ยังเอาอยู่ แต่ยังไม่พร้อมลง" — คนละอย่างกับ
        # 🗑 ไม่โพสต์ ที่แปลว่าทิ้งเลย ต้องแยกปุ่มกัน ไม่งั้นจะกดทิ้งทั้งที่แค่อยากพัก
        [{"text": "🅿 รอแก้", "callback_data": f"clip:park:{job['id']}:"}],
    ]}
    _clip_say(job["chat_id"], "\n".join(lines), keyboard)


def _tiktok_post(job: dict) -> None:
    """ขั้นสุดท้าย: โพสต์คลิปขึ้น TikTok ด้วยตัวโพสต์เดิมใน tiktok_post.py"""
    chat_id = job["chat_id"]
    run = clip_store.load_run(DATA_DIR, job.get("item_id", ""))
    videos = run.get("videos") or []
    if not videos:
        _clip_say(chat_id, "❌ ไม่มีไฟล์คลิปให้โพสต์")
        raise RuntimeError("ไม่มีคลิปให้โพสต์")

    # ด่านลำดับการลง — TikTok เป็นที่สุดท้าย ต้องลง Shopee Video กับ Facebook Reels
    # ก่อน และห่างจากที่ลงล่าสุดอย่างน้อย 1 วัน (นับวันปฏิทิน)
    #
    # ต้องกันที่นี่ด้วย ไม่ใช่กันแค่ฝั่งมือถือ เพราะ TikTok ใช้ตัวโพสต์คนละตัว
    # (เบราว์เซอร์บนคอม) ถ้ากันข้างเดียว คลิปจะขึ้น TikTok ก่อนที่อื่นได้เลย
    ok, why = publish_order.check(run, "tiktok")
    if not ok:
        _clip_say(chat_id, f"⏳ <b>ยังลง TikTok ไม่ได้</b>\n{_escape(why)}\n\n"
                           f"{_escape(publish_order.summary(run))}")
        _clip_log(f"ไม่ได้โพสต์ TikTok ของ {job.get('item_id','')} — {why}")
        return

    folder = Path(run["folder"])
    video = folder / videos[0]
    _clip_say(chat_id, f"🚀 กำลังโพสต์ขึ้น TikTok… ({video.name})")
    outcome = tiktok_repost.post_to_tiktok(
        video,
        caption=tiktok_repost.build_post_caption(run),
        tags=run.get("highlights") or [],
        pid=run.get("tiktok_product_id") or "",
        log=_clip_log,
    )
    # จดว่าลง TikTok แล้ว — **ขาดตรงนี้มาตลอด** ผลคือ run.json ไม่เคยรู้ว่า
    # คลิปขึ้น TikTok ไปแล้ว ด่านลำดับจึงตรวจไม่ได้ และรายงานบน Drive ก็ไม่ตรง
    try:
        clip_store.mark_posted(DATA_DIR, job.get("item_id", ""), "tiktok",
                               outcome.get("url") or "")
    except Exception as error:                               # noqa: BLE001
        _clip_log(f"โพสต์ TikTok สำเร็จแต่จดไม่ลง: {type(error).__name__}: {error}")

    clip_jobs.update(job["id"], stage=clip_queue.STAGE_DONE)
    _clip_say(
        chat_id,
        "✅ <b>โพสต์ขึ้น TikTok แล้ว</b>\n"
        f"ผูกสินค้า: {'ใช่' if outcome.get('product_attached') else 'ไม่ได้ผูก'} · "
        f"แก้ปก: {'ใช่' if outcome.get('cover_edited') else 'ไม่'}",
    )


STAGE_WORK_NAME = {
    clip_queue.STAGE_QUEUED: "ดึงข้อมูลสินค้า",
    clip_queue.STAGE_READY_STORYBOARD: "ทำสตอรีบอร์ด",
    clip_queue.STAGE_REVISING: "สั่งแก้ตามที่พิมพ์มา",
    clip_queue.STAGE_READY_FLOW: "เจนคลิปใน Google Flow",
    clip_queue.STAGE_POSTING: "โพสต์ขึ้น TikTok",
}


def _clip_worker(job: dict) -> None:
    """ตัวรันคิวเรียกเข้ามาที่นี่ — แยกตามสถานะที่หยิบมา แล้วค่อยแยกตามสายงาน

    **งานพังต้องเด้งเข้าแชทเสมอ** ตัวรันจับ error แล้วมาร์ค failed ให้ก็จริง
    แต่คนที่นั่งรออยู่ในแชทไม่เห็นอะไรเลย — เกิดจริง 12 ส.ค.: รอบสั่งแก้บทพูด
    พังตอน 13:41 แต่ข้อความสุดท้ายในแชทคือ "กำลังสั่งแก้บทพูด…" ผู้ใช้รอเก้อ
    23 นาทีกว่าจะมาถามเอง
    """
    came_from = job.get("claimed_from")
    tiktok = _job_kind(job) == "tiktok"
    try:
        if came_from == clip_queue.STAGE_QUEUED:
            _tiktok_collect(job) if tiktok else _clip_collect(job)
        elif came_from == clip_queue.STAGE_READY_STORYBOARD:
            _tiktok_analyze(job) if tiktok else _clip_make(job)
        elif came_from == clip_queue.STAGE_REVISING:
            _clip_revise(job)
        elif came_from == clip_queue.STAGE_READY_FLOW:
            _clip_generate(job)
        elif came_from == clip_queue.STAGE_POSTING:
            _tiktok_post(job)
        else:
            _clip_log(f"งาน {job['id']} สถานะ {came_from} ไม่รู้จัก ข้ามไป")
    except Exception as error:                                   # noqa: BLE001
        what = STAGE_WORK_NAME.get(came_from, came_from or "งานนี้")
        # **สั่งแก้พังไม่ใช่เหตุให้ทั้งงานตาย** ของที่อนุมัติไปแล้วยังอยู่ครบ
        # ดันกลับไปขั้นตรวจเพื่อให้ปุ่ม ✅/✏️ ในแชทยังกดได้ ไม่งั้นผู้ใช้ตัน
        if came_from == clip_queue.STAGE_REVISING:
            clip_jobs.update(
                job["id"], stage=clip_queue.STAGE_STORYBOARD_REVIEW,
                pending_edit=None, awaiting="",
                note=f"สั่งแก้ไม่สำเร็จ: {str(error)[:120]}",
            )
            target = (job.get("pending_edit") or {}).get("target")
            label = "บทพูด" if target == "script" else "สตอรีบอร์ด"
            _clip_say(
                job.get("chat_id", ""),
                f"❌ <b>สั่งแก้{label}ไม่สำเร็จ</b>\n"
                f"<code>{telegram_bot._escape(str(error)[:200])}</code>\n\n"
                "ของเดิมยังอยู่ครบ กด ✏️ ลองใหม่ได้เลย",
            )
            _clip_log(f"สั่งแก้ล้ม — ดันงาน {job['id']} กลับไปขั้นตรวจ")
            return
        _clip_say(
            job.get("chat_id", ""),
            f"❌ <b>ขั้น “{what}” ไม่สำเร็จ</b>\n"
            f"<code>{telegram_bot._escape(str(error)[:250])}</code>\n\n"
            "ของที่ทำเสร็จไปแล้วยังอยู่ครบ — กด ✏️ สั่งแก้อีกครั้ง "
            "หรือส่งลิงก์เดิมเข้ามาใหม่ได้เลย",
        )
        raise                       # ส่งต่อให้ตัวรันมาร์ค failed เหมือนเดิม


def _clip_blocked_alert(info: dict) -> None:
    """ติด CAPTCHA / โดนบล็อก → **หยุดคิวแล้วบอกผู้ใช้ทางแชท รอยืนยันถึงจะทำต่อ**

    ผู้ใช้สั่งไว้ 25 ส.ค. 2026: *"ถ้าติด capcha ให้หยุดและส่งกลับมาบอกผมทาง
    telegram ว่าติด capcha ผมจะแก้ให้ก่อน แล้วคอนเฟิร์มกลับไปค่อยรันต่อ"*

    ส่งลิงก์ของใบที่ติดไปด้วย เพื่อให้กดเปิดแล้วเลื่อนจิ๊กซอว์ได้เลยจากมือถือ
    ไม่ต้องไปหาเองว่าติดที่ลิงก์ไหน
    """
    job = info.get("job") or {}
    chat_id = str(job.get("chat_id") or "") or str(
        shared.read_config().get("telegram_clip_chat_id") or "")
    if not chat_id:
        _clip_log("ติด CAPTCHA แต่ไม่รู้ว่าจะแจ้งเข้าแชทไหน — ตั้ง telegram_clip_chat_id ก่อน")
        return
    waiting = sum(1 for j in clip_jobs.all() if j.get("stage") == clip_queue.STAGE_QUEUED)
    link = job.get("link") or ""
    escape = telegram_bot._escape
    minutes = int((info.get("seconds") or 0) // 60)

    if info.get("kind") == "wait":
        # **หน้าที่ไม่มีอะไรให้คนทำ** — บอกให้รู้ว่าเกิดอะไรขึ้น แต่ห้ามขอให้เขา
        # ไปแก้ เพราะไม่มีอะไรให้แก้ (27 ส.ค. 2026 เคยขอแล้วคิวนอน 6 ชม. 48 นาที)
        lines = [
            "😴 <b>Shopee ขอให้พักก่อน — พักคิวเองแล้ว</b>",
            "",
            f"ใบที่ติด: {escape((job.get('name') or link)[:70])}",
            f"เหลือรอคิวอีก <b>{waiting}</b> ใบ — ยังอยู่ครบ ไม่ได้หายไปไหน",
            "",
            "หน้าที่ได้คือ “Please Try Again Later” ซึ่ง <b>ไม่มีจิ๊กซอว์ให้เลื่อน</b>",
            "และ <b>ไม่มีอะไรที่คุณต้องไปทำ</b> — เขาแค่บอกให้รอสักครู่",
            "",
            f"⏳ ระบบจะ <b>พัก {minutes or 20} นาทีแล้วทำต่อเอง</b> ไม่ต้องกดอะไรทั้งนั้น",
            "อยากให้เริ่มเดี๋ยวนี้เลยค่อยกดปุ่มข้างล่าง",
        ]
        keyboard = {"inline_keyboard": [[
            {"text": "▶️ ไม่ต้องรอ เริ่มเลย", "callback_data": "clip:unhold:-"},
        ], [
            {"text": "🛑 ยกเลิกที่เหลือทั้งหมด", "callback_data": "clip:holdcancel:-"},
        ]]}
        _clip_log(f"แจ้งผู้ใช้แล้วว่าโดนพัก — จะทำต่อเองใน {minutes or 20} นาที "
                  f"(ค้าง {waiting} ใบ ไม่ต้องรอใครกด)")
    else:
        lines = [
            "⛔ <b>ติดด่านยืนยันตัวตนของ Shopee — หยุดคิวไว้แล้ว</b>",
            "",
            f"ใบที่ติด: {escape((job.get('name') or link)[:70])}",
            f"เหลือรอคิวอีก <b>{waiting}</b> ใบ — ยังอยู่ครบ ไม่ได้หายไปไหน",
            "",
            "หน้านี้ <b>ต้องมีคนเลื่อนจิ๊กซอว์เอง</b> โปรแกรมทำแทนไม่ได้",
            "ระบบจึงหยุดรอ <b>ไม่ยิงต่อ</b> เพื่อไม่ให้โดนหนักกว่าเดิม",
            "",
            "<b>ทำยังไง</b> — เปิดลิงก์ข้างล่างในเบราว์เซอร์ แล้วเลื่อนจิ๊กซอว์ให้ผ่าน",
            "เสร็จแล้วกดปุ่ม ✅ ข้างล่างนี้ ระบบจะทำต่อจากที่ค้างไว้ทันที",
        ]
        keyboard = {"inline_keyboard": [[
            {"text": "✅ เลื่อนจิ๊กซอว์ผ่านแล้ว ทำต่อเลย", "callback_data": "clip:unhold:-"},
        ], [
            {"text": "🛑 ยกเลิกที่เหลือทั้งหมด", "callback_data": "clip:holdcancel:-"},
        ]]}
        _clip_log(f"แจ้งผู้ใช้แล้วว่าติดด่านยืนยันตัวตน — รอยืนยันก่อนทำต่อ "
                  f"(ค้าง {waiting} ใบ)")
    if link:
        lines += ["", f"<code>{escape(link)}</code>"]
    _clip_say(chat_id, "\n".join(lines), keyboard, preview=False)


clip_runner = clip_queue.ClipRunner(clip_jobs, _clip_worker, log=_clip_log,
                                    on_hold=_clip_blocked_alert)


# Telegram รับข้อความละไม่เกิน ~4096 ตัว — คำสั่งยาวๆ ต้องหั่นส่ง
TELEGRAM_TEXT_LIMIT = 3500


def _split_text(text: str, limit: int) -> list[str]:
    """หั่นข้อความยาว โดยพยายามตัดที่ท้ายบรรทัด ไม่ตัดกลางคำ"""
    text = (text or "").strip()
    if len(text) <= limit:
        return [text] if text else []
    parts: list[str] = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts


# หมายเหตุ: เดิมมี _clip_send_flow_prompts() ส่งคำสั่งเจนวิดีโอเข้าแชท
# ถอดออกตามที่ผู้ใช้สั่ง — คำสั่งพวกนั้นยาวหลายพันตัวและเป็นศัพท์เทคนิคล้วน
# ตอนนี้เก็บไว้ในเครื่อง (clip_store) แล้วเอาไปใช้ตอนเจนเอง ส่วนที่ส่งให้คนตรวจ
# คือ **บทพูด** เท่านั้น


REVIEW_STAGES = {
    clip_queue.STAGE_IMAGE_REVIEW,
    clip_queue.STAGE_STORYBOARD_REVIEW, clip_queue.STAGE_SCRIPT_REVIEW,
    clip_queue.STAGE_VIDEO_REVIEW,
}


def _apply_edit_text(job: dict, text: str, target: str = "") -> str:
    """เอาข้อความที่คนพิมพ์มาเป็น "คำสั่งแก้" ของงานนี้ — ใช้ร่วมกันทั้งแชทและหน้าเว็บ

    แยกออกมาจาก _clip_take_edit เพราะสองทางรู้ "งานไหน" คนละแบบ: ในแชทต้องเดา
    จากงานล่าสุดของแชท ส่วนหน้าเว็บกดจากรายการจึงรู้รหัสงานอยู่แล้ว แต่ **สิ่งที่
    เกิดขึ้นหลังจากนั้นต้องเหมือนกันเป๊ะ** ถ้าปล่อยให้เขียนคนละชุด พอแก้ข้างเดียว
    พฤติกรรมสองทางจะเพี้ยนกันโดยไม่มีอะไรฟ้อง

    คืนข้อความสรุปสั้นๆ · คืนค่าว่างแปลว่าไม่มีอะไรให้ทำ
    """
    target = target or job.get("awaiting") or ""
    if not target:
        return ""
    chat_id = job.get("chat_id", "")

    # แก้จุดเด่น = เปลี่ยนข้อความตรงๆ ไม่ต้องคุยกับ GPT
    # (ต่างจากสตอรีบอร์ด/บทพูดที่ต้องให้ GPT ทำใหม่ให้)
    if target.startswith("highlight:"):
        index = int(target.split(":", 1)[1])
        item_id = job.get("item_id", "")
        run = clip_store.load_run(DATA_DIR, item_id)
        highlights = list(run.get("highlights") or [])
        new_text = text.strip()
        if index < len(highlights):
            highlights[index] = new_text
            note = f"แก้ข้อ {index + 1} แล้ว"
        else:
            highlights.append(new_text)
            note = "เพิ่มจุดเด่นแล้ว"
        clip_jobs.update(job["id"], awaiting="")
        _clip_keep(
            lambda: clip_store.set_highlights(DATA_DIR, item_id, highlights), "จุดเด่น"
        )
        # สั่งจากเว็บ **ไม่ต้องแจ้งเข้าแชทเลย** — ทั้งข้อความและการ์ด
        #
        # วัดจริง 25 ส.ค. 2026: ยิงข้อความหา Telegram หนึ่งครั้งกินเวลา ~0.85 วินาที
        # ผู้ใช้กดแก้จุดเด่นทีละข้อ จึงรู้สึกหน่วงทุกครั้งทั้งที่งานจริงคือเขียนไฟล์
        # (ส่วนการ์ดหนักกว่านั้นอีก เพราะอัปโหลดรูปทั้งอัลบั้ม)
        #
        # แชทได้ของครบตอนกด "ใช้จุดเด่นชุดนี้" ซึ่งเป็นจังหวะที่ต้องเห็นของจริง
        if not _web_call():
            _clip_say(chat_id, f"📝 {note}")
            _clip_send_worksheet(clip_jobs.get(job["id"]))
        return note

    what = "สตอรีบอร์ด" if target == "storyboard" else "บทพูด"
    clip_jobs.update(
        job["id"], awaiting="", stage=clip_queue.STAGE_REVISING,
        pending_edit={"target": target, "instruction": text.strip()},
    )
    clip_runner.wake()
    _clip_say(chat_id, f"📝 รับคำสั่งแก้{what}แล้ว — เข้าคิวสั่ง GPT ให้")
    return f"รับคำสั่งแก้{what}แล้ว — เข้าคิวสั่ง GPT ให้"


def _clip_take_edit(chat_id: str, text: str) -> bool:
    """ผู้ใช้กด ✏️ ไว้แล้วพิมพ์คำสั่งตามมา — เอาข้อความนี้ไปเป็นคำสั่งแก้

    ผูกกับ **งานล่าสุดของแชทที่กำลังรอตรวจอยู่** ไม่ให้ผู้ใช้ต้องจำรหัสงาน
    ถ้าไม่ได้กด ✏️ ไว้ก่อน ข้อความจะไม่ถูกดูดไปเป็นคำสั่งแก้ — จะได้ยังวางลิงก์ได้ปกติ
    """
    # หา "งานที่กด ✏️ ค้างไว้" — ต้องมองงานที่ **ล้มเหลว** ด้วย
    #
    # เดิมดูเฉพาะงานที่อยู่ในขั้นตรวจ พอรอบสั่งแก้พังงานจะกลายเป็น failed แล้ว
    # หลุดจากรายการนี้ถาวร ผู้ใช้กด ✏️ แล้วพิมพ์ตามไปก็ไม่มีใครรับ — ตัน
    # (เกิดจริง 12 ส.ค. ผู้ใช้พิมพ์แล้วเงียบไป 3 ชั่วโมง)
    job = clip_jobs.latest_for_chat(chat_id, REVIEW_STAGES)
    if not job or not job.get("awaiting"):
        stuck = clip_jobs.latest_for_chat(chat_id, {clip_queue.STAGE_FAILED})
        job = stuck if stuck and stuck.get("awaiting") else job
    if not job or not job.get("awaiting"):
        return False
    return bool(_apply_edit_text(job, text))


def _clip_telegram_text(chat_id: str, text: str) -> None:
    if _clip_take_edit(chat_id, text):
        return

    # วางหลายลิงก์รวดเดียวได้ — เข้าคิวเรียงตามลำดับที่วางมา
    # ทำทีละงานเพราะเบราว์เซอร์มีโปรไฟล์เดียว เปิดซ้อนกันจะไล่หน้าต่างกันเอง
    # รับได้สองสาย: ลิงก์สินค้า Shopee (สายเดิม) และลิงก์คลิป TikTok (สาย repost)
    # เช็ค TikTok ก่อนเสมอ — เหตุผลอยู่ที่คอมเมนต์ของ TIKTOK_LINK_RE
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for link in TIKTOK_LINK_RE.findall(text):
        if link not in seen:             # วางซ้ำในข้อความเดียวกันไม่ต้องทำสองรอบ
            seen.add(link)
            links.append(("tiktok", link))
    for link in SHOPEE_LINK_RE.findall(text):
        if link not in seen:
            seen.add(link)
            links.append(("shopee", link))
    if not links:
        _clip_say(
            chat_id,
            "ส่ง<b>ลิงก์สินค้า Shopee</b> หรือ <b>ลิงก์คลิป TikTok</b> "
            "มาได้เลย (/help ดูวิธีใช้)",
        )
        return

    waiting = len(clip_jobs.waiting())
    for kind, link in links:
        job = clip_jobs.add(link, chat_id)
        # ตั้ง kind ด้วย update() แทนการแก้ ClipQueue.add() — งานเก่าในไฟล์คิวที่ไม่มี
        # ฟิลด์นี้จะยังอ่านเป็น "shopee" ตามค่าปริยายที่ฝั่งอ่านใช้ ไม่พังย้อนหลัง
        clip_jobs.update(job["id"], kind=kind)
        _clip_log(f"เข้าคิว {job['id']} [{kind}] — {link[:60]}")
    clip_runner.wake()

    if len(links) == 1 and waiting == 0:
        _clip_say(chat_id, "🔎 รับลิงก์แล้ว กำลังเริ่มทำ…")
    else:
        _clip_say(
            chat_id,
            f"📥 รับ <b>{len(links)}</b> ลิงก์เข้าคิวแล้ว "
            f"(ในคิวตอนนี้ {waiting + len(links)} งาน)\n"
            # บอกเพดานตรงนี้ด้วย — ส่งมา 33 ใบแล้วเห็นขยับแค่ 8 ใบ
            # ถ้าไม่บอกไว้ก่อน ผู้ใช้จะนึกว่าระบบค้าง (25 ส.ค. 2026)
            + clip_jobs.load_text() + "\n"
            "/queue ดูสถานะ",
        )


# งานที่ "จอดรอคนกด" — คนละพวกกับงานที่รอเครื่องทำ (ACTIONABLE)
#
# ค่าคือ (ชื่อที่คนอ่านรู้เรื่อง, ชื่อฟังก์ชันที่ส่งการ์ดอนุมัติของขั้นนั้น)
# **ใช้ฟังก์ชันเดิมที่บอทใช้ส่งครั้งแรกทั้งหมด ไม่เขียนการ์ดชุดใหม่** เพราะถ้าเขียนซ้ำ
# พอวันหลังแก้ปุ่มข้างหนึ่ง อีกข้างจะเพี้ยนเงียบๆ — ปุ่มอนุมัติจึงเป็นตัวเดียวกันเป๊ะ
# (สร้างจาก _clip_buttons ผูกกับ job_id เดิม) กดจากตรงไหนก็ให้ผลเหมือนกัน
PENDING_STAGES = {
    clip_queue.STAGE_IMAGE_REVIEW: "ตรวจชุดรูป + จุดเด่น",
    clip_queue.STAGE_STORYBOARD_REVIEW: "ตรวจสตอรีบอร์ด",
    clip_queue.STAGE_SCRIPT_REVIEW: "ตรวจบทพูด",
    clip_queue.STAGE_VIDEO_REVIEW: "ตรวจคลิป",
    clip_queue.STAGE_POST_REVIEW: "ยืนยันก่อนโพสต์ TikTok",
}

# ส่งซ้ำทีเดียวได้มากสุดกี่งาน — แต่ละงานกินหลายข้อความ (รูป + ข้อความ + ปุ่ม)
# ยิงหมด 12 งานรวดเดียวจะได้ 50+ ข้อความ เลื่อนหาไม่เจอ กลายเป็นซ่อนของที่
# ตั้งใจจะเอามาโชว์
PENDING_SEND_LIMIT = 3


def _clip_resend_card(job: dict) -> str:
    """เด้งการ์ดอนุมัติของงานนั้นกลับเข้าแชทอีกครั้ง — ใช้ฟังก์ชันเดิมของแต่ละขั้น"""
    stage = job.get("stage")
    if stage not in PENDING_STAGES:
        return f"งานนี้ไม่ได้รออนุมัติ (ตอนนี้อยู่ขั้น {clip_queue.STAGE_LABEL.get(stage, stage)})"

    run = clip_store.load_run(DATA_DIR, job.get("item_id", "")) or {}
    if stage == clip_queue.STAGE_IMAGE_REVIEW:
        _clip_send_worksheet(job)
    elif stage == clip_queue.STAGE_STORYBOARD_REVIEW:
        _clip_send_storyboard(job, run)
    elif stage == clip_queue.STAGE_SCRIPT_REVIEW:
        _clip_send_script(job, run)
    elif stage == clip_queue.STAGE_VIDEO_REVIEW:
        _clip_send_video(job, run)
    elif stage == clip_queue.STAGE_POST_REVIEW:
        _tiktok_send_post_review(job)
    return f"ส่ง{PENDING_STAGES[stage]}มาให้แล้ว"


def _clip_pending_list(chat_id: str, argument: str = "") -> None:
    """งานที่จอดรออนุมัติอยู่ — เรียกกลับมากดได้ทุกเมื่อ

    **ทำไมต้องมี** บอทส่งการ์ดอนุมัติแค่ตอนทำเสร็จครั้งเดียว พอคุยเรื่องอื่นต่อ
    การ์ดเลื่อนหายขึ้นไปด้านบน งานเลยจอดค้างโดยไม่มีอะไรเตือน (วัดจริง 22 ส.ค.
    2026: จอดรออนุมัติ 12 งาน — รอตรวจสตอรีบอร์ด 7 · รอตรวจชุดรูป 5)
    """
    jobs = [job for job in clip_jobs.all() if job.get("stage") in PENDING_STAGES]
    if not jobs:
        _clip_say(chat_id, "✅ ไม่มีงานค้างรออนุมัติ — /queue ดูงานที่กำลังทำ")
        return

    escape = telegram_bot._escape
    want = (argument or "").strip().lower()

    # /pending <เลข> — เด้งงานนั้นงานเดียว
    if want.isdigit() and 1 <= int(want) <= len(jobs):
        _clip_say(chat_id, _clip_resend_card(jobs[int(want) - 1]))
        return

    # /pending all — เด้งทุกงาน (มีเพดาน กันแชทท่วม)
    if want in ("all", "ทั้งหมด", "หมด"):
        batch = jobs[:PENDING_SEND_LIMIT]
        for job in batch:
            _clip_resend_card(job)
        if len(jobs) > len(batch):
            _clip_say(
                chat_id,
                f"ส่งมาแล้ว {len(batch)} งาน — เหลืออีก {len(jobs) - len(batch)} งาน\n"
                "กดอนุมัติชุดนี้ก่อน แล้วสั่ง <code>/pending all</code> ซ้ำได้",
            )
        return

    lines = [f"⏳ <b>งานที่รออนุมัติ</b> {len(jobs)} งาน\n"]
    buttons = []
    for index, job in enumerate(jobs, 1):
        stage = job.get("stage")
        waited = _clip_waited_text(job)
        lines.append(
            f"<b>{index}.</b> {escape(str(job.get('name') or job.get('link') or '')[:50])}\n"
            f"     {PENDING_STAGES[stage]}{waited} · <code>/pending {index}</code>"
        )
        if len(buttons) < 8:
            buttons.append([{
                "text": f"⏳ {index}. {str(job.get('name') or '')[:24]}",
                "callback_data": f"clip:pend:{job.get('id', '')}",
            }])
    # ✅ ปุ่มอนุมัติรวดเดียว (ผู้ใช้สั่ง 22 ส.ค. 2026) — อยู่ **แถวบนสุด**
    #
    # คนเปิด /pending มาเพราะอยากเคลียร์งานค้าง การต้องพิมพ์ /approveall ต่ออีกที
    # ทั้งที่รายการอยู่ตรงหน้าแล้วคือขั้นตอนเกินจำเป็น
    #
    # **ยังไม่กดผ่านทันทีที่แตะ** — พาไปหน้าสรุปที่บอกยอดเครดิตก่อน เพราะปุ่มนี้
    # ปล่อยงานเข้าคิวเจนคลิปได้ทีละหลายงาน = จ่ายเครดิตจริงหลักร้อย กดพลาดแล้ว
    # เอาคืนไม่ได้ · หน้าสรุปยังบอกด้วยว่างานไหน**ไม่**รวมให้ (ขั้นที่โพสต์ออกนอก)
    ready = _clip_approve_all_plan()["ready"]
    if ready:
        buttons.insert(0, [{
            "text": f"✅ อนุมัติรวดเดียว {len(ready)} งาน",
            "callback_data": "clip:apvall::ask",
        }])
        lines.append(
            f"\n✅ <b>กดปุ่มบนสุด</b> อนุมัติ {len(ready)} งานรวดเดียว "
            "(บอกยอดเครดิตก่อน แล้วค่อยยืนยัน)"
        )
    lines.append(
        "\nกดปุ่มรายชื่อเพื่อเรียกงานนั้นมาอนุมัติทีละใบ · "
        "<code>/pending all</code> เรียกมาทีละชุด"
    )
    parts = _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT)
    for part in parts[:-1]:
        _clip_say(chat_id, part)
    _clip_say(chat_id, parts[-1], {"inline_keyboard": buttons} if buttons else None)


def _clip_waited_text(job: dict) -> str:
    """จอดมานานแค่ไหนแล้ว — บอกเป็นชั่วโมง/วัน ให้รู้ว่าอันไหนค้างนานสุด"""
    stamp = job.get("updated_at") or job.get("created_at") or ""
    try:
        waited = datetime.now() - datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return ""
    hours = waited.total_seconds() / 3600
    if hours < 1:
        return f" · จอดมา {int(waited.total_seconds() // 60)} นาที"
    if hours < 24:
        return f" · จอดมา {int(hours)} ชม."
    return f" · จอดมา {int(hours // 24)} วัน"


# ======================================== /approveall — กดผ่านงานค้างรวดเดียว
#
# **ครอบคลุมทุกขั้นที่รอคนกด รวมขั้นอนุมัติคลิปด้วย** (ผู้ใช้ยืนยัน 22 ส.ค. 2026)
#
# ตอนแรกกันขั้นอนุมัติคลิปออกไป เพราะกดผ่านแล้วของเข้าคิวโพสต์ออกสาธารณะ แต่
# เจ้าของงานสั่งชัดว่าต้องการ "ทั้งหมด" จริงๆ — เขาเป็นคนดูคลิปเองอยู่แล้วก่อนกด
# และการบังคับให้กดทีละ 8 ใบทำให้เครื่องมือนี้ไม่มีประโยชน์ตามที่ตั้งใจไว้
#
# ที่ยังเหลือไว้เป็นด่านกันพลาดคือ **หน้าสรุปก่อนยืนยัน** ซึ่งบอกชัดว่ากี่ใบจะ
# โพสต์ออกนอก และเตือนใบที่ผลตรวจไม่ผ่าน (ไม่ใช่ 1080p / ไม่มีเสียงพูด) — เห็น
# ก่อนตัดสินใจ ไม่ใช่ห้ามไม่ให้ตัดสินใจ
APPROVE_ALL_STAGES = {
    clip_queue.STAGE_IMAGE_REVIEW: "ชุดรูป + จุดเด่น",
    clip_queue.STAGE_STORYBOARD_REVIEW: "สตอรีบอร์ด + บทพูด",
    clip_queue.STAGE_SCRIPT_REVIEW: "บทพูด",
    clip_queue.STAGE_VIDEO_REVIEW: "คลิป → เข้าคิวโพสต์",
    clip_queue.STAGE_POST_REVIEW: "ยืนยันโพสต์ TikTok",
}

# ขั้นที่กดผ่านแล้ว "ของออกไปข้างนอก" — ยังรวมให้ แต่ต้องนับแยกเพื่อเตือนในหน้าสรุป
APPROVE_ALL_PUBLISH = {
    clip_queue.STAGE_VIDEO_REVIEW: "เข้าคิวโพสต์ Facebook + Shopee",
    clip_queue.STAGE_POST_REVIEW: "โพสต์ขึ้น TikTok",
}

APPROVE_ALL_BLOCKED: dict = {}


def _clip_approve_all_plan() -> dict:
    """คัดว่างานไหนกดผ่านรวดเดียวได้ — **อ่านอย่างเดียว ไม่แตะคิว ไม่เสียเครดิต**

    แยกออกมาเหมือน `_genall_plan` เพราะตัวเลขที่คืนไปคือตัวเลข**เครดิต**ที่ผู้ใช้
    ใช้ตัดสินใจก่อนกดจ่ายจริง ถ้าตอนแสดงกับตอนทำคำนวณคนละที่ วันหนึ่งจะไม่ตรงกัน
    """
    ready, blocked, missing = [], [], []
    for job in clip_jobs.all():
        stage = job.get("stage")
        if stage in APPROVE_ALL_BLOCKED:
            blocked.append((job, APPROVE_ALL_BLOCKED[stage]))
            continue
        if stage not in APPROVE_ALL_STAGES:
            continue
        run = clip_store.load_run(DATA_DIR, job.get("item_id", "")) or {}
        name = (job.get("name") or run.get("name") or job.get("item_id") or "")[:42]

        # ของที่ขั้นถัดไปต้องใช้ ต้องมีครบก่อน ไม่งั้นกดผ่านไปแล้วไปตายขั้นถัดไป
        warn = ""
        if stage == clip_queue.STAGE_IMAGE_REVIEW:
            if not (run.get("images") and run.get("highlights")):
                missing.append(f"{name} — ยังไม่มีรูปหรือจุดเด่นครบ")
                continue
            cost = 0                       # ขั้นนี้ไปคุยกับ GPT ไม่ใช้เครดิต Flow
        elif stage in APPROVE_ALL_PUBLISH:
            # ขั้นปล่อยของออกนอก — ไม่ต้องมีคำสั่ง Flow แล้ว (คลิปเสร็จอยู่ในมือ)
            # แต่ถ้าผลตรวจคลิปไม่ผ่านต้องเตือนให้เห็นก่อนกด ไม่ใช่ปล่อยเงียบ
            cost = 0
            check = run.get("video_check") or {}
            if check and not check.get("ok"):
                warn = " / ".join(check.get("problems") or []) or "ผลตรวจไม่ผ่าน"
            elif not check:
                warn = "ยังไม่ได้ตรวจคลิป"
        else:
            if not run.get("flow_prompt_count"):
                missing.append(f"{name} — ยังไม่มีคำสั่งเจนคลิป")
                continue
            cost = _credit_estimate(run) if flow_enabled() else 0
        ready.append({"job": job, "name": name, "stage": stage,
                      "cost": cost, "warn": warn})

    have, age = known_credits()
    return {
        "ready": ready, "blocked": blocked, "missing": missing,
        "publish": [i for i in ready if i["stage"] in APPROVE_ALL_PUBLISH],
        "warned": [i for i in ready if i["warn"]],
        "cost": sum(item["cost"] for item in ready),
        "credits": have, "credits_age": age,
    }


def _clip_approve_one(job: dict) -> str:
    """กดผ่านงานหนึ่งชิ้น — เดินสถานะแบบเดียวกับปุ่มในการ์ดเป๊ะ

    ตั้งธงให้ครบก่อนแล้วค่อยเรียก `_clip_after_approve` ครั้งเดียว **ไม่ยิง sb_ok
    แล้วตามด้วย sc_ok** เพราะจะได้ข้อความ "เหลืออีกอย่าง: บทพูด" แทรกมาทุกงาน
    กดรวด 8 งานจะได้ข้อความขยะ 8 อัน บังของจริงที่ต้องอ่าน
    """
    job_id, chat_id = job["id"], job["chat_id"]
    stage = job.get("stage")

    if stage == clip_queue.STAGE_IMAGE_REVIEW:
        clip_jobs.update(
            job_id, images_ok=True, highlights_ok=True, awaiting="",
            stage=clip_queue.STAGE_READY_STORYBOARD,
        )
        clip_runner.wake()
        return "เข้าคิวทำสตอรีบอร์ด"

    # ขั้นปล่อยของออกนอก — **เรียกปุ่มตัวจริง** ไม่เขียนตรรกะซ้ำ เพราะขั้นนี้มี
    # ของต้องทำต่ออีกหลายอย่าง (แยกสาย TikTok · ตั้งสถานะพร้อมโพสต์ · ส่งแคปชัน)
    # เขียนซ้ำแล้วพลาดข้อใดข้อหนึ่งคือของค้างกลางทางโดยไม่มีอะไรฟ้อง
    if stage == clip_queue.STAGE_VIDEO_REVIEW:
        _clip_telegram_button(chat_id, f"vid_ok:{job_id}:", {})
        fresh = clip_jobs.get(job_id) or {}
        return clip_queue.STAGE_LABEL.get(fresh.get("stage"), fresh.get("stage") or "")
    if stage == clip_queue.STAGE_POST_REVIEW:
        _clip_telegram_button(chat_id, f"tt_post:{job_id}:", {})
        fresh = clip_jobs.get(job_id) or {}
        return clip_queue.STAGE_LABEL.get(fresh.get("stage"), fresh.get("stage") or "")

    clip_jobs.update(job_id, storyboard_ok=True, script_ok=True, awaiting="")
    _clip_after_approve(job_id, chat_id, "")
    fresh = clip_jobs.get(job_id) or {}
    return clip_queue.STAGE_LABEL.get(fresh.get("stage"), fresh.get("stage") or "")


def _clip_approve_all(chat_id: str, argument: str = "") -> None:
    """กดผ่านงานที่จอดรออนุมัติทั้งหมดในทีเดียว (ผู้ใช้สั่ง 22 ส.ค. 2026)

    **ทำไมต้องยืนยันอีกที** กดครั้งเดียวอาจปล่อยงานเข้าคิวเจนคลิปพร้อมกันสิบงาน
    = จ่ายเครดิต Flow จริงหลักร้อย ถ้าพิมพ์ผิดหรือกดพลาดแล้วเผาไปเลยจะเรียกคืนไม่ได้
    จึงแสดงรายการ + ยอดเครดิตก่อน แล้วให้กดปุ่มยืนยันอีกครั้ง (ยังเหลือแค่ 2 แตะ
    เทียบกับกดทีละใบ 8 ครั้ง) ใครมั่นใจแล้วสั่ง `/approveall เลย` ข้ามหน้ายืนยันได้
    """
    escape = telegram_bot._escape
    want = (argument or "").strip().lower()
    go = want in ("เลย", "ยืนยัน", "now", "go", "yes", "ok")

    plan = _clip_approve_all_plan()
    ready, blocked, missing = plan["ready"], plan["blocked"], plan["missing"]
    cost, have, age = plan["cost"], plan["credits"], plan["credits_age"]

    if not ready:
        lines = ["✅ ไม่มีงานที่กดผ่านรวดเดียวได้ตอนนี้"]
        if blocked:
            lines.append(
                f"\n🔒 มีอีก {len(blocked)} งานที่ต้องกดเองทีละใบ — /pending")
        if missing:
            lines.append("\n⚠️ ของยังไม่ครบ:\n" +
                         "\n".join("  · " + escape(text) for text in missing[:10]))
        _clip_say(chat_id, "\n".join(lines))
        return

    # ---- ด่านเครดิต: ไม่พอก็ไม่ต้องเริ่ม (กติกาเดียวกับ /genall) ----
    if have is not None and cost > have:
        _clip_say(
            chat_id,
            "🛑 <b>เครดิตไม่พอ — ยังไม่กดผ่านให้</b>\n\n"
            f"กดผ่านทั้งหมดจะเข้าคิวเจนคลิป {len(ready)} งาน ใช้ราว <b>{cost:,}</b> เครดิต\n"
            f"แต่เหลืออยู่ <b>{have:,}</b> (อ่านเมื่อ {_age_text(age)})\n\n"
            "กดทีละใบด้วย /pending หรือเช็คยอดจริงด้วย <code>/credits สด</code>",
        )
        return

    if not go:
        lines = [f"✅ <b>จะกดผ่าน {len(ready)} งาน</b>", ""]
        for index, item in enumerate(ready, 1):
            money = f" · ~{item['cost']} เครดิต" if item["cost"] else ""
            mark = "📤 " if item["stage"] in APPROVE_ALL_PUBLISH else ""
            lines.append(
                f"<b>{index}.</b> {mark}{escape(item['name'])}\n"
                f"     {APPROVE_ALL_STAGES[item['stage']]}{money}"
            )
            if item["warn"]:
                lines.append(f"     ⚠️ {escape(item['warn'])[:90]}")
        lines.append("")
        # ของที่ออกไปข้างนอกต้องเห็นเป็นตัวเลขชัดๆ ไม่ใช่ปนอยู่ในรายการยาว
        publish = plan["publish"]
        if publish:
            lines.append(
                f"📤 <b>{len(publish)} ใบจะออกสู่สาธารณะ</b> "
                "(เข้าคิวโพสต์ Facebook Reels + Shopee Video) — โพสต์แล้วเรียกกลับไม่ได้"
            )
        if plan["warned"]:
            lines.append(
                f"⚠️ <b>{len(plan['warned'])} ใบผลตรวจไม่ผ่าน</b> "
                "(ดูเครื่องหมาย ⚠️ ในรายการ)"
            )
            lines.append("")
        if cost:
            lines.append(f"💳 รวมราว <b>{cost:,}</b> เครดิต" + (
                f" · เหลืออยู่ {have:,} (อ่านเมื่อ {_age_text(age)})" if have is not None else ""))
        else:
            lines.append("💳 ขั้นพวกนี้ยังไม่ใช้เครดิต Flow")
        if not flow_enabled():
            lines.append("ℹ️ ขั้นเจนคลิปปิดอยู่ — งานจะหยุดหลังอนุมัติ ยังไม่เจนจริง")
        if blocked:
            lines.append("")
            lines.append(f"🔒 <b>ไม่รวมให้ {len(blocked)} งาน</b> ต้องกดเองทีละใบ")
            for job, why in blocked[:6]:
                lines.append(f"  · {escape(str(job.get('name') or '')[:34])} — {why}")
        if missing:
            lines.append("")
            lines.append("⚠️ <b>ข้ามให้เพราะของยังไม่ครบ</b>")
            lines += ["  · " + escape(text) for text in missing[:6]]
        lines.append("")
        lines.append("กดปุ่มข้างล่างเพื่อยืนยัน · หรือสั่ง <code>/approveall เลย</code>")
        for part in _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT)[:-1]:
            _clip_say(chat_id, part)
        _clip_say(
            chat_id,
            _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT)[-1],
            {"inline_keyboard": [[{
                "text": f"✅ ยืนยัน อนุมัติทั้ง {len(ready)} งาน",
                "callback_data": "clip:apvall::go",
            }]]},
        )
        return

    # ---- ลงมือจริง ----
    done, failed = [], []
    for item in ready:
        try:
            where = _clip_approve_one(item["job"])
        except Exception as error:                           # noqa: BLE001
            failed.append(f"{item['name']} — {error}")
            _clip_log(f"อนุมัติรวด: {item['name']} ไม่ผ่าน — {error}")
            continue
        done.append(f"{item['name']} → {where}")
    _clip_log(f"อนุมัติรวดเดียว {len(done)} งาน · ไม่ผ่าน {len(failed)}")

    lines = [f"✅ <b>อนุมัติแล้ว {len(done)} งาน</b>", ""]
    lines += ["  · " + escape(text) for text in done[:20]]
    if len(done) > 20:
        lines.append(f"  …และอีก {len(done) - 20} งาน")
    if failed:
        lines += ["", f"❌ <b>ไม่ผ่าน {len(failed)} งาน</b>"]
        lines += ["  · " + escape(text) for text in failed[:10]]
    if blocked:
        lines += ["", f"🔒 เหลือ {len(blocked)} งานที่ต้องกดเองทีละใบ — /pending"]
    lines += ["", "/queue ดูงานที่กำลังทำ"]
    for part in _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT):
        _clip_say(chat_id, part)


# เว้นกี่วินาทีระหว่างคลิปตอนตรวจทีละหลายใบ
#
# **ตั้งไว้ต่ำเพราะเพดานจริงคือรายวัน ไม่ใช่รายนาที** — วัดจากคำตอบของ Google
# เอง 22 ส.ค. 2026: quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier
# ให้ 20 ครั้ง/วัน/โมเดล การเว้นจังหวะจึงไม่ได้ช่วยให้ตรวจได้มากขึ้นเลย
# (เคยตั้ง 5 วิแล้ววัดจริง: 8 นาทีตรวจได้ 4 ใบจาก 15 เท่าเดิม) เหลือไว้ 2 วิ
# แค่กันยิงชนกันเองในวินาทีเดียว
RECHECK_GAP = 2


def _clip_refresh_features(chat_id: str, argument: str = "") -> None:
    """คัดจุดเด่นใหม่จากข้อความที่เก็บไว้ — `/features <รหัส|เลข>` (ผู้ใช้สั่ง 22 ส.ค. 2026)

    **ไม่ต้องดึงสินค้าซ้ำ** เพราะข้อความรายละเอียดดิบถูกเก็บไว้ใน detail.txt ตั้งแต่
    ตอนดึงมาแล้ว การดึงซ้ำต้องเปิดเบราว์เซอร์ ซึ่งช้าและต้องแย่งกับงานเจนคลิป

    ใช้ตอน: จุดเด่นชุดเดิมไม่ถูกใจ · หรือของเดิมคัดตอน AI ล่มเลยได้ของไม่ดี
    """
    escape = telegram_bot._escape
    from flow_worker import load_gemini_api_key
    import shopee_scrape

    runs = clip_store.list_runs(DATA_DIR)
    target = (argument or "").strip()
    if not target:
        _clip_say(
            chat_id,
            "บอกด้วยว่าจะคัดจุดเด่นของงานไหน\n"
            "<code>/features &lt;เลขจาก /clips&gt;</code> หรือ <code>/features &lt;รหัสสินค้า&gt;</code>",
        )
        return

    run = None
    if target.isdigit() and 1 <= int(target) <= len(runs):
        run = runs[int(target) - 1]
    else:
        run = clip_store.load_run(DATA_DIR, target) or None
    if not run:
        _clip_say(chat_id, f"ไม่พบงานที่ {escape(target)} — /clips ดูรายการ")
        return

    item_id = str(run.get("item_id") or "")
    detail = clip_store.read_detail(DATA_DIR, item_id)
    if not detail.strip():
        _clip_say(
            chat_id,
            "งานนี้ไม่มีข้อความรายละเอียดเก็บไว้ (ดึงมาก่อนวันที่ระบบเริ่มเก็บ)\n"
            "ต้องส่งลิงก์เข้ามาใหม่เพื่อดึงสินค้าอีกครั้ง",
        )
        return

    _clip_say(chat_id, f"🔎 กำลังไล่จุดขายของ <b>{escape((run.get('name') or '')[:44])}</b>…")
    try:
        analysis = shopee_scrape.analyse_features(
            run.get("name", ""), detail, load_gemini_api_key(), log=_clip_log,
        )
    except Exception as error:                               # noqa: BLE001
        _clip_say(chat_id, f"❌ คัดจุดเด่นไม่สำเร็จ: {escape(str(error))}")
        return
    if not analysis.get("highlights"):
        _clip_say(chat_id, "❌ คัดจุดเด่นไม่ได้เลย — ลองใหม่อีกครั้ง")
        return

    clip_store.save_features(DATA_DIR, item_id, analysis)
    fresh = clip_store.load_run(DATA_DIR, item_id)
    _clip_say(chat_id, _clip_features_text(fresh), _clip_features_buttons(fresh))


# ที่พักการแก้จุดเด่นก่อนกดส่ง (ผู้ใช้สั่ง 23 ส.ค. 2026)
#
# **ทำไมต้องมีที่พัก** ของเดิมกดปุ่มทีเดียวบันทึกทันทีทีนึง แล้วส่งการ์ดใหม่ทั้งใบ
# ผู้ใช้ที่ต้อง "ลบข้อ 3 แล้วเพิ่มข้อ 6 7 8" ต้องกด 4 ครั้ง = บันทึก 4 รอบ +
# การ์ดใหม่ 4 ใบท่วมแชท และระหว่างทางข้อมูลอยู่ในสถานะครึ่งๆ กลางๆ ตลอด
#
# แบบใหม่: กดสะสมไว้ในหน่วยความจำ **แก้ข้อความการ์ดเดิมในที่เดิม** ให้เห็นผลทันที
# แล้วค่อยกดส่งครั้งเดียว — ไฟล์ถูกเขียนรอบเดียว แชทมีการ์ดใบเดียว
#
# เก็บในหน่วยความจำ ไม่ลงไฟล์ เพราะเป็นของชั่วคราวระหว่างกด รีสตาร์ตแล้วหายก็ถูกแล้ว
# (ของที่ยังไม่กดส่ง = ยังไม่ได้ตั้งใจให้มีผล)
_feature_drafts: dict[str, dict] = {}


def _draft_key(chat_id: str, item_id: str) -> str:
    return f"{chat_id}:{item_id}"


def _get_draft(chat_id: str, item_id: str, run: dict) -> dict:
    """ที่พักของงานนี้ — ยังไม่มีก็สร้างจากของที่บันทึกไว้ตอนนี้"""
    key = _draft_key(chat_id, item_id)
    draft = _feature_drafts.get(key)
    if draft is None:
        draft = {"highlights": list(run.get("highlights") or []), "changes": []}
        _feature_drafts[key] = draft
    return draft


def _drop_draft(chat_id: str, item_id: str) -> None:
    _feature_drafts.pop(_draft_key(chat_id, item_id), None)


def _edit_card(chat_id: str, message_id, text: str, keyboard=None) -> None:
    """แก้ข้อความการ์ดใบเดิม — ไม่มี message_id ค่อยส่งใบใหม่

    **แก้ในที่เดิมสำคัญกับการ์ดที่กดหลายครั้ง** ไม่งั้นกด 4 ครั้งได้การ์ด 4 ใบ
    ผู้ใช้ต้องเลื่อนหาว่าใบไหนใหม่สุด แล้วกดผิดใบได้ง่ายมาก
    """
    token = load_clip_token() or ""
    target = chat_id or load_config().get("telegram_clip_chat_id", "")
    if token and target and message_id:
        try:
            telegram_bot.edit_message(token, target, int(message_id), text, keyboard)
            return
        except telegram_bot.TelegramError as error:
            append_log("input", f"[บอทคลิป] แก้การ์ดเดิมไม่ได้ ({error}) — ส่งใบใหม่แทน")
    _clip_say(chat_id, text, keyboard)


def _storyboard_stale(run: dict) -> str:
    """สตอรีบอร์ดที่มีอยู่ยังตรงกับจุดเด่นตอนนี้ไหม — คืนคำอธิบายถ้าไม่ตรง

    **ตอบคำถามที่ผู้ใช้ถาม 23 ส.ค. 2026**: "ถ้าจุดเด่นเปลี่ยน ต้องแก้สตอรีบอร์ดใหม่ไหม"
    คำตอบคือ **ต้อง** เพราะจุดเด่นถูกใช้ตอนคุยกับ GPT ครั้งเดียว ของที่ได้มา
    (ภาพสตอรีบอร์ด / คำสั่ง Flow / บทพูด) ไม่ได้ผูกกลับไปหาจุดเด่นอีกเลย
    แก้จุดเด่นทีหลังจึงไม่มีผลกับคลิป จนกว่าจะสั่งทำสตอรีบอร์ดใหม่

    ก่อนหน้านี้ความไม่ตรงกันนี้**เงียบสนิท** — แก้จุดเด่นแล้วนึกว่าคลิปจะเปลี่ยนตาม
    """
    if not run.get("storyboard_count"):
        return ""
    used = run.get("storyboard_highlights")
    if used is None:
        return ""           # ทำก่อนวันที่ระบบเริ่มจำ บอกไม่ได้ ดีกว่าเดาผิด
    now = [str(x).strip() for x in (run.get("highlights") or [])]
    was = [str(x).strip() for x in used]
    if now == was:
        return ""
    added = len([x for x in now if x not in was])
    gone = len([x for x in was if x not in now])
    parts = []
    if added:
        parts.append("เพิ่ม/แก้ %d ข้อ" % added)
    if gone:
        parts.append("เอาออก %d ข้อ" % gone)
    return " / ".join(parts) or "จุดเด่นเปลี่ยนไป"


def _clip_features_buttons(run: dict, draft: dict | None = None) -> dict:
    """ปุ่มแก้จุดเด่นสำหรับการ์ด /features (ผู้ใช้สั่ง 23 ส.ค. 2026)

    **ผูกกับรหัสสินค้า ไม่ใช่รหัสงานในคิว** ต่างจากปุ่มในใบงาน เพราะ /features
    เปิดดูงานไหนก็ได้ รวมทั้งงานที่จบไปแล้วและไม่มีรายการในคิวอีกต่อไป

    ปุ่มหลักคือ **เลือกจากรายการเต็ม** — เรามีจุดขายที่ไล่ไว้ 15 ข้อ แต่ใช้จริง 3 ข้อ
    การสลับข้อที่ไม่ถูกใจจึงควรเป็นแค่ "แตะเลข" ไม่ใช่พิมพ์ใหม่ทั้งประโยค
    """
    item = str(run.get("item_id") or "")
    # ระหว่างมีที่พัก ให้ปุ่มอ้างอิง **ของในที่พัก** ไม่ใช่ของที่บันทึกไว้
    # ไม่งั้นเลขข้อบนปุ่มจะไม่ตรงกับรายการที่แสดงอยู่ตรงหน้า
    pending = bool(draft and draft.get("changes"))
    highlights = list((draft or {}).get("highlights") or run.get("highlights") or [])
    features = run.get("features") or []
    rows: list[list[dict]] = []

    # แถวบน: แก้/ลบ ของ 3 ข้อที่ใช้อยู่
    for index in range(1, len(highlights) + 1):
        row = [{"text": f"✏️ แก้ {index}",
                "callback_data": f"clip:ft_edit:{item}:{index}"}]
        if len(highlights) > 1:
            row.append({"text": f"🗑 ลบ {index}",
                        "callback_data": f"clip:ft_del:{item}:{index}"})
        rows.append(row)

    # แถวถัดมา: หยิบจากรายการเต็ม — เอาเฉพาะข้อที่ยังไม่ได้ใช้
    used = {text.strip() for text in highlights}
    row: list[dict] = []
    for number, text in enumerate(features, 1):
        if text.strip() in used:
            continue
        if len(highlights) >= CLIP_MAX_HIGHLIGHTS:
            break
        row.append({"text": f"➕ {number}",
                    "callback_data": f"clip:ft_use:{item}:{number}"})
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # **มีการแก้ค้างอยู่ → โชว์แค่ บันทึก / ยกเลิก**
    #
    # ซ่อนปุ่มทางออก (อนุมัติ · ทำสตอรีบอร์ดใหม่) ไว้ก่อน เพราะกดตอนที่ยังไม่บันทึก
    # จะได้ผลจากจุดเด่นชุดเก่า ไม่ใช่ชุดที่เห็นอยู่ตรงหน้า — สับสนและผิดเงียบ
    if pending:
        rows.append([
            {"text": f"✅ บันทึก {len(draft['changes'])} การแก้",
             "callback_data": f"clip:ft_save:{item}:"},
            {"text": "↩️ ยกเลิก", "callback_data": f"clip:ft_cancel:{item}:"},
        ])
        return {"inline_keyboard": rows}

    rows.append([{"text": "🔄 คัดจุดเด่นใหม่ทั้งชุด",
                  "callback_data": f"clip:ft_new:{item}:"}])

    # ปุ่มทางออก — **แก้เสร็จแล้วต้องมีทางไปต่อ** (ผู้ใช้ทัก 23 ส.ค. 2026)
    #
    # ของเดิมมีแต่ปุ่มแก้ พอแก้เสร็จก็ตัน ต้องกลับไปพิมพ์ /pending เอง
    # ปุ่มที่ใส่ให้ต่างกันตามสถานะงาน เพราะ "ไปต่อ" ของแต่ละสถานะคนละเรื่อง
    job = next((j for j in clip_jobs.all()
                if str(j.get("item_id")) == str(item)
                and j.get("stage") in clip_queue.OPEN_STAGES), None)
    stage = (job or {}).get("stage")

    if stage == clip_queue.STAGE_IMAGE_REVIEW:
        # ยังไม่เคยทำสตอรีบอร์ด — กดผ่านใบงานได้เลยจากตรงนี้
        rows.append([{"text": "✅ ใช้จุดเด่นชุดนี้ → ทำสตอรีบอร์ดต่อ",
                      "callback_data": f"clip:sheet_ok:{job['id']}:"}])
    elif job:
        # อยู่ในคิวขั้นอื่นอยู่ — บอกให้ไปกดที่การ์ดของขั้นนั้น อย่าให้กดซ้อน
        rows.append([{"text": f"⏳ งานนี้อยู่ขั้น {clip_queue.STAGE_LABEL.get(stage, stage)}",
                      "callback_data": f"clip:pend:{job['id']}:"}])
    else:
        # จบไปแล้ว / ยังไม่มีในคิว — สร้างสตอรีบอร์ดใหม่จากจุดเด่นชุดนี้
        #
        # **นี่คือคำตอบของคำถามที่ว่า "แก้จุดเด่นแล้วสตอรีบอร์ดเปลี่ยนตามไหม"**
        # คำตอบคือไม่เปลี่ยนเอง — จุดเด่นถูกใช้ตอนทำสตอรีบอร์ดเท่านั้น
        # แก้ทีหลังจึงต้องสั่งทำใหม่ ปุ่มนี้คือที่สั่ง
        rows.append([{"text": "🎬 ทำสตอรีบอร์ดใหม่จากจุดเด่นชุดนี้",
                      "callback_data": f"clip:ft_sb:{item}:"}])

    # 🅿 พักไว้รอแก้ — ใบที่ยังอยู่ในคิวพักที่ใบงาน ใบที่จบไปแล้วพักที่ไฟล์งาน
    # (สองตัวคนละที่เก็บ ถ้าใช้ตัวเดียวปนกันจะหาใบงานไม่เจอแล้วปุ่มกดไม่ติดเงียบๆ)
    rows.append([{
        "text": "🅿 รอแก้",
        "callback_data": (f"clip:park:{job['id']}:" if job else f"clip:rpark::{item}"),
    }])
    return {"inline_keyboard": rows}


def _clip_features_edit(item_id: str, chat_id: str, action: str, arg: str,
                        message_id=0) -> str:
    """ปุ่มบนการ์ด /features — **สะสมการแก้ไว้ก่อน แล้วกดบันทึกครั้งเดียว**

    (ผู้ใช้สั่ง 23 ส.ค. 2026: "ผมลบจุดเด่น 3 เพิ่ม 6 7 8 เสร็จปุ๊บกดส่งครั้งเดียว")

    ของเดิมกดทีนึงเขียนไฟล์ทีนึงแล้วส่งการ์ดใหม่ทั้งใบ — แก้ 4 จุดได้การ์ด 4 ใบ
    และไฟล์ถูกเขียนทับ 4 รอบ ระหว่างทางข้อมูลอยู่ในสถานะครึ่งๆ กลางๆ ตลอด

    แบบใหม่แก้ลง **ที่พักในหน่วยความจำ** แล้วแก้ข้อความการ์ดใบเดิมให้เห็นผลทันที
    ไฟล์ถูกเขียนรอบเดียวตอนกดบันทึก
    """
    run = clip_store.load_run(DATA_DIR, item_id)
    if not run:
        return "ไม่พบงานนี้"
    features = list(run.get("features") or [])
    index = int(arg) - 1 if arg.isdigit() else -1
    key = _draft_key(chat_id, item_id)

    def show(note_text: str) -> str:
        draft = _feature_drafts.get(key)
        _edit_card(chat_id, message_id,
                   _clip_features_text(run, draft), _clip_features_buttons(run, draft))
        return note_text

    # ---------- บันทึกของที่สะสมไว้ ----------
    if action == "ft_save":
        draft = _feature_drafts.get(key)
        if not draft or not draft.get("changes"):
            # **ที่พักหายไป = เคยกดแก้แล้วระบบรีสตาร์ตกลางคัน**
            # ต้องบอกตรงๆ ไม่ใช่บันทึกของเก่าทับแล้วทำเหมือนสำเร็จ
            return "ไม่มีอะไรค้างให้บันทึก (ถ้าเพิ่งกดแก้ไว้ แปลว่าที่พักหาย — กดแก้ใหม่อีกครั้ง)"
        picked = list(draft["highlights"])
        count = len(draft["changes"])
        _clip_keep(lambda: clip_store.set_highlights(DATA_DIR, item_id, picked), "จุดเด่น")
        _drop_draft(chat_id, item_id)
        run = clip_store.load_run(DATA_DIR, item_id)
        _edit_card(chat_id, message_id,
                   _clip_features_text(run), _clip_features_buttons(run))
        return f"บันทึก {count} การแก้แล้ว"

    if action == "ft_cancel":
        had = bool(_feature_drafts.get(key, {}).get("changes"))
        _drop_draft(chat_id, item_id)
        _edit_card(chat_id, message_id,
                   _clip_features_text(run), _clip_features_buttons(run))
        return "ยกเลิกการแก้แล้ว" if had else "ไม่มีอะไรให้ยกเลิก"

    # ---------- คำสั่งที่ต้องบันทึกก่อนถึงจะทำได้ ----------
    # ทั้งสามอย่างนี้ทำงานกับ **ของที่บันทึกแล้ว** ถ้ามีของค้างในที่พักจะได้ผลจาก
    # ชุดเก่า ซึ่งไม่ตรงกับที่เห็นบนจอ — กันไว้ให้บันทึกก่อน
    if action in ("ft_new", "ft_sb", "ft_edit"):
        if _feature_drafts.get(key, {}).get("changes"):
            return "มีการแก้ค้างอยู่ — กด ✅ บันทึก ก่อน แล้วค่อยกดปุ่มนี้"

    if action == "ft_new":
        _clip_refresh_features(chat_id, item_id)
        return "คัดจุดเด่นใหม่ให้แล้ว"

    if action == "ft_sb":
        # สั่งทำสตอรีบอร์ดใหม่จากจุดเด่นชุดปัจจุบัน
        # **ของเดิมไม่ถูกลบ** — ตัวทำสตอรีบอร์ดเขียนทับเมื่อทำเสร็จเท่านั้น
        note = _clip_start_storyboard(chat_id, item_id)
        if note:
            return note
        clip_runner.wake()
        _clip_say(
            chat_id,
            "🎬 <b>เข้าคิวทำสตอรีบอร์ดใหม่แล้ว</b>\n"
            f"ใช้จุดเด่น {len(run.get('highlights') or [])} ข้อชุดปัจจุบัน · "
            "เสร็จแล้วจะส่งมาให้ตรวจอีกรอบ",
        )
        return "เข้าคิวทำสตอรีบอร์ดใหม่แล้ว"

    if action == "ft_edit":
        job = next((j for j in clip_jobs.all()
                    if str(j.get("item_id")) == str(item_id)
                    and j.get("stage") in PENDING_STAGES), None)
        if not job:
            return ("งานนี้ไม่ได้อยู่ในขั้นรอตรวจแล้ว พิมพ์แก้เองไม่ได้ — "
                    "ใช้ปุ่ม ➕ เลือกจากรายการ หรือ 🔄 คัดใหม่แทน")
        return _clip_edit_highlights(job["id"], chat_id, "hl_edit", arg)

    # ---------- แก้ลงที่พัก ----------
    draft = _get_draft(chat_id, item_id, run)
    highlights = draft["highlights"]

    if action == "ft_use":
        if not 0 <= index < len(features):
            return "ไม่มีข้อนั้นในรายการ"
        if len(highlights) >= CLIP_MAX_HIGHLIGHTS:
            return f"ใช้ครบ {CLIP_MAX_HIGHLIGHTS} ข้อแล้ว — ลบข้อที่ไม่เอาออกก่อน"
        picked = features[index]
        if picked.strip() in {x.strip() for x in highlights}:
            return "ข้อนี้ใช้อยู่แล้ว"
        highlights.append(picked)
        draft["changes"].append(f"เพิ่มข้อ {index + 1}")
        return show(f"เพิ่มข้อ {index + 1} · ยังไม่บันทึก")

    if action == "ft_del":
        if not 0 <= index < len(highlights):
            return "ข้อนั้นไม่มีแล้ว"
        if len(highlights) <= 1:
            return "เหลือข้อเดียว ลบไม่ได้ — จุดเด่นเป็นวัตถุดิบที่ส่งเข้า GPT"
        highlights.pop(index)
        draft["changes"].append(f"ลบข้อ {index + 1}")
        return show(f"ลบข้อ {index + 1} · ยังไม่บันทึก")

    return f"ไม่รู้จักปุ่ม {action}"


def _clip_features_text(run: dict, draft: dict | None = None) -> str:
    """ข้อความแสดงจุดขายทั้งหมด + 3 ข้อที่เลือก + เหตุผล

    โชว์รายการเต็มด้วย ไม่ใช่แค่ 3 ข้อ เพราะคนตรวจงานต้องเห็นว่า "ของที่ไม่ได้เลือก
    มีอะไรบ้าง" ถึงจะรู้ว่าเลือกถูกไหม — เห็นแต่ผลลัพธ์จะตรวจไม่ได้เลย
    """
    escape = telegram_bot._escape
    pending = list((draft or {}).get("changes") or [])
    highlights = list((draft or {}).get("highlights") or run.get("highlights") or [])
    features = run.get("features") or []
    why = [] if pending else (run.get("highlight_why") or [])

    head = "✨ <b>จุดเด่นที่เลือกมาใช้</b>"
    if pending:
        head = "📝 <b>กำลังแก้จุดเด่น — ยังไม่บันทึก</b>"
    lines = [f"{head} ({len(highlights)} ข้อ)"]
    for index, text in enumerate(highlights):
        lines.append(f"<b>{index + 1}.</b> {escape(text)}")
        if index < len(why) and why[index]:
            lines.append(f"     <i>เลือกเพราะ {escape(why[index])}</i>")
    if features:
        # รายการเต็มยาว 15+ ข้อ — พับไว้ แตะแล้วค่อยกาง ไม่งั้นดันของสำคัญตกจอ
        lines += ["", fold(
            f"📋 <b>จุดขายที่เจอทั้งหมด</b> {len(features)} ข้อ (แตะเพื่อกาง)",
            "\n".join(f"{i}. {escape(t)}" for i, t in enumerate(features, 1)),
        )]
    if pending:
        lines += ["", "📝 <b>ที่แก้ไว้ยังไม่ได้บันทึก</b>"]
        lines += ["  · " + escape(x) for x in pending]
        lines += ["", "กด <b>✅ บันทึก</b> เพื่อยืนยัน หรือ <b>↩️ ยกเลิก</b> ทิ้งทั้งหมด"]
        return "\n".join(lines)

    # เตือนเมื่อสตอรีบอร์ดที่ทำไว้ไม่ตรงกับจุดเด่นชุดปัจจุบันแล้ว
    #
    # จุดเด่นถูกใช้ตอนคุยกับ GPT ครั้งเดียว แก้ทีหลังไม่มีผลกับคลิปจนกว่าจะสั่งทำใหม่
    # ก่อนหน้านี้ความไม่ตรงกันนี้เงียบสนิท — แก้แล้วนึกว่าคลิปจะเปลี่ยนตาม
    stale = _storyboard_stale(run)
    if stale:
        lines += ["", f"⚠️ <b>สตอรีบอร์ดที่ทำไว้ยังใช้จุดเด่นชุดเก่า</b> ({escape(stale)})",
                  "ของที่ทำไว้แล้ว (ภาพ · คำสั่ง · บทพูด) <b>จะไม่เปลี่ยนตาม</b> "
                  "จนกว่าจะสั่งทำสตอรีบอร์ดใหม่"]
    return "\n".join(lines)


def _clip_recheck(chat_id: str, argument: str = "") -> None:
    """สั่งตรวจคลิปใหม่ — `/recheck` ทุกงานที่ยังไม่เคยตรวจ · `/recheck <รหัส|เลข>` งานเดียว

    **บังคับตรวจใหม่เสมอเมื่อระบุงานมา** เพราะคนพิมพ์คำสั่งนี้แปลว่าไม่เชื่อผลเดิม
    ส่วนแบบไม่ระบุจะข้ามงานที่ผลยังตรงกับไฟล์อยู่ ไม่ยิง Gemini ซ้ำฟรีๆ
    """
    escape = telegram_bot._escape
    runs = clip_store.list_runs(DATA_DIR)
    target = (argument or "").strip()

    if target:
        run = None
        if target.isdigit() and 1 <= int(target) <= len(runs):
            run = runs[int(target) - 1]
        else:
            run = clip_store.load_run(DATA_DIR, target) or None
        if not run:
            _clip_say(chat_id, f"ไม่พบงานที่ {escape(target)} — /clips ดูรายการ")
            return
        item_id = str(run.get("item_id") or "")
        try:
            _clip_check_videos(item_id, force=True)
        except Exception as error:                           # noqa: BLE001
            _clip_say(chat_id, f"❌ ตรวจไม่ได้: {escape(str(error))}")
            return
        _clip_say(chat_id, _clip_check_text(clip_store.load_run(DATA_DIR, item_id)))
        return

    todo = [r for r in runs if r.get("videos") and _clip_check_stale(r)]
    if not todo:
        with_video = sum(1 for r in runs if r.get("videos"))
        _clip_say(
            chat_id,
            f"✅ ตรวจครบแล้วทั้ง {with_video} คลิป — "
            "ดูผลได้ที่ /clips หรือสั่ง <code>/recheck &lt;รหัส&gt;</code> ให้ตรวจใหม่ทีละงาน",
        )
        return

    _clip_say(
        chat_id,
        f"🔍 กำลังตรวจ {len(todo)} คลิป "
        f"(ราว {int(len(todo) * (RECHECK_GAP + 3) / 60) + 1} นาที)…",
    )
    ok, bad, err = [], [], []
    for order, run in enumerate(todo):
        # เว้นจังหวะระหว่างคลิป — โควตา Gemini นับเป็น **ต่อนาที** ยิงรวดเร็วเกิน
        # จะโดน 429 แล้วต้องไปรอ 15/30/60 วิ ซึ่งช้ากว่าเว้นจังหวะไว้ตั้งแต่แรก
        # (วัดจริง 22 ส.ค.: ยิง 15 คลิปติดกันใน 27 วิ โดนตัดตั้งแต่คลิปที่ 4)
        if order:
            time.sleep(RECHECK_GAP)
        item_id = str(run.get("item_id") or "")
        name = (run.get("name") or item_id)[:36]
        try:
            result = _clip_check_videos(item_id, force=True)
        except Exception as error:                           # noqa: BLE001
            err.append(f"{name} — {error}")
            # โควตาวันนี้หมดแล้ว ใบที่เหลือก็หมดเหมือนกัน หยุดตรงนี้ดีกว่า
            # ไล่ยิงต่อจนครบแล้วได้ข้อความเดิมซ้ำสิบรอบ
            if "โควตา" in str(error):
                err.append(f"หยุดตรงนี้ — เหลืออีก {len(todo) - order - 1} ใบยังไม่ได้ตรวจ")
                break
            continue
        (ok if result.get("ok") else bad).append(
            f"{name} — {' / '.join(result.get('problems') or []) or 'ผ่าน'}")

    lines = [f"🔍 <b>ตรวจแล้ว {len(todo)} คลิป</b>", "",
             f"✅ ผ่านทั้งสองข้อ {len(ok)} · ⚠️ มีปัญหา {len(bad)} · ❌ ตรวจไม่ได้ {len(err)}"]
    if bad:
        lines += ["", "⚠️ <b>ที่ต้องดู</b>"] + ["  · " + escape(t) for t in bad[:15]]
    if err:
        lines += ["", "❌ <b>ตรวจไม่ได้</b>"] + ["  · " + escape(t) for t in err[:8]]
    for part in _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT):
        _clip_say(chat_id, part)


def _clip_list_done(chat_id: str) -> None:
    """งานที่ติ๊กว่า "ทำแล้ว" — แสดงเหมือน /clips ทุกอย่าง (ผู้ใช้สั่ง 22 ส.ค. 2026)

    ใช้ตัววาดรายการตัวเดียวกับ /clips (`_clip_render_runs`) ไม่เขียนซ้ำ เพราะถ้า
    แยกเขียน พอวันหลังเพิ่มข้อมูลในรายการหลัก รายการนี้จะขาดไปเงียบๆ
    """
    runs = clip_store.list_done(DATA_DIR)
    if not runs:
        _clip_say(
            chat_id,
            "ยังไม่มีงานที่ติ๊กว่าทำแล้ว — กด <b>✅ ทำแล้ว</b> ใน /clip เพื่อเก็บงานมาไว้ที่นี่",
        )
        return
    _clip_render_runs(chat_id, runs, "✅ <b>งานที่ทำแล้ว</b>", "/clipfb")


def _clips_in_bucket(bucket: str, runs: list[dict] | None = None) -> list[dict]:
    """งานที่รอลง **ปลายทางนั้น** — ใช้ร่วมกันทั้ง /clips, /clipsfb, /clipstiktok

    ผู้ใช้สั่ง 27 ส.ค. 2569 ให้แยกรายการตามปลายทาง:

        /clips        มีคลิปแล้ว รอลง Shopee Video
        /clipsfb      ลง Shopee แล้ว รอลง Facebook Reels
        /clipstiktok  ลง Facebook แล้ว รอลง TikTok

    **อ่านจากกระดานตัวเดียวกับหน้าเว็บ ไม่กรองเอง** (`clip_board.build`)
    เดิมกรองเองด้วย `bucket_of_run` ซึ่งดูแต่ไฟล์ในโฟลเดอร์ ไม่ดูใบงานในคิว
    วัดจริง 27 ส.ค. 2569: มี 2 ใบที่ **เจนคลิปเสร็จแล้วแต่ยังรออนุมัติคลิปอยู่**
    กระดานจัดไว้กอง 🎬 คลิป (ถูก — ยังกดลงไม่ได้) แต่ `/clips` นับเป็นพร้อมลง
    เลขสองที่จึงไม่ตรงกัน 23 กับ 25 แล้วไม่มีใครรู้ว่าฝั่งไหนถูก

    **งานที่พักไว้รอแก้ไม่นับ** — กระดานแยกใส่ถัง `parked` ให้แล้ว
    คนเปิดรายการนี้อยากได้ของที่ *กดลงได้เลย* ใบที่พักไว้ดูที่ /wait ของขั้นนั้น
    """
    rows = clip_store.list_runs(DATA_DIR) if runs is None else runs
    board = clip_board.build(
        clip_jobs.all(), lambda item: clip_store.load_run(DATA_DIR, item), rows)
    wanted = next((b for b in board["buckets"] if b["key"] == bucket), None)
    order = {str(r.get("item_id")): n for n, r in enumerate(wanted["jobs"] or [])}         if wanted else {}
    picked = [r for r in rows if str(r.get("item_id")) in order]
    picked.sort(key=lambda r: order[str(r.get("item_id"))])
    return picked


def _clips_ready(runs: list[dict] | None = None) -> list[dict]:
    """งานที่มีคลิปแล้วและยังไม่ได้ลง Shopee Video — รายการที่ `/clips` ใช้"""
    return _clips_in_bucket(clip_board.SHOPEE, runs)


# ---- รายการแยกตามปลายทาง (ผู้ใช้สั่ง 27 ส.ค. 2569) -------------------------
#
# แต่ละรายการมี **คำสั่งเปิดงานของตัวเอง** เพราะเลขลำดับเป็นคนละชุดกัน
# พิมพ์ `/clip 2` จากรายการ Facebook จะไปโดนสินค้าคนละตัว — เคยพลาดมาแล้ว
CLIP_LISTS = {
    "/clips": (clip_board.SHOPEE, "/clip",
               "🎬 <b>คลิปที่พร้อมลง Shopee Video</b>",
               "เจนคลิปเสร็จแล้วและยังไม่ได้ลง Shopee"),
    "/clipsfb": (clip_board.REELS, "/clipfb",
                 "📘 <b>คลิปที่พร้อมลง Facebook Reels</b>",
                 "ลง Shopee Video แล้วและยังไม่ได้ลง Facebook"),
    "/clipstiktok": (clip_board.TIKTOK, "/cliptiktok",
                     "🎵 <b>คลิปที่พร้อมลง TikTok</b>",
                     "ลง Facebook Reels แล้วและยังไม่ได้ลง TikTok"),
}


def _clip_list_bucket(chat_id: str, list_cmd: str) -> None:
    """วาดรายการของปลายทางหนึ่ง — ตัวเดียวใช้ได้ทั้งสามคำสั่ง"""
    bucket, open_cmd, title, need = CLIP_LISTS[list_cmd]
    everything = clip_store.list_runs(DATA_DIR)
    runs = _clips_in_bucket(bucket, everything)
    if not runs:
        # บอกด้วยว่าที่กรองออกไปมีเท่าไร ไม่งั้น "ว่าง" จะแยกไม่ออกจาก "พัง"
        parked = sum(1 for r in everything
                     if r.get("parked") and clip_board.bucket_of_run(r) == bucket)
        note = (f"มีงานเก็บไว้ทั้งหมด {len(everything)} ชิ้น "
                f"แต่ยังไม่มีชิ้นไหนที่ <b>{need}</b>"
                if everything else "ส่งลิงก์ Shopee มาได้เลย")
        if parked:
            note += f"\n🅿 มีอีก {parked} ชิ้นที่พักไว้รอแก้ — ดูที่ /wait"
        _clip_say(chat_id, f"{title} — <b>ยังไม่มีสักชิ้น</b>\n{note}")
        return
    _clip_render_runs(chat_id, runs, title, open_cmd, bucket)


def _clip_open_from_list(chat_id: str, list_cmd: str, argument: str) -> None:
    """`/clip <เลข>` `/clipfb <เลข>` `/cliptiktok <เลข>` — แปลงเลขเป็นรหัสสินค้า

    **ต้องแปลงจากรายการของคำสั่งนั้นเท่านั้น** เลขลำดับของสามรายการไม่ตรงกัน
    ใส่รหัสสินค้ามาตรงๆ ก็ได้ ไม่ต้องแปลง
    """
    target = (argument or "").strip()
    if not target:
        _clip_list_bucket(chat_id, list_cmd)
        return
    if target.isdigit():
        rows = _clips_in_bucket(CLIP_LISTS[list_cmd][0])
        index = int(target)
        if 1 <= index <= len(rows):
            _clip_show_run(chat_id, str(rows[index - 1].get("item_id", "")))
            return
        _clip_say(chat_id, f"รายการนี้มี {len(rows)} ชิ้น ไม่มีเลข {index} — "
                           f"พิมพ์ <code>{list_cmd}</code> ดูรายการก่อน")
        return
    _clip_show_run(chat_id, target)


def _clip_list_runs(chat_id: str) -> None:
    """`/clips` — เฉพาะงานที่มีคลิปแล้วและรอลง Shopee Video

    เหลือไว้เป็นทางเข้าเดิม ตัวจริงอยู่ที่ `_clip_list_bucket` ที่ใช้ร่วมกัน
    ทั้งสามปลายทาง — ห้ามเขียนวิธีวาดรายการซ้ำที่นี่
    """
    _clip_list_bucket(chat_id, "/clips")


def _clip_render_runs(chat_id: str, runs: list[dict], title: str, cmd: str,
                      target: str = "") -> None:
    """วาดรายการงาน — ใช้ร่วมกันทั้ง /clips และ /clipsfb

    `cmd` คือคำสั่งที่พิมพ์เปิดงานในรายการนั้น (`/clip` หรือ `/clipfb`) — ต้องแยก
    เพราะเลขลำดับของสองรายการไม่ตรงกัน พิมพ์ /clip 2 จากรายการงานที่ทำแล้วจะไป
    โดนสินค้าคนละตัว ส่วนปุ่มลัดใช้ callback เดียวกันได้เพราะผูกด้วยรหัสสินค้า
    """
    escape = telegram_bot._escape
    lines = [f"{title} {len(runs)} ชิ้น\n"]
    buttons = []
    for index, run in enumerate(runs, 1):
        # บอกให้ครบว่าชิ้นไหนมีอะไรบ้าง จะได้รู้ว่าอันไหนทำไม่จบโดยไม่ต้องเปิดดู
        marks = []
        marks.append(f"🖼{run.get('storyboard_count', 0)}" if run.get("storyboard") else "🖼—")
        marks.append(f"🎥{run.get('flow_prompt_count', 0)}" if run.get("flow_prompts") else "🎥—")
        if run.get("videos"):
            marks.append(f"▶️{len(run.get('videos') or [])}")
        if run.get("refused"):
            marks.append("⚠️โดนปฏิเสธ")
        # **รอลง ≠ ลงได้เดี๋ยวนี้** — คลิปเดียวกันต้องเว้นอย่างน้อย 1 วัน
        # ระหว่างแต่ละที่ (กติกาข้อ 2.8) ถ้าไม่บอก คนจะกดแล้วโดนปฏิเสธ
        # โดยไม่รู้ว่าเพราะอะไร แล้วคิดว่าปุ่มพัง
        if target:
            can, _why = publish_order.check(run, target)
            if not can:
                marks.append("⏳รอวันถัดไป")
        when = (run.get("storyboard_at") or run.get("product_at") or "")[5:16].replace("T", " ")
        lines.append(
            f"<b>{index}.</b> {escape(run.get('name', '')[:55])}\n"
            f"     {' '.join(marks)} · {escape(when)} · <code>{cmd} {index}</code>"
        )
        # ปุ่มลัด 8 ตัวแรก — เพดานเท่า /videos เพราะ Telegram ย่อปุ่มจนอ่านไม่ออก
        # ถ้าใส่มากกว่านี้ งานที่เหลือยังเปิดได้ด้วย /clip <เลข> ที่พิมพ์ไว้ให้แล้ว
        if len(buttons) < 8:
            buttons.append([{
                "text": f"📄 {index}. {(run.get('name') or '')[:24]}",
                "callback_data": f"clip:open::{run.get('item_id', '')}",
            }])
    if len(runs) > len(buttons):
        lines.append(f"\n(ปุ่มลัดแสดง {len(buttons)} อันแรก "
                     f"ที่เหลือพิมพ์ <code>{cmd} &lt;เลข&gt;</code>)")
    parts = _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT)
    for part in parts[:-1]:
        _clip_say(chat_id, part)
    _clip_say(chat_id, parts[-1], {"inline_keyboard": buttons} if buttons else None)


def _clip_show_run(chat_id: str, argument: str) -> None:
    """เปิดดูงานหนึ่งชิ้น — รับได้ทั้งเลขลำดับจาก /clips และรหัสสินค้า

    งานที่ติ๊กว่าทำแล้ว (ย้ายไป `shopee_products_done/`) เปิดดูได้ด้วยรหัสสินค้า
    เหมือนกัน — ปุ่มลัดใน /clipsfb ส่งรหัสมา แล้ว `load_run` หาให้ทั้งสองโฟลเดอร์
    """
    runs = clip_store.list_runs(DATA_DIR)
    argument = (argument or "").strip()
    run = None
    if argument.isdigit():
        # **เลขต้องนับจากรายการเดียวกับที่ /clips แสดง** ไม่ใช่รายการเต็ม
        # (แก้ 27 ส.ค. 2026 พร้อมกับตอนกรอง /clips — ไม่งั้นเลข 2 ไปโดนคนละตัว)
        ready = _clips_ready(runs)
        if 1 <= int(argument) <= len(ready):
            run = ready[int(argument) - 1]
    if run is None:
        # หาด้วยรหัสสินค้ายัง **หาได้จากทุกงาน** ไม่ใช่แค่ที่พร้อมลง
        # เพราะรหัสระบุตัวได้แน่นอนอยู่แล้ว ไม่มีทางกำกวมเหมือนเลขลำดับ
        run = next((r for r in runs if str(r.get("item_id")) == argument), None)
        # ไม่เจอในรายการหลัก = อาจเป็นงานที่เก็บไปแล้ว ลองหาในโฟลเดอร์ที่ทำแล้ว
        if run is None and argument:
            run = clip_store.load_run(DATA_DIR, argument) or None
    if not run:
        _clip_say(
            chat_id,
            f"ไม่พบงานที่ {telegram_bot._escape(argument)} — "
            "/clips ดูรายการ · /clipsfb ดูงานที่ทำแล้ว",
        )
        return

    escape = telegram_bot._escape
    folder = Path(run["folder"])
    token = load_clip_token() or ""

    for name in run.get("storyboard", []):
        path = folder / name
        if not path.is_file():
            continue
        try:
            telegram_bot.send_photo(token, chat_id, path, run.get("name", "")[:60])
        except telegram_bot.TelegramError as error:
            append_log("input", f"[บอทคลิป] ส่งสตอรีบอร์ดไม่ได้: {error}")

    # ①②③ ส่งแยกทีละก้อน ไม่รวมเป็นข้อความเดียว
    #
    # เหตุผล: ผู้ใช้เอาของสามอย่างนี้ไปทำต่อทีละอย่าง (ชื่อไปตั้งแคปชัน · ลิงก์ไปวาง
    # ในโพสต์ · คลิปไปอัปโหลด) ถ้ารวมก้อนเดียว การก๊อปจะติดหัวข้อกับของอย่างอื่น
    # มาด้วยทุกครั้ง ต้องมานั่งลบเอง — ห่อด้วย <code> เพราะ Telegram ให้แตะก้อน
    # เดียวแล้วก๊อปทั้งก้อนได้เลย ไม่ต้องลากเลือกทีละตัวอักษรบนมือถือ
    name_text = (run.get("name") or "").strip()
    _clip_say(
        chat_id,
        f"🛍 <b>ชื่อสินค้า</b>\n<code>{escape(name_text)}</code>"
        if name_text else "🛍 <b>ชื่อสินค้า</b>\n⚠️ งานนี้ไม่มีชื่อสินค้าเก็บไว้",
    )

    affiliate = (run.get("affiliate_url") or "").strip()
    _clip_say(
        chat_id,
        f"🔗 <b>ลิงก์ affiliate</b>\n<code>{escape(affiliate)}</code>"
        if affiliate else "🔗 <b>ลิงก์ affiliate</b>\n⚠️ งานนี้ไม่มีลิงก์ affiliate เก็บไว้",
    )

    # แฮชแท็ก 5 ตัว (ผู้ใช้สั่ง 22 ส.ค. 2026) — ทำตอนเจนคลิปเสร็จ
    tags = run.get("hashtags") or []
    tag_line = " ".join(f"#{tag}" for tag in tags)
    if tags:
        _clip_say(
            chat_id,
            f"🏷 <b>แฮชแท็ก</b> ({len(tags)} ตัว)\n<code>{escape(tag_line)}</code>",
        )
    else:
        _clip_say(
            chat_id,
            "🏷 <b>แฮชแท็ก</b>\n⚠️ งานนี้ยังไม่มี — กดปุ่ม 🏷 ด้านล่างให้สร้างได้",
        )

    # ก้อนรวม — Android ก๊อปได้ทีละก้อนเดียว (ก๊อปใหม่ทับของเก่าเสมอ) คนที่อยาก
    # ได้ทั้งชื่อ ลิงก์ และแท็กไปวางรวดเดียวจึงต้องมีก้อนที่รวมไว้แล้วให้แตะครั้งเดียว
    # ไม่งั้นต้องสลับแอปไปกลับสามรอบต่อสินค้าหนึ่งชิ้น
    if name_text or affiliate or tag_line:
        combined = "\n".join(part for part in (name_text, affiliate, tag_line) if part)
        _clip_say(
            chat_id,
            "📋 <b>ก๊อปรวดเดียว</b> (แตะที่ก้อนล่าง)\n"
            f"<code>{escape(combined)}</code>",
        )

    # ③ คลิป — ส่งไฟล์จริงมาเลย ไม่ให้ต้องกดปุ่มอีกทีก่อนถึงจะได้โหลด
    if run.get("videos"):
        note = _clip_send_videos(chat_id, str(run.get("item_id")))
        if note.startswith(("ไม่พบ", "งานนี้ยังไม่มี", "ส่งคลิปไม่สำเร็จ")):
            _clip_say(chat_id, f"🎥 <b>คลิป</b>\n⚠️ {escape(note)}")
        # ④ ผลตรวจแนบท้ายคลิป (ผู้ใช้สั่ง 22 ส.ค. 2026) — ยืนยันว่า 1080p จริง
        # และมีเสียงพูดจริง ก่อนเอาไปโพสต์ ไม่ต้องเปิดไฟล์ดูเองทุกใบ
        run = _clip_ensure_check(run)
        _clip_say(chat_id, _clip_check_text(run))
    else:
        _clip_say(chat_id, "🎥 <b>คลิป</b>\n⚠️ งานนี้ยังไม่มีคลิป")

    lines = []
    if run.get("highlights"):
        lines.append("✨ <b>คุณสมบัติเด่น</b>")
        lines += [f"   {i}. {escape(text)}" for i, text in enumerate(run["highlights"], 1)]
    if run.get("chat_url"):
        lines += ["", f"💬 แชท GPT: {escape(run['chat_url'])}"]
    if run.get("refused"):
        lines += ["", "⚠️ รอบนั้น ChatGPT ปฏิเสธการสร้างภาพ"]
    if lines:
        _clip_say(chat_id, "\n".join(lines))

    # ส่ง **บทพูด** ไม่ส่งคำสั่งเจนวิดีโอ — คำสั่งยาวและเป็นศัพท์เทคนิค
    # เก็บไว้ในเครื่องแล้วดูในแท็บ 🎬 สตอรีบอร์ด บนหน้าเว็บได้ถ้าอยากอ่าน
    script = run.get("script") or []
    if script:
        body = fold(
            f"🗣 <b>บทพูดในคลิป</b> ({len(script)} ฉาก · แตะเพื่อกาง)",
            "\n".join(f"<b>{i}.</b> {escape(text)}" for i, text in enumerate(script, 1)),
        )
        for part in _split_text(body, TELEGRAM_TEXT_LIMIT):
            _clip_say(chat_id, part)
    else:
        _clip_say(chat_id, "⚠️ งานนี้ยังไม่มีบทพูดเก็บไว้")

    # ปุ่มเดินต่อ — งานที่หยุดไว้ตอนขั้นเจนปิดอยู่ กดตรงนี้ทำต่อได้เลย
    # ไม่ต้องส่งลิงก์ใหม่และไม่ต้องคุยกับ GPT ซ้ำ
    count = run.get("flow_prompt_count") or 0
    videos = run.get("videos") or []
    item_id = run.get("item_id", "")
    rows = []
    # ส่งคลิปไปแล้วข้างบน ปุ่มนี้ไว้เรียกซ้ำตอนเลื่อนแชทหาย
    if videos:
        rows.append([{
            "text": f"▶️ ส่งคลิปอีกครั้ง ({len(videos)} ไฟล์)",
            "callback_data": f"clip:vid::{item_id}",
        }])
    if count:
        rows.append([{
            "text": f"🎬 เจนคลิปจากงานนี้ ({count} ฉาก)",
            "callback_data": f"clip:gen::{item_id}",
        }])
    # 🏷 งานที่เจนคลิปไว้ก่อนวันที่เพิ่มขั้นทำแท็ก (22 ส.ค.) ยังไม่มีแท็กติดมา
    # ให้สั่งทำย้อนหลังได้ ไม่ต้องเจนคลิปใหม่ทั้งงานเพื่อให้ได้แค่แท็ก
    rows.append([{
        "text": "🏷 ทำแฮชแท็กใหม่" if tags else "🏷 สร้างแฮชแท็ก",
        "callback_data": f"clip:tags::{item_id}",
    }])
    # 🚀 ลง Facebook Reels + 🅿 รอแก้ — **ต้องมีในใบงานหลักด้วย** (ผู้ใช้สั่ง
    # 27 ส.ค. 2569: *"เพิ่มลงในใบงานหลักด้วย"*) จะได้ไม่ต้องย้อนไปเปิด /clipsfb
    # ปุ่มขึ้นเฉพาะงานที่มีคลิปแล้ว — ไม่มีคลิปก็ไม่มีอะไรให้ลง
    if videos:
        rows.append([{
            "text": "🚀 ลง Facebook Reels",
            "callback_data": f"clip:fbcard::{item_id}",
        }])
        # ❌ **ไม่ใส่ปุ่มติ๊กตรงนี้** — ปุ่ม "✅ ลง … แล้ว" ข้างล่างทำหน้าที่นี้แล้ว
        # ผมเคยใส่ไว้ตอนแรกแล้วกลายเป็นปุ่มสองอันข้อความเกือบเหมือนกัน
        # อยู่ติดกันในใบงานเดียว เจ้าของเห็นแล้วสั่งให้เอาออก (27 ส.ค. 2569)
    # 🅿 พักไว้รอแก้ — งานที่ออกจากคิวไปแล้วก็ต้องพักได้ ไม่ใช่เฉพาะใบในคิว
    rows.append([{
        "text": "↩️ เอากลับจากรอแก้" if run.get("parked") else "🅿 รอแก้",
        "callback_data": (f"clip:runpark::{item_id}" if run.get("parked")
                          else f"clip:rpark::{item_id}"),
    }])
    # ✅ ติ๊กว่าทำแล้ว — ต้องมีทุกงาน ไม่ใช่เฉพาะงานที่มีคลิป เพราะงานที่ตัดสินใจ
    # ว่าไม่เอาแล้วก็ต้องเก็บออกจากรายการได้เหมือนกัน
    # ป้ายต้องบอกตรงกับสิ่งที่มันทำ — กดแล้วเลื่อนไปรอลงที่ถัดไป
    # ไม่ใช่ "เก็บออกจากรายการ" อีกต่อไป (เว้นตอนลงครบสามที่แล้ว)
    _nxt = publish_order.next_target(run)
    rows.append([{
        "text": (f"✅ ลง {POSTED_LABEL.get(_nxt, _nxt)} แล้ว" if _nxt
                 else "✅ ลงครบแล้ว เก็บออกจากรายการ"),
        "callback_data": f"clip:done::{item_id}",
    }])
    note = []
    if videos:
        note.append(f"▶️ มีคลิปเก็บไว้ <b>{len(videos)} ไฟล์</b>")
    if count:
        note.append(f"🎥 มีคำสั่งเจนวิดีโอเก็บไว้ <b>{count} ฉาก</b>")
    note.append("กด <b>✅ ทำแล้ว</b> เมื่อโพสต์เสร็จ — งานจะหายจากรายการ (กดกลับได้)")
    _clip_say(chat_id, "\n".join(note), {"inline_keyboard": rows})


def _clip_send_videos(chat_id: str, item_id: str) -> str:
    """ส่งคลิปของงานนั้นเข้าแชท — เปิดดูย้อนหลังได้ทุกเมื่อ ไม่ต้องรอขั้นอนุมัติ

    คลิปที่เจนเสร็จแล้วเคยดูได้แค่ตอนบอทส่งมาให้อนุมัติรอบเดียว พอกดผ่านไปแล้ว
    ก็หาย ต้องไปเปิดไฟล์ในเครื่องเอง — ตัวนี้ทำให้เรียกกลับมาดูได้เรื่อยๆ
    """
    run = clip_store.load_run(DATA_DIR, item_id)
    if not run:
        return "ไม่พบงานนี้"
    videos = run.get("videos") or []
    if not videos:
        return "งานนี้ยังไม่มีคลิป"

    token = load_clip_token() or ""
    folder = Path(run["folder"])
    name = telegram_bot._escape((run.get("name") or "")[:90])
    sent, failed = 0, []
    for index, item in enumerate(videos, 1):
        path = folder / item
        caption = (f"🎬 <b>{name}</b>"
                   + (f" · คลิปที่ {index}/{len(videos)}" if len(videos) > 1 else ""))
        try:
            telegram_bot.send_video(token, chat_id, path, caption)
            sent += 1
        except telegram_bot.TelegramError as error:
            failed.append(f"{item}: {error}")
            append_log("input", f"[บอทคลิป] ส่งคลิป {item} ไม่ได้: {error}")

    if failed:
        _clip_say(
            chat_id,
            f"⚠️ ส่งคลิปไม่ได้ {len(failed)} ไฟล์\n"
            + "\n".join(f"  • {telegram_bot._escape(text)}" for text in failed[:5]),
        )
    return f"ส่งคลิปแล้ว {sent} ไฟล์" if sent else "ส่งคลิปไม่สำเร็จ"


def _clip_video_list(chat_id: str) -> None:
    """รายการงานที่**มีคลิปแล้ว** พร้อมปุ่มกดเรียกคลิปมาดู

    เลขที่แสดงเป็นเลขเดียวกับ /clips เพื่อให้พิมพ์ /video <เลข> ได้ตรงกัน
    (เหตุผลเดียวกับ /storyboard — ไล่เลขใหม่แล้วผู้ใช้จะกดไปโดนสินค้าคนละตัว)
    """
    runs = clip_store.list_runs(DATA_DIR)
    have = [(index, run) for index, run in enumerate(runs, 1) if run.get("videos")]
    if not have:
        _clip_say(
            chat_id,
            "ยังไม่มีคลิปที่เจนเสร็จ — <code>/genall</code> ไล่เจนงานที่พร้อมแล้ว"
            if runs else "ยังไม่มีงานที่เก็บไว้",
        )
        return

    escape = telegram_bot._escape
    lines = [f"🎬 <b>คลิปที่เจนไว้แล้ว</b> {len(have)} ชิ้น\n"]
    buttons = []
    for index, run in have:
        count = len(run.get("videos") or [])
        when = (run.get("video_at") or "")[5:16].replace("T", " ")
        lines.append(
            f"<b>{index}.</b> {escape((run.get('name') or '')[:55])}\n"
            f"     🎥 {count} ไฟล์ · {escape(when)} · <code>/video {index}</code>"
        )
        if len(buttons) < 8:
            buttons.append([{
                "text": f"▶️ {index}. {(run.get('name') or '')[:24]}",
                "callback_data": f"clip:vid::{run.get('item_id', '')}",
            }])

    lines.append("\nกดปุ่มหรือพิมพ์ <code>/video &lt;เลข&gt;</code> เพื่อให้ส่งคลิปมาดู")
    parts = _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT)
    for part in parts[:-1]:
        _clip_say(chat_id, part)
    _clip_say(chat_id, parts[-1], {"inline_keyboard": buttons} if buttons else None)


def _clip_send_video_by_index(chat_id: str, argument: str) -> None:
    """/video <เลข> — รับได้ทั้งเลขลำดับจาก /clips และรหัสสินค้า เหมือน /clip"""
    runs = clip_store.list_runs(DATA_DIR)
    target = (argument or "").strip()
    if not target:
        _clip_video_list(chat_id)
        return
    run = None
    if target.isdigit() and 1 <= int(target) <= len(runs):
        run = runs[int(target) - 1]
    else:
        run = next((r for r in runs if str(r.get("item_id")) == target), None)
    if not run:
        _clip_say(chat_id, "ใช้ <code>/video &lt;เลขจาก /clips&gt;</code> — /videos ดูรายการที่มีคลิป")
        return
    note = _clip_send_videos(chat_id, str(run.get("item_id")))
    if note.startswith(("ไม่พบ", "งานนี้ยังไม่มี")):
        _clip_say(chat_id, f"⚠️ {note}")


def _clip_start_storyboard(chat_id: str, item_id: str) -> str:
    """เอางานที่ดึงสินค้าไว้แล้ว มาเข้าคิวทำสตอรีบอร์ด (ไม่ต้องส่งลิงก์ใหม่)"""
    run = clip_store.load_run(DATA_DIR, item_id)
    if not run:
        return "ไม่พบงานนี้"
    if not (run.get("images") and run.get("highlights")):
        return "งานนี้ยังไม่มีรูปหรือจุดเด่นครบ"
    for job in clip_jobs.waiting():
        if str(job.get("item_id")) == str(item_id):
            return f"อยู่ในคิวอยู่แล้ว ({clip_queue.STAGE_LABEL.get(job.get('stage'), '')})"

    job = clip_jobs.add(run.get("affiliate_url") or run.get("product_url") or "", chat_id)
    clip_jobs.update(
        job["id"], item_id=item_id, name=(run.get("name") or "")[:80],
        images_ok=True, highlights_ok=True,
        stage=clip_queue.STAGE_READY_STORYBOARD,
    )
    return ""


def _main_server_up(timeout: float = 3.0) -> bool:
    """เซิร์ฟเวอร์หลัก (8866) ยังตอบอยู่ไหม

    404 ก็ถือว่าตอบ — เราถามแค่ว่า "มีใครรับสายไหม" ไม่ได้สนใจว่าเส้นทางนั้นมีจริง
    (เคยพลาดมาแล้ว: เช็คด้วย urlopen('/') แล้วได้ 404 เลยรายงานว่าเซิร์ฟเวอร์ดับ
    ทั้งที่มันทำงานปกติ)
    """
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{MAIN_PORT}/", timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:                                            # noqa: BLE001
        return False


def _clip_health(chat_id: str, argument: str) -> None:
    """สถานะรวมของทุกสาย — ตอบได้ทันที ไม่ต้องเปิดเบราว์เซอร์

    **ทำไมต้องมี** เซิร์ฟเวอร์เคยดับเงียบสองครั้งในสัปดาห์เดียว และวิธีเดียวที่
    รู้คือพิมพ์คำสั่งแล้วบอทไม่ตอบ — ซึ่งรู้ก็ต่อเมื่อบังเอิญไปสั่งอะไรพอดี
    มีคำสั่งถามตรงๆ ได้ดีกว่านั่งเดา

    `/health สด` = ไปเปิด Flow เช็คของจริงด้วย (ช้ากว่า ~15 วิ แต่ไม่เสียเครดิต)
    """
    live = argument.strip().lower() in ("สด", "live", "full", "เต็ม")

    jobs = clip_jobs.all()
    counts: dict[str, int] = {}
    for job in jobs:
        counts[str(job.get("stage"))] = counts.get(str(job.get("stage")), 0) + 1
    open_now = sum(n for s, n in counts.items() if s in clip_queue.OPEN_STAGES)
    failed = counts.get(clip_queue.STAGE_FAILED, 0)
    working = clip_runner.busy          # เป็น property ไม่ใช่เมธอด

    main_ok = _main_server_up()
    credits, age = known_credits()
    account = str(shared.read_config().get("flow_account") or "ยังไม่ได้ตั้ง")

    lines = ["🩺 <b>สถานะระบบ</b>", ""]
    lines.append(f"{'✅' if main_ok else '❌'} เซิร์ฟเวอร์หลัก (8866) "
                 f"{'ตอบปกติ' if main_ok else '<b>ไม่ตอบ</b>'}")
    lines.append(f"✅ สายคลิป ({PORT}) ตอบปกติ — คุณกำลังคุยกับมันอยู่")
    lines.append(f"{'🔄' if working else '💤'} ตัวเดินคิว: "
                 f"{'กำลังทำงานอยู่' if working else 'ว่าง'}")
    lines += ["", f"📋 งานทั้งหมด {len(jobs)} ชิ้น · ค้างอยู่ในสาย {open_now}"]
    if failed:
        lines.append(f"⚠️ ล้มค้างไว้ {failed} ชิ้น — <code>/failed</code> ดูรายการ")
    lines += ["", f"🎥 ขั้นเจน Flow: <b>{'เปิด' if flow_enabled() else 'ปิด'}</b>"]
    lines.append(f"👤 บัญชี: <code>{telegram_bot._escape(account)}</code>")
    if credits is None:
        lines.append("💳 เครดิต: ยังไม่เคยอ่านได้ — <code>/credits สด</code>")
    else:
        lines.append(f"💳 เครดิต: <b>{credits:,}</b> (อ่านเมื่อ {_age_text(age)})")

    if live:
        _clip_say(chat_id, "\n".join(lines) + "\n\n🔄 กำลังเช็ค Flow ของจริง…")
        result = _clip_flow_probe(want_credits=True)
        mark = {True: "✅", False: "❌", None: "⏳"}[result["ok"]]
        extra = f"{mark} Flow: {telegram_bot._escape(result['detail'])}"
        if result.get("credits") is not None:
            extra += f"\n💳 เครดิตจริงตอนนี้: <b>{result['credits']:,}</b>"
        _clip_say(chat_id, extra)
        return

    lines += ["", "<code>/health สด</code> = เช็ค Flow ของจริงด้วย (ไม่เสียเครดิต)"]
    _clip_say(chat_id, "\n".join(lines))


def _clip_retry_job(job_id: str, source: str = "แชท") -> str:
    """เอางานที่ล้ม/ยกเลิกกลับเข้าคิว โดย **ไม่ทำซ้ำขั้นที่ทำสำเร็จไปแล้ว**

    ทำใหม่ตั้งแต่ต้นทุกครั้งคือเผาเวลาและเครดิตฟรี — มีคำสั่ง Flow อยู่แล้วก็ไป
    เริ่มที่ขั้นเจนเลย มีรูปแล้วก็ไปเริ่มที่ขั้นทำสตอรีบอร์ด

    **ตัวเดียวที่ทั้งหน้าเว็บและบอทเรียก** ถ้าแยกกันเขียนสองที่ วันหนึ่งจะเริ่ม
    ทำไม่เหมือนกันแล้วผู้ใช้ได้ผลต่างกันตามว่าสั่งจากไหน

    คืนคำอธิบายว่าจะไปเริ่มที่ขั้นไหน · โยน ValueError ถ้าสั่งไม่ได้
    """
    job = clip_jobs.get(job_id)
    if not job:
        raise ValueError("ไม่พบงานนี้")
    if job.get("stage") in clip_queue.OPEN_STAGES:
        raise ValueError("งานนี้ยังไม่จบ ไม่ต้องสั่งใหม่")

    run = clip_store.load_run(DATA_DIR, job.get("item_id", "")) or {}
    if run.get("flow_prompts"):
        stage, what = clip_queue.STAGE_READY_FLOW, "เริ่มที่ขั้นเจนคลิป"
    elif run.get("images"):
        stage, what = clip_queue.STAGE_READY_STORYBOARD, "เริ่มที่ขั้นทำสตอรีบอร์ด"
    else:
        stage, what = clip_queue.STAGE_QUEUED, "เริ่มใหม่ตั้งแต่ดึงสินค้า"

    clip_jobs.update(job_id, stage=stage, error="", note=f"สั่งใหม่จาก{source} — {what}")
    clip_runner.wake()
    _clip_log(f"สั่งงาน {job_id} ใหม่จาก{source} — {what}")
    return what


def _failed_jobs() -> list[dict]:
    """งานที่ล้ม/ยกเลิก เรียงใหม่สุดขึ้นก่อน — ใช้ลำดับนี้ที่เดียวทั้ง /failed และ /retry

    เหตุผลเดียวกับ /clips: ถ้าสองคำสั่งไล่เลขคนละแบบ ผู้ใช้อ่านเลขจากอันหนึ่ง
    แล้วพิมพ์ใส่อีกอันจะไปโดนงานคนละตัว
    """
    stages = (clip_queue.STAGE_FAILED, clip_queue.STAGE_CANCELLED)
    return [job for job in reversed(clip_jobs.all()) if job.get("stage") in stages]


# ช่องรอแก้ **แยกตามขั้น** (ผู้ใช้สั่ง 27 ส.ค. 2569)
#
# *"งานพักให้แยกแต่ละขั้น เช่น พักตอนรอลง shopee = /waitclips"*
#
# ชื่อคำสั่งจงใจให้ล้อกับรายการปกติ — จำได้ง่ายกว่าเพราะเป็นคู่กัน
#     /clips → /waitclips  ·  /clipsfb → /waitclipsfb  ·  /clipstiktok → /waitclipstiktok
WAIT_LISTS = {
    "/waitlink": (clip_board.LINK, "🐣 ดึงข้อมูล"),
    "/waitstoryboard": (clip_board.STORY, "🎨 สตอรีบอร์ด + บทพูด"),
    "/waitclip": (clip_board.CLIP, "🎬 คลิป"),
    "/waitclips": (clip_board.SHOPEE, "🛍 รอลง Shopee Video"),
    "/waitclipsfb": (clip_board.REELS, "📘 รอลง Facebook Reels"),
    "/waitclipstiktok": (clip_board.TIKTOK, "🎵 รอลง TikTok"),
}


def _clip_parked_all() -> list[dict]:
    """ใบที่พักไว้ **ทั้งสองที่เก็บ** — ใบงานในคิว + ไฟล์งานที่จบจากคิวไปแล้ว

    **ต้องรวมกัน ไม่งั้นช่องรอแก้จะเห็นแค่ครึ่งเดียว** งานขั้นโพสต์ออกจากคิว
    ไปแล้วทุกใบ (เจนคลิปจบ = จบงาน) ถ้าอ่านแต่คิว กด 🅿 ที่การ์ด Facebook แล้ว
    ใบนั้นจะหายไปเฉยๆ ไม่โผล่ใน /wait เลย

    ใบจากไฟล์งานไม่มีรหัสงานในคิว จึงใส่ `item_id` ไว้ให้ปุ่มใช้แทน
    """
    rows = list(clip_jobs.parked())
    seen = {str(r.get("item_id")) for r in rows}
    for run in clip_store.list_runs(DATA_DIR):
        item_id = str(run.get("item_id") or "")
        if not run.get("parked") or not item_id or item_id in seen:
            continue
        park = run.get("parked") or {}
        rows.append({
            "id": "",                       # ไม่มีใบงานในคิว — ปุ่มใช้ item_id แทน
            "item_id": item_id,
            "name": run.get("name") or item_id,
            "stage": park.get("from") or clip_board.bucket_of_run(run),
            "parked": park,
        })
    return rows


def _clip_wait_list(chat_id: str, argument: str = "",
                    only: str = "") -> None:
    """`/wait` — งานที่พักไว้รอแก้ทั้งหมด พร้อมปุ่มเอากลับเข้าขั้นเดิม

    ผู้ใช้สั่ง 27 ส.ค. 2026: *"ฟังก์ชั่นรอแก้ ให้ลิ้งไปที่คำสั่ง /wait ใน telegram
    เวลาเรียกดู"* — หน้าเว็บกับแชทจึงต้องเห็นรายการเดียวกัน ไม่ใช่คนละชุด

    `/wait <เลข>` = เอาใบนั้นกลับเข้าขั้นเดิมเลย · `/wait all` = เอากลับทั้งหมด
    """
    escape = telegram_bot._escape
    rows_all = _clip_parked_all()
    # `only` = ดูเฉพาะขั้นเดียว (มาจาก /waitclips ฯลฯ) — กรองก่อนนับทุกอย่าง
    # ไม่งั้นเลขที่พิมพ์กับเลขในรายการจะคนละชุด แล้วกดไปโดนใบอื่น
    if only:
        rows_all = [r for r in rows_all
                    if (clip_board.parked_by_bucket([r]) or [{}])[0].get("key") == only]
    target = (argument or "").strip().lower()

    if target:
        picked: list[dict] = []
        if target in ("all", "ทั้งหมด"):
            picked = list(rows_all)
        elif target.isdigit() and 1 <= int(target) <= len(rows_all):
            picked = [rows_all[int(target) - 1]]
        elif any(g["key"] == target for g in clip_board.parked_by_bucket(rows_all)):
            # `/wait images` = เอากลับทั้งกลุ่มเดียว (ผู้ใช้สั่งแยกกลุ่ม 27 ส.ค.)
            # มีประโยชน์ตอนแก้เสร็จทั้งกอง เช่นหารูปมาเพิ่มครบแล้วทุกใบ
            picked = next(g["jobs"] for g in clip_board.parked_by_bucket(rows_all)
                          if g["key"] == target)
        else:
            keys = " · ".join(g["key"] for g in clip_board.parked_by_bucket(rows_all))
            _clip_say(chat_id,
                      f"ไม่มีใบที่ {escape(target)} ในช่องรอแก้\n"
                      f"ใส่ได้: เลขใบ · <code>all</code>"
                      + (f" · ชื่อกลุ่ม ({escape(keys)})" if keys else "")
                      + "\nพิมพ์ /wait เฉยๆ ดูรายการก่อน")
            return
        done = []
        for job in picked:
            # ใบที่จบจากคิวไปแล้วไม่มีรหัสงาน ต้องเอากลับที่ไฟล์งานแทน
            if not job.get("id"):
                try:
                    clip_store.unpark_run(DATA_DIR, str(job.get("item_id") or ""))
                except clip_store.ClipStoreError:
                    continue
                done.append(str(job.get("stage") or ""))
                continue
            try:
                fresh = clip_jobs.unpark(job["id"])
            except clip_queue.ClipQueueError:
                continue
            done.append(clip_queue.STAGE_LABEL.get(fresh.get("stage") or "",
                                                   fresh.get("stage") or ""))
        clip_runner.wake()
        _clip_log(f"เอางานออกจากช่องรอแก้ {len(done)} ใบ")
        _clip_say(chat_id, f"↩️ เอากลับเข้าขั้นเดิมแล้ว <b>{len(done)}</b> ใบ "
                           f"— ระบบจะทำต่อให้เอง")
        return

    if not rows_all:
        head = next((t for c, (k, t) in WAIT_LISTS.items() if k == only), "")
        _clip_say(chat_id, f"✅ ไม่มีงานพักรอแก้ในขั้น {head}" if head
                  else "✅ ไม่มีงานพักรอแก้เลย — ช่อง 🅿️ รอแก้ว่างอยู่")
        return

    # **แยกกลุ่มตามชนิดของการแก้** (ผู้ใช้สั่ง 27 ส.ค. 2026)
    # ใช้ตัวจัดกลุ่มตัวเดียวกับหน้าเว็บ (`clip_board.parked_by_bucket`) ห้ามจัดเองซ้ำ
    # ไม่งั้นวันหนึ่งแชทกับหน้าเว็บจะบอกไม่ตรงกันแล้วไม่มีใครรู้ว่าอันไหนถูก
    groups = clip_board.parked_by_bucket(rows_all)
    head = next((t for c, (k, t) in WAIT_LISTS.items() if k == only), "")
    lines = [f"🅿️ <b>พักไว้รอแก้ {len(rows_all)} ใบ</b>"
             + (f" · เฉพาะ {head}" if head else f" · ค้างอยู่ {len(groups)} ขั้น"),
             "เครื่องไม่แตะใบพวกนี้ ของที่ทำไว้แล้วยังอยู่ครบ"]
    buttons = []
    index = 0
    last_fix = ""
    for group in groups:
        lines += ["", f"━━ {group['title']} · {group['count']} ใบ ━━"]
        last_fix = ""
        for job in group["jobs"]:
            # หัวข้อย่อยตามชนิดการแก้ — โผล่เมื่อเปลี่ยนชนิดเท่านั้น ไม่ซ้ำทุกบรรทัด
            came = (job.get("parked") or {}).get("from") or job.get("stage") or ""
            gkey = clip_board.fix_group_of(came)
            if gkey != last_fix:
                title, hint = clip_board.fix_group_meta(gkey)
                lines.append(f"  <b>{title}</b> — <i>{escape(hint)}</i>")
                last_fix = gkey
            index += 1
            if index > 20:
                continue
            name = str(job.get("name") or job.get("link") or job.get("id"))[:42]
            park = job.get("parked") or {}
            why = str(park.get("why") or "ไม่ได้บอกเหตุผล")[:70]
            when = str(park.get("at") or "")[5:16].replace("T", " ")
            lines.append(f"{index}. {escape(name)}")
            lines.append(f"    <i>{escape(why)}"
                         + (f" · พักไว้ {escape(when)}" if when else "") + "</i>")
            if len(buttons) < 8:
                buttons.append([{
                    "text": f"↩️ {index}. {name[:22]}",
                    # ใบในคิวเอากลับที่ใบงาน · ใบที่จบไปแล้วเอากลับที่ไฟล์งาน
                    "callback_data": (f"clip:unpark:{job['id']}" if job.get("id")
                                      else f"clip:runpark::{job.get('item_id')}"),
                }])
        # ปุ่มเอากลับทั้งกลุ่ม — แก้เสร็จทั้งกองแล้วกดทีเดียวจบ
        if len(buttons) < 10 and group["count"] > 1:
            buttons.append([{
                "text": f"↩️ เอากลับทั้ง {group['title']} ({group['count']})",
                "callback_data": f"clip:unpkg:{group['key']}:",
            }])
    if index > 20:
        lines.append(f"\n…และอีก {index - 20} ใบ")
    keys = " · ".join(g["key"] for g in groups)
    lines += ["", "เอากลับด้วย <code>/wait &lt;เลข&gt;</code> · "
                  f"ทั้งกลุ่ม <code>/wait &lt;ชื่อกลุ่ม&gt;</code> ({escape(keys)})",
              "ทั้งหมด <code>/wait all</code> — กลับเข้า<b>ขั้นเดิมที่ค้างไว้</b> ไม่ได้เริ่มใหม่"]
    keyboard = {"inline_keyboard": buttons} if buttons else None
    parts = _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT)
    for index, part in enumerate(parts):
        _clip_say(chat_id, part, keyboard if index == len(parts) - 1 else None)


def _clip_failed_list(chat_id: str) -> None:
    """รายการงานที่ล้ม พร้อมเหตุผล และปุ่มสั่งทำต่อ"""
    jobs = _failed_jobs()
    if not jobs:
        _clip_say(chat_id, "✅ ไม่มีงานที่ล้มหรือถูกยกเลิกค้างอยู่")
        return

    escape = telegram_bot._escape
    lines = [f"⚠️ <b>งานที่ล้ม/ยกเลิก {len(jobs)} ชิ้น</b>", ""]
    rows = []
    for index, job in enumerate(jobs[:20], 1):
        name = str(job.get("name") or job.get("link") or job.get("id"))[:42]
        label = "ยกเลิก" if job.get("stage") == clip_queue.STAGE_CANCELLED else "ล้ม"
        why = str(job.get("error") or job.get("note") or "ไม่ได้บอกเหตุผล")[:70]
        lines.append(f"{index}. {escape(name)}")
        lines.append(f"    <i>{label} — {escape(why)}</i>")
        if len(rows) < 8:
            rows.append([{
                "text": f"🔄 {index}. {name[:22]}",
                "callback_data": f"clip:again:{job.get('id')}",
            }])
    if len(jobs) > 20:
        lines.append(f"…และอีก {len(jobs) - 20} ชิ้น")
    lines += ["", "สั่งทำต่อด้วย <code>/retry &lt;เลข&gt;</code> "
                  "(<code>/retry all</code> = ทุกชิ้น)",
              "ทำ<b>ต่อจากขั้นที่ค้าง</b> ไม่ได้เริ่มใหม่ทั้งหมด"]
    keyboard = {"inline_keyboard": rows} if rows else None
    parts = _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT)
    for index, part in enumerate(parts):
        # ปุ่มติดกับข้อความก้อนสุดท้ายเท่านั้น ไม่งั้นปุ่มชุดเดียวกันโผล่ซ้ำทุกก้อน
        _clip_say(chat_id, part, keyboard if index == len(parts) - 1 else None)


def _clip_retry(chat_id: str, argument: str) -> None:
    """สั่งงานที่ล้มให้ทำต่อ — รับเลขจาก /failed หรือ id ตรงๆ หรือ all"""
    want = argument.strip().lower()
    if not want:
        _clip_failed_list(chat_id)
        return

    jobs = _failed_jobs()
    if not jobs:
        _clip_say(chat_id, "✅ ไม่มีงานที่ล้มค้างอยู่")
        return

    if want in ("all", "ทั้งหมด", "หมด"):
        targets = jobs
    elif want.isdigit() and 1 <= int(want) <= len(jobs):
        targets = [jobs[int(want) - 1]]
    else:
        found = next((j for j in jobs if str(j.get("id")) == argument.strip()), None)
        if not found:
            _clip_say(
                chat_id,
                f"ไม่รู้จัก <code>{telegram_bot._escape(argument.strip()[:30])}</code> — "
                f"ใส่เลข 1–{len(jobs)} จาก /failed หรือ <code>/retry all</code>",
            )
            return
        targets = [found]

    escape = telegram_bot._escape
    done, failed = [], []
    for job in targets:
        name = str(job.get("name") or job.get("id"))[:42]
        try:
            what = _clip_retry_job(str(job.get("id")), "แชท")
        except ValueError as error:
            failed.append(f"{name} — {error}")
        else:
            done.append(f"{name} — {what}")

    lines = []
    if done:
        lines += [f"🔄 <b>สั่งทำต่อแล้ว {len(done)} ชิ้น</b>"]
        lines += [f"  {i}. {escape(n)}" for i, n in enumerate(done, 1)]
    if failed:
        lines += ["", f"⚠️ <b>สั่งไม่ได้ {len(failed)} ชิ้น</b>"]
        lines += [f"  • {escape(n)}" for n in failed]
    if done:
        lines += ["", "ดูความคืบหน้าที่ <code>/queue</code>"]
    for part in _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT):
        _clip_say(chat_id, part)


def _clip_flow_probe(want_credits: bool = True) -> dict:
    """เปิด Flow ดูว่าพร้อมใช้งานไหม + อ่านเครดิต โดย **ไม่เจนอะไรเลย**

    ไม่เสียเครดิตสักหน่วย ใช้เวลาราว 10–20 วินาที — ตรวจก่อนสั่งคิวยาวคุ้มกว่า
    ปล่อยให้ล้มทีละใบแล้วค่อยรู้ (เจอจริง 13 ส.ค.: ทั้งคิวล้มเพราะค้างอยู่หน้า
    เลือกบัญชี Google กว่าจะรู้ก็เสียเวลาไปทั้งชุด)

    คืน ok=True พร้อม · ok=False มีปัญหา · ok=None ตรวจไม่ได้ตอนนี้
    """
    import flow_driver
    from flow_worker import (
        FLOW_URL, open_browser, _app_page, _enter_app, _is_signed_in,
    )
    from playwright.sync_api import sync_playwright

    try:
        # timeout สั้น — ถ้าคิวกำลังเจนอยู่ อย่าให้ /credits ค้างรอเป็นนาที
        with shared.browser_lock(timeout=8, label="ตรวจสถานะ Flow"):
            with sync_playwright() as playwright:
                browser = open_browser(playwright, hidden=True)
                try:
                    page = browser.pages[0] if browser.pages else browser.new_page()
                    page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=90_000)
                    _enter_app(page)
                    page = _app_page(browser, page)
                    if not _is_signed_in(page):
                        return {
                            "ok": False, "credits": None,
                            "detail": f"เข้าแอปไม่ได้ — ค้างอยู่ที่ {page.url[:70]}",
                        }
                    credits = None
                    if want_credits:
                        credits = flow_driver.FlowDriver(
                            page, log=_clip_log
                        ).read_credits()
                        _remember_credits(credits)
                    return {"ok": True, "credits": credits, "detail": "เข้า Flow ได้"}
                finally:
                    browser.close()
    except shared.BrowserBusy:
        return {
            "ok": None, "credits": None,
            "detail": "เบราว์เซอร์ไม่ว่าง — กำลังเจนงานอยู่ ลองใหม่ทีหลัง",
        }
    except Exception as error:                                   # noqa: BLE001
        return {"ok": False, "credits": None,
                "detail": f"{type(error).__name__}: {error}"}


# สรุปประจำวัน — ส่งเข้าแชทเองทุกเช้า
DIGEST_TIME_KEY = "clip_digest_time"
DIGEST_ENABLED_KEY = "clip_digest_enabled"
DIGEST_LAST_KEY = "clip_digest_last"            # วันที่ส่งล่าสุด YYYY-MM-DD
DIGEST_CREDIT_MARK_KEY = "clip_digest_credit"   # ยอดเครดิตตอนสรุปรอบก่อน
DIGEST_DEFAULT_TIME = "09:00"


def digest_time() -> str:
    want = str(shared.read_config().get(DIGEST_TIME_KEY) or DIGEST_DEFAULT_TIME)
    return want if _parse_hhmm(want) else DIGEST_DEFAULT_TIME


def _parse_hhmm(text: str) -> tuple[int, int] | None:
    """'09:00' → (9, 0) · รูปแบบไม่ถูกคืน None ไม่ใช่ระเบิด"""
    parts = str(text).strip().split(":")
    if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    return (hour, minute) if 0 <= hour < 24 and 0 <= minute < 60 else None


def _job_time(job: dict, field: str) -> float:
    """เวลาในงานเป็น epoch — อ่านไม่ได้คืน 0 ไม่ใช่เดาเป็นเวลาปัจจุบัน

    ถ้าเดาเป็นตอนนี้ งานเก่าที่ timestamp เสียจะโผล่ในสรุปทุกวันไม่จบ
    """
    try:
        return datetime.fromisoformat(str(job.get(field) or "")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _digest_text(hours: int = 24) -> str:
    """สรุปว่าช่วงที่ผ่านมาระบบทำอะไรไปบ้าง — ข้อมูลจากของจริงทั้งหมด"""
    escape = telegram_bot._escape
    now = time.time()
    since = now - hours * 3600

    jobs = clip_jobs.all()
    new_jobs = [j for j in jobs if _job_time(j, "created_at") >= since]
    finished = [
        j for j in jobs
        if j.get("stage") == clip_queue.STAGE_DONE
        and _job_time(j, "updated_at") >= since
    ]
    broke = [
        j for j in jobs
        if j.get("stage") == clip_queue.STAGE_FAILED
        and _job_time(j, "updated_at") >= since
    ]

    waiting: dict[str, int] = {}
    for job in jobs:
        stage = str(job.get("stage"))
        if stage in clip_queue.OPEN_STAGES:
            waiting[stage] = waiting.get(stage, 0) + 1

    # คลิปใหม่นับจาก **เวลาแก้ไขไฟล์จริง** ไม่ใช่สถานะงาน
    # งานอาจถูกลบออกจากคิวไปแล้วแต่ไฟล์ยังอยู่ — นับจากไฟล์จึงตรงกว่า
    fresh_clips = []
    for run in clip_store.list_runs(DATA_DIR):
        for name in run.get("videos") or []:
            try:
                path = clip_store.file_path(DATA_DIR, str(run.get("item_id")), name)
                if path.is_file() and path.stat().st_mtime >= since:
                    fresh_clips.append(str(run.get("name") or run.get("item_id"))[:40])
            except Exception:                                # noqa: BLE001
                continue

    credits, age = known_credits()
    config = shared.read_config()
    try:
        mark = int(config.get(DIGEST_CREDIT_MARK_KEY))
    except (TypeError, ValueError):
        mark = None
    used = (mark - credits) if (mark is not None and credits is not None) else None

    lines = [f"📊 <b>สรุป {hours} ชั่วโมงที่ผ่านมา</b>", ""]
    lines.append(f"🎬 คลิปที่เจนได้ <b>{len(fresh_clips)}</b> ชิ้น")
    for name in fresh_clips[:8]:
        lines.append(f"    • {escape(name)}")
    lines.append(f"📥 งานเข้าใหม่ {len(new_jobs)} · ✅ จบไป {len(finished)}")
    if broke:
        lines.append(f"⚠️ ล้ม {len(broke)} ชิ้น — <code>/failed</code> ดูเหตุผล")

    if waiting:
        lines += ["", "⏳ <b>ค้างรออยู่</b>"]
        for stage, count in sorted(waiting.items(), key=lambda x: -x[1]):
            label = clip_queue.STAGE_LABEL.get(stage, stage)
            lines.append(f"    {escape(str(label))} — {count}")
    else:
        lines += ["", "⏳ ไม่มีงานค้าง"]

    lines.append("")
    if credits is None:
        lines.append("💳 เครดิต: ยังไม่เคยอ่านได้ — <code>/credits สด</code>")
    else:
        text = f"💳 เครดิตเหลือ <b>{credits:,}</b> (อ่านเมื่อ {_age_text(age)})"
        if used is not None and used > 0:
            text += f" · ช่วงนี้ใช้ไป <b>{used:,}</b>"
        elif used is not None and used <= 0:
            text += " · ช่วงนี้ยังไม่ได้ใช้"
        lines.append(text)
    lines.append(f"🎥 ขั้นเจน Flow: <b>{'เปิด' if flow_enabled() else 'ปิด'}</b>")

    return "\n".join(lines)


def _clip_digest(chat_id: str, argument: str) -> None:
    """`/digest` ส่งสรุปเดี๋ยวนี้ · `/digest 09:00` ตั้งเวลา · `/digest off` ปิด"""
    want = argument.strip().lower()
    if want in ("off", "ปิด", "0"):
        set_config(DIGEST_ENABLED_KEY, False)
        _clip_say(chat_id, "🔕 ปิดสรุปประจำวันแล้ว — สั่ง <code>/digest</code> เองได้ตลอด")
        return
    if want in ("on", "เปิด", "1"):
        set_config(DIGEST_ENABLED_KEY, True)
        _clip_say(chat_id, f"🔔 เปิดสรุปประจำวันแล้ว — ส่งทุกวัน {digest_time()} น.")
        return
    if _parse_hhmm(want):
        set_config(DIGEST_TIME_KEY, want)
        set_config(DIGEST_ENABLED_KEY, True)
        _clip_say(chat_id, f"⏰ ตั้งเวลาสรุปประจำวันเป็น <b>{want} น.</b> แล้ว")
        return
    if want:
        _clip_say(
            chat_id,
            "ใช้ <code>/digest</code> · <code>/digest 09:00</code> · "
            "<code>/digest off</code>",
        )
        return

    for part in _split_text(_digest_text(), TELEGRAM_TEXT_LIMIT):
        _clip_say(chat_id, part)


def _digest_due(now: datetime, config: dict) -> bool:
    """ถึงเวลาส่งสรุปของวันนี้หรือยัง

    แยกออกมาจากลูปเพื่อให้ทดสอบได้ — ตรรกะเวลาเป็นที่ที่พลาดง่ายที่สุด
    และถ้าพลาดจะไปโผล่เป็น "ส่งซ้ำทั้งวัน" หรือ "ไม่ส่งเลย" ซึ่งรู้ตัวช้ามาก

    ตัดสินจาก **วันที่ส่งล่าสุด** ไม่ใช่ตัวนับถอยหลัง เพราะเซิร์ฟเวอร์รีสตาร์ต
    บ่อย ตัวนับจะรีเซ็ตทุกครั้ง
    """
    if not config.get(DIGEST_ENABLED_KEY, True):
        return False
    target = _parse_hhmm(
        str(config.get(DIGEST_TIME_KEY) or DIGEST_DEFAULT_TIME)
    ) or _parse_hhmm(DIGEST_DEFAULT_TIME)
    if now.hour * 60 + now.minute < target[0] * 60 + target[1]:
        return False
    return str(config.get(DIGEST_LAST_KEY) or "") != now.strftime("%Y-%m-%d")


def _digest_keeper() -> None:
    """ถึงเวลาแล้วส่งสรุปเข้าแชทเอง — เช็คทุกนาที"""
    while True:
        try:
            now = datetime.now()
            config = shared.read_config()
            if _digest_due(now, config):
                today = now.strftime("%Y-%m-%d")
                chat_id = str(config.get("telegram_clip_chat_id") or "")
                if chat_id:
                    for part in _split_text(_digest_text(), TELEGRAM_TEXT_LIMIT):
                        _clip_say(chat_id, part)
                    _clip_log(f"ส่งสรุปประจำวันแล้ว ({today})")
                # จดวันไว้เสมอ แม้ยังไม่มี chat id — ไม่งั้นจะวนพยายามทุกนาที
                set_config(DIGEST_LAST_KEY, today)
                credits, _ = known_credits()
                if credits is not None:
                    set_config(DIGEST_CREDIT_MARK_KEY, credits)
        except Exception as error:                           # noqa: BLE001
            _clip_log(f"ตัวส่งสรุปประจำวันผิดพลาด: {type(error).__name__}: {error}")
        time.sleep(60)


DRIVE_LOG_EVERY = 600          # ยกบันทึกขึ้น Drive ทุก 10 นาที


def _drive_log_keeper() -> None:
    """ยกบทสนทนาแชทกับ log ระบบขึ้น Drive ให้เอง

    ต้องมีตัวนี้เพราะบันทึกแชทเขียนลงเครื่องตลอดเวลา แต่ `sync_run` ทำงาน
    เฉพาะตอนมีคลิป/สตอรีบอร์ดใหม่ ถ้าไม่มีตัวเฝ้าแยก บันทึกของวันที่ไม่ได้
    เจนคลิปเลยจะไม่มีวันขึ้น Drive — ซึ่งเป็นวันที่อยากย้อนดูที่สุด

    10 นาทีต่อรอบ เพราะไฟล์ที่ยกเป็นข้อความล้วน (บันทึกวันแรกวัดได้ 423 ไบต์)
    และตัวยกข้ามไฟล์ที่ไม่เปลี่ยนอยู่แล้ว รอบที่ไม่มีอะไรใหม่จึงแทบไม่มีต้นทุน
    """
    while True:
        time.sleep(DRIVE_LOG_EVERY)
        try:
            import clip_drive
            root = clip_drive.data_dir()
            if not clip_drive.enabled(root):
                continue
            report = clip_drive.sync_logs(root)
            if report.get("copied"):
                append_log("clip", f"[Drive] ยกบันทึก {report['copied']} ไฟล์")
            elif not report.get("ok"):
                append_log("clip", f"[Drive] ยกบันทึกไม่สำเร็จ — {report.get('why')}")
        except Exception as error:                           # noqa: BLE001
            append_log("clip", "[Drive] ตัวยกบันทึกผิดพลาด: "
                               f"{type(error).__name__}: {error}")


def _clip_trash_list(chat_id: str) -> None:
    """งานที่ลบไปแล้วแต่ยังกู้ได้"""
    items = clip_jobs.trash()
    if not items:
        _clip_say(
            chat_id,
            f"🗑 ถังขยะว่าง\n\nงานที่ลบจากคิวจะเก็บไว้ที่นี่ "
            f"{clip_queue.TRASH_DAYS} วันก่อนหายเอง",
        )
        return
    escape = telegram_bot._escape
    lines = [f"🗑 <b>ถังขยะ {len(items)} ชิ้น</b> "
             f"(เก็บไว้ {clip_queue.TRASH_DAYS} วัน)", ""]
    rows = []
    for index, item in enumerate(items[:20], 1):
        name = str(item.get("name") or item.get("link") or item.get("id"))[:42]
        age = _age_text(time.time() - float(item.get("_trashed_at") or 0))
        lines.append(f"{index}. {escape(name)}")
        lines.append(f"    <i>{escape(str(item.get('_trashed_why') or 'ลบ'))} · {age}</i>")
        if len(rows) < 8:
            rows.append([{
                "text": f"↩️ {index}. {name[:22]}",
                "callback_data": f"clip:undo:{item.get('id')}",
            }])
    if len(items) > 20:
        lines.append(f"…และอีก {len(items) - 20} ชิ้น")
    lines += ["", "กู้กลับด้วย <code>/undo &lt;เลข&gt;</code> "
                  "(ไม่ใส่เลข = กู้ใบที่ลบล่าสุด)",
              "กู้แล้ว<b>ไม่เจนใหม่ให้อัตโนมัติ</b> — จะเจนค่อยสั่ง /retry เอง"]
    parts = _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT)
    keyboard = {"inline_keyboard": rows} if rows else None
    for index, part in enumerate(parts):
        _clip_say(chat_id, part, keyboard if index == len(parts) - 1 else None)


def _clip_undo(chat_id: str, argument: str) -> None:
    """กู้งานจากถังขยะ — รับเลขจาก /trash หรือ id ตรงๆ หรือเว้นว่าง = ใบล่าสุด"""
    want = argument.strip()
    items = clip_jobs.trash()
    if not items:
        _clip_say(chat_id, "🗑 ถังขยะว่าง ไม่มีอะไรให้กู้")
        return

    job_id = ""
    if want.isdigit() and 1 <= int(want) <= len(items):
        job_id = str(items[int(want) - 1].get("id") or "")
    elif want:
        if not any(str(i.get("id")) == want for i in items):
            _clip_say(
                chat_id,
                f"ไม่รู้จัก <code>{telegram_bot._escape(want[:30])}</code> — "
                f"ใส่เลข 1–{len(items)} จาก /trash",
            )
            return
        job_id = want

    try:
        job = clip_jobs.restore(job_id)
    except clip_queue.ClipQueueError as error:
        _clip_say(chat_id, f"❌ กู้ไม่สำเร็จ — {telegram_bot._escape(str(error))}")
        return
    name = str(job.get("name") or job.get("id"))[:60]
    label = clip_queue.STAGE_LABEL.get(job.get("stage"), job.get("stage"))
    _clip_say(
        chat_id,
        f"↩️ <b>กู้กลับแล้ว</b>\n{telegram_bot._escape(name)}\n"
        f"สถานะเดิม: <b>{telegram_bot._escape(str(label))}</b>\n\n"
        "จะเจนใหม่สั่ง <code>/retry</code> · ดูคิวที่ <code>/queue</code>",
    )


def _clip_flow_check(chat_id: str) -> None:
    """ตรวจว่า Flow พร้อมใช้งานไหม — ไม่เจน ไม่เสียเครดิต"""
    _clip_say(chat_id, "🔎 กำลังเปิด Flow ตรวจสถานะ (ไม่เสียเครดิต) รอสักครู่…")
    result = _clip_flow_probe(want_credits=True)
    mark = {True: "✅", False: "❌", None: "⏳"}[result["ok"]]
    text = f"{mark} <b>Flow:</b> {telegram_bot._escape(result['detail'])}"
    if result.get("credits") is not None:
        text += f"\n💳 เครดิตคงเหลือ: <b>{result['credits']:,}</b>"
    if result["ok"] is False:
        text += ("\n\nถ้าค้างที่หน้าเลือกบัญชี Google ให้ตั้งบัญชีที่ "
                 "<code>flow_account</code> ในหน้าตั้งค่า")
    _clip_say(chat_id, text)


def _clip_credits(chat_id: str, argument: str) -> None:
    """ยอดเครดิต Flow — ปริยายตอบจากที่จำไว้ (ทันที) · `/credits สด` ไปอ่านของจริง

    ไม่ไปอ่านสดทุกครั้งเพราะต้องเปิดเบราว์เซอร์และแย่งโปรไฟล์กับคิวที่กำลังเจน
    แต่ต้องบอกอายุของตัวเลขเสมอ ไม่งั้นผู้ใช้เอายอดเมื่อวานมาตัดสินใจวันนี้
    """
    live = argument.strip().lower() in ("สด", "live", "now", "ใหม่", "refresh")
    if live:
        _clip_say(chat_id, "🔄 กำลังเปิด Flow อ่านยอดจริง (ไม่เสียเครดิต) รอสักครู่…")
        result = _clip_flow_probe(want_credits=True)
        if result["ok"] is None:
            _clip_say(chat_id, f"⏳ {result['detail']}")
            return
        if not result["ok"]:
            _clip_say(chat_id, f"❌ อ่านไม่ได้ — {telegram_bot._escape(result['detail'])}")
            return
        if result["credits"] is None:
            _clip_say(chat_id, "⚠️ เข้า Flow ได้ แต่อ่านยอดเครดิตไม่เจอบนหน้า")
            return

    value, age = known_credits()
    if value is None:
        _clip_say(
            chat_id,
            "💳 <b>เครดิต Flow</b>\n\nยังไม่เคยอ่านยอดได้เลย\n"
            "สั่ง <code>/credits สด</code> เพื่อเปิด Flow ไปอ่านของจริง",
        )
        return

    account = str(shared.read_config().get("flow_account") or "ยังไม่ได้ตั้ง")
    rounds = value // FLOW_CREDIT_PER_CLIP
    _clip_say(
        chat_id,
        f"💳 <b>เครดิต Flow: {value:,}</b>\n"
        f"อ่านเมื่อ {_age_text(age)}\n"
        f"บัญชี: <code>{telegram_bot._escape(account)}</code>\n\n"
        f"พอเจนได้อีกราว <b>{rounds:,} คลิป</b> "
        f"(คิดที่ {FLOW_CREDIT_PER_CLIP} เครดิต/คลิป)\n"
        "<code>/credits สด</code> = ไปอ่านยอดจริงจากหน้า Flow",
    )


def _genall_plan() -> dict:
    """คัดว่างานไหนพร้อมเจนวิดีโอ — **อ่านอย่างเดียว ไม่แตะคิว ไม่เสียเครดิต**

    แยกออกมาเพราะมีสองที่ต้องใช้คำตอบชุดเดียวกัน: `/genall` ในแชท กับ
    `POST /api/genall` จากนอกแชท ถ้าต่างคนต่างคำนวณ วันหนึ่งจะตอบไม่ตรงกัน
    แล้วเชื่อไม่ได้ทั้งคู่ — ซึ่งอันตรายเป็นพิเศษเพราะตัวเลขนี้คือตัวเลข**เครดิต**
    ที่คนใช้ตัดสินใจก่อนกดจ่ายจริง

    "พร้อมครบ" = มีสตอรีบอร์ด + บทพูด + คำสั่ง Flow และยังไม่มีคลิป
    """
    runs = clip_store.list_runs(DATA_DIR)
    # แยกเป็นสองรอบ: รอบแรกแค่ **คัด** ว่าใครพร้อม รอบสองค่อยเข้าคิวจริง
    # เพราะต้องรู้ยอดเครดิตรวมก่อนตัดสินใจ — เข้าคิวไปครึ่งทางแล้วเพิ่งพบว่า
    # เครดิตไม่พอ คืองานค้างครึ่งคิวและเครดิตที่จ่ายไปแล้วเอาคืนไม่ได้
    ready, has_video, not_ready = [], 0, []
    for run in runs:
        item_id = str(run.get("item_id") or "")
        if not item_id:
            continue
        name = (run.get("name") or item_id)[:42]
        if run.get("videos"):
            has_video += 1
            continue
        missing = []
        if not run.get("storyboard_count"):
            missing.append("สตอรีบอร์ด")
        if not run.get("script_count"):
            missing.append("บทพูด")
        if not run.get("flow_prompt_count"):
            missing.append("คำสั่ง Flow")
        if missing:
            not_ready.append(f"{name} — ขาด{' + '.join(missing)}")
            continue
        ready.append((item_id, name, _credit_estimate(run)))

    have, age = known_credits()
    return {
        "total": len(runs), "ready": ready, "has_video": has_video,
        "not_ready": not_ready, "cost": sum(item[2] for item in ready),
        "credits": have, "credits_age": age,
    }


def _clip_gen_all(chat_id: str, argument: str) -> None:
    """ไล่ **เจนวิดีโอ** ทุกงานที่ยังไม่มีคลิป และของพร้อมครบแล้ว

    "พร้อมครบ" = มีสตอรีบอร์ด + มีบทพูด + มีคำสั่ง Flow  ขาดข้อไหนไม่เอาเข้าคิว
    แต่รายงานออกมาให้เห็นว่าขาดอะไร ไม่เงียบหาย

    ข้ามงานที่มีคลิปแล้วเสมอ และ **ไม่มีตัวเลือกบังคับทำใหม่** เพราะเจนซ้ำหนึ่ง
    รอบ = จ่ายเครดิต Flow จริง (รอบละ 15) การพิมพ์ผิดครั้งเดียวไม่ควรเผาเครดิต
    ทั้งคิว — ถ้าจะเจนซ้ำจริงๆ ให้สั่งเจาะจงทีละงานด้วย /gen <เลข>

    ของเดิมที่ /genall เคยทำ (ไล่ทำสตอรีบอร์ด) ย้ายไปอยู่ที่ `/genall sb`
    """
    want = argument.strip().lower()
    if want in ("sb", "storyboard", "สตอรีบอร์ด", "all", "ทั้งหมด", "force"):
        _clip_gen_all_storyboards(chat_id, want in ("all", "ทั้งหมด", "force"))
        return
    # ลองดูก่อนว่าจะทำอะไรบ้าง ใช้เครดิตเท่าไร — ไม่เข้าคิวจริง
    dry_run = want in ("ลอง", "dry", "preview", "ดู", "เช็ค")

    plan = _genall_plan()
    total_runs = plan["total"]
    if not total_runs:
        _clip_say(chat_id, "ยังไม่มีงานที่เก็บไว้ — ส่งลิงก์ Shopee เข้ามาก่อน")
        return

    escape = telegram_bot._escape
    ready, has_video, not_ready = plan["ready"], plan["has_video"], plan["not_ready"]
    cost, have, age = plan["cost"], plan["credits"], plan["credits_age"]

    # ---- ด่านเครดิต: ไม่พอก็ไม่ต้องเริ่ม ----
    if ready and have is not None and cost > have:
        _clip_say(
            chat_id,
            f"🛑 <b>เครดิตไม่พอ — ยังไม่เข้าคิวให้</b>\n\n"
            f"งานที่พร้อมเจน {len(ready)} ชิ้น ต้องใช้ราว <b>{cost:,}</b> เครดิต\n"
            f"แต่เหลืออยู่ <b>{have:,}</b> (อ่านเมื่อ {_age_text(age)})\n\n"
            f"เจนได้ประมาณ {have // FLOW_CREDIT_PER_CLIP} ชิ้นเท่านั้น — "
            "สั่งทีละชิ้นด้วย <code>/gen &lt;เลข&gt;</code> "
            "หรือเช็คยอดจริงด้วย <code>/credits สด</code>",
        )
        return

    if dry_run:
        lines = [
            f"🔍 <b>/genall ลอง — ยังไม่เข้าคิว</b> · งานที่เก็บไว้ {total_runs} ชิ้น",
            "",
            f"📥 <b>จะเข้าคิว {len(ready)} งาน</b> · ใช้ราว <b>{cost:,}</b> เครดิต",
        ]
        lines += [f"  {i}. {escape(n)} ({c})" for i, (_, n, c) in enumerate(ready[:20], 1)]
        if len(ready) > 20:
            lines.append(f"  …และอีก {len(ready) - 20} งาน")
        if have is not None:
            lines += ["", f"💳 เครดิตที่มี {have:,} (อ่านเมื่อ {_age_text(age)}) → "
                          f"เหลือราว {have - cost:,}"]
        else:
            lines += ["", "💳 ยังไม่รู้ยอดเครดิต — <code>/credits สด</code> ก่อนได้"]
        if has_video:
            lines += ["", f"⏭ ข้าม {has_video} งาน (มีคลิปแล้ว)"]
        if not_ready:
            lines += ["", f"🚧 ยังไม่พร้อม {len(not_ready)} งาน"]
            lines += [f"  • {escape(n)}" for n in not_ready[:10]]
        lines += ["", "สั่งจริงด้วย <code>/genall</code>"]
        for part in _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT):
            _clip_say(chat_id, part)
        return

    # ---- ด่านความพร้อมของ Flow ----
    #
    # เจอจริง 13 ส.ค.: คิวทั้งชุดล้มทีละใบเพราะ Flow ค้างอยู่หน้าเลือกบัญชี
    # ตรวจก่อน 10–20 วินาที (ไม่เสียเครดิต) คุ้มกว่าปล่อยให้ล้มทั้งคิวแล้วค่อยรู้
    # ok=None = ตรวจไม่ได้เพราะเบราว์เซอร์ไม่ว่าง → ปล่อยผ่าน ไม่ใช่บล็อก
    # (คิวกำลังเจนอยู่แปลว่า Flow ใช้งานได้อยู่แล้ว)
    if ready:
        check = _clip_flow_probe(want_credits=False)
        if check["ok"] is False:
            _clip_say(
                chat_id,
                f"🛑 <b>Flow ยังไม่พร้อม — ยังไม่เข้าคิวให้</b>\n\n"
                f"{telegram_bot._escape(check['detail'])}\n\n"
                f"มีงานพร้อมเจนรออยู่ {len(ready)} ชิ้น จะสั่งใหม่เมื่อแก้แล้ว\n"
                "ตรวจซ้ำด้วย <code>/flow check</code>",
            )
            return

    queued, blocked = [], []
    for item_id, name, _cost in ready:
        note = _clip_start_flow(chat_id, item_id, announce=False)
        (blocked if note != "เข้าคิวเจนคลิปแล้ว ✅" else queued).append(
            f"{name} — {note}" if note != "เข้าคิวเจนคลิปแล้ว ✅" else name
        )

    if queued:
        _clip_log(f"/genall เข้าคิวเจนวิดีโอ {len(queued)} งาน · ประเมิน {cost:,} เครดิต")

    lines = [f"🎥 <b>/genall — เจนวิดีโอ</b> · งานที่เก็บไว้ {total_runs} ชิ้น"]
    if queued:
        lines += ["", f"💳 ประเมินใช้เครดิตราว <b>{cost:,}</b>" + (
            f" · เหลืออยู่ {have:,} (อ่านเมื่อ {_age_text(age)})" if have is not None
            else " · ยังไม่รู้ยอดคงเหลือ"
        )]
        lines += ["", f"📥 <b>เข้าคิวเจนแล้ว {len(queued)} งาน</b>"]
        lines += [f"  {i}. {escape(n)}" for i, n in enumerate(queued[:20], 1)]
        if len(queued) > 20:
            lines.append(f"  …และอีก {len(queued) - 20} งาน")
    if has_video:
        lines += ["", f"⏭ <b>ข้าม {has_video} งาน</b> (มีคลิปแล้ว)"]
    if not_ready:
        lines += ["", f"🚧 <b>ยังไม่พร้อม {len(not_ready)} งาน</b>"]
        lines += [f"  • {escape(n)}" for n in not_ready[:10]]
        lines.append("  ทำสตอรีบอร์ดให้ครบก่อนด้วย <code>/genall sb</code>")
    if blocked:
        lines += ["", f"⚠️ <b>เข้าคิวไม่ได้ {len(blocked)} งาน</b>"]
        lines += [f"  • {escape(n)}" for n in blocked[:10]]
    if not queued:
        lines += ["", "ไม่มีงานที่พร้อมเจนวิดีโอตอนนี้"]
    else:
        lines += ["", "ทำทีละงานตามลำดับ — <code>/queue</code> ดูสถานะ",
                  "ครั้งหน้าลองดูก่อนได้ด้วย <code>/genall ลอง</code>"]
    for part in _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT):
        _clip_say(chat_id, part)


def _clip_gen_all_storyboards(chat_id: str, force: bool) -> None:
    """ไล่ทำสตอรีบอร์ดให้ทุกงานที่ยังไม่มี — เข้าคิวรวดเดียว แล้วทำทีละงาน

    ปริยายทำ **เฉพาะงานที่ยังไม่มีสตอรีบอร์ด** เพราะการรันซ้ำงานที่มีอยู่แล้วคือ
    เขียนทับของเดิม (ทั้งภาพ คำสั่ง Flow และบทพูด) และเผาเวลาคุยกับ GPT ฟรี
    พิมพ์ `/genall all` ถึงจะทำใหม่ทั้งหมดรวมของที่มีแล้ว

    ทำทีละงานอยู่แล้วเพราะเบราว์เซอร์มีโปรไฟล์เดียว — คิวเป็นคนคุมลำดับให้
    """
    runs = clip_store.list_runs(DATA_DIR)
    if not runs:
        _clip_say(chat_id, "ยังไม่มีงานที่เก็บไว้ — ส่งลิงก์ Shopee เข้ามาก่อน")
        return

    queued, skipped, blocked = [], [], []
    for run in runs:
        item_id = str(run.get("item_id") or "")
        if not item_id:
            continue
        name = (run.get("name") or item_id)[:42]
        if run.get("storyboard_count") and not force:
            skipped.append(name)
            continue
        note = _clip_start_storyboard(chat_id, item_id)
        (blocked if note else queued).append(f"{name} — {note}" if note else name)

    if queued:
        clip_runner.wake()
        _clip_log(f"/genall เข้าคิวทำสตอรีบอร์ด {len(queued)} งาน"
                  + (" (บังคับทำใหม่ทั้งหมด)" if force else ""))

    escape = telegram_bot._escape
    lines = [f"🖼 <b>/genall sb — ทำสตอรีบอร์ด</b> · งานที่เก็บไว้ {len(runs)} ชิ้น"]
    if queued:
        lines += ["", f"📥 <b>เข้าคิวแล้ว {len(queued)} งาน</b>"]
        lines += [f"  {i}. {escape(n)}" for i, n in enumerate(queued[:20], 1)]
        if len(queued) > 20:
            lines.append(f"  …และอีก {len(queued) - 20} งาน")
    if skipped:
        lines += ["", f"⏭ <b>ข้าม {len(skipped)} งาน</b> (มีสตอรีบอร์ดแล้ว) "
                      "— สั่งทำใหม่ด้วย <code>/genall all</code>"]
    if blocked:
        lines += ["", f"⚠️ <b>ทำไม่ได้ {len(blocked)} งาน</b>"]
        lines += [f"  • {escape(n)}" for n in blocked[:10]]
    if not queued:
        lines += ["", "ไม่มีอะไรต้องทำเพิ่ม"]
    else:
        lines += ["", "ทำทีละงานตามลำดับ — <code>/queue</code> ดูสถานะ"]
    for part in _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT):
        _clip_say(chat_id, part)


def _clip_pending_storyboards(chat_id: str) -> None:
    """สตอรีบอร์ดที่ทำเสร็จแล้วแต่ **ยังไม่ได้เอาไปเจนคลิป**

    คือรายการที่ค้างอยู่กลางทางจริงๆ — ของพร้อมหมดแล้วรอแค่กดเจน
    (เกิดเยอะเวลาสวิตช์ /flow ปิดอยู่ งานจะจบที่สตอรีบอร์ดแล้วนอนรอ)

    เลขที่แสดงเป็น **เลขเดียวกับ /clips** เพื่อให้พิมพ์ /gen <เลข> ได้ตรงกัน
    ถ้าไล่เลขใหม่เฉพาะรายการนี้ ผู้ใช้จะพิมพ์ /gen แล้วไปโดนสินค้าคนละตัว
    """
    runs = clip_store.list_runs(DATA_DIR)
    pending = [
        (index, run) for index, run in enumerate(runs, 1)
        if run.get("storyboard_count") and not (run.get("videos") or [])
    ]
    if not pending:
        done = sum(1 for r in runs if r.get("videos"))
        _clip_say(
            chat_id,
            "✅ ไม่มีสตอรีบอร์ดค้าง — เจนคลิปครบทุกงานแล้ว\n"
            f"(งานที่เก็บไว้ {len(runs)} ชิ้น · มีคลิปแล้ว {done} ชิ้น)"
            if runs else "ยังไม่มีงานที่เก็บไว้",
        )
        return

    escape = telegram_bot._escape
    lines = [f"🖼 <b>สตอรีบอร์ดที่ยังไม่ได้เจนคลิป</b> {len(pending)} ชิ้น\n"]
    buttons = []
    for index, run in pending:
        prompts = run.get("flow_prompt_count") or 0
        marks = [f"🖼{run.get('storyboard_count', 0)}",
                 f"🎥{prompts}" if prompts else "🎥— (เจนไม่ได้)",
                 f"🗣{run.get('script_count', 0)}"]
        when = (run.get("storyboard_at") or "")[5:16].replace("T", " ")
        lines.append(
            f"<b>{index}.</b> {escape((run.get('name') or '')[:55])}\n"
            f"     {' '.join(marks)} · {escape(when)} · <code>/gen {index}</code>"
        )
        # ปุ่มให้เฉพาะงานที่มีคำสั่ง Flow จริง — ไม่งั้นกดแล้วเด้ง error ทุกครั้ง
        if prompts and len(buttons) < 8:
            buttons.append([{
                "text": f"🎬 {index}. {(run.get('name') or '')[:24]}",
                "callback_data": f"clip:gen::{run.get('item_id', '')}",
            }])

    stuck = [i for i, r in pending if not (r.get("flow_prompt_count") or 0)]
    if stuck:
        lines.append(
            f"\n⚠️ ข้อ {', '.join(str(i) for i in stuck)} ไม่มีคำสั่ง Flow "
            "— กด ✏️ สั่งแก้สตอรีบอร์ดเพื่อขอใหม่ก่อน"
        )
    parts = _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT)
    for part in parts[:-1]:
        _clip_say(chat_id, part)
    _clip_say(chat_id, parts[-1],
              {"inline_keyboard": buttons} if buttons else None)


def _clip_start_flow(chat_id: str, item_id: str, announce: bool = True) -> str:
    """เอางานที่มีสตอรีบอร์ด+คำสั่งเก็บไว้แล้ว มาเข้าคิวเจนคลิปต่อ

    ใช้กับงานที่ทำค้างไว้ตอนขั้นเจนยังปิดอยู่ — ไม่ต้องส่งลิงก์ใหม่ ไม่ต้องคุยกับ
    GPT ซ้ำ หยิบของที่เก็บไว้มาเดินต่อได้เลย

    **สั่งตรงแบบนี้ข้ามสวิตช์ /flow** เพราะเป็นการสั่งเจาะจงทีละงาน ต่างจากการ
    เจนอัตโนมัติหลังอนุมัติที่สวิตช์คุมอยู่

    announce=False สำหรับตอนสั่งทีเดียวหลายงาน (/genall) — ไม่งั้นยิงข้อความ
    รายงานทีละงานจนท่วมแชท ตัวเรียกไปสรุปรวมทีเดียวเองแทน
    """
    run = clip_store.load_run(DATA_DIR, item_id)
    if not run:
        return "ไม่พบงานนี้"
    prompts = run.get("flow_prompts") or []
    if not prompts:
        if announce:
            _clip_say(chat_id, "❌ งานนี้ไม่มีคำสั่งสำหรับ Google Flow เจนต่อไม่ได้")
        return "ไม่มีคำสั่ง Flow"

    # งานที่ยังไม่จบของสินค้าชิ้นเดียวกันอย่าให้ซ้อน — เบราว์เซอร์มีตัวเดียว
    # และไฟล์ปลายทางชื่อเดียวกัน สองงานจะเขียนทับกันเอง
    for job in clip_jobs.waiting():
        if str(job.get("item_id")) == str(item_id):
            return f"งานนี้อยู่ในคิวอยู่แล้ว ({clip_queue.STAGE_LABEL.get(job.get('stage'), '')})"

    job = clip_jobs.add(run.get("affiliate_url") or run.get("product_url") or "", chat_id)
    clip_jobs.update(
        job["id"], item_id=item_id, name=(run.get("name") or "")[:80],
        storyboard_ok=True, script_ok=True, sent_script=True,
        stage=clip_queue.STAGE_READY_FLOW,
    )
    clip_runner.wake()
    _clip_log(f"สั่งเจนต่อจากงานเดิม {item_id} — คำสั่ง {len(prompts)} ชุด")
    if announce:
        _clip_say(
            chat_id,
            f"🎥 เข้าคิวเจนคลิปแล้ว — <b>{telegram_bot._escape((run.get('name') or '')[:60])}</b>\n"
            f"คำสั่ง {len(prompts)} ฉาก · ใช้สตอรีบอร์ดกับบทพูดที่อนุมัติไว้แล้ว",
        )
    return "เข้าคิวเจนคลิปแล้ว ✅"


def _clip_queue_text(chat_id: str) -> None:
    """สถานะคิว — งานที่ยังไม่จบทั้งหมด"""
    jobs = [j for j in clip_jobs.all() if str(j.get("chat_id")) == str(chat_id)]
    open_jobs = [j for j in jobs if j.get("stage") in clip_queue.OPEN_STAGES]
    if not open_jobs:
        _clip_say(chat_id, "คิวว่าง — วางลิงก์ Shopee มาได้เลย (วางทีเดียวหลายลิงก์ก็ได้)")
        return
    escape = telegram_bot._escape
    # บอกภาระคิวก่อนเสมอ — เพดานที่มองไม่เห็นแยกไม่ออกจากระบบค้าง
    lines = [f"📋 <b>คิวงาน</b> {len(open_jobs)} งาน",
             clip_jobs.load_text(), ""]
    for index, job in enumerate(open_jobs, 1):
        label = clip_queue.STAGE_LABEL.get(job.get("stage"), job.get("stage", ""))
        title = job.get("name") or job.get("link", "")[:45]
        lines.append(f"<b>{index}.</b> {escape(title[:55])}\n     {escape(label)}")
    # เลขในรายการนี้ใช้กับ /cancel ได้ตรงๆ — ใช้เกณฑ์คัดงานชุดเดียวกัน
    lines.append("\nยกเลิกด้วย <code>/cancel &lt;เลข&gt;</code> หรือ <code>/cancel</code> ทั้งหมด")
    for part in _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT):
        _clip_say(chat_id, part)


def _clip_cancel(chat_id: str, argument: str) -> None:
    """ยกเลิกงาน — ไม่ใส่เลข = ยกเลิกทุกงานที่ยังไม่จบของแชทนี้

    เลขที่ใช้คือเลขเดียวกับที่ /queue แสดง จะได้ไม่ต้องจำรหัสงาน
    """
    mine = [
        job for job in clip_jobs.all()
        if str(job.get("chat_id")) == str(chat_id)
        and job.get("stage") in clip_queue.OPEN_STAGES
    ]
    if not mine:
        _clip_say(chat_id, "ไม่มีงานค้างให้ยกเลิก — คิวว่างอยู่แล้ว")
        return

    target = (argument or "").strip()
    if target:
        if not (target.isdigit() and 1 <= int(target) <= len(mine)):
            _clip_say(
                chat_id,
                f"ใช้ <code>/cancel &lt;เลข 1–{len(mine)}&gt;</code> "
                "หรือ <code>/cancel</code> เฉยๆ เพื่อยกเลิกทั้งหมด — /queue ดูรายการ",
            )
            return
        mine = [mine[int(target) - 1]]

    escape = telegram_bot._escape
    running = clip_runner.current
    lines, warned = [], False
    for job in mine:
        try:
            clip_jobs.update(
                job["id"], stage=clip_queue.STAGE_CANCELLED,
                awaiting="", pending_edit=None,
                note="ผู้ใช้สั่งยกเลิก",
            )
        except clip_queue.ClipQueueError:
            continue
        name = job.get("name") or job.get("link", "")
        lines.append(f"• {escape(name[:48])}")
        if job["id"] == running:
            warned = True

    _clip_log(f"ยกเลิกงาน {len(lines)} งานตามคำสั่งผู้ใช้")
    body = [f"🛑 <b>ยกเลิกแล้ว {len(lines)} งาน</b>", ""] + lines
    if warned:
        # หยุดกลางคันไม่ได้จริง — งานที่กำลังทำอยู่ต้องจบขั้นปัจจุบันก่อน
        # บอกให้ชัด ไม่ใช่ปล่อยให้ผู้ใช้เห็นมันทำงานต่อแล้วงงว่ายกเลิกไม่ติด
        body += [
            "",
            "⚠️ งานที่<b>กำลังทำอยู่</b>จะหยุดเมื่อจบขั้นปัจจุบัน "
            "(หยุดกลางคันไม่ได้) แต่จะไม่ไปขั้นถัดไป",
        ]
    _clip_say(chat_id, "\n".join(body))


def _clip_telegram_command(chat_id: str, text: str) -> bool:
    command, _, argument = text.partition(" ")
    command = command.lower().split("@")[0]
    if command in ("/start", "/help"):
        _clip_say(chat_id, CLIP_HELP)
        return True
    # ---- รายการคลิปแยกตามปลายทาง (ผู้ใช้สั่ง 27 ส.ค. 2569) ----------------
    #
    # สามรายการ · สามคำสั่งเปิดงาน **เลขลำดับเป็นคนละชุดกัน ห้ามใช้ปนกัน**
    #   /clips        → /clip <เลข>        รอลง Shopee Video
    #   /clipsfb      → /clipfb <เลข>      รอลง Facebook Reels
    #   /clipstiktok  → /cliptiktok <เลข>  รอลง TikTok
    #
    # เดิม /clipsfb คือ "งานที่ติ๊กว่าทำแล้ว" — ผู้ใช้สั่งเลิก ("/done ไม่ต้องมี")
    # กองที่เก็บไปแล้วยังเปิดดูได้ด้วย /archive และด้วยรหัสสินค้าเหมือนเดิม
    if command in CLIP_LISTS:
        _clip_list_bucket(chat_id, command)
        return True
    if command == "/clipfb":
        _clip_open_from_list(chat_id, "/clipsfb", argument)
        return True
    if command == "/cliptiktok":
        _clip_open_from_list(chat_id, "/clipstiktok", argument)
        return True
    if command in ("/archive", "/ทำแล้ว"):
        _clip_list_done(chat_id)
        return True
    if command == "/clip":
        _clip_open_from_list(chat_id, "/clips", argument)
        return True
    if command == "/queue":
        _clip_queue_text(chat_id)
        return True
    if command in ("/dup", "/ซ้ำ"):
        _clip_dup_list(chat_id)
        return True
    if command in ("/history", "/สมุด", "/ลงไปแล้ว"):
        _clip_posted_log(chat_id)
        return True
    if command in ("/posted", "/ลงแล้ว"):
        _clip_posted_command(chat_id, argument)
        return True
    if command in ("/wait", "/รอแก้"):
        _clip_wait_list(chat_id, argument)
        return True
    # ช่องรอแก้แยกรายขั้น — /waitclips, /waitclipsfb, /waitstoryboard ฯลฯ
    if command in WAIT_LISTS:
        _clip_wait_list(chat_id, argument, only=WAIT_LISTS[command][0])
        return True
    if command in ("/pending", "/รออนุมัติ"):
        _clip_pending_list(chat_id, argument)
        return True
    if command in ("/approveall", "/อนุมัติทั้งหมด", "/approve_all"):
        _clip_approve_all(chat_id, argument)
        return True
    if command in ("/recheck", "/ตรวจคลิป"):
        _clip_recheck(chat_id, argument)
        return True
    if command in ("/features", "/จุดเด่น"):
        _clip_refresh_features(chat_id, argument)
        return True
    if command in ("/failed", "/fail"):
        _clip_failed_list(chat_id)
        return True
    if command == "/retry":
        _clip_retry(chat_id, argument)
        return True
    if command in ("/credits", "/credit", "/เครดิต"):
        _clip_credits(chat_id, argument)
        return True
    if command in ("/health", "/status"):
        _clip_health(chat_id, argument)
        return True
    if command in ("/digest", "/สรุป"):
        _clip_digest(chat_id, argument)
        return True
    if command in ("/trash", "/ถังขยะ"):
        _clip_trash_list(chat_id)
        return True
    if command in ("/undo", "/กู้"):
        _clip_undo(chat_id, argument)
        return True
    if command == "/basket":
        # ข้อ ④ ของผัง — คำพูดที่ไปอยู่บนปุ่มตะกร้าตอนโพสต์ TikTok
        want = argument.strip()
        if want:
            set_config("tiktok_basket_text", want[:60])
            _clip_say(chat_id, f"💬 คำพูดบนตะกร้า: <b>{telegram_bot._escape(want[:60])}</b>")
        else:
            _clip_say(
                chat_id,
                f"💬 คำพูดบนตะกร้าตอนนี้: <b>"
                f"{telegram_bot._escape(tiktok_repost.basket_text())}</b>\n"
                "เปลี่ยนด้วย <code>/basket ข้อความใหม่</code>",
            )
        return True
    if command == "/cancel":
        _clip_cancel(chat_id, argument)
        return True
    if command == "/sec":
        want = argument.strip()
        if want.rstrip("s").isdigit() and int(want.rstrip("s")) in FLOW_SECONDS_CHOICES:
            set_config(FLOW_SECONDS_KEY, int(want.rstrip("s")))
            _clip_say(chat_id, f"⏱ ตั้งความยาวคลิปเป็น <b>{want.rstrip('s')} วินาที</b>")
        else:
            _clip_say(
                chat_id,
                f"⏱ ความยาวคลิปตอนนี้: <b>{flow_seconds()} วินาที</b>\n"
                f"เลือกได้: {' · '.join(str(x) for x in FLOW_SECONDS_CHOICES)}\n"
                "เปลี่ยนด้วย /sec 10",
            )
        return True
    if command == "/mode":
        want = argument.strip().lower()
        if want in ("รวม", "one", "1"):
            set_config(FLOW_ONE_CLIP_KEY, True)
            _clip_say(chat_id, "🎬 โหมด <b>คลิปเดียวจบทุกฉาก</b> — เจนครั้งเดียว เสียเครดิตครั้งเดียว")
        elif want in ("แยก", "scene", "split"):
            set_config(FLOW_ONE_CLIP_KEY, False)
            _clip_say(chat_id, "🎬 โหมด <b>แยกฉากละคลิป</b> — เสียเครดิตเท่าจำนวนฉาก")
        else:
            now = "คลิปเดียวจบทุกฉาก" if one_clip_mode() else "แยกฉากละคลิป"
            _clip_say(
                chat_id,
                f"🎬 โหมดเจนตอนนี้: <b>{now}</b>\n"
                "เปลี่ยนด้วย /mode รวม หรือ /mode แยก",
            )
        return True
    if command == "/gen":
        # รับได้ทั้งเลขลำดับจาก /clips และรหัสสินค้า เหมือน /clip
        runs = clip_store.list_runs(DATA_DIR)
        target = (argument or "").strip()
        run = None
        if target.isdigit() and 1 <= int(target) <= len(runs):
            run = runs[int(target) - 1]
        else:
            run = next((r for r in runs if str(r.get("item_id")) == target), None)
        if not run:
            _clip_say(chat_id, "ใช้ <code>/gen &lt;เลขจาก /clips&gt;</code> — /clips ดูรายการ")
            return True
        _clip_start_flow(chat_id, str(run.get("item_id")))
        return True
    if command == "/genall":
        _clip_gen_all(chat_id, argument)
        return True

    if command == "/storyboard":
        _clip_pending_storyboards(chat_id)
        return True

    if command == "/videos":
        _clip_video_list(chat_id)
        return True

    if command == "/video":
        _clip_send_video_by_index(chat_id, argument)
        return True

    if command == "/claude":
        # ช่องฝากงานของ **สายคลิปโดยเฉพาะ** — แยกจากช่องของสายโพสต์ที่บอทหลัก
        # ไม่งั้นงานสองสายไปโผล่ในเซสชันของกันและกัน
        note = argument.strip()
        if not note:
            _clip_say(chat_id, "ใช้ <code>/claude &lt;สิ่งที่อยากให้ทำ&gt;</code> "
                               "— ฝากไว้แล้ว Claude สายคลิปจะเห็นเอง")
            return True
        try:
            body = json.dumps(
                {"text": note, "source": "telegram-clip", "channel": "clip"}
            ).encode("utf-8")
            request = urllib.request.Request(
                "http://127.0.0.1:8866/api/claude/inbox", data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                entry = json.load(response).get("entry", {})
            _clip_say(chat_id, f"📮 ฝากไว้ให้ Claude สายคลิปแล้ว ({entry.get('id','')})")
        except Exception as error:                                # noqa: BLE001
            # กล่องอยู่ที่โปรเซส 8866 — ถ้าตัวนั้นดับต้องบอกตรงๆ ไม่ใช่เงียบ
            _clip_log(f"ฝากข้อความให้ Claude ไม่สำเร็จ: {type(error).__name__}: {error}")
            _clip_say(chat_id, "❌ ฝากไม่สำเร็จ — เซิร์ฟเวอร์หลัก (8866) ไม่ตอบ")
        return True

    if command == "/flow":
        want = argument.strip().lower()
        if want in ("check", "เช็ค", "ตรวจ", "status"):
            _clip_flow_check(chat_id)
        elif want in ("on", "เปิด", "1"):
            set_config(FLOW_ENABLED_KEY, True)
            _clip_say(chat_id, "🎥 เปิดขั้นเจนคลิปใน Google Flow แล้ว")
        elif want in ("off", "ปิด", "0"):
            set_config(FLOW_ENABLED_KEY, False)
            _clip_say(chat_id, "⏸ ปิดขั้นเจนคลิปแล้ว — จะหยุดที่สตอรีบอร์ด + บทพูด")
        else:
            state = "เปิด" if flow_enabled() else "ปิด"
            _clip_say(
                chat_id,
                f"🎥 ขั้นเจนคลิปใน Google Flow ตอนนี้: <b>{state}</b>\n"
                "เปลี่ยนด้วย /flow on หรือ /flow off",
            )
        return True
    return False


def _clip_after_approve(job_id: str, chat_id: str, note: str) -> str:
    """กดผ่านไปหนึ่งอย่างแล้ว — ไปต่อได้ก็ต่อเมื่อ **ผ่านครบทั้งสองอย่าง**

    สตอรีบอร์ดกับบทพูดส่งมาพร้อมกันและกดแยกกัน จะกดผ่านอันไหนก่อนก็ได้
    ตัวที่ยังไม่ผ่านต้องบอกให้ชัดว่าเหลืออะไร ไม่ใช่เงียบแล้วผู้ใช้นึกว่าค้าง
    """
    job = clip_jobs.get(job_id) or {}
    if not (job.get("storyboard_ok") and job.get("script_ok")):
        waiting = "บทพูด" if job.get("storyboard_ok") else "สตอรีบอร์ด"
        _clip_say(chat_id, f"👍 {note}\nเหลืออีกอย่าง: <b>{waiting}</b> ยังไม่ได้อนุมัติ")
        return note

    if not flow_enabled():
        # ขั้นเจน Flow ปิดอยู่ — จบงานตรงนี้ ของที่ทำเสร็จถูกเก็บครบแล้วตั้งแต่
        # ก่อนขออนุมัติ ไม่ต้องไปเปิด Flow ทิ้งไว้ฉากละ ~50 วินาทีโดยไม่ได้อะไร
        clip_jobs.update(job_id, stage=clip_queue.STAGE_DONE)
        item_id = job.get("item_id", "")
        run = clip_store.load_run(DATA_DIR, item_id)
        _clip_say(
            chat_id,
            "✅ <b>อนุมัติครบแล้ว — จบงานตรงนี้</b>\n"
            "(ขั้นเจนคลิปใน Google Flow ปิดอยู่ระหว่างแก้ไข)\n\n"
            f"เก็บไว้แล้ว: 🖼 สตอรีบอร์ด {run.get('storyboard_count', 0)} ภาพ · "
            f"🎥 คำสั่ง {run.get('flow_prompt_count', 0)} ชุด · "
            f"🗣 บทพูด {run.get('script_count', 0)} ท่อน\n"
            f"<code>{telegram_bot._escape(str(run.get('folder', '')))}</code>\n\n"
            "เปิดขั้นเจนคลิปเมื่อพร้อมด้วย /flow on",
        )
        return note

    clip_jobs.update(job_id, stage=clip_queue.STAGE_READY_FLOW)
    clip_runner.wake()
    _clip_say(chat_id, "✅ อนุมัติครบทั้งคู่ — เข้าคิวเจนคลิปใน Google Flow")
    return note


# ============================================================================
# การ์ดลง Facebook Reels — **มีปุ่มกดโพสต์จริง** (ผู้ใช้สั่ง 27 ส.ค. 2569)
# ============================================================================
#
# *"เพิ่มการ์ดลง facebook ด้วย"* + เลือกแบบ ข = **กดแล้วโพสต์ได้เลย**
#
# **ทำไมต้องยิงไปที่เซิร์ฟเวอร์หลัก (พอร์ต 8866) ไม่ใช่กดมือถือเอง**
# ตัวกดจอจริงอยู่ที่ `publish_flow.py` ฝั่งนั้น พร้อมด่านลำดับการลง
# (`publish_order`) · บัตรคิวจอ (`phone_queue`) · การจดว่าลงแล้ว
# (`clip_store.mark_posted`) ครบทุกอย่าง ถ้าฝั่งคลิปกดเอง จะต้องเขียนซ้ำทั้งชุด
# แล้ววันหนึ่งสองฝั่งจะไม่ตรงกัน — กติกาข้อ 2.8 ห้ามเขียนกติกาลำดับซ้ำที่อื่น
#
# **ต้องเลือกเครื่องเสมอ ห้ามเดา** (กติกาข้อ 8) สายโพสต์มีมือถือหลายเครื่อง
# ผูกคนละบัญชี — เดาผิด = โพสต์ขึ้นบัญชีผิด ซึ่งกู้คืนไม่ได้
# จึงทำเป็นปุ่มแยกเครื่องละปุ่ม ไม่มีปุ่ม "โพสต์เลย" แบบไม่ระบุเครื่อง

MAIN_SERVER = "http://127.0.0.1:8866"


def _post_devices() -> list[tuple[str, str]]:
    """มือถือที่ลงคลิปได้ — [(serial, ชื่อที่คนอ่าน)] **สายคลิปมาก่อนเสมอ**

    เจ้าของแยกเครื่องให้สายวิดีโอโดยเฉพาะเมื่อ 27 ส.ค. 2569
    (`REDMI 15C — วิดีโอ` ล็อกอิน Shopee กับ Facebook Reels ไว้แล้ว)

    **ถ้ามีเครื่องสายคลิป ให้ใช้เฉพาะเครื่องนั้น ไม่เอาเครื่องสายโพสต์มาปน**
    เพราะเครื่องสายโพสต์ล็อกอินคนละบัญชี ลงผิดเครื่อง = ลงผิดบัญชี ถอนไม่ได้
    (กติกาข้อ 8 ของโปรเจกต์)

    ยังไม่ได้แยกเครื่อง (ทะเบียนไม่มีเครื่องสายคลิปเลย) ค่อยถอยไปใช้
    สายโพสต์เหมือนเดิม — ไม่งั้นระบบเก่าที่ยังไม่ได้ตั้งจะกดปุ่มไม่ได้เลย
    """
    try:
        import devices                                          # noqa: PLC0415
        serials = devices.enabled_serials("clip")
        if not serials:
            serials = devices.enabled_serials("post")
        return [(s, devices.label(s)) for s in serials]
    except Exception as error:                                  # noqa: BLE001
        _clip_log(f"อ่านทะเบียนมือถือไม่ได้: {type(error).__name__}: {error}")
        return []


def _clip_send_fb_card(chat_id: str, item_id: str) -> str:
    """การ์ด "ลง Facebook Reels" ของสินค้าหนึ่งชิ้น พร้อมปุ่มโพสต์รายเครื่อง"""
    run = clip_store.load_run(DATA_DIR, item_id) or {}
    if not run:
        return "ไม่เจองานชิ้นนี้"
    escape = telegram_bot._escape
    videos = run.get("videos") or []
    ok, why = publish_order.check(run, "facebook_reels")

    lines = [
        "📘 <b>ลง Facebook Reels</b>",
        f"<b>{escape((run.get('name') or item_id)[:70])}</b>",
        "",
        f"🎥 คลิป {len(videos)} ไฟล์"
        + (f" — {escape(str(videos[0]))}" if videos else " — ⛔ ยังไม่มีคลิป"),
        "",
        escape(publish_order.summary(run)),
    ]
    rows: list[list[dict]] = []
    if not ok:
        lines += ["", f"⏳ <b>ยังลงไม่ได้</b> — {escape(why)}"]
        # ติดเพราะระบบไม่รู้ว่าลง Shopee ไปแล้ว → ให้ติ๊กเองได้ตรงนี้
        # (คลิปที่โพสต์ด้วยมือบนมือถือ ระบบไม่มีทางรู้เอง)
        if ((run.get("publish") or {}).get("shopee_video") or {}).get(
                "status") != "posted":
            rows.append([{
                "text": "✅ ลง Shopee ไปแล้ว (ติ๊กเอง)",
                "callback_data": f"clip:posted:shopee_video:{item_id}",
            }])
    elif not videos:
        lines += ["", "⛔ <b>ยังลงไม่ได้</b> — ไม่มีไฟล์คลิปในโฟลเดอร์งาน"]
    else:
        phones = _post_devices()
        if not phones:
            lines += ["", "⛔ <b>ไม่มีมือถือสายโพสต์ที่เปิดใช้อยู่</b> — "
                          "เปิดเครื่องในหน้าตั้งค่าก่อน"]
        else:
            lines += ["", "เลือกเครื่องที่จะโพสต์ — <b>แต่ละเครื่องคนละบัญชี</b>"]
            import devices                                       # noqa: PLC0415
            for serial, label in phones:
                # **บอกชื่อบัญชีบนปุ่ม ไม่ใช่แค่ชื่อเครื่อง** (27 ส.ค. 2569)
                # ชื่อเครื่องบอกไม่ได้ว่าคลิปจะขึ้นไอดีไหน ซึ่งเป็นสิ่งเดียว
                # ที่กดผิดแล้วกู้ไม่ได้ — ชื่อบัญชีต่างหากที่ต้องเห็นก่อนกด
                who = devices.account(serial) or ""
                text = f"🚀 ลง {who}" if who else f"🚀 ลงเครื่อง {label}"
                rows.append([{"text": text[:60],
                              "callback_data": f"clip:fbgo:{serial}:{item_id}"}])
                lines.append(f"   • {escape(label)}"
                             + (f" → บัญชี <b>{escape(who)}</b>" if who
                                else " → ⚠️ <b>ยังไม่ได้ผูกบัญชี</b> — ไม่รู้ว่าจะขึ้นไอดีไหน"))
    rows.append([
        {"text": "🅿 รอแก้", "callback_data": f"clip:rpark::{item_id}"},
        {"text": "📄 ใบงาน", "callback_data": f"clip:open::{item_id}"},
    ])
    _clip_say(chat_id, "\n".join(lines), {"inline_keyboard": rows})
    return "เปิดการ์ดลง Facebook ให้แล้ว"


def _clip_fb_post_now(chat_id: str, serial: str, item_id: str) -> str:
    """กดโพสต์จริง — ส่งงานให้เซิร์ฟเวอร์หลักเดินผังกดจอมือถือ

    **ไม่กดมือถือเองที่นี่** เหตุผลอยู่ในคอมเมนต์หัวหมวดข้างบน
    ตอบกลับด้วยผลจริงที่เซิร์ฟเวอร์หลักคืนมา ไม่ใช่ "ส่งคำสั่งแล้ว" ลอยๆ —
    ถ้าด่านลำดับปฏิเสธ (409) ต้องเห็นเหตุผลทันที ไม่ใช่ไปรู้เอาตอนเปิด log
    """
    if not serial:
        return "ไม่ได้บอกว่าจะลงเครื่องไหน — เปิดการ์ดใหม่แล้วกดปุ่มของเครื่องนั้น"
    run = clip_store.load_run(DATA_DIR, item_id) or {}
    name = (run.get("name") or item_id)[:40]
    _clip_say(chat_id, f"🚀 กำลังลง Facebook Reels — <b>{telegram_bot._escape(name)}</b>"
                       f"\nเครื่อง <code>{telegram_bot._escape(serial)}</code> · รอสักครู่…")

    body = json.dumps({"serial": serial, "target": "facebook_reels",
                       "item_id": item_id}).encode("utf-8")
    request = urllib.request.Request(
        MAIN_SERVER + "/api/publish/flow/run", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        try:
            detail = json.loads(detail).get("detail") or detail
        except Exception:                                       # noqa: BLE001
            pass
        _clip_log(f"ลง Facebook ไม่สำเร็จ {item_id} — {error.code} {detail}")
        _clip_say(chat_id, f"❌ <b>ลงไม่สำเร็จ</b>\n{telegram_bot._escape(str(detail))}")
        return "ลงไม่สำเร็จ"
    except Exception as error:                                  # noqa: BLE001
        _clip_log(f"ลง Facebook ไม่สำเร็จ {item_id} — {type(error).__name__}: {error}")
        _clip_say(chat_id, "❌ <b>ติดต่อเซิร์ฟเวอร์หลักไม่ได้</b>\n"
                           f"{telegram_bot._escape(str(error))}\n"
                           "เซิร์ฟเวอร์พอร์ต 8866 เปิดอยู่หรือเปล่า")
        return "ติดต่อเซิร์ฟเวอร์หลักไม่ได้"

    done, total = result.get("done", 0), result.get("total", 0)
    if result.get("ok"):
        _clip_say(chat_id, f"✅ <b>ลง Facebook Reels แล้ว</b> ({done}/{total} ขั้น)")
        return "ลงแล้ว ✅"
    _clip_say(chat_id, f"⚠️ <b>เดินผังไม่จบ</b> — ทำได้ {done}/{total} ขั้น\n"
                       f"{telegram_bot._escape(str(result.get('error') or ''))}")
    return "เดินผังไม่จบ"


def _clip_park_run(chat_id: str, item_id: str, park: bool) -> str:
    """พัก/เอากลับ งานที่ **ออกจากคิวไปแล้ว** (มีแต่ไฟล์งาน ไม่มีใบงานในคิว)

    คนละตัวกับ `clip_jobs.park` ที่ใช้กับใบงานในคิว — งานขั้นโพสต์ส่วนใหญ่
    จบจากคิวไปแล้ว ถ้าใช้ตัวเดิมจะหาใบงานไม่เจอแล้วปุ่มกดไม่ติดเฉยๆ
    """
    try:
        if park:
            came = clip_board.bucket_of_run(
                clip_store.load_run(DATA_DIR, item_id) or {})
            clip_store.park_run(DATA_DIR, item_id, "กดพักจากแชท", came)
            _clip_log(f"พักงานเก็บไว้ {item_id} รอแก้ (กอง {came})")
            return (f"🅿️ พักไว้รอแก้แล้ว (ค้างที่ {_stage_words(came)}) "
                    "— ดูทั้งหมดที่ /wait")
        clip_store.unpark_run(DATA_DIR, item_id)
        _clip_log(f"เอางานเก็บไว้ {item_id} ออกจากช่องรอแก้")
        return "↩️ เอากลับเข้ารายการแล้ว"
    except clip_store.ClipStoreError as error:
        return str(error)


# ============================================================================
# ติ๊กว่า "ลงไปแล้ว" ด้วยมือ (ผู้ใช้ทัก 27 ส.ค. 2569)
# ============================================================================
#
# *"ทำไมคลิป /clipsfb ถึงไม่มี มันมีงานที่ลง shopee แล้วและรอลง facebook
#   อยู่แล้วสิ"*
#
# **ไล่หาสาเหตุแล้วพบว่าระบบไม่เคยรู้เลยว่ามีอะไรลงไปแล้วบ้าง**
#
#   อาการ    /clipsfb ว่างเปล่า ทั้งที่มีคลิปอยู่บน Shopee จริง
#   ทำไม 1   ระบบดูจาก `publish.shopee_video.status` ในไฟล์งาน
#            → วัดจริง: ทั้ง 23 ใบเป็น `pending` ไม่มีใบไหนเป็น `posted` เลย
#   ทำไม 2   `mark_posted()` ถูกเรียกตอนเดินผังจบทั้งชุดเท่านั้น
#   ทำไม 3   ไม่เคยมีการเดินผังจบสักครั้ง — log บอกว่าทุกครั้งเป็น
#            "เดินผัง 1/22 ขั้น" กับ "1/28 ขั้น" ซึ่งคือการไล่เทรนพิกัดทีละขั้น
#            (นับจาก log จริง: 26+10+6+3+1 = 46 ครั้ง ไม่มีครั้งไหนจบครบผัง)
#   รากเหง้า **คลิปที่ขึ้น Shopee ไปแล้วถูกโพสต์ด้วยมือบนมือถือ**
#            แล้ว **ไม่มีทางไหนเลยให้คนบอกระบบว่าใบนี้ลงไปแล้ว**
#            มีแต่ทางเดินผังอัตโนมัติซึ่งยังใช้จริงไม่ได้
#
# ตัวนี้คือทางที่ขาดไป — ติ๊กเองได้ แล้วด่านลำดับกับรายการทั้งหมดจะเดินต่อถูก
#
# **ไม่ใช่การข้ามด่าน** ด่านลำดับยังทำงานเหมือนเดิมทุกอย่าง แค่รับข้อมูลจาก
# คนแทนที่จะรับจากตัวกดจอ — คนคือผู้ที่รู้จริงว่าลงไปแล้วหรือยัง

POSTED_LABEL = {"shopee_video": "🛍 Shopee Video",
                "facebook_reels": "📘 Facebook Reels",
                "tiktok": "🎵 TikTok"}

# ปลายทางนั้นไปโผล่ในรายการไหน — บอกคนว่ากดแล้วงานย้ายไปอยู่ที่ไหนต่อ
_LIST_OF = {"shopee_video": "/clips", "facebook_reels": "/clipsfb",
            "tiktok": "/clipstiktok"}


def _clip_mark_posted(chat_id: str, item_id: str, target: str) -> str:
    """ติ๊กว่าลงปลายทางนั้นไปแล้ว — สำหรับคลิปที่โพสต์ด้วยมือ"""
    if target not in POSTED_LABEL:
        return "ไม่รู้จักปลายทางนี้"
    run = clip_store.load_run(DATA_DIR, item_id) or {}
    if not run:
        return "ไม่เจองานชิ้นนี้"
    already = ((run.get("publish") or {}).get(target) or {}).get("status")
    if already == "posted":
        return f"ใบนี้จดว่าลง {POSTED_LABEL[target]} ไปแล้ว"
    try:
        fresh = clip_store.mark_posted(DATA_DIR, item_id, target, "")
    except clip_store.ClipStoreError as error:
        return str(error)
    _clip_log(f"ติ๊กด้วยมือว่า {item_id} ลง {target} แล้ว")
    nxt = publish_order.next_target(fresh)
    _clip_say(chat_id,
              f"✅ จดแล้วว่าลง <b>{POSTED_LABEL[target]}</b> ไปแล้ว" + '\n' +
              f"{telegram_bot._escape(publish_order.summary(fresh))}" + '\n' + '\n' +
              (f"ต่อไปคือ <b>{POSTED_LABEL.get(nxt, nxt)}</b> — "
               "ลงได้ตั้งแต่พรุ่งนี้ (ต้องห่างกันอย่างน้อย 1 วัน)"
               if nxt else "ลงครบทั้งสามที่แล้ว 🎉"))
    return "จดแล้ว ✅"


def _clip_dup_list(chat_id: str) -> None:
    """`/dup` — สินค้าที่มีโฟลเดอร์งานซ้อนกันสองชุด

    ไม่ลบให้เอง ไม่ย้ายให้เอง — บอกอย่างเดียวว่ามีอะไรซ้อนกันและชุดไหนมีของครบ
    **การเลือกว่าจะเก็บชุดไหนเป็นการตัดสินใจของคน** เพราะทั้งสองชุดอาจมีของที่
    จ่ายเครดิตไปแล้ว เดาผิดแล้วลบ = จ่ายซ้ำ (กติกาข้อ 7.4 ของโปรเจกต์)
    """
    escape = telegram_bot._escape
    rows = clip_store.duplicates(DATA_DIR)
    if not rows:
        _clip_say(chat_id, "✅ ไม่มีสินค้าที่มีโฟลเดอร์ซ้อนกัน")
        return
    lines = [f"⚠️ <b>มีสินค้า {len(rows)} ชิ้นที่มีโฟลเดอร์ซ้อนกัน</b>", "",
             "เกิดจากส่งลิงก์เดิมเข้ามาซ้ำ ตัวดึงสินค้าสร้างโฟลเดอร์ใหม่ทับ",
             "<b>ชุดที่มีคลิปอาจถูกมองข้าม</b> เพราะระบบเจอชุดที่ว่างกว่าก่อน", ""]
    for row in rows[:15]:
        lines.append(f"<b>{escape(row['name'][:46])}</b>")
        for copy in row["copies"]:
            mark = f"🎥{copy['videos']}" if copy["videos"] else "ไม่มีคลิป"
            lines.append(f"    <code>{copy['folder']}/</code> · {mark} · "
                         f"🖼{copy['storyboard']} · ดึง {str(copy['at'])[:10]}")
    if len(rows) > 15:
        lines.append(f"…และอีก {len(rows) - 15} ชิ้น")
    lines += ["", "เลือกเองว่าจะเก็บชุดไหน — ระบบไม่ลบให้ เพราะทั้งสองชุด",
              "อาจมีของที่จ่ายเครดิตไปแล้ว"]
    for part in _split_text('\n'.join(lines), TELEGRAM_TEXT_LIMIT):
        _clip_say(chat_id, part)


def _clip_posted_log(chat_id: str) -> None:
    """`/history` — **สมุดบันทึกการลง** ลงอะไรไปแล้วบ้าง ที่ไหน เมื่อไร

    ผู้ใช้สั่ง 27 ส.ค. 2569: *"ผมจำไม่ได้ว่าโพสต์อันไหนบ้าง ไม่มีลิ้สที่จดไว้
    ว่าลงแล้วหรอ บอกให้จด"*

    **จัดกลุ่มตามวัน** เพราะคำถามที่คนถามจริงคือ "เมื่อวานลงอะไรไปบ้าง"
    ไม่ใช่ "ใบที่ 47 ลงเมื่อไร" — และกติกาเว้น 1 วันก็นับเป็นวันเหมือนกัน
    """
    escape = telegram_bot._escape
    rows = clip_store.posted_history(DATA_DIR)
    if not rows:
        _clip_say(
            chat_id,
            "📕 <b>สมุดบันทึกการลงยังว่างเปล่า</b>" + '\n' + '\n' +
            "ระบบยังไม่เคยจดว่าลงคลิปไหนไปเลยสักใบ" + '\n' +
            "คลิปที่คุณโพสต์เองด้วยมือ ระบบไม่มีทางรู้ — ต้องกดบอกมันก่อน" + '\n' + '\n' +
            "พิมพ์ <code>/posted</code> จะได้รายการพร้อมปุ่มติ๊กทีละใบ",
        )
        return

    days: dict[str, list[dict]] = {}
    for row in rows:
        days.setdefault(str(row["at"])[:10], []).append(row)

    lines = [f"📕 <b>สมุดบันทึกการลง</b> — จดไว้ {len(rows)} ครั้ง", ""]
    for day, items in list(days.items())[:14]:      # 2 สัปดาห์ล่าสุดพอ
        nice = day[8:10] + "/" + day[5:7] if len(day) >= 10 else day
        lines.append(f"━━ <b>{nice}</b> · {len(items)} ครั้ง ━━")
        for row in items:
            when = str(row["at"])[11:16]
            mark = POSTED_LABEL.get(row["target"], row["target"])
            lines.append(f"  {when} {mark} — {escape(row['name'][:44])}")
        lines.append("")
    if len(days) > 14:
        lines.append(f"…และอีก {len(days) - 14} วันก่อนหน้า")
    lines.append("จดเพิ่มด้วย <code>/posted</code> · ถอนที่จดผิดด้วยปุ่ม ↩️ ในใบงาน")
    for part in _split_text('\n'.join(lines), TELEGRAM_TEXT_LIMIT):
        _clip_say(chat_id, part)


def _clip_posted_command(chat_id: str, argument: str) -> None:
    """`/posted <เลข|รหัสสินค้า> [ปลายทาง]` — ติ๊กว่าลงไปแล้วด้วยมือ

    ไม่ใส่ปลายทาง = ใช้ **ปลายทางถัดไปที่ควรลง** ของใบนั้น ซึ่งเป็นสิ่งที่
    ถูกเกือบทุกครั้ง — คนติ๊กหลังเพิ่งลงเสร็จ ย่อมลงตามลำดับอยู่แล้ว
    """
    escape = telegram_bot._escape
    parts = (argument or "").split()
    if not parts:
        # **โชว์รายการพร้อมปุ่มติ๊ก ไม่ใช่แค่บอกวิธีพิมพ์**
        # คนที่เพิ่งลงคลิปเสร็จจำชื่อสินค้าได้ ไม่ได้จำเลขลำดับ
        rows = _clips_in_bucket(clip_board.SHOPEE)
        if not rows:
            _clip_say(chat_id, "ไม่มีคลิปที่รอลง Shopee Video อยู่")
            return
        lines = ["✅ <b>ติ๊กว่าลงไปแล้ว</b> — สำหรับคลิปที่โพสต์เองด้วยมือ", "",
                 "ระบบรู้ว่าคลิปขึ้นไปแล้วจากตรงนี้ที่เดียว "
                 "<b>ไม่ติ๊ก = /clipsfb กับ /clipstiktok จะว่างตลอด</b>", ""]
        buttons = []
        for index, run in enumerate(rows, 1):
            name = (run.get("name") or "")[:48]
            lines.append(f"<b>{index}.</b> {escape(name)}")
            if len(buttons) < 10:
                buttons.append([{
                    "text": f"✅ {index}. {name[:26]}",
                    "callback_data":
                        f"clip:posted:shopee_video:{run.get('item_id')}",
                }])
        if len(rows) > len(buttons):
            lines.append(f"\n(ปุ่มแสดง {len(buttons)} อันแรก "
                         f"ที่เหลือพิมพ์ <code>/posted &lt;เลข&gt;</code>)")
        for part in _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT)[:-1]:
            _clip_say(chat_id, part)
        _clip_say(chat_id, _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT)[-1],
                  {"inline_keyboard": buttons})
        return

    want = parts[0]
    rows = _clips_in_bucket(clip_board.SHOPEE)
    if want.isdigit() and 1 <= int(want) <= len(rows):
        item_id = str(rows[int(want) - 1].get("item_id"))
    else:
        item_id = want
    run = clip_store.load_run(DATA_DIR, item_id) or {}
    if not run:
        _clip_say(chat_id, f"ไม่เจองาน <code>{escape(item_id[:30])}</code> — "
                           "พิมพ์ /clips ดูเลขก่อน")
        return

    if len(parts) > 1:
        key = parts[1].lower()
        target = next((t for t in POSTED_LABEL
                       if key in t or t.startswith(key)), "")
        if not target:
            _clip_say(chat_id, "ปลายทางมี: <code>shopee_video</code> · "
                               "<code>facebook_reels</code> · <code>tiktok</code>")
            return
    else:
        target = publish_order.next_target(run)
        if not target:
            _clip_say(chat_id, "ใบนี้ลงครบทั้งสามที่แล้ว 🎉")
            return
    _clip_mark_posted(chat_id, item_id, target)


def _clip_telegram_button(chat_id: str, data: str, callback: dict) -> str:
    """ปุ่มอนุมัติ/สั่งแก้ในแชทบอทคลิป (คำนำหน้า clip: ถูกตัดออกมาแล้ว)

    ทุกทางต้องคืนข้อความสั้นๆ เสมอ — Telegram ต้องได้คำตอบ ไม่งั้นปุ่มบนมือถือ
    จะหมุนค้างจนผู้ใช้คิดว่าแอปแฮงก์
    """
    # รูปแบบ: <action>:<job_id>[:<arg>] — ปุ่มรายรูปต้องส่งลำดับใบมาด้วย
    action, _, rest = data.partition(":")
    job_id, _, arg = rest.partition(":")

    # ปุ่มของ /approveall — ไม่ผูกกับงานใดงานหนึ่ง ต้องดักก่อนไปหาในคิว
    #
    # ปุ่ม "เอากลับทั้งกลุ่ม" ใน /wait — ผูกกับ **ชื่อกลุ่ม** ไม่ใช่รหัสงาน
    # จึงต้องดักก่อนไปหางานในคิวเหมือนกับ apvall
    if action == "unpkg":
        key = job_id                       # ตำแหน่งนี้เป็นชื่อกลุ่ม ไม่ใช่รหัสงาน
        group = next((g for g in clip_board.parked_by_bucket(clip_jobs.parked())
                      if g["key"] == key), None)
        if not group:
            return "ไม่มีกลุ่มนี้ในช่องรอแก้แล้ว — พิมพ์ /wait ดูใหม่"
        # **ต้องบอกได้ว่าใบไหนตกค้าง ไม่ใช่แค่นับจำนวนที่สำเร็จ**
        # (เลน main ทำแบบนี้ฝั่งหน้าเว็บแล้ว ดีกว่าของเดิมที่ผมเขียนไว้)
        # ถ้าบอกแค่ "สำเร็จ 3 จาก 4" คนอ่านต้องไปไล่หาเองว่าใบไหนตก
        done, stuck = [], []
        for item in group["jobs"]:
            try:
                fresh = clip_jobs.unpark(item["id"])
            except clip_queue.ClipQueueError as error:
                stuck.append((item.get("name") or item["id"], str(error)[:50]))
                continue
            done.append(clip_queue.STAGE_LABEL.get(fresh.get("stage") or "",
                                                   fresh.get("stage") or ""))
        clip_runner.wake()
        _clip_log(f"เอางานกลุ่ม {key} ออกจากช่องรอแก้ {len(done)} ใบ"
                  + (f" · ตกค้าง {len(stuck)} ใบ" if stuck else ""))
        if not stuck:
            return f"↩️ เอากลับเข้าขั้นเดิมแล้ว {len(done)} ใบ ({group['title']})"
        names = " · ".join(f"{n} ({why})" for n, why in stuck[:3])
        return (f"↩️ เอากลับได้ {len(done)}/{len(group['jobs'])} ใบ ({group['title']})\n"
                f"ตกค้าง {len(stuck)} ใบ — {names}")

    # แยกสองจังหวะชัดๆ: `ask` = ขอดูก่อน (จากปุ่มใน /pending) · `go` = ยืนยันแล้ว
    # ค่าอื่น/ไม่ระบุถือเป็น `ask` เสมอ — **ผิดพลาดแล้วต้องไม่กลายเป็นการจ่ายเงิน**
    if action == "apvall":
        if arg == "go":
            _clip_approve_all(chat_id, "เลย")
            return "กำลังอนุมัติให้ทั้งหมด"
        _clip_approve_all(chat_id, "")
        return "ดูรายการก่อนยืนยัน"

    # ปุ่ม "เจนคลิปจากงานนี้" ผูกกับ **รหัสสินค้า** ไม่ใช่รหัสงานในคิว
    # (งานเดิมจบไปแล้ว จะสร้างงานใหม่ให้) จึงต้องดักก่อนไปหาในคิว
    if action == "gen":
        return _clip_start_flow(chat_id, arg)

    # ปุ่ม "ดูคลิป" ก็ผูกกับรหัสสินค้าเหมือนกัน — งานในคิวจบไปแล้วแต่ไฟล์ยังอยู่
    if action == "vid":
        return _clip_send_videos(chat_id, arg)

    # ---- การ์ดลง Facebook Reels — ผูกกับ **รหัสสินค้า** ไม่ใช่รหัสงานในคิว --
    #
    # งานขั้นโพสต์ส่วนใหญ่ออกจากคิวไปแล้ว (เจนคลิปจบ = จบงาน) ถ้าปล่อยให้ไหล
    # ไปหาใบงานในคิวข้างล่าง จะเจอ "ไม่มีงานนี้" แล้วปุ่มกดไม่ติดโดยไม่มีอะไรฟ้อง
    if action == "fbcard":
        return _clip_send_fb_card(chat_id, arg)

    # `clip:fbgo:<เครื่อง>:<รหัสสินค้า>` — **ต้องระบุเครื่องเสมอ** (กติกาข้อ 8)
    if action == "fbgo":
        return _clip_fb_post_now(chat_id, job_id, arg)

    # ติ๊กว่าลงปลายทางนั้นไปแล้วด้วยมือ — `clip:posted:<ปลายทาง>:<รหัสสินค้า>`
    if action == "posted":
        return _clip_mark_posted(chat_id, arg, job_id)

    # พัก/เอากลับ งานที่เก็บไว้เป็นไฟล์แล้ว (ไม่มีใบงานในคิว)
    if action in ("rpark", "runpark"):
        return _clip_park_run(chat_id, arg, action == "rpark")

    # ปุ่มจาก /clips — กดเปิดดูงานได้เลย ไม่ต้องพิมพ์ /clip <เลข> เอง
    if action == "open":
        _clip_show_run(chat_id, arg)
        return "เปิดงานให้แล้ว"

    # ✅ ปุ่ม "ทำแล้ว" = **ลงปลายทางปัจจุบันเสร็จแล้ว → เลื่อนไปรอลงที่ถัดไป**
    #
    # เจ้าของนิยามไว้เอง 27 ส.ค. 2569:
    #
    #     คลิปใน /clips                = รอลง Shopee
    #     /clips   + กดทำแล้ว → /clipsfb      = รอลง Facebook
    #     /clipsfb + กดทำแล้ว → /clipstiktok  = รอลง TikTok
    #
    # *"ไม่ต้องทำปุ่มเพิ่ม ให้ใช้เกณฑ์ตามนี้"* — ปุ่มเดิมปุ่มเดียวเดินได้ทั้งสาย
    #
    # **ของเดิมปุ่มนี้เก็บงานออกจากรายการเลย** (ย้ายโฟลเดอร์ไป
    # `shopee_products_done/`) ซึ่งข้ามขั้น Facebook กับ TikTok ไปทั้งคู่
    # เป็นสาเหตุที่ /clipsfb ว่างตลอด — ระบบไม่เคยรู้ว่าคลิปลงที่ไหนไปแล้วบ้าง
    #
    # **เก็บออกจากรายการเมื่อลงครบทั้งสามที่แล้วเท่านั้น** ถึงตอนนั้นไม่มีอะไร
    # ให้ทำต่อจริงๆ การเก็บออกจึงเป็นสิ่งที่ถูก
    if action == "done":
        run = clip_store.load_run(DATA_DIR, arg) or {}
        if not run:
            return "ไม่เจองานชิ้นนี้"
        target = publish_order.next_target(run)
        name = str(run.get("name") or arg)[:40]

        if target:
            try:
                fresh = clip_store.mark_posted(DATA_DIR, arg, target, "")
            except clip_store.ClipStoreError as error:
                return str(error)
            nxt = publish_order.next_target(fresh)
            _clip_log(f"ติ๊กว่า {arg} ลง {target} แล้ว — {name}")
            _clip_say(
                chat_id,
                f"✅ จดแล้วว่าลง <b>{POSTED_LABEL.get(target, target)}</b> แล้ว: "
                f"<b>{telegram_bot._escape(name)}</b>" + '\n' + '\n' +
                telegram_bot._escape(publish_order.summary(fresh)) + '\n' + '\n' +
                (f"ต่อไปอยู่ในรายการ <code>{_LIST_OF.get(nxt, '/clips')}</code> "
                 "— ลงได้ตั้งแต่พรุ่งนี้ (คลิปเดียวกันต้องเว้นอย่างน้อย 1 วัน)"
                 if nxt else "🎉 ลงครบทั้งสามที่แล้ว — กดปุ่มนี้อีกครั้งเพื่อเก็บออกจากรายการ"),
                {"inline_keyboard": [[{
                    "text": "↩️ กดผิด เอากลับ",
                    "callback_data": f"clip:unpost:{target}:{arg}",
                }]]},
            )
            return f"ลง {POSTED_LABEL.get(target, target)} แล้ว ✅"

        # ลงครบสามที่แล้ว — ถึงเวลาเก็บออกจากรายการจริงๆ
        try:
            moved = clip_store.mark_done(DATA_DIR, arg)
        except clip_store.ClipStoreError as error:
            return str(error)
        _clip_log(f"เก็บงาน {arg} ออกจากรายการ (ลงครบสามที่แล้ว) — {name}")
        _clip_say(
            chat_id,
            f"✅ ลงครบทั้งสามที่แล้ว เก็บออกจากรายการ: "
            f"<b>{telegram_bot._escape(str(moved.get('name') or name)[:40])}</b>" + '\n' +
            "ไฟล์ยังอยู่ครบ ย้ายไปโฟลเดอร์ <code>shopee_products_done</code> "
            "— ดูได้ที่ /archive",
            {"inline_keyboard": [[{
                "text": "↩️ เอากลับเข้ารายการ",
                "callback_data": f"clip:undone::{arg}",
            }]]},
        )
        return "เก็บออกจากรายการแล้ว ✅"

    # ↩️ กดปุ่ม "ทำแล้ว" ผิดใบ — ถอนการจดว่าลงแล้วของปลายทางนั้น
    #
    # **ต้องมี** เพราะปุ่มเดียวเดินหน้าทั้งสาย กดพลาดหนึ่งทีคลิปจะข้ามไปรอ
    # ปลายทางถัดไปทันที แล้วรายการเดิมหายไปโดยไม่มีทางกลับ
    if action == "unpost":
        try:
            fresh = clip_store.unmark_posted(DATA_DIR, arg, job_id)
        except clip_store.ClipStoreError as error:
            return str(error)
        _clip_log(f"ถอนการจดว่า {arg} ลง {job_id} แล้ว")
        _clip_say(chat_id, "↩️ ถอนแล้ว — กลับไปรออยู่ที่เดิม" + '\n' +
                  telegram_bot._escape(publish_order.summary(fresh)))
        return "ถอนแล้ว ↩️"

    # 🏷 สั่งทำแฮชแท็กย้อนหลัง — งานเก่าที่เจนคลิปไว้ก่อนมีขั้นนี้ยังไม่มีแท็ก
    if action == "tags":
        try:
            saved = _clip_make_hashtags(arg)
        except Exception as error:                           # noqa: BLE001
            return f"ทำแฮชแท็กไม่สำเร็จ: {error}"
        made = saved.get("hashtags") or []
        if not made:
            return "ทำแฮชแท็กไม่ได้ — งานนี้ไม่มีชื่อสินค้า/จุดเด่นให้ใช้"
        _clip_say(
            chat_id,
            f"🏷 <b>แฮชแท็ก</b> ({len(made)} ตัว)\n"
            f"<code>{telegram_bot._escape(' '.join('#' + tag for tag in made))}</code>",
        )
        return f"ทำแฮชแท็กแล้ว {len(made)} ตัว"

    # ↩️ กดผิด — ย้ายกลับเข้ารายการ
    if action == "undone":
        try:
            back = clip_store.restore_done(DATA_DIR, arg)
        except clip_store.ClipStoreError as error:
            return str(error)
        name = str(back.get("name") or arg)[:40]
        _clip_log(f"เอากลับเข้ารายการ {arg} — {name}")
        return f"เอากลับแล้ว: {name}"

    # ปุ่ม ↩️ ใน /trash — งานอยู่ใน**ถังขยะ ไม่ใช่ในคิว** ต้องดักก่อนไปหาในคิว
    # ไม่งั้นจะตอบ "ไม่พบงานนี้แล้ว" ทั้งที่ของยังอยู่ครบ
    if action == "undo":
        try:
            restored = clip_jobs.restore(job_id)
        except clip_queue.ClipQueueError as error:
            return str(error)
        return f"กู้กลับแล้ว: {str(restored.get('name') or job_id)[:40]}"

    # ปุ่มบนการ์ด /features — ช่องกลางเป็น **รหัสสินค้า** ไม่ใช่รหัสงานในคิว
    #
    # **ต้องดักตรงนี้ ก่อนบรรทัดที่ไปหางานในคิว** งานที่จบไปแล้วไม่มีรายการในคิว
    # อีกต่อไป ถ้าปล่อยให้ไหลลงไปจะตอบ "ไม่พบงานนี้แล้ว" ทั้งที่ของอยู่ครบ
    # (เจอจริง 23 ส.ค. 2026 — ผู้ใช้กดปุ่มแก้ใน /features แล้วขึ้นข้อความนี้)
    # ปุ่มจากข้อความ "ติด CAPTCHA" — ไม่ผูกกับงานใดงานหนึ่ง ต้องดักก่อนหางานในคิว
    if action == "unhold":
        if not clip_jobs.held():
            return "คิวไม่ได้ถูกพักอยู่แล้ว — ทำงานต่อได้ตามปกติ"
        clip_jobs.release_hold()
        clip_runner.wake()
        waiting = sum(1 for j in clip_jobs.all()
                      if j.get("stage") == clip_queue.STAGE_QUEUED)
        _clip_log(f"ผู้ใช้ยืนยันว่าแก้ CAPTCHA แล้ว — ทำงานต่อ (ค้าง {waiting} ใบ)")
        _clip_say(chat_id, f"▶️ <b>ทำงานต่อแล้ว</b> — เหลือในคิว {waiting} ใบ")
        return "ทำงานต่อแล้ว"
    if action == "holdcancel":
        dropped = 0
        for j in clip_jobs.all():
            if j.get("stage") == clip_queue.STAGE_QUEUED:
                try:
                    clip_jobs.update(j["id"], stage=clip_queue.STAGE_CANCELLED)
                    dropped += 1
                except clip_queue.ClipQueueError:
                    pass
        clip_jobs.release_hold()
        _clip_log(f"ผู้ใช้สั่งยกเลิกที่เหลือทั้งหมด — ยกเลิก {dropped} ใบ")
        _clip_say(chat_id, f"🛑 ยกเลิกที่เหลือแล้ว {dropped} ใบ (กู้คืนได้ที่ /trash)")
        return f"ยกเลิกแล้ว {dropped} ใบ"

    if action in ("ft_use", "ft_del", "ft_edit", "ft_new", "ft_sb",
                  "ft_save", "ft_cancel"):
        # ส่งเลขข้อความของการ์ดไปด้วย เพื่อให้แก้ในที่เดิมได้ ไม่ต้องส่งใบใหม่ทุกครั้ง
        card = (callback or {}).get("message") or {}
        return _clip_features_edit(job_id, chat_id, action, arg,
                                   message_id=card.get("message_id") or 0)

    job = clip_jobs.get(job_id)
    if not job:
        return "ไม่พบงานนี้แล้ว"

    # ⏳ ปุ่มจาก /pending — เด้งการ์ดอนุมัติของงานนั้นกลับมา (ปุ่มอนุมัติของเดิม)
    if action == "pend":
        return _clip_resend_card(job)

    # ปุ่ม 🔄 ใน /failed — สั่งทำต่อจากขั้นที่ค้าง
    if action == "again":
        try:
            return _clip_retry_job(job_id, "ปุ่มในแชท")
        except ValueError as error:
            return str(error)

    # ปุ่ม 🅿️ / ↩️ ของช่องรอแก้ (ผู้ใช้สั่ง 27 ส.ค. 2026)
    if action == "park":
        if clip_runner.current == job_id:
            return "งานนี้กำลังทำอยู่ — พักกลางคันไม่ได้ รอให้จบขั้นนี้ก่อน"
        if job.get("parked"):
            return "งานนี้พักไว้อยู่แล้ว — ดูรายการทั้งหมดที่ /wait"
        came = clip_queue.STAGE_LABEL.get(job.get("stage") or "", job.get("stage") or "")
        try:
            clip_jobs.park(job_id, "กดพักจากแชท")
        except clip_queue.ClipQueueError as error:
            return str(error)
        _clip_log(f"พักงาน {job_id} ไว้รอแก้จากแชท (ค้างที่ขั้น {came})")
        return f"🅿️ พักไว้รอแก้แล้ว (ค้างที่ขั้น {came}) — ดูทั้งหมดที่ /wait"

    if action == "unpark":
        if not job.get("parked"):
            return "งานนี้ไม่ได้พักไว้"

        try:
            fresh = clip_jobs.unpark(job_id)
        except clip_queue.ClipQueueError as error:
            return str(error)
        clip_runner.wake()
        came = clip_queue.STAGE_LABEL.get(fresh.get("stage") or "", fresh.get("stage") or "")
        _clip_log(f"เอางาน {job_id} ออกจากช่องรอแก้จากแชท → ขั้น {came}")
        return f"↩️ เอากลับเข้าขั้น “{came}” แล้ว"

    if action == "img_all":
        return _clip_send_all_images(job_id, chat_id)

    if action in ("img_del", "img_swap", "img_add", "img_use"):
        return _clip_edit_images(job_id, chat_id, action, arg)

    if action in ("hl_edit", "hl_del", "hl_add"):
        return _clip_edit_highlights(job_id, chat_id, action, arg)

    if action == "sheet_ok":
        # อนุมัติทั้งใบงานทีเดียว — รูปกับจุดเด่นอยู่ในใบเดียวกันแล้ว
        # ไม่มีเหตุผลให้กดผ่านแยกกันสองครั้งเหมือนของเดิม
        run = clip_store.load_run(DATA_DIR, job.get("item_id", ""))
        if not (run.get("images") and run.get("highlights")):
            return "ยังไม่มีรูปหรือจุดเด่นครบ ส่งเข้า GPT ไม่ได้"
        clip_jobs.update(
            job_id, images_ok=True, highlights_ok=True, awaiting="",
            stage=clip_queue.STAGE_READY_STORYBOARD,
        )
        clip_runner.wake()
        _clip_say(
            chat_id,
            f"✅ <b>อนุมัติใบงานแล้ว</b> — ใช้รูป {len(run['images'])} ใบ · "
            f"จุดเด่น {len(run['highlights'])} ข้อ\nเข้าคิวทำสตอรีบอร์ดต่อ",
        )
        return "อนุมัติใบงานแล้ว ✅"

    if action == "sheet_cancel":
        clip_jobs.update(job_id, stage=clip_queue.STAGE_CANCELLED, awaiting="",
                         note="ผู้ใช้กด Cancel ที่ใบงาน")
        _clip_say(chat_id, "✖️ ยกเลิกใบงานนี้แล้ว — ส่งลิงก์ใหม่ได้ตลอด")
        return "ยกเลิกแล้ว"

    if action in ("img_ok", "hl_ok"):
        # ปุ่มรุ่นเก่า — เหลือไว้ให้ใบงานที่ส่งไปก่อนหน้านี้ยังกดได้
        # ต้องผ่านทั้ง **รูป** และ **จุดเด่น** ถึงจะไปทำสตอรีบอร์ด
        # ทั้งคู่เป็นวัตถุดิบที่ส่งเข้า GPT พอๆ กัน กดผ่านอันเดียวแล้วไปต่อไม่ได้
        field = "images_ok" if action == "img_ok" else "highlights_ok"
        clip_jobs.update(job_id, **{field: True}, awaiting="")
        fresh = clip_jobs.get(job_id) or {}
        if not (fresh.get("images_ok") and fresh.get("highlights_ok")):
            waiting = "จุดเด่น" if fresh.get("images_ok") else "ชุดรูป"
            _clip_say(chat_id, f"👍 รับแล้ว — เหลืออีกอย่าง: <b>{waiting}</b>")
            return "รับแล้ว ✅"
        run = clip_store.load_run(DATA_DIR, fresh.get("item_id", ""))
        clip_jobs.update(job_id, stage=clip_queue.STAGE_READY_STORYBOARD)
        clip_runner.wake()
        _clip_say(
            chat_id,
            f"✅ ใช้รูป {len(run.get('images') or [])} ใบ · "
            f"จุดเด่น {len(run.get('highlights') or [])} ข้อ — เข้าคิวทำสตอรีบอร์ด",
        )
        return "รับครบแล้ว ✅"

    if action == "sb_ok":
        clip_jobs.update(job_id, storyboard_ok=True, awaiting="")
        # งานรุ่นก่อนยังไม่ได้ส่งบทพูดไปพร้อมกัน — ส่งตามให้ตรงนี้ จะได้ไม่ค้าง
        if not job.get("sent_script"):
            run = clip_store.load_run(DATA_DIR, job.get("item_id", ""))
            clip_jobs.update(job_id, sent_script=True)
            _clip_send_script(clip_jobs.get(job_id), run)
        return _clip_after_approve(job_id, chat_id, "อนุมัติสตอรีบอร์ดแล้ว ✅")

    if action == "sc_ok":
        clip_jobs.update(job_id, script_ok=True, awaiting="")
        return _clip_after_approve(job_id, chat_id, "อนุมัติบทพูดแล้ว ✅")

    if action in ("sb_edit", "sc_edit"):
        target = "storyboard" if action == "sb_edit" else "script"
        clip_jobs.update(job_id, awaiting=target)
        what = "สตอรีบอร์ด" if target == "storyboard" else "บทพูด"
        _clip_say(
            chat_id,
            f"✏️ <b>จะแก้{what}ตรงไหน</b>\n"
            "พิมพ์บอกมาได้เลยในข้อความถัดไป เช่น "
            + ("“ฉาก 3 ให้ถ่ายใกล้กว่านี้ เห็นเนื้อผ้าชัดๆ”"
               if target == "storyboard" else
               "“ฉาก 2 พูดสั้นลง ให้เหมือนเพื่อนคุยกันมากกว่านี้”"),
        )
        return f"พิมพ์คำสั่งแก้{what}มาได้เลย"

    if action == "vid_ok":
        # สาย TikTok ยังไม่จบตรงนี้ — ผังกำหนดให้ยืนยันของอีก 4 อย่างก่อนโพสต์
        if _job_kind(job) == "tiktok":
            clip_jobs.update(
                job_id, stage=clip_queue.STAGE_POST_REVIEW, awaiting="",
            )
            _tiktok_send_post_review(clip_jobs.get(job_id))
            return "อนุมัติคลิปแล้ว — ยืนยันอีกครั้งก่อนโพสต์"
        clip_jobs.update(job_id, stage=clip_queue.STAGE_DONE, awaiting="")
        # ตั้งคิวปลายทางไว้รอตัวโพสต์ — แยกสถานะราย Reels / Shopee Video
        # เพราะโพสต์ที่หนึ่งผ่านแต่อีกที่ล้มได้ ต้องรู้ว่าเหลืออันไหนต้องตามเก็บ
        ready = {}
        _clip_keep(
            lambda: ready.update(
                clip_store.mark_ready_to_post(DATA_DIR, job.get("item_id", ""))
            ),
            "สถานะพร้อมโพสต์",
        )
        caption = (ready.get("caption") or "")[:400]
        _clip_say(
            chat_id,
            "✅ <b>อนุมัติคลิปแล้ว</b> — เข้าคิวโพสต์ Facebook Reels + Shopee Video\n\n"
            "<b>แคปชันที่เตรียมไว้</b>\n"
            f"<pre>{telegram_bot._escape(caption)}</pre>",
        )
        return "อนุมัติคลิปแล้ว ✅"

    if action == "vid_edit":
        # ต้องลบไฟล์เดิมก่อน ไม่งั้นตัวเจนเห็นว่ามีไฟล์อยู่แล้วจะข้ามทุกฉาก
        # แล้วส่งคลิปเดิมกลับมาให้ดูซ้ำ ผู้ใช้จะงงว่ากดเจนใหม่แล้วทำไมได้ของเดิม
        run = clip_store.load_run(DATA_DIR, job.get("item_id", ""))
        removed = 0
        for name in run.get("videos", []):
            path = Path(run["folder"]) / name
            if path.is_file():
                path.unlink()
                removed += 1
        # **ลบไฟล์แล้วต้องลบรายการด้วย** ไม่งั้นสมุดบันทึกบอกว่ามีคลิป แต่โฟลเดอร์ว่าง
        # แล้วทุกอย่างที่อ่านสมุดบันทึกจะเชื่อผิด (เจอจริง 23 ส.ค. 2026 — ดู clear_videos)
        _clip_keep(
            lambda: clip_store.clear_videos(DATA_DIR, job.get("item_id", "")),
            "ล้างรายการคลิปเดิม",
        )
        clip_jobs.update(job_id, stage=clip_queue.STAGE_READY_FLOW, awaiting="")
        clip_runner.wake()
        _clip_say(chat_id, f"🔄 ลบคลิปเดิม {removed} ชิ้น แล้วเข้าคิวเจนใหม่")
        return "สั่งเจนใหม่แล้ว"

    # ---- ปุ่มของสาย TikTok repost (ขั้นยืนยันก่อนโพสต์)
    if action == "tt_post":
        clip_jobs.update(job_id, stage=clip_queue.STAGE_POSTING, awaiting="")
        clip_runner.wake()
        _clip_say(chat_id, "🚀 เข้าคิวโพสต์ TikTok แล้ว — เดี๋ยวรายงานผลกลับมา")
        return "เข้าคิวโพสต์แล้ว"

    if action == "tt_skip":
        clip_jobs.update(job_id, stage=clip_queue.STAGE_DONE, awaiting="")
        _clip_say(chat_id, "🗑 ไม่โพสต์คลิปนี้ — เก็บไฟล์ไว้ในเครื่องเหมือนเดิม")
        return "ไม่โพสต์"

    return f"ไม่รู้จักปุ่ม {action}"


clip_watcher.on_text = _clip_telegram_text
clip_watcher.on_command = _clip_telegram_command
clip_watcher.on_callback = _clip_telegram_button


# ------------------------------------- บอทเพิ่มเติมที่ตั้งหน้าที่เป็น "สายเจนคลิป"
#
# ทะเบียนบอทถูกแก้ที่หน้าเว็บ (พอร์ต 8866) แต่ **ตัวอ่านต้องอยู่ที่นี่**
# เพราะ getUpdates ของโทเคนหนึ่งตัวมีตัวอ่านได้ตัวเดียว ถ้า 8866 อ่านด้วยจะชน 409
# และตัวจัดการข้อความของสายคลิป (_clip_telegram_*) ก็อยู่ในไฟล์นี้ไฟล์เดียว
#
# ที่นี่ไม่ได้เป็นคนแก้ทะเบียน จึงวนอ่านซ้ำเป็นระยะแทนการรอสัญญาณข้ามโปรเซส

_clip_extra_watchers: dict[str, object] = {}
EXTRA_SYNC_SECONDS = 30


def _extra_clip_bots() -> dict[str, dict]:
    items = load_config().get("extra_bots")
    if not isinstance(items, list):
        return {}
    return {
        str(bot["id"]): bot for bot in items
        if isinstance(bot, dict) and bot.get("id") and bot.get("role") == "clip"
    }


def _extra_bot_token(bot_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", bot_id)[:40]
    return shared.load_key(DATA_DIR / "bots" / f"{safe}.bin") or ""


def sync_clip_extra_watchers() -> None:
    """เปิด/ปิดตัวเฝ้าของบอทสายคลิปให้ตรงกับทะเบียนล่าสุด"""
    wanted = _extra_clip_bots()
    for bot_id in list(_clip_extra_watchers):
        if bot_id not in wanted:
            _clip_extra_watchers.pop(bot_id).stop()
            _clip_log(f"ปิดตัวเฝ้าของบอทสายคลิป {bot_id}")
    for bot_id, bot in wanted.items():
        if bot_id in _clip_extra_watchers or not _extra_bot_token(bot_id):
            continue
        name = bot.get("name", bot_id)
        watcher = telegram_bot.ApprovalWatcher(
            approval_store,
            get_token=lambda i=bot_id: _extra_bot_token(i),
            log=lambda message, n=name: append_log("clip", f"[{n}] {message}"),
        )
        watcher.on_text = _clip_telegram_text
        watcher.on_command = _clip_telegram_command
        watcher.on_callback = _clip_telegram_button
        _clip_extra_watchers[bot_id] = watcher
        watcher.start()
        _clip_log(f"เปิดตัวเฝ้าข้อความของบอทสายคลิป {name}")


def _extra_sync_loop() -> None:
    while True:
        try:
            sync_clip_extra_watchers()
        except Exception as error:                               # noqa: BLE001
            # ต้องจับทุกชนิด ไม่ใช่แค่ TelegramError — thread ตายเงียบแล้วบอท
            # ที่เพิ่มทีหลังจะไม่มีใครอ่านให้ โดยไม่มีอะไรฟ้อง (เคยเกิดมาแล้ว)
            _clip_log(f"ซิงก์บอทสายคลิปไม่สำเร็จ: {type(error).__name__}: {error}")
        time.sleep(EXTRA_SYNC_SECONDS)


# ------------------------------------------------------------- API ของหน้าเว็บ
#
# หน้าเว็บยังอยู่ที่พอร์ต 8866 ตัวเดิม แค่ยิงถามข้ามมาที่นี่ — จึงต้องเปิด CORS
# ให้เฉพาะเครื่องตัวเอง ไม่เปิดกว้าง (ระบุ origin ตรงๆ ไม่ใช้ "*")
# ทำแบบนี้แทนการสร้างหน้าเว็บใหม่ทั้งหน้า เพราะผู้ใช้ดูงานทุกอย่างที่เดียวสะดวกกว่า

# เปิดให้ชื่อโฮสต์ของ Tailscale ด้วย (<เครื่อง>.<tailnet>.ts.net) — ผู้ใช้เปิดหน้าเว็บ
# จากคอมอีกเครื่องผ่าน Tailscale ได้แล้ว หน้าเว็บจะยิงมาที่นี่ด้วย origin นั้น
# ยังไม่ใช่การเปิดกว้าง: ชื่อ .ts.net เข้าถึงได้เฉพาะเครื่องที่อยู่ใน tailnet เดียวกัน
# (ยืนยันแล้วว่า serve เป็น "tailnet only" ไม่ได้เปิดสู่อินเทอร์เน็ต)
_TAILNET_ORIGIN = r"^https?://[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.ts\.net(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8866", "http://localhost:8866",
        "http://127.0.0.1:8877", "http://localhost:8877",
    ],
    allow_origin_regex=_TAILNET_ORIGIN,
    # เดิมเปิดแค่ GET ตอนที่หน้าเว็บอ่านอย่างเดียว — ตอนนี้สั่งงานจากหน้าเว็บได้แล้ว
    # จึงต้องเปิด POST/DELETE ด้วย แต่ยัง **ล็อก origin ไว้ที่เครื่องตัวเองเหมือนเดิม**
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "service": "clip",
        "version": APP_VERSION,
        "port": PORT,
        "queue": len(clip_jobs.waiting()),
        "busy": clip_runner.busy,
        "browser": shared.who_holds_browser(),
        # บอกตั้งแต่หน้า health ว่าบอทคลิปส่งได้จริงไหม จะได้ไม่ไปรู้ตอนงานจบ
        "clip_bot": clip_bot_status(),
    }


@app.get("/api/clips")
async def clips_list() -> dict:
    """รายการงานเจนคลิปที่เก็บไว้ ใหม่สุดขึ้นก่อน"""
    runs = await asyncio.to_thread(clip_store.list_runs, DATA_DIR)
    # ติดป้ายว่างานแต่ละชิ้นอยู่ขั้นไหน เพื่อให้หน้าเว็บกรองตามหัวข้อได้
    # (ผู้ใช้สั่ง 26 ส.ค. 2026: "แยกงานที่เก็บไว้ตามแต่ละขั้นเลย")
    for run in runs:
        run["bucket"] = clip_board.bucket_of_run(run)
    return {"ok": True, "runs": runs}


def _check_payload(run: dict) -> dict:
    """ผลตรวจคลิปในรูปที่หน้าเว็บวาดได้เลย — ป้ายพร้อมสี + คำเตือนเมื่อผลล้าสมัย

    ต้องแยก "ยังไม่ได้ตรวจ" ออกจาก "ตรวจแล้วไม่ผ่าน" ให้ชัด ไม่งั้นผู้ใช้กดอนุมัติ
    คลิปที่ไม่มีใครดูสักครั้งโดยนึกว่ามันผ่านแล้ว — เจนใหม่รอบหนึ่งเสียเครดิต Flow
    15 หน่วย ซึ่งแพงกว่าการขึ้นป้ายบอกมาก
    """
    result = run.get("video_check") or {}
    has_video = bool(run.get("videos"))
    stale = bool(result) and has_video and _clip_check_stale(run)
    if not has_video:
        note = ""
    elif not result:
        note = "ยังไม่ได้ตรวจคลิปนี้ — สั่ง /recheck ในแชทให้ตรวจได้"
    elif stale:
        note = "ไฟล์เปลี่ยนไปหลังตรวจ — ผลข้างล่างเป็นของไฟล์เก่า สั่ง /recheck ให้ตรวจใหม่"
    else:
        note = ""
    return {
        "checked": bool(result),
        "stale": stale,
        "ok": bool(result.get("ok")),
        "chips": clip_check.chips(result),
        "note": note,
        "problems": list(result.get("problems") or []),
    }


@app.get("/api/clips/{item_id}")
async def clips_detail(item_id: str) -> dict:
    """งานหนึ่งชิ้นพร้อมของดิบ — คำตอบเต็มของ GPT และรายละเอียดสินค้า"""
    run = await asyncio.to_thread(clip_store.load_run, DATA_DIR, item_id)
    if not run:
        raise HTTPException(status_code=404, detail="ไม่พบงานนี้")
    # ผลตรวจคลิปกับลำดับการลง ต้องมาที่หน้ารายละเอียดของ **งานที่เก็บไว้** ด้วย
    # ไม่ใช่เฉพาะงานที่ยังอยู่ในคิว — ตอนจะโพสต์จริงผู้ใช้เปิดดูจากตรงนี้
    return {
        "ok": True, **run,
        "video_check_view": _check_payload(run),
        "publish_order": publish_order.rows(run),
        "publish_next": publish_order.next_target(run),
    }


@app.get("/api/clips/{item_id}/file/{name:path}")
async def clips_file(item_id: str, name: str) -> FileResponse:
    """ส่งไฟล์ในโฟลเดอร์งาน (รูปสินค้า / ภาพสตอรีบอร์ด / คลิป) ให้หน้าเว็บแสดง"""
    try:
        path = clip_store.file_path(DATA_DIR, item_id, name)
    except clip_store.ClipStoreError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์")
    return FileResponse(path)


@app.post("/api/clips/{item_id}/generate")
async def clips_generate(item_id: str, request: Request) -> dict:
    """สั่งเจนคลิปของสินค้านี้เดี๋ยวนี้ ด้วยคำสั่ง Flow ที่ทำไว้แล้ว

    ใช้ตอนอยากเจนซ้ำหรือเจนจากหน้าเว็บ/เครื่องมือ โดยไม่ต้องเข้าคิวและไม่ต้องกด
    ปุ่มในแชท — งานกินเวลาหลายนาที จึงแยกเธรดแล้วตอบกลับทันที ดูความคืบหน้าที่
    /api/log ส่วนการกันงานซ้อนใช้ `browser_lock` ตัวเดียวกับคิว (Chrome โปรไฟล์
    เดียวเปิดซ้อนไม่ได้)
    """
    run = await asyncio.to_thread(clip_store.load_run, DATA_DIR, item_id)
    if not run:
        raise HTTPException(status_code=404, detail="ไม่พบงานของสินค้านี้")
    if not (run.get("flow_prompts") or []):
        raise HTTPException(status_code=400, detail="งานนี้ยังไม่มีคำสั่งสำหรับ Google Flow")
    if clip_runner.busy:
        raise HTTPException(status_code=409, detail="คิวกำลังทำงานอยู่ รอให้จบก่อน")

    payload = {}
    try:
        payload = await request.json()
    except Exception:
        pass
    chat_id = str(payload.get("chat_id") or shared.read_config().get("telegram_clip_chat_id") or "")
    job = {"id": f"manual-{item_id}", "chat_id": chat_id, "item_id": item_id}

    def work() -> None:
        try:
            _clip_generate(job)
        except Exception as error:                              # noqa: BLE001
            # ต้องลง log เสมอ ไม่ใช่ส่งเข้าแชทอย่างเดียว — ความล้มเหลวที่ไม่มี log
            # คือความล้มเหลวที่ไล่ต่อไม่ได้
            _clip_log(f"สั่งเจนตรงล้มเหลว: {type(error).__name__}: {error}")

    threading.Thread(target=work, daemon=True).start()
    _clip_log(f"สั่งเจนคลิปตรงสำหรับ {item_id} ({len(run['flow_prompts'])} ฉาก)")
    return {"ok": True, "message": "เริ่มเจนแล้ว — ดูความคืบหน้าที่ /api/log", "item_id": item_id}


@app.get("/api/queue")
async def queue_list() -> dict:
    """คิวงานทั้งหมด พร้อมคำอธิบายสถานะเป็นภาษาคน"""
    jobs = clip_jobs.all()
    for job in jobs:
        job["stage_label"] = clip_queue.STAGE_LABEL.get(job.get("stage"), job.get("stage", ""))
    # ภาระคิว + เพดาน "ทำทีละ 8" — หน้าเว็บต้องโชว์ ไม่งั้นผู้ใช้ส่งลิงก์ 33 ใบ
    # แล้วเห็นขยับแค่ 8 ใบ จะนึกว่าระบบค้าง (กติกา CLAUDE.md ข้อ 2.7.1)
    return {"ok": True, "jobs": jobs, "busy": clip_runner.busy,
            "load": clip_jobs.load_now(), "load_text": clip_jobs.load_text()}


# ------------------------------- สั่งงานสายเจนคลิปจากหน้าเว็บ (ทำได้ทั้งสองทาง)
#
# **หลักการเดียวที่ห้ามแหก**: หน้าเว็บไม่มีตรรกะเป็นของตัวเอง ทุกเส้นทางข้างล่าง
# วิ่งเข้า `_clip_telegram_button` / `_apply_edit_text` ซึ่งเป็นชุดเดียวกับที่ปุ่ม
# ในแชทกด ถ้าเขียนแยกกันสองชุด พอแก้ข้างเดียวพฤติกรรมจะเพี้ยนกันเงียบๆ แล้วไล่ยาก
#
# งานที่สร้างจากหน้าเว็บผูก chat_id ของสายคลิปไว้ด้วย ทุกอย่างจึงยังเด้งเข้า
# Telegram เหมือนเดิม — เปิดค้างไว้ทางไหนก็เห็นตรงกัน ไม่มีทางไหนเป็นทางลับ

# กันสองคำสั่งจากหน้าเว็บชนกันเอง (กดรัวหรือเปิดหลายแท็บ) — งานหนักจริงอยู่ใน
# เธรดของตัวรัน ตรงนี้แค่เปลี่ยนสถานะกับส่งข้อความ จึงถือล็อกสั้นมาก
_web_lock = threading.Lock()

# ปุ่มที่สั่งจากหน้าเว็บได้ — ตัด *_edit ออกเพราะมันแค่ "ตั้งท่ารอพิมพ์" ซึ่งเป็น
# ท่าของแชทที่ต้องพิมพ์ข้อความตามมาอีกที หน้าเว็บใช้ /revise กับ /highlight
# ที่จบในครั้งเดียวแทน
WEB_ACTIONS = {
    # img_use = เลือกรูปใบเจาะจงจากคลัง — หน้าเว็บโชว์คลังให้กดเลือกได้แล้ว
    # (25 ส.ค. 2026 ลืมใส่ตัวนี้ กดรูปในคลังแล้วเซิร์ฟเวอร์ตอบ 400 รูปไม่เข้า
    #  โดยหน้าเว็บไม่ได้บอกอะไร ผู้ใช้เห็นแค่ "กดแล้วไม่มีอะไรเกิดขึ้น")
    "img_ok", "img_del", "img_swap", "img_add", "img_use",
    "hl_ok", "hl_del",
    "sb_ok", "sc_ok",
    "vid_ok", "vid_edit",
    "tt_post", "tt_skip",
}


# คำสั่งชุดนี้กำลังมาจากหน้าเว็บอยู่หรือเปล่า
#
# ใช้ตัดสินว่าต้องยิงการ์ดกลับเข้าแชทไหม — สั่งจากแชทต้องยิง (คนรออยู่ในแชท)
# สั่งจากเว็บไม่ต้อง (หน้าเว็บวาดเองอยู่แล้ว) การยิงคืออัปโหลดรูปทั้งอัลบั้ม
# ซึ่งกินเวลาหลายวินาทีต่อการกดหนึ่งครั้ง
#
# เป็น global ธรรมดาได้เพราะทุกคำสั่งจากเว็บถูกจัดคิวด้วย `_web_lock` อยู่แล้ว
# ไม่มีทางมีสองคำสั่งจากเว็บทับกัน
_WEB_CALL = False


def _web_call() -> bool:
    return _WEB_CALL


@contextlib.contextmanager
def _as_web_call():
    """ทำเครื่องหมายว่าช่วงนี้คือคำสั่งจากหน้าเว็บ — ต้องอยู่ในกรอบ `_web_lock` เสมอ"""
    global _WEB_CALL
    before = _WEB_CALL
    _WEB_CALL = True
    try:
        yield
    finally:
        _WEB_CALL = before


def _default_clip_chat() -> str:
    return str(load_config().get("telegram_clip_chat_id", "") or "")


def _find_job(job_id: str) -> dict:
    job = clip_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ไม่พบงานนี้ในคิว")
    return job


def _job_card(job: dict, run: dict | None = None) -> dict:
    """ข้อมูลงานหนึ่งแถวสำหรับหน้าเว็บ — พอให้ตัดสินใจได้โดยไม่ต้องเปิดดูรายละเอียด"""
    run = run or {}
    return {
        **job,
        "stage_label": clip_queue.STAGE_LABEL.get(job.get("stage"), job.get("stage", "")),
        "name": job.get("name") or run.get("name", ""),
        "storyboard_count": run.get("storyboard_count", 0),
        "script_count": run.get("script_count", 0),
        "video_count": len(run.get("videos") or []),
        "needs_review": job.get("stage") in REVIEW_STAGES,
        "running": clip_runner.current == job.get("id"),
        "open": job.get("stage") in clip_queue.OPEN_STAGES,
    }


@app.post("/api/jobs")
async def jobs_add(request: Request) -> dict:
    """วางลิงก์จากหน้าเว็บแล้วต่อคิว — วางหลายลิงก์รวดเดียวได้เหมือนในแชท"""
    payload = await request.json()
    text = str(payload.get("links") or payload.get("link") or "")

    # เช็ค TikTok ก่อน Shopee เสมอ ให้ตรงกับฝั่งแชท (เหตุผลอยู่ที่ TIKTOK_LINK_RE)
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for kind, pattern in (("tiktok", TIKTOK_LINK_RE), ("shopee", SHOPEE_LINK_RE)):
        for link in pattern.findall(text):
            if link not in seen:
                seen.add(link)
                links.append((kind, link))
    if not links:
        raise HTTPException(
            status_code=400,
            detail="ไม่พบลิงก์ Shopee หรือ TikTok ในข้อความที่วางมา",
        )

    def work() -> list[str]:
        chat_id = _default_clip_chat()
        added = []
        with _web_lock:
            waiting = len(clip_jobs.waiting())
            for kind, link in links:
                job = clip_jobs.add(link, chat_id)
                clip_jobs.update(job["id"], kind=kind, source="web")
                added.append(job["id"])
                _clip_log(f"เข้าคิวจากหน้าเว็บ {job['id']} [{kind}] — {link[:60]}")
        clip_runner.wake()
        # บอกในแชทด้วยว่ามีของเข้าคิวจากหน้าเว็บ ไม่งั้นคนที่เฝ้าอยู่ฝั่งแชท
        # จะเห็นงานโผล่มาเองโดยไม่รู้ว่ามาจากไหน
        _clip_say(
            chat_id,
            f"🖥 เพิ่มจากหน้าเว็บ <b>{len(added)}</b> ลิงก์เข้าคิวแล้ว "
            f"(ในคิวตอนนี้ {waiting + len(added)} งาน)",
        )
        return added

    added = await asyncio.to_thread(work)
    # ส่งเพดาน "ทำทีละ 8" กลับไปด้วย **ตั้งแต่ตอนรับลิงก์** (กติกา CLAUDE.md 2.7.1)
    # วางลิงก์ 33 ใบแล้วเห็นขยับ 8 ใบ ถ้าไม่บอกตรงนี้ ผู้ใช้จะนึกว่าระบบค้าง
    return {
        "ok": True, "added": added, "count": len(added),
        "waiting": len(clip_jobs.waiting()),
        "load": clip_jobs.load_now(), "load_text": clip_jobs.load_text(),
    }


@app.get("/api/jobs")
async def jobs_list() -> dict:
    """คิวทั้งหมด ใหม่สุดอยู่ล่างตามลำดับที่จะถูกหยิบไปทำ"""
    def build() -> dict:
        cards = []
        for job in clip_jobs.all():
            item_id = job.get("item_id") or ""
            run = clip_store.load_run(DATA_DIR, item_id) if item_id else {}
            cards.append(_job_card(job, run))
        return {
            "ok": True,
            "jobs": cards,
            "busy": clip_runner.busy,
            "current": clip_runner.current,
            "waiting": len(clip_jobs.waiting()),
            "flow_enabled": flow_enabled(),
            # เพดาน "ทำทีละ 8" — หน้าเว็บดึงรายการคิวจากที่นี่ ไม่ใช่ /api/queue
            # ต้องส่งไปด้วย ไม่งั้นผู้ใช้เห็นลิงก์ค้างแล้วนึกว่าระบบพัง
            "load": clip_jobs.load_now(),
            "load_text": clip_jobs.load_text(),
        }

    return await asyncio.to_thread(build)


@app.get("/api/jobs/{job_id}")
async def jobs_detail(job_id: str) -> dict:
    """งานหนึ่งชิ้นพร้อมของที่ต้องใช้ตรวจในขั้นปัจจุบัน"""
    def build() -> dict:
        job = clip_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="ไม่พบงานนี้ในคิว")
        item_id = job.get("item_id") or ""
        run = clip_store.load_run(DATA_DIR, item_id) if item_id else {}
        # ลำดับการลง (Shopee → Facebook → TikTok เว้น 1 วัน) — คำนวณให้หน้าเว็บ
        # ที่ `publish_order.rows()` ที่เดียว ห้ามให้หน้าเว็บคิดเอง ไม่งั้นกติกา
        # จะมีสองชุดที่เพี้ยนกันได้เงียบๆ ตอนแก้ข้างเดียว
        order = publish_order.rows(run)
        return {
            "ok": True,
            "job": _job_card(job, run),
            "run": run,
            "max_images": CLIP_MAX_IMAGES,
            "max_highlights": CLIP_MAX_HIGHLIGHTS,
            # เมนูโมเดลของปุ่ม "ให้ AI ดูรูปแล้วเขียนจุดเด่น" (ผู้ใช้สั่ง 27 ส.ค. 2026)
            # ส่งทั้งเมนูไปให้หน้าเว็บวาดเอง — เพิ่ม/ตัดโมเดลที่ `shopee_scrape` ที่เดียว
            # แล้วดรอปดาวน์เปลี่ยนตาม ไม่ต้องแก้หน้าเว็บ (เหมือน `framing_menu`)
            "highlight_models": [dict(row) for row in shopee_scrape.IMAGE_HIGHLIGHT_MENU],
            # แนวการวางกล้องของสตอรีบอร์ด — ส่งทั้งเมนูและค่าที่ใช้อยู่ไปให้
            # หน้าเว็บวาดเอง เพิ่มตัวเลือกใหม่ที่ `clip_rules.MODES` ที่เดียว
            # แล้วปุ่มจะโผล่เองโดยไม่ต้องแก้หน้าเว็บ
            "framing_menu": clip_rules.menu(),
            "framing": clip_rules.full_shot_of(run),
            # งานใบนี้เคยเลือกเองหรือยัง — ยังไม่เคย = กำลังใช้ค่าที่จำไว้ล่าสุด
            # ต้องบอกให้หน้าเว็บรู้ ไม่งั้นผู้ใช้แยกไม่ออกว่าเลือกไว้เองหรือได้มาอัตโนมัติ
            "framing_own": run.get("story_full_shot") is not None,
            # เกณฑ์ความยาวบทพูด — ส่งไปให้หน้าเว็บนับตามเกณฑ์เดียวกับที่สั่ง GPT
            #
            # **ต้องส่งค่าไป ห้ามให้หน้าเว็บตั้งเลขเอง** ไม่งั้นวันหนึ่งแก้เกณฑ์ฝั่งนี้
            # แล้วหน้าเว็บยังเตือนด้วยเลขเก่า — ผู้ใช้จะแก้บทตามตัวเลขที่ไม่ตรงกับ
            # ที่ระบบใช้จริง (หลักการเดียวกับ publish_order: กติกามีชุดเดียว)
            #
            # `thai_chars_per_word` คือสูตรประมาณจำนวนคำไทย — **ห้ามนับตามช่องว่าง**
            # ภาษาไทยไม่เว้นวรรคระหว่างคำ วัดของจริงแล้วบทพูด ~40 คำ นับตามช่องว่าง
            # ได้แค่ 15 (เหตุผลเต็มอยู่ที่ `chatgpt_driver.count_words`)
            "script_min_words": chatgpt_driver.SCRIPT_MIN_WORDS,
            "script_max_words": chatgpt_driver.SCRIPT_MAX_WORDS,
            "thai_chars_per_word": chatgpt_driver.THAI_CHARS_PER_WORD,
            "script_words": chatgpt_driver.count_words(run.get("script") or []),
            "flow_enabled": flow_enabled(),
            # ผลตรวจคลิป (1080p · เสียงพูด · ตัวอักษรอ่านออก) อยู่ใน run.video_check
            # อยู่แล้ว — ยกขึ้นมาไว้ชั้นบนด้วยเพื่อให้หน้าเว็บหาเจอง่าย
            "video_check": run.get("video_check") or {},
            # ...และรูปที่วาดได้เลย (ป้ายพร้อมสถานะ) จะได้ไม่ต้องตีความเองสองที่
            "video_check_view": _check_payload(run),
            "publish_order": order,
            "publish_next": publish_order.next_target(run),
        }

    return await asyncio.to_thread(build)


@app.post("/api/jobs/{job_id}/action")
async def jobs_action(job_id: str, request: Request) -> dict:
    """กดปุ่มเดียวกับในแชท — `index` เป็นลำดับเริ่มที่ 1 เหมือนที่ปุ่มในแชทส่ง"""
    payload = await request.json()
    action = str(payload.get("action") or "")
    index = payload.get("index")
    if action not in WEB_ACTIONS:
        raise HTTPException(status_code=400, detail=f"ปุ่ม “{action}” สั่งจากหน้าเว็บไม่ได้")
    job = _find_job(job_id)
    try:
        arg = "" if index in (None, "") else str(int(index))
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="index ต้องเป็นตัวเลข") from error

    def work() -> str:
        with _web_lock, _as_web_call():
            return _clip_telegram_button(
                job.get("chat_id", ""), f"{action}:{job_id}:{arg}", {},
            )

    message = await asyncio.to_thread(work)
    return {"ok": True, "message": message}


@app.post("/api/jobs/{job_id}/revise")
async def jobs_revise(job_id: str, request: Request) -> dict:
    """สั่งแก้สตอรีบอร์ด/บทพูดจบในครั้งเดียว (ในแชทต้องกดปุ่มแล้วพิมพ์ตามอีกที)"""
    payload = await request.json()
    target = str(payload.get("target") or "storyboard")
    instruction = str(payload.get("instruction") or "").strip()
    if target not in ("storyboard", "script"):
        raise HTTPException(status_code=400, detail="แก้ได้เฉพาะ storyboard หรือ script")
    if not instruction:
        raise HTTPException(status_code=400, detail="พิมพ์คำสั่งแก้มาด้วยว่าจะแก้ตรงไหน")

    job = _find_job(job_id)
    # ยอมให้สั่งแก้งานที่ **ล้มเหลว** ได้ด้วย — รอบสั่งแก้ที่พังไม่ได้ทำให้ของหาย
    # ห้ามบังคับให้ต้องเริ่มใหม่ทั้งงานเพียงเพราะรอบก่อนไม่สำเร็จ
    if job.get("stage") not in REVIEW_STAGES | {clip_queue.STAGE_FAILED}:
        label = clip_queue.STAGE_LABEL.get(job.get("stage"), job.get("stage", ""))
        raise HTTPException(status_code=409, detail=f"งานนี้อยู่ขั้น “{label}” ยังสั่งแก้ไม่ได้")

    def work() -> str:
        with _web_lock, _as_web_call():
            return _apply_edit_text(clip_jobs.get(job_id) or job, instruction, target)

    message = await asyncio.to_thread(work)
    return {"ok": True, "message": message}


@app.post("/api/jobs/{job_id}/highlights")
async def jobs_highlights_bulk(job_id: str, request: Request) -> dict:
    """บันทึกจุดเด่น **ทั้งชุดรวดเดียว** — ให้ปุ่ม "ยืนยัน" ในหน้าเว็บใช้

    **ทำไมต้องมีตัวนี้ ไม่ใช่ยิงทีละข้อรัวๆ ตอนกดยืนยัน**
        ผู้ใช้สั่งไว้ 23 ส.ค. ว่าอยากแก้ให้ครบก่อนแล้วกดส่งทีเดียว ("ลบจุดเด่น 3
        เพิ่ม 6 7 8 เสร็จปุ๊บกดส่งครั้งเดียว") ถ้าหน้าเว็บสะสมเองแล้วยิงทีละข้อ
        ตอนกด พอขาดกลางคัน (เน็ตหลุด · ปิดหน้า) จะเหลือครึ่งๆ **ซึ่งแย่กว่า
        ไม่ได้แก้เลย** เพราะไม่มีใครรู้ว่ามันหยุดตรงไหน
        ที่นี่เขียนลงไฟล์ครั้งเดียวจบ — ได้หมดหรือไม่ได้เลย

    ฝั่งแชทมีที่พักของตัวเอง (`_feature_drafts`) ทำงานเหมือนกันอยู่แล้ว
    """
    payload = await request.json()
    raw = payload.get("highlights")
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="ต้องส่ง highlights มาเป็นรายการ")
    texts, seen = [], set()
    for item in raw:
        text = str(item or "").strip()
        if not text or text in seen:
            continue                    # ข้อว่าง/ซ้ำ ตัดทิ้งเงียบได้ ไม่ใช่ความผิดพลาด
        seen.add(text)
        texts.append(text)
    if not texts:
        raise HTTPException(status_code=400, detail="ต้องเหลือจุดเด่นอย่างน้อย 1 ข้อ")
    if len(texts) > CLIP_MAX_HIGHLIGHTS:
        raise HTTPException(status_code=400,
                            detail=f"เก็บได้สูงสุด {CLIP_MAX_HIGHLIGHTS} ข้อ (ส่งมา {len(texts)})")

    job = _find_job(job_id)
    item_id = job.get("item_id") or ""
    if not item_id:
        raise HTTPException(status_code=409, detail="งานนี้ยังไม่มีข้อมูลสินค้า")

    def work() -> dict:
        with _web_lock:
            before = list((clip_store.load_run(DATA_DIR, item_id) or {}).get("highlights") or [])
            run = clip_store.set_highlights(DATA_DIR, item_id, texts)
            return {"before": before, "after": list(run.get("highlights") or [])}

    result = await asyncio.to_thread(work)
    added = [t for t in result["after"] if t not in result["before"]]
    removed = [t for t in result["before"] if t not in result["after"]]
    bits = []
    if added:
        bits.append(f"เพิ่ม {len(added)}")
    if removed:
        bits.append(f"เอาออก {len(removed)}")
    _clip_log(f"บันทึกจุดเด่นทั้งชุดของ {item_id} — เหลือ {len(result['after'])} ข้อ"
              + (f" ({' · '.join(bits)})" if bits else " (ไม่เปลี่ยน)"))
    return {"ok": True, "highlights": result["after"], "added": added, "removed": removed,
            "message": f"บันทึกจุดเด่นแล้ว {len(result['after'])} ข้อ"
                       + (f" · {' · '.join(bits)}" if bits else "")}


@app.post("/api/jobs/{job_id}/images")
async def jobs_images_bulk(job_id: str, request: Request) -> dict:
    """เลือกชุดรูป **ทั้งชุดรวดเดียว** — เหตุผลเดียวกับ `/highlights` ข้างบน

    ส่ง `images` มาเป็นรายชื่อไฟล์ที่ต้องการใช้ (ต้องเป็นชื่อที่มีอยู่ในคลังของงานนี้)
    """
    payload = await request.json()
    raw = payload.get("images")
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="ต้องส่ง images มาเป็นรายการ")

    job = _find_job(job_id)
    item_id = job.get("item_id") or ""
    if not item_id:
        raise HTTPException(status_code=409, detail="งานนี้ยังไม่มีข้อมูลสินค้า")
    picked, seen = [], set()
    for item in raw:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        picked.append(name)
    if not picked:
        raise HTTPException(status_code=400, detail="ต้องเลือกรูปอย่างน้อย 1 ใบ")
    if len(picked) > CLIP_MAX_IMAGES:
        raise HTTPException(status_code=400,
                            detail=f"เลือกได้สูงสุด {CLIP_MAX_IMAGES} ใบ (ส่งมา {len(picked)})")

    def work() -> list[str]:
        # อ่านคลังของจริง **ในล็อก** ไม่ใช่อ่านไว้ก่อนแล้วค่อยเข้าล็อก ไม่งั้นถ้ามีอีกทาง
        # (ปุ่มในแชท) แก้ชุดรูปคั่นกลาง เราจะเขียนทับด้วยคลังรุ่นเก่าที่อ่านมาก่อน
        with _web_lock:
            run = clip_store.load_run(DATA_DIR, item_id) or {}
            # **ลำดับคลังต้องคงเดิม** ของเดิมหยิบจาก set ซึ่งไม่มีลำดับ ทำให้คลังสำรอง
            # บนหน้าเว็บสลับที่ใหม่ทุกครั้งที่กดบันทึก แล้วผู้ใช้หาใบที่เพิ่งดูอยู่ไม่เจอ
            known: list[str] = []
            for name in list(run.get("images") or []) + list(run.get("image_pool") or []):
                if name not in known:
                    known.append(name)
            # กันชื่อไฟล์ที่ไม่ได้มาจากคลังของงานนี้ — หน้าเว็บส่งอะไรมาก็ได้
            missing = [n for n in picked if n not in known]
            if missing:
                raise clip_store.ClipStoreError(f"ไม่มีรูป {missing[0]} ในคลังของงานนี้")
            pool = [n for n in known if n not in seen]
            updated = clip_store.set_images(DATA_DIR, item_id, picked, pool)
            return list(updated.get("images") or [])

    try:
        after = await asyncio.to_thread(work)
    except clip_store.ClipStoreError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    _clip_log(f"บันทึกชุดรูปทั้งชุดของ {item_id} — ใช้ {len(after)} ใบ")
    return {"ok": True, "images": after,
            "message": f"บันทึกชุดรูปแล้ว {len(after)} ใบ"}


@app.post("/api/jobs/{job_id}/script")
async def jobs_script_save(job_id: str, request: Request) -> dict:
    """บันทึกบทพูดที่ผู้ใช้พิมพ์แก้เอง **ทั้งชุดรวดเดียว** (ผู้ใช้สั่ง 26 ส.ค. 2026)

    เดิมแก้บทพูดได้ทางเดียวคือสั่งให้ AI เขียนใหม่ (`sc_edit`) ซึ่งต้องอธิบายเป็น
    คำพูดว่าอยากได้แบบไหน แล้วรอมันตีความ — ผิดคำเดียวก็ต้องสั่งใหม่ทั้งฉาก
    ทั้งที่บางทีแค่อยากเปลี่ยนคำเดียว ตอนนี้พิมพ์ทับลงไปตรงๆ ได้เลย

    **เขียนทั้งชุดครั้งเดียวจบ** เหมือน `/highlights` — ไม่ใช่ทยอยทีละฉาก
    ถ้าขาดกลางคันจะเหลือบทพูดครึ่งเก่าครึ่งใหม่ ซึ่งไล่ไม่ออกว่าฉากไหนคือของใหม่

    จำนวนฉากต้องเท่าเดิม — ด่านอยู่ที่ `clip_store.set_script()` ที่เดียว
    """
    payload = await request.json()
    raw = payload.get("script")
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="ต้องส่ง script มาเป็นรายการ")

    job = _find_job(job_id)
    item_id = job.get("item_id") or ""
    if not item_id:
        raise HTTPException(status_code=409, detail="งานนี้ยังไม่มีข้อมูลสินค้า")

    def work() -> dict:
        with _web_lock:
            before = list((clip_store.load_run(DATA_DIR, item_id) or {}).get("script") or [])
            run = clip_store.set_script(DATA_DIR, item_id, raw)
            return {"before": before, "after": list(run.get("script") or [])}

    try:
        result = await asyncio.to_thread(work)
    except clip_store.ClipStoreError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    before, after = result["before"], result["after"]
    changed = [i + 1 for i, text in enumerate(after)
               if i >= len(before) or text != before[i]]
    if changed:
        _clip_log(f"ผู้ใช้พิมพ์แก้บทพูดของ {item_id} — ฉาก {changed}")
        for i in changed:
            _clip_log(f"   ฉาก {i}: {before[i - 1] if i <= len(before) else '—'}"
                      f"  →  {after[i - 1]}")
    else:
        _clip_log(f"กดบันทึกบทพูดของ {item_id} แต่ไม่มีอะไรเปลี่ยน")
    return {
        "ok": True, "script": after, "changed": changed,
        "message": (f"บันทึกบทพูดแล้ว — แก้ไป {len(changed)} ฉาก "
                    f"(ฉาก {', '.join(str(i) for i in changed)})")
                   if changed else "บทพูดเหมือนเดิม ไม่มีอะไรเปลี่ยน",
    }


@app.get("/api/board")
async def clip_board_view() -> dict:      # ห้ามตั้งชื่อ `clip_board` — ทับชื่อโมดูล
    """กระดาน 6 ขั้น — งานไหนค้างอยู่ตรงไหน (ผู้ใช้สั่ง 26 ส.ค. 2026)

    *"ตอนนี้ผมงงกับงานมากไม่รู้ว่าอันไหนอยู่ stage ไหนเท่าไรบ้าง"*

    **ฝั่งเซิร์ฟเวอร์เป็นคนตัดสินว่างานอยู่กองไหน ห้ามให้หน้าเว็บคิดเอง**
    เพราะกอง 4–6 ใช้ `publish_order` ตัวเดียวกับด่านที่กั้นก่อนโพสต์จริง
    ถ้าเขียนแยกกันสองชุด วันหลังจะกลายเป็น "กระดานบอกว่าลงได้ แต่กดแล้วโดนปฏิเสธ"
    แล้วไม่มีใครรู้ว่าฝั่งไหนถูก (กติกาข้อ 2.8 ของโปรเจกต์)
    """
    def work() -> dict:
        jobs = clip_jobs.all()
        # **ส่งไฟล์งานเข้าไปด้วย** ไม่งั้นกองปลายทางจะนับได้แค่ใบที่ยังอยู่ในคิว
        # วัดจริง 27 ส.ค. 2569: `/clips` บอก 25 ใบ แต่กระดานบอก 8 ใบ — หายไป 17
        runs = clip_store.list_runs(DATA_DIR)
        board = clip_board.build(
            jobs, lambda item: clip_store.load_run(DATA_DIR, item), runs)
        # **ของซ้ำต้องดังขึ้นบนหน้าจอ ไม่ใช่รอให้คนมานั่งนับโฟลเดอร์เอง**
        # สินค้าที่มีโฟลเดอร์สองชุด ชุดที่มีคลิปจะหายจากทุกรายการเงียบๆ
        # (เจอจริง 4 คู่ เมื่อ 27 ส.ค. 2569 — กว่าจะรู้ก็ตอนย้ายโฟลเดอร์)
        dup = clip_store.duplicates(DATA_DIR)
        board["duplicates"] = dup
        board["warning"] = ("" if not dup else
            f"⚠️ มีสินค้า {len(dup)} ชิ้นที่มีโฟลเดอร์งานซ้อนกันสองชุด — "
            "ชุดที่มีคลิปอาจถูกมองข้าม สั่ง <code>/dup</code> ในแชทเพื่อดู")
        return board

    return {"ok": True, **await asyncio.to_thread(work)}


@app.get("/api/posted")
async def posted_view() -> dict:
    """สมุดบันทึกการลง — ลงอะไรไปแล้วบ้าง ที่ไหน เมื่อไร (ผู้ใช้สั่ง 27 ส.ค. 2569)

    *"ผมจำไม่ได้ว่าโพสต์อันไหนบ้าง ไม่มีลิ้สที่จดไว้ว่าลงแล้วหรอ บอกให้จด"*

    คืนรายการเรียงใหม่สุดขึ้นก่อน + สรุปรายวัน ให้หน้าเว็บวาดได้เลยไม่ต้องคิดเอง
    """
    def work() -> dict:
        rows = clip_store.posted_history(DATA_DIR)
        days: dict[str, int] = {}
        for row in rows:
            days[str(row["at"])[:10]] = days.get(str(row["at"])[:10], 0) + 1
        return {
            "rows": rows,
            "total": len(rows),
            "by_day": [{"day": d, "count": c} for d, c in days.items()],
            # เคสว่างต้องบอกให้ชัดว่าทำไมว่าง ไม่ใช่ปล่อยหน้าเปล่า
            "empty_note": ("ระบบยังไม่เคยจดว่าลงคลิปไหนไปเลย — "
                           "คลิปที่โพสต์เองด้วยมือต้องกดปุ่ม ✅ บอกระบบก่อน"
                           if not rows else ""),
        }
    return {"ok": True, **await asyncio.to_thread(work)}


@app.post("/api/jobs/{item_id}/posted")
async def jobs_mark_posted(item_id: str, request: Request) -> dict:
    """จดว่าคลิปนี้ลงปลายทางนั้นไปแล้ว — สำหรับคลิปที่โพสต์เองด้วยมือ

    body `{"target": "shopee_video"}` — ไม่ส่ง `target` มา = ใช้ปลายทางถัดไป
    ที่ควรลงของใบนั้น ซึ่งถูกเกือบทุกครั้งเพราะคนกดหลังเพิ่งลงเสร็จ

    ส่ง `{"undo": true}` มาเพื่อถอนการจด (กดผิดใบ)
    """
    payload = await request.json() if await request.body() else {}
    run = clip_store.load_run(DATA_DIR, item_id) or {}
    if not run:
        raise HTTPException(status_code=404, detail=f"ไม่พบงาน {item_id}")
    target = str((payload or {}).get("target") or "").strip()
    undo = bool((payload or {}).get("undo"))
    if not target:
        # **ค่าตั้งต้นของสองคำสั่งนี้ตรงข้ามกัน อย่าใช้ตัวเดียวกัน**
        #
        #   จด   → ปลายทาง **ถัดไป** ที่ควรลง (คนกดหลังเพิ่งลงเสร็จ)
        #   ถอน  → ปลายทางที่ **เพิ่งจดไปล่าสุด** (คนกดเพราะกดผิด)
        #
        # เคยใช้ตัวเดียวกันแล้วพัง — จด Shopee เสร็จ ถัดไปกลายเป็น Facebook
        # พอสั่งถอนเลยไปถอน Facebook ที่ยังไม่ได้จด แล้วตอบ 400
        # ส่วน Shopee ที่จดผิดยังค้างอยู่ (เจอตอนทดสอบ 27 ส.ค. 2569)
        if undo:
            done = [(str((info or {}).get("posted_at") or ""), name)
                    for name, info in (run.get("publish") or {}).items()
                    if isinstance(info, dict) and info.get("status") == "posted"]
            target = max(done)[1] if done else ""
            if not target:
                raise HTTPException(status_code=400,
                                    detail="ใบนี้ยังไม่ได้จดว่าลงที่ไหนเลย")
        else:
            target = publish_order.next_target(run)
            if not target:
                raise HTTPException(status_code=400,
                                    detail="ใบนี้ลงครบทั้งสามที่แล้ว")

    try:
        if undo:
            fresh = await asyncio.to_thread(
                clip_store.unmark_posted, DATA_DIR, item_id, target)
        else:
            fresh = await asyncio.to_thread(
                clip_store.mark_posted, DATA_DIR, item_id, target, "")
    except clip_store.ClipStoreError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    _clip_log(("ถอนการจดว่า " if undo else "จดว่า ") + f"{item_id} ลง {target} แล้ว")
    return {"ok": True, "run": fresh, "item_id": item_id, "target": target,
            "next_target": publish_order.next_target(fresh),
            "summary": publish_order.summary(fresh),
            "message": (f"ถอนการจดว่าลง {target} แล้ว" if undo
                        else f"จดแล้วว่าลง {target} ไปแล้ว")}


@app.post("/api/jobs/{job_id}/storyboard")
async def jobs_storyboard_drop(job_id: str, request: Request) -> dict:
    """ลบภาพสตอรีบอร์ดที่ไม่เอาออกจากงาน (ผู้ใช้สั่ง 26 ส.ค. 2026)

    ที่ต้องมีปุ่มนี้: ChatGPT บางครั้งวาดมาสองใบพร้อมกล่องถามว่าชอบใบไหนมากกว่า
    ("Which image do you like more?") ซึ่งเป็นการทดลองของ OpenAI ไม่ใช่สิ่งที่
    เราขอ — ตัวโหลดของเราเห็นเป็นภาพสองใบในคำตอบเดียวจึงเก็บมาทั้งคู่

    **ไม่ลบถาวร ย้ายลงถังขยะ** และเหลือใบสุดท้ายลบไม่ได้ — ด่านทั้งสองอยู่ที่
    `clip_store.drop_storyboard()` ที่เดียว ตรงนี้แค่ส่งต่อ
    """
    payload = await request.json()
    name = str(payload.get("drop") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="ต้องบอกด้วยว่าจะลบภาพใบไหน")

    job = _find_job(job_id)
    item_id = job.get("item_id") or ""
    if not item_id:
        raise HTTPException(status_code=409, detail="งานนี้ยังไม่มีข้อมูลสินค้า")

    def work() -> dict:
        with _web_lock:
            return clip_store.drop_storyboard(DATA_DIR, item_id, name)

    try:
        run = await asyncio.to_thread(work)
    except clip_store.ClipStoreError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    left = list(run.get("storyboard") or [])
    _clip_log(f"ลบภาพสตอรีบอร์ด {name} ของ {item_id} — เหลือ {len(left)} ใบ "
              "(ย้ายลงถังขยะที่ storyboard/_trash แล้ว)")
    return {
        "ok": True, "storyboard": left,
        "message": f"ลบภาพนั้นแล้ว เหลือ {len(left)} ใบ (กู้ได้ที่ storyboard/_trash)",
    }


@app.post("/api/jobs/{job_id}/regen")
async def jobs_regen(job_id: str, request: Request) -> dict:
    """ลบคลิปเดิมแล้วเจนใหม่ — พร้อมคอมเมนต์บอกว่าต้องแก้อะไร

    ผู้ใช้สั่ง 26 ส.ค. 2026 · ลำดับที่ต้องการ:
        AI ดูคลิป → ดูคอมเมนต์ → ปรับคำสั่ง (จะปรับบางชุดก็ได้ แต่ต้องมีที่แก้) → เจนใหม่

    **ทำไมต้องมีช่องรับแยก ไม่ใช้ปุ่ม `/action` เดิม** ปุ่มนั้นส่งได้แค่ชื่อปุ่มกับ
    เลขลำดับ (รูปแบบเดียวกับปุ่มในแชท Telegram) ส่งข้อความยาวๆ ผ่านไม่ได้

    **ลำดับสำคัญมาก — แก้คำสั่งให้เสร็จก่อนลบไฟล์คลิป**
    ลบก่อนแล้ว AI จะไม่มีอะไรให้ดู และถ้าแก้ไม่สำเร็จต้อง**ไม่ลบอะไรเลย**
    ปล่อยให้ดูคลิปเดิมต่อ ดีกว่าลบทิ้งแล้วเจนซ้ำด้วยคำสั่งเดิม ซึ่งได้ของหน้าตาเดิม
    กลับมาและเสียเครดิต Flow ฟรี (กติกาข้อ 3: retry ต้องเปลี่ยนอะไรบางอย่าง)
    """
    payload = await request.json()
    note = str(payload.get("note") or "").strip()

    job = _find_job(job_id)
    item_id = job.get("item_id") or ""
    if not item_id:
        raise HTTPException(status_code=409, detail="งานนี้ยังไม่มีข้อมูลสินค้า")
    run = await asyncio.to_thread(clip_store.load_run, DATA_DIR, item_id)
    if not run:
        raise HTTPException(status_code=409, detail=f"ไม่พบข้อมูลงาน {item_id}")

    fixed = None
    if note:
        from flow_worker import load_gemini_api_key
        import clip_fix

        clip_path = None
        for name in run.get("videos", []):
            candidate = Path(run["folder"]) / name
            if candidate.is_file():
                clip_path = candidate
                break

        def revise() -> dict:
            return clip_fix.apply_note(
                run.get("flow_prompts") or [], note,
                load_gemini_api_key(), video=clip_path, log=_clip_log,
            )

        try:
            fixed = await asyncio.to_thread(revise)
        except Exception as error:                           # noqa: BLE001
            _clip_log(f"แก้คำสั่งตามคอมเมนต์ไม่สำเร็จ: {error}")
            raise HTTPException(status_code=502, detail=str(error)) from error

        def save() -> None:
            with _web_lock:
                clip_store.set_flow_prompts(DATA_DIR, item_id, fixed["prompts"])

        await asyncio.to_thread(save)

    def wipe() -> int:
        # ต้องลบไฟล์เดิม ไม่งั้นตัวเจนเห็นว่ามีไฟล์อยู่แล้วจะข้ามทุกฉาก
        # แล้วส่งคลิปเดิมกลับมาให้ดูซ้ำ
        fresh = clip_store.load_run(DATA_DIR, item_id) or {}
        gone = 0
        for name in fresh.get("videos", []):
            path = Path(fresh["folder"]) / name
            if path.is_file():
                path.unlink()
                gone += 1
        # **ลบไฟล์แล้วต้องลบรายการด้วย** ไม่งั้นสมุดบันทึกบอกว่ามีคลิป แต่โฟลเดอร์ว่าง
        clip_store.clear_videos(DATA_DIR, item_id)
        return gone

    with _web_lock:
        removed = await asyncio.to_thread(wipe)
    clip_jobs.update(job_id, stage=clip_queue.STAGE_READY_FLOW, awaiting="")
    clip_runner.wake()

    bits = [f"ลบคลิปเดิม {removed} ชิ้น แล้วเข้าคิวเจนใหม่"]
    if fixed:
        bits.append(f"แก้คำสั่งไป {len(fixed['changed'])} ชุด "
                    f"(ชุดที่ {', '.join(str(n) for n in fixed['changed'])}) "
                    f"· {fixed['how']}")
        _clip_log(f"เจนคลิปใหม่ของ {item_id} ตามคอมเมนต์: {note[:90]}")
    else:
        bits.append("ไม่ได้ใส่คอมเมนต์ — ใช้คำสั่งชุดเดิม จะได้คลิปหน้าตาใกล้เคียงเดิม")
    return {
        "ok": True, "removed": removed,
        "changed": (fixed or {}).get("changed") or [],
        "problems": (fixed or {}).get("problems") or [],
        "why": (fixed or {}).get("why") or "",
        "how": (fixed or {}).get("how") or "",
        "message": " · ".join(bits),
    }


@app.post("/api/jobs/{job_id}/framing")
async def jobs_framing(job_id: str, request: Request) -> dict:
    """ติ๊ก "เห็นสินค้าเต็มทุกฉาก" ให้งานใบนี้ (ผู้ใช้สั่ง 26 ส.ค. 2026)

    ติ๊กแล้วข้อความข้อบังคับจะถูกแนบไปกับคำขอสตอรีบอร์ด **ในช่องเดิมจุดเดิม**
    และ**ค่าที่ติ๊กกลายเป็นค่าตั้งต้นของงานถัดไป** จนกว่าจะเปลี่ยน
    ("สินค้าต่อไปให้ติ๊กแบบเดิมไว้เลย จนกว่าจะมีการกดเปลี่ยน จำค่าเดิมไว้")

    จดค่าที่จำไว้**หลัง**เขียนลงงานสำเร็จเท่านั้น ไม่งั้นถ้าเขียนงานพลาด
    ค่าตั้งต้นจะเปลี่ยนไปแล้วทั้งที่งานใบนี้ยังเป็นของเดิม
    """
    payload = await request.json()
    key = clip_rules.clean(payload.get("framing"))

    job = _find_job(job_id)
    item_id = job.get("item_id") or ""
    if not item_id:
        raise HTTPException(status_code=409, detail="งานนี้ยังไม่มีข้อมูลสินค้า")

    def work() -> dict:
        with _web_lock:
            return clip_store.set_story_full_shot(DATA_DIR, item_id, key)

    try:
        await asyncio.to_thread(work)
    except clip_store.ClipStoreError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    clip_rules.remember(key)
    _clip_log(f"ตั้งค่า \"{clip_rules.FULL_SHOT_LABEL}\" ของ {item_id}: "
              + ("ติ๊ก" if key else "ไม่ติ๊ก")
              + " · จำไว้เป็นค่าตั้งต้นของงานถัดไปแล้ว")
    return {
        "ok": True, "framing": key,
        "message": (f"ติ๊ก \"{clip_rules.FULL_SHOT_LABEL}\" แล้ว "
                    "และจำไว้ให้งานถัดไปด้วย"
                    if key else
                    "เอาเครื่องหมายออกแล้ว — ปล่อยให้ GPT จัดมุมกล้องเอง (จำไว้แล้ว)"),
    }


@app.post("/api/jobs/{job_id}/features")
async def jobs_features_regen(job_id: str, request: Request) -> dict:
    """ให้ AI **ดูรูปที่เลือกไว้** แล้วคิดจุดเด่นชุดใหม่ (ผู้ใช้สั่ง 26 ส.ค. 2026)

    ต้นทางคือรูป ไม่ใช่ข้อความ — จุดเด่นที่ดีที่สุดคือข้อที่พูดแล้วตัดภาพให้ดูได้ทันที
    ถ้าคัดจากข้อความล้วน (`/features` ในแชท) จะได้ข้อที่หน้าเว็บเขียนไว้แต่ไม่มีรูป
    ประกอบ แล้วคลิปต้องพูดถึงของที่คนดูไม่เห็น

    รับ `images` มาเป็นรายชื่อไฟล์ที่หน้าเว็บ **กำลังโชว์อยู่ตอนนี้** ไม่ใช่อ่านจาก
    ไฟล์งานเอง เพราะผู้ใช้อาจสลับรูปค้างไว้ยังไม่ได้บันทึก — ถ้าไปอ่านของที่บันทึกแล้ว
    จะกลายเป็น "เห็นรูปแบบหนึ่ง แต่ AI ดูอีกแบบหนึ่ง" โดยไม่มีอะไรฟ้อง
    ไม่ส่งมาก็ใช้ชุดที่บันทึกไว้ตามเดิม

    **ทับของเดิม** ทั้งจุดเด่นและคลังจุดขาย เหมือน `/features` ในแชททุกประการ
    (ใช้ `clip_store.save_features()` ตัวเดียวกัน) จึงเขียน log ของเก่าไว้ก่อนทับ
    ให้ย้อนดูได้ว่าเมื่อกี้มีอะไรบ้าง
    """
    from flow_worker import load_gemini_api_key
    import shopee_scrape

    payload = await request.json()
    raw = payload.get("images")

    # โมเดลที่ผู้ใช้เลือกจากดรอปดาวน์ (ผู้ใช้สั่ง 27 ส.ค. 2026) — ว่าง = อัตโนมัติ
    #
    # **ต้องตรวจที่นี่ ไม่ใช่เชื่อหน้าเว็บ** หน้าเว็บส่งชื่ออะไรมาก็ได้ ถ้าไม่กัน
    # จะกลายเป็นยิงชื่อมั่วไปที่ Google แล้วได้ 404 ที่อ่านไม่รู้เรื่อง
    want_model = str(payload.get("model") or "").strip()
    if want_model and want_model not in shopee_scrape.IMAGE_HIGHLIGHT_CHOICES:
        raise HTTPException(status_code=400, detail=f"ไม่รู้จักโมเดล {want_model}")

    job = _find_job(job_id)
    item_id = job.get("item_id") or ""
    if not item_id:
        raise HTTPException(status_code=409, detail="งานนี้ยังไม่มีข้อมูลสินค้า")

    run = await asyncio.to_thread(clip_store.load_run, DATA_DIR, item_id) or {}
    known: list[str] = []
    for name in list(run.get("images") or []) + list(run.get("image_pool") or []):
        if name not in known:
            known.append(name)

    wanted: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            name = str(item or "").strip()
            if not name or name in wanted:
                continue
            # กันชื่อไฟล์ที่ไม่ได้มาจากคลังของงานนี้ — หน้าเว็บส่งอะไรมาก็ได้
            if name not in known:
                raise HTTPException(status_code=400,
                                    detail=f"ไม่มีรูป {name} ในคลังของงานนี้")
            wanted.append(name)
    if not wanted:
        wanted = list(run.get("images") or [])
    if not wanted:
        raise HTTPException(status_code=400, detail="ยังไม่ได้เลือกรูปสักใบ")

    paths = []
    for name in wanted:
        try:
            paths.append(clip_store.file_path(DATA_DIR, item_id, name))
        except clip_store.ClipStoreError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    before = list(run.get("highlights") or [])
    name = run.get("name", "")

    # **ได้จุดเด่นเท่ากับจำนวนรูป** (ผู้ใช้สั่ง 26 ส.ค. 2026) เพราะรูปหนึ่งใบคือ
    # หนึ่งฉากในคลิป ฉากที่ไม่มีอะไรให้พูดคือฉากที่เสียเปล่า
    #
    # แต่ต้องไม่เกินเพดานจุดเด่น เพราะ `save_features()` เขียนลงไฟล์ตรงๆ
    # โดยไม่ผ่านด่านเพดาน ถ้าปล่อยให้เกิน ผู้ใช้จะติดกับ: แก้อะไรนิดเดียวแล้ว
    # กดบันทึกไม่ผ่านตลอด เพราะ `/highlights` ปฏิเสธชุดที่เกิน 6 ข้อ
    want = min(len(paths), CLIP_MAX_HIGHLIGHTS)
    capped = len(paths) > CLIP_MAX_HIGHLIGHTS

    def work() -> dict:
        # **ชุดรูปที่ส่งมาต้องถูกบันทึกด้วย ไม่ใช่แค่ยืมไปให้ AI ดู**
        # (แก้ 26 ส.ค. 2026 — ผู้ใช้แจ้งว่า "เลือกรูปใหม่ แล้วส่งเจนจุดเด่น รูปที่เลือกหายหมด")
        #
        # ของเดิมวิเคราะห์จากรูปชุดใหม่ แต่ไฟล์งานยังเก็บชุดเก่า พอหน้าเว็บวาดใหม่
        # ก็ได้รูปเก่ากลับมา — และจุดเด่นที่เพิ่งได้ก็คิดมาจากรูปที่มองไม่เห็นแล้ว
        # **จุดเด่นพูดถึงของที่ไม่มีในรูป โดยไม่มีอะไรฟ้อง**
        #
        # ด่านอยู่ตรงนี้ ไม่ใช่ที่หน้าเว็บอย่างเดียว เพราะกติกา "รูปที่วิเคราะห์ =
        # รูปที่บันทึก" ต้องเป็นจริงเสมอไม่ว่าใครเรียก (หน้าเว็บ · แชท · สคริปต์)
        moved = []
        with _web_lock:
            now = clip_store.load_run(DATA_DIR, item_id) or {}
            if list(now.get("images") or []) != wanted:
                order: list[str] = []
                for label in list(now.get("images") or []) + list(now.get("image_pool") or []):
                    if label not in order:
                        order.append(label)
                pool = [label for label in order if label not in wanted]
                clip_store.set_images(DATA_DIR, item_id, wanted, pool)
                moved = list(wanted)
                _clip_log(f"บันทึกชุดรูปใหม่ของ {item_id} ก่อนคิดจุดเด่น: {wanted}")

        _clip_log(f"ให้ AI ดูรูป {len(paths)} ใบของ {item_id} แล้วเขียนจุดเด่น {want} ข้อ "
                  f"(ของเดิม {len(before)} ข้อ: {' / '.join(before) or '—'})")
        analysis = shopee_scrape.analyse_features_from_images(
            name, paths, load_gemini_api_key(), log=_clip_log, count=want,
            model=want_model,
        )
        with _web_lock:
            fresh = clip_store.save_features(DATA_DIR, item_id, analysis)
        return {"analysis": analysis, "run": fresh, "images_saved": moved}

    try:
        result = await asyncio.to_thread(work)
    except HTTPException:
        raise
    except Exception as error:                               # noqa: BLE001
        # ล้มแล้วต้องบอกเหตุผลจริง ไม่ใช่ "ไม่สำเร็จ" ลอยๆ — ผู้ใช้กดเองและรออยู่
        _clip_log(f"คิดจุดเด่นจากรูปของ {item_id} ไม่สำเร็จ: {error}")
        raise HTTPException(status_code=502, detail=str(error)) from error

    fresh = result["run"]
    after = list(fresh.get("highlights") or [])
    seen = result["analysis"].get("images_seen", len(paths))
    _clip_log(f"จุดเด่นชุดใหม่ของ {item_id}: {' / '.join(after)}")

    # บอกให้ครบว่าได้กี่ข้อจากกี่ใบ และถ้าไม่ตรงกันเพราะอะไร — ผู้ใช้สั่งว่า
    # "5 รูป = 5 ข้อ" ถ้าได้ไม่ครบแล้วเงียบ เขาจะนับแล้วงงว่าระบบทำงานถูกไหม
    bits = [f"AI ดูรูป {seen} ใบ แล้วเขียนจุดเด่น {len(after)} ข้อ"]
    if capped:
        bits.append(f"เลือกรูปไว้ {len(paths)} ใบ แต่เก็บจุดเด่นได้สูงสุด "
                    f"{CLIP_MAX_HIGHLIGHTS} ข้อ จึงเขียนให้ {want} ข้อ")
    elif len(after) < want:
        bits.append(f"ขอไว้ {want} ข้อตามจำนวนรูป แต่ AI เขียนมาให้ไม่ครบ "
                    f"— กดซ้ำอีกครั้งได้ถ้าอยากได้ครบ")
    if result.get("images_saved"):
        bits.insert(0, f"บันทึกชุดรูป {len(result['images_saved'])} ใบที่เลือกไว้แล้ว")
    # **บอกว่าตัวไหนตอบจริง ไม่ใช่ตัวไหนถูกขอ** — เลือกอัตโนมัติแล้วตัวแรกล่ม
    # ระบบจะข้ามไปตัวสำรอง ถ้าไม่บอกก็ไม่มีใครรู้ว่าผลมาจากโมเดลไหน
    used = (result.get("analysis") or {}).get("model") or ""
    if used:
        bits.append(f"ใช้ {used}")
    bits.append(f"คลังจุดขาย {len(fresh.get('features') or [])} ข้อ")
    return {
        "ok": True,
        "highlights": after,
        "features": list(fresh.get("features") or []),
        "why": list(fresh.get("highlight_why") or []),
        "before": before,
        "images_seen": seen,
        "images_saved": result.get("images_saved") or [],
        "wanted": want,
        "capped": capped,
        "message": " · ".join(bits),
    }


@app.post("/api/jobs/{job_id}/highlight")
async def jobs_highlight(job_id: str, request: Request) -> dict:
    """แก้/เพิ่มจุดเด่นจบในครั้งเดียว — `index` เริ่มที่ 1 เหมือนที่แสดงให้ผู้ใช้เห็น"""
    payload = await request.json()
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="พิมพ์ข้อความจุดเด่นมาด้วย")

    job = _find_job(job_id)
    run = await asyncio.to_thread(clip_store.load_run, DATA_DIR, job.get("item_id", ""))
    highlights = list((run or {}).get("highlights") or [])
    raw = payload.get("index")
    if raw in (None, ""):                       # ไม่ระบุลำดับ = เพิ่มข้อใหม่ต่อท้าย
        index = len(highlights)
    else:
        try:
            index = int(raw) - 1
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail="index ต้องเป็นตัวเลข") from error
        if not 0 <= index <= len(highlights):
            raise HTTPException(status_code=400, detail="ไม่มีจุดเด่นข้อนั้น")
    if index >= len(highlights) and len(highlights) >= CLIP_MAX_HIGHLIGHTS:
        raise HTTPException(
            status_code=400, detail=f"เพิ่มได้สูงสุด {CLIP_MAX_HIGHLIGHTS} ข้อ",
        )

    def work() -> str:
        with _web_lock, _as_web_call():
            return _apply_edit_text(clip_jobs.get(job_id) or job, text, f"highlight:{index}")

    message = await asyncio.to_thread(work)
    return {"ok": True, "message": message}


def _stage_words(code: str) -> str:
    """แปลรหัสขั้น/รหัสกอง เป็นชื่อที่คนอ่านรู้เรื่อง

    **ต้องแปลทุกจุดที่ข้อความไปถึงคน** สายกลางทักมา 27 ส.ค. 2569 ว่าปุ่มเอากลับ
    ขึ้นว่า *"เอากลับเข้าขั้น shopee_video"* ซึ่งเป็นรหัสดิบ ไม่ใช่ชื่อไทย

    สาเหตุ: มีรหัสสองชุดปนกัน — **ขั้นในคิว** (`image_review`) กับ **ชื่อกอง
    บนกระดาน** (`shopee_video`) แต่ละที่แปลด้วยตารางของตัวเองแล้วไม่รู้จักอีกชุด
    ตัวนี้ลองทั้งสองตาราง เจอไหนเอาไหน ไม่เจอค่อยคืนรหัสดิบ
    """
    code = str(code or "").strip()
    if not code:
        return ""
    known = clip_queue.STAGE_LABEL.get(code)
    if known:
        return known
    return next((t for k, t, _h in clip_board.BOARD if k == code), code)


def _park_target(key: str) -> tuple[dict | None, str]:
    """แปลงรหัสที่หน้าเว็บส่งมาเป็นงานจริง — คืน (ใบงานในคิว, รหัสสินค้า)

    **รับได้ทั้งรหัสใบงานในคิวและรหัสสินค้า** (สายกลางขอไว้ 27 ส.ค. 2569)
    หาในคิวก่อน ไม่เจอค่อยไปหาไฟล์งาน

    **ทำไมต้องรับสองแบบ** ไม่ใช่แค่ความสะดวก — วัดจริงบนกระดาน
    **19 จาก 23 แถวในกอง Shopee Video ไม่มีรหัสใบงานให้ใช้เลย**
    เพราะงานเจนคลิปเสร็จแล้วออกจากคิวไป ถ้าที่อยู่นี้รับแค่รหัสใบงาน
    แถวส่วนใหญ่ของกองที่มีของมากที่สุดจะกดพักไม่ได้ตลอดกาล
    """
    key = str(key or "").strip()
    job = next((j for j in clip_jobs.all() if str(j.get("id")) == key), None)
    if job:
        return job, str(job.get("item_id") or "")
    # ไม่ใช่รหัสใบงาน — ลองเป็นรหัสสินค้า แล้วดูว่ามีใบงานที่ยังเปิดอยู่ไหม
    job = next((j for j in clip_jobs.all()
                if str(j.get("item_id")) == key
                and j.get("stage") in clip_queue.OPEN_STAGES), None)
    if job:
        return job, key
    if clip_store.load_run(DATA_DIR, key):
        return None, key
    return None, ""


@app.post("/api/jobs/{job_id}/park")
async def jobs_park(job_id: str, request: Request) -> dict:
    """พักงานไว้ "รอแก้" — เครื่องหยุดแตะ แต่ของที่ทำไว้แล้วยังอยู่ครบ

    ผู้ใช้สั่ง 27 ส.ค. 2026: *"ให้สร้างอีกช่องนึงเป็นช่องรอแก้ สำหรับทุกขั้นตอน
    โดยมีปุ่มให้กดไปรอแก้ในใบงานด้วย"*

    **ต่างจาก "ยกเลิก" ตรงที่กลับมาทำต่อได้** ยกเลิกคือทิ้ง ส่วนพักคือ "ยังเอาอยู่
    แต่ยังไม่พร้อม" — ก่อนหน้านี้มีแค่สองทางคือปล่อยให้ค้างอยู่ในกองเดิม
    (แล้วไปปนกับงานที่เดินได้จริงจนนับไม่ถูก) หรือยกเลิกทิ้ง ซึ่งแรงเกินไป

    **งานที่กำลังทำอยู่พักไม่ได้** เหมือนกับยกเลิก — เบราว์เซอร์เปิดค้างอยู่และ
    อาจใช้เครดิตไปแล้ว การแกล้งเปลี่ยนสถานะให้ดูเหมือนหยุดคือการโกหกหน้าจอ

    รับได้ทั้ง **รหัสใบงานในคิว** และ **รหัสสินค้า** — ดู `_park_target`
    """
    payload = await request.json() if await request.body() else {}
    why = str((payload or {}).get("why") or "").strip()
    stage_hint = str((payload or {}).get("stage") or "").strip()

    job, item_id = _park_target(job_id)
    if not job and not item_id:
        raise HTTPException(status_code=404, detail=f"ไม่พบงาน {job_id}")

    # ---- ยังอยู่ในคิว: พักที่ใบงาน ----------------------------------------
    if job:
        if clip_runner.current == job["id"]:
            raise HTTPException(
                status_code=409,
                detail="งานนี้กำลังทำอยู่ — พักกลางคันไม่ได้ รอให้จบขั้นนี้ก่อน",
            )
        if job.get("parked"):
            raise HTTPException(status_code=400, detail="งานนี้พักไว้อยู่แล้ว")
        try:
            fresh = await asyncio.to_thread(clip_jobs.park, job["id"], why)
        except clip_queue.ClipQueueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        came = clip_queue.STAGE_LABEL.get(job.get("stage") or "", job.get("stage") or "")
        _clip_log(f"พักงาน {job['id']} ไว้รอแก้ (ค้างที่ขั้น {came}) — {why or 'ไม่ได้บอกเหตุผล'}")
        return {"ok": True, "job": fresh, "item_id": item_id,
                "message": f"พักไว้ในช่อง 🅿️ รอแก้แล้ว (ค้างที่ขั้น {came}) "
                           f"— เครื่องจะไม่แตะจนกว่าจะกดเอากลับ"}

    # ---- จบจากคิวไปแล้ว: พักที่ไฟล์งาน ------------------------------------
    run = clip_store.load_run(DATA_DIR, item_id) or {}
    if run.get("parked"):
        raise HTTPException(status_code=400, detail="งานนี้พักไว้อยู่แล้ว")
    came = stage_hint or clip_board.bucket_of_run(run)
    try:
        fresh = await asyncio.to_thread(
            clip_store.park_run, DATA_DIR, item_id, why, came)
    except clip_store.ClipStoreError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    label = _stage_words(came)
    _clip_log(f"พักงานเก็บไว้ {item_id} รอแก้ (กอง {came}) — {why or 'ไม่ได้บอกเหตุผล'}")
    return {"ok": True, "run": fresh, "item_id": item_id,
            "message": f"พักไว้ในช่อง 🅿️ รอแก้แล้ว (ค้างที่ {label}) "
                       f"— เครื่องจะไม่แตะจนกว่าจะกดเอากลับ"}


@app.post("/api/jobs/{job_id}/unpark")
async def jobs_unpark(job_id: str) -> dict:
    """เอางานที่พักไว้กลับเข้าขั้นเดิม — กลับไปตรงที่ค้างไว้เป๊ะ ไม่ต้องเริ่มใหม่

    รับได้ทั้งรหัสใบงานในคิวและรหัสสินค้า เหมือน `/park`
    """
    job, item_id = _park_target(job_id)
    if not job and not item_id:
        raise HTTPException(status_code=404, detail=f"ไม่พบงาน {job_id}")

    if job:
        if not job.get("parked"):
            raise HTTPException(status_code=400, detail="งานนี้ไม่ได้พักไว้")
        try:
            fresh = await asyncio.to_thread(clip_jobs.unpark, job["id"])
        except clip_queue.ClipQueueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        came = clip_queue.STAGE_LABEL.get(fresh.get("stage") or "", fresh.get("stage") or "")
        clip_runner.wake()      # อาจเป็นงานที่เครื่องหยิบไปทำต่อได้ทันที
        _clip_log(f"เอางาน {job['id']} กลับเข้าขั้น {came} แล้ว")
        return {"ok": True, "job": fresh, "item_id": item_id,
                "message": f"เอากลับเข้าขั้น “{_stage_words(came)}” แล้ว"}

    try:
        fresh = await asyncio.to_thread(clip_store.unpark_run, DATA_DIR, item_id)
    except clip_store.ClipStoreError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    back = _stage_words(clip_board.bucket_of_run(fresh))
    _clip_log(f"เอางานเก็บไว้ {item_id} ออกจากช่องรอแก้แล้ว → {back}")
    return {"ok": True, "run": fresh, "item_id": item_id, "bucket": back,
            "message": f"เอากลับเข้า {back} แล้ว" if back
                       else "เอากลับเข้ารายการแล้ว"}


@app.post("/api/jobs/{job_id}/cancel")
async def jobs_cancel(job_id: str) -> dict:
    """ยกเลิกงานที่ยังไม่ได้เริ่ม — งานที่กำลังทำอยู่หยุดกลางคันไม่ได้ ต้องบอกตรงๆ

    ระหว่างทำอยู่มีเบราว์เซอร์เปิดค้างและอาจใช้เครดิต Flow ไปแล้ว การ "ยกเลิก"
    ที่ทำได้จริงคือปล่อยให้จบแล้วค่อยไม่เอาผล ไม่ใช่แกล้งเปลี่ยนสถานะให้ดูเหมือนหยุด
    """
    job = _find_job(job_id)
    if clip_runner.current == job_id:
        raise HTTPException(
            status_code=409,
            detail="งานนี้กำลังทำอยู่ — หยุดกลางคันไม่ได้ รอให้จบแล้วค่อยกดไม่เอาผล",
        )
    if job.get("stage") not in clip_queue.OPEN_STAGES:
        raise HTTPException(status_code=400, detail="งานนี้จบไปแล้ว")
    clip_jobs.update(job_id, stage=clip_queue.STAGE_CANCELLED, note="ยกเลิกจากหน้าเว็บ")
    _clip_log(f"ยกเลิกงาน {job_id} จากหน้าเว็บ")
    return {"ok": True, "message": "ยกเลิกแล้ว"}


@app.post("/api/jobs/{job_id}/retry")
async def jobs_retry(job_id: str) -> dict:
    """เอางานที่ล้ม/ยกเลิกกลับเข้าคิว โดย **ไม่ทำซ้ำขั้นที่ทำสำเร็จไปแล้ว**

    ทำใหม่ตั้งแต่ต้นทุกครั้งคือเผาเวลาและเครดิตฟรี — มีคำสั่ง Flow อยู่แล้วก็ไป
    เริ่มที่ขั้นเจนเลย มีรูปแล้วก็ไปเริ่มที่ขั้นทำสตอรีบอร์ด
    """
    _find_job(job_id)                       # ไม่พบ = 404 ตามเดิม
    try:
        what = await asyncio.to_thread(_clip_retry_job, job_id, "หน้าเว็บ")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "message": f"เข้าคิวแล้ว · {what}"}


@app.post("/api/jobs/{job_id}/move")
async def jobs_move(job_id: str, request: Request) -> dict:
    """สลับลำดับงานที่ยังรอคิว — ของด่วนแซงขึ้นก่อนได้"""
    payload = await request.json()
    try:
        delta = int(payload.get("delta") or 0)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="delta ต้องเป็นตัวเลข") from error
    if delta == 0:
        raise HTTPException(status_code=400, detail="delta ต้องเป็น -1 หรือ 1")
    try:
        await asyncio.to_thread(clip_jobs.move, job_id, delta)
    except clip_queue.ClipQueueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "message": "เลื่อนแล้ว"}


@app.delete("/api/jobs/{job_id}")
async def jobs_delete(job_id: str) -> dict:
    """ลบแถวในคิว — ไฟล์งานในเครื่องไม่ถูกแตะ ยังเปิดดูได้จากรายการงานที่เก็บไว้"""
    try:
        await asyncio.to_thread(clip_jobs.remove, job_id)
    except clip_queue.ClipQueueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "message": "ลบออกจากคิวแล้ว"}


@app.post("/api/genall")
async def genall_run(request: Request) -> dict:
    """สั่ง `/genall` จากนอกแชท — เรียกฟังก์ชันตัวเดียวกับที่บอทใช้

    **ทำไมต้องเรียกตัวเดิม ไม่เขียนใหม่ให้เหมือน** — `_clip_gen_all` มีด่านกันพลาด
    สองชั้นอยู่ข้างใน (เครดิตไม่พอ = ไม่เข้าคิวสักงาน · Flow ไม่พร้อม = ไม่เข้าคิว
    สักงาน) ถ้าเขียนเลียนแบบข้างนอก วันหนึ่งจะหลุดด่านแล้วเผาเครดิตทั้งคิว

    เดิมสั่งได้จากแชทที่เดียว จะสั่งจากหน้าเว็บหรือเครื่องมือไม่มีทางเลย

    body: `{"dry": true}` = ดูก่อนว่าจะทำอะไร ใช้เครดิตเท่าไร ไม่เข้าคิวจริง

    รายงานผลไปที่แชทเหมือนสั่งจากแชท — คนที่เฝ้าฝั่งแชทจะได้ไม่งงว่างานโผล่มาจากไหน
    ส่วนตัวเลขที่ตอบกลับทางนี้คือจำนวนงานที่เข้าคิว **เพิ่มขึ้นจริง** วัดจากคิวก่อน/หลัง
    """
    payload = {}
    try:
        payload = await request.json()
    except Exception:                                           # noqa: BLE001
        pass
    dry = bool(payload.get("dry"))
    chat_id = str(payload.get("chat_id") or _default_clip_chat())

    before = len(clip_jobs.waiting())

    def work() -> None:
        with _web_lock:
            _clip_gen_all(chat_id, "ลอง" if dry else "")

    await asyncio.to_thread(work)
    after = len(clip_jobs.waiting())
    return {
        "ok": True, "dry": dry,
        "queued": after - before, "waiting": after,
        "message": ("ดูผลในแชท (ยังไม่เข้าคิวจริง)" if dry
                    else f"เข้าคิวเพิ่ม {after - before} งาน — ดูผลในแชทและที่ /api/queue"),
    }


@app.post("/api/flow-enabled")
async def flow_enabled_set(request: Request) -> dict:
    """เปิด/ปิดขั้นเจนคลิปใน Google Flow (เท่ากับ /flow on|off ในแชท)

    มีผลกับสิ่งที่เกิดขึ้น "หลังกดอนุมัติครบ" โดยตรง จึงต้องเห็นและสลับได้จาก
    หน้าเว็บด้วย ไม่ใช่ซ่อนไว้ในคำสั่งแชทอย่างเดียว
    """
    payload = await request.json()
    on = bool(payload.get("on"))
    set_config(FLOW_ENABLED_KEY, on)
    _clip_log(f"{'เปิด' if on else 'ปิด'}ขั้นเจนคลิปใน Google Flow (จากหน้าเว็บ)")
    return {"ok": True, "flow_enabled": on}


@app.get("/api/log")
async def log_tail(tail: int = 80) -> dict:
    return {"ok": True, "lines": shared.read_log("clip", tail)}


@app.get("/api/evidence")
async def evidence_list(limit: int = 30, tag: str = "") -> dict:
    """หลักฐานตอนพัง — ภาพหน้าจอ + บริบท (กติกา CLAUDE.md ข้อ 2.6.1)

    ให้หน้าเว็บเปิดดูได้โดยไม่ต้องไปเปิดโฟลเดอร์เอง — หลักฐานที่เรียกดูยาก
    เท่ากับไม่ได้เก็บ
    """
    def build() -> dict:
        import evidence
        every = evidence.events()
        rows = [r for r in every if not tag or tag.lower() in r["tag"].lower()]
        picked = rows[:max(1, min(limit, 200))]

        # ไฟล์ที่มีจริงของแต่ละเหตุการณ์ — เก็บครบสามอย่างบ้าง ไม่ครบบ้าง แล้วแต่ว่า
        # ตอนพังนั้นแคปอะไรได้ ถ้าไม่บอก หน้าเว็บต้องเดาแล้วโชว์ลิงก์ที่กดไปเจอ 404
        #
        # ไล่ทีละไฟล์แทน glob เพราะชื่อไฟล์คือข้อความภาษาคน มี `[` `]` ปนได้
        # ซึ่ง glob จะตีเป็นรูปแบบพิเศษแล้วหาไฟล์ไม่เจอเงียบๆ
        want = {r["stem"] for r in picked}
        found: dict[str, list[str]] = {stem: [] for stem in want}
        if evidence.EVIDENCE_DIR.is_dir():
            for path in evidence.EVIDENCE_DIR.iterdir():
                if path.is_file() and path.stem in want:
                    found[path.stem].append(path.suffix.lstrip(".").lower())

        return {
            "ok": True, "total": len(rows),
            "tags": sorted({r["tag"] for r in every if r["tag"]}),
            "events": [
                {"stem": r["stem"], "when": r["when"], "tag": r["tag"],
                 "why": r["why"], "has_shot": r["shot"],
                 "kinds": sorted(found.get(r["stem"], []))}
                for r in picked
            ],
        }

    return await asyncio.to_thread(build)


@app.get("/api/evidence/{stem}/{kind}")
async def evidence_file(stem: str, kind: str):
    """ไฟล์หลักฐานหนึ่งใบ — kind = png | txt | html | xml"""
    import evidence
    if kind not in {"png", "txt", "html", "xml", "txt2"}:
        raise HTTPException(status_code=400, detail="ชนิดไฟล์ไม่ถูกต้อง")
    # กันเรียกไฟล์นอกโฟลเดอร์ด้วยชื่อแบบ ../.. — รับเฉพาะชื่อที่มีอยู่จริง
    target = (evidence.EVIDENCE_DIR / f"{stem}.{kind}").resolve()
    if evidence.EVIDENCE_DIR.resolve() not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์หลักฐานนี้")
    return FileResponse(target)


@app.on_event("startup")
async def _startup() -> None:
    clip_watcher.start()
    # งานที่ค้างกลางทางตอนเซิร์ฟเวอร์ดับ ต้องเอากลับเข้าคิว ไม่งั้นค้างสถานะ
    # "กำลังทำ" ตลอดกาลแล้วผู้ใช้รอเก้อโดยไม่มีอะไรฟ้อง
    revived = clip_jobs.recover()
    if revived:
        append_log("clip", f"เอางานค้าง {revived} งานกลับเข้าคิว")
    clip_runner.start()
    # บอทเพิ่มเติมที่ตั้งหน้าที่เป็นสายคลิป — อ่านที่นี่ที่เดียว กันชน 409 กับ 8866
    sync_clip_extra_watchers()
    threading.Thread(target=_extra_sync_loop, daemon=True).start()
    # สรุปประจำวันส่งเข้าแชทเอง — อยู่ที่นี่เพราะคิวกับคลังคลิปอยู่ในโปรเซสนี้
    threading.Thread(target=_digest_keeper, daemon=True).start()
    # บทสนทนาแชท + log ระบบ ขึ้น Drive เอง — ไม่ต้องรอให้มีคลิปใหม่
    threading.Thread(target=_drive_log_keeper, daemon=True).start()
    append_log("clip", f"เซิร์ฟเวอร์สายคลิปพร้อม — พอร์ต {PORT}")


if __name__ == "__main__":
    import uvicorn

    print(f"Pipeline Studio — สายเจนคลิป v{APP_VERSION} — http://127.0.0.1:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
