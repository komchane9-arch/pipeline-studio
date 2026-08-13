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
import json
import re
import shutil
import threading
import time
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

import chatgpt_driver
import clip_queue
import clip_store
import studio_shared as shared
import telegram_bot
import thai_speech
import tiktok_repost
import tiktok_source
from shopee_service import shopee_collect

APP_VERSION = "1"
PORT = 8877

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
    """แก้ค่าเดียวใน config.json

    อ่านสดก่อนเขียนทุกครั้ง เพราะอีกโปรเซส (app.py) ก็เขียนไฟล์นี้เหมือนกัน —
    ลดโอกาสทับค่าที่อีกฝั่งเพิ่งใส่ (ทั้งคู่เขียนนานๆ ครั้ง จึงพอ)
    """
    import json

    config = shared.read_config()
    if config.get(key) == value:
        return True
    config[key] = value
    try:
        shared.CONFIG_FILE.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as error:
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


def flow_enabled() -> bool:
    return bool(shared.read_config().get(FLOW_ENABLED_KEY, False))


def one_clip_mode() -> bool:
    return bool(shared.read_config().get(FLOW_ONE_CLIP_KEY, True))


def build_one_clip_prompt(prompts: list[str], seconds: int = 8) -> str:
    """รวม prompt ทุกฉากเป็นก้อนเดียวสำหรับเจนคลิปเดียวจบ

    ต้องบอกให้ชัดว่า **คลิปเดียวต่อเนื่อง** ไม่ใช่หลายคลิป ไม่งั้นโมเดลจะตีความว่า
    ให้ทำฉากแรกอย่างเดียว (แต่ละก้อนเดิมเขียนไว้แบบ "เจนทีละฉาก")
    """
    header = (
        f"Create ONE continuous {seconds}-second vertical 9:16 video that plays "
        f"through ALL {len(prompts)} scenes below in order, as a single seamless clip. "
        "Divide the time evenly between scenes with smooth cuts. "
        "Keep the same product, colours and lighting style across every scene.\n\n"
    )
    body = "\n\n".join(
        f"--- SCENE {index} ---\n{text.strip()}"
        for index, text in enumerate(prompts, 1)
    )
    combined = header + body
    if len(combined) <= FLOW_PROMPT_LIMIT:
        return combined
    # ตัดแบบเฉลี่ยทุกฉาก ไม่ใช่ตัดท้ายทิ้ง — ไม่งั้นฉากหลังหายไปทั้งฉาก
    room = max(200, (FLOW_PROMPT_LIMIT - len(header)) // max(1, len(prompts)) - 20)
    body = "\n\n".join(
        f"--- SCENE {index} ---\n{text.strip()[:room]}"
        for index, text in enumerate(prompts, 1)
    )
    return (header + body)[:FLOW_PROMPT_LIMIT]


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
    "/cancel [เลข] — ยกเลิกงาน (ไม่ใส่เลข = ยกเลิกทั้งหมด)\n"
    "/flow on | off — เปิด/ปิดขั้นเจนคลิปใน Google Flow\n"
    "/mode รวม | แยก — เจนคลิปเดียวจบทุกฉาก หรือแยกฉากละคลิป\n"
    "/clips — รายการงานที่เก็บไว้\n"
    "/clip &lt;เลข&gt; — เปิดดูงานนั้น (สตอรีบอร์ด + บทพูด)\n"
    "/gen &lt;เลข&gt; — <b>เจนคลิปต่อ</b>จากสตอรีบอร์ดที่ทำไว้แล้ว\n"
    "/genall — <b>ไล่เจนวิดีโอทุกงานที่ยังไม่มีคลิป</b> (ต้องมีสตอรีบอร์ด + บทพูดครบ)\n"
    "/genall sb — ไล่ทำสตอรีบอร์ดทุกงานที่ยังไม่มี (<code>/genall all</code> = ทำใหม่ทั้งหมด)\n"
    "/storyboard — สตอรีบอร์ดที่ทำแล้วแต่<b>ยังไม่ได้เจนคลิป</b>\n"
    "/videos — <b>คลิปที่เจนไว้แล้วทั้งหมด</b> กดดูย้อนหลังได้\n"
    "/video &lt;เลข&gt; — ส่งคลิปของงานนั้นมาดูในแชท\n"
    "/basket &lt;ข้อความ&gt; — คำพูดบนปุ่มตะกร้าตอนโพสต์ TikTok"
)


def _clip_say(chat_id: str, text: str, keyboard=None, preview: bool = True) -> int:
    token = load_clip_token() or ""
    target = chat_id or load_config().get("telegram_clip_chat_id", "")
    if not token or not target:
        return 0
    try:
        return telegram_bot.send_message(token, target, text, keyboard, preview=preview)
    except telegram_bot.TelegramError as error:
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


def _clip_log(message: str) -> None:
    append_log("input", f"[คลิป] {message}")


def _clip_buttons(job_id: str, kind: str) -> dict:
    """ปุ่มอนุมัติ/สั่งแก้ — คำนำหน้า clip: จองไว้ให้ on_callback ของบอทคลิป"""
    labels = {
        "storyboard": ("✅ อนุมัติสตอรีบอร์ด", "✏️ สั่งแก้สตอรีบอร์ด", "sb"),
        "script": ("✅ อนุมัติบทพูด", "✏️ สั่งแก้บทพูด", "sc"),
        "video": ("✅ อนุมัติคลิป", "🔄 เจนใหม่", "vid"),
    }
    ok_text, edit_text, tag = labels[kind]
    return {"inline_keyboard": [[
        {"text": ok_text, "callback_data": f"clip:{tag}_ok:{job_id}"},
        {"text": edit_text, "callback_data": f"clip:{tag}_edit:{job_id}"},
    ]]}


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
    rows.append([
        {"text": "✅ Approve", "callback_data": f"clip:sheet_ok:{job_id}:"},
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
    _clip_send_worksheet(clip_jobs.get(job_id))
    return note


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
    else:
        return f"ไม่รู้จักปุ่ม {action}"

    _clip_keep(
        lambda: clip_store.set_images(DATA_DIR, item_id, images, pool), "ชุดรูป"
    )
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
    lines = [f"🗣 <b>บทพูดในคลิป</b> — ราว {words} คำ {mark} (เกณฑ์ {low}–{high})", ""]
    lines += [f"<b>{i}.</b> {escape(text)}" for i, text in enumerate(script, 1)]
    body = "\n".join(lines)
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

    # สินค้าปรับเปลี่ยนได้ → สั่ง GPT ให้ยึดรูปที่แนบไปในฉากที่โชว์การเปลี่ยน
    extra_ask = (
        TRANSFORM_STORYBOARD_ASK
        if transform_hint(highlights, data.get("name", "")) else ""
    )
    _clip_say(
        chat_id,
        f"🎬 ส่งรูป {len(images)} ใบเข้า GPT นักสร้างสตอรีบอร์ด… ใช้เวลาสักพัก"
        + ("\n(สั่งให้ยึดรูปท่าที่แนบไปในฉากที่โชว์การปรับเปลี่ยน)" if extra_ask else ""),
    )
    if extra_ask:
        _clip_log("สินค้าปรับเปลี่ยนได้ — แนบคำสั่งให้ GPT ยึดรูปท่าที่ส่งไป")
    folder = base / "storyboard"
    try:
        with shared.browser_lock(label="ทำสตอรีบอร์ด"):
            result = chatgpt_driver.make_storyboard(
                open_browser, data.get("name", ""), highlights, images, folder,
                log=_clip_log, extra_ask=extra_ask,
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


def _speech_retry(prompt: str, attempt: int, error) -> str:
    """ปรับจังหวะบทพูดก่อนลองใหม่ — ใช้เมื่อ Veo สร้างเสียงไทยไม่ผ่าน

    KVID เจอมาก่อนว่าเสียงไทยล้มเพราะประโยคยาวติดกันไม่มีจังหวะพัก retry ด้วยบท
    เดิมจึงได้ผลเดิม ต้องเปลี่ยนจังหวะคำก่อน
    """
    level = min(attempt, thai_speech.MAX_LEVEL)
    _clip_log(f"  ปรับจังหวะบทพูดเป็นระดับ {level} ก่อนลองใหม่")
    return thai_speech.speech_ready(prompt, level)


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
                        driver.new_project()
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
                        # ห้ามลองซ้ำด้วย prompt เดิม — เผาเครดิตฟรี
                        failed.append(f"{label}: ขัดนโยบาย ({str(error)[:80]})")
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
    keyboard = {"inline_keyboard": [[
        {"text": "🚀 โพสต์เลย", "callback_data": f"clip:tt_post:{job['id']}"},
        {"text": "🗑 ไม่โพสต์", "callback_data": f"clip:tt_skip:{job['id']}"},
    ]]}
    _clip_say(job["chat_id"], "\n".join(lines), keyboard)


def _tiktok_post(job: dict) -> None:
    """ขั้นสุดท้าย: โพสต์คลิปขึ้น TikTok ด้วยตัวโพสต์เดิมใน tiktok_post.py"""
    chat_id = job["chat_id"]
    run = clip_store.load_run(DATA_DIR, job.get("item_id", ""))
    videos = run.get("videos") or []
    if not videos:
        _clip_say(chat_id, "❌ ไม่มีไฟล์คลิปให้โพสต์")
        raise RuntimeError("ไม่มีคลิปให้โพสต์")

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


clip_runner = clip_queue.ClipRunner(clip_jobs, _clip_worker, log=_clip_log)


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
            "ทำทีละงานตามลำดับ — /queue ดูสถานะ",
        )


def _clip_list_runs(chat_id: str) -> None:
    """รายการงานที่เก็บไว้ ใหม่สุดขึ้นก่อน"""
    runs = clip_store.list_runs(DATA_DIR)
    if not runs:
        _clip_say(chat_id, "ยังไม่มีงานที่เก็บไว้ — ส่งลิงก์ Shopee มาได้เลย")
        return
    escape = telegram_bot._escape
    lines = [f"🎬 <b>งานที่เก็บไว้</b> {len(runs)} ชิ้น\n"]
    for index, run in enumerate(runs, 1):
        # บอกให้ครบว่าชิ้นไหนมีอะไรบ้าง จะได้รู้ว่าอันไหนทำไม่จบโดยไม่ต้องเปิดดู
        marks = []
        marks.append(f"🖼{run.get('storyboard_count', 0)}" if run.get("storyboard") else "🖼—")
        marks.append(f"🎥{run.get('flow_prompt_count', 0)}" if run.get("flow_prompts") else "🎥—")
        if run.get("refused"):
            marks.append("⚠️โดนปฏิเสธ")
        when = (run.get("storyboard_at") or run.get("product_at") or "")[5:16].replace("T", " ")
        lines.append(
            f"<b>{index}.</b> {escape(run.get('name', '')[:55])}\n"
            f"     {' '.join(marks)} · {escape(when)} · <code>/clip {index}</code>"
        )
    for part in _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT):
        _clip_say(chat_id, part)


def _clip_show_run(chat_id: str, argument: str) -> None:
    """เปิดดูงานหนึ่งชิ้น — รับได้ทั้งเลขลำดับจาก /clips และรหัสสินค้า"""
    runs = clip_store.list_runs(DATA_DIR)
    if not runs:
        _clip_say(chat_id, "ยังไม่มีงานที่เก็บไว้")
        return

    argument = (argument or "").strip()
    run = None
    if argument.isdigit() and 1 <= int(argument) <= len(runs):
        run = runs[int(argument) - 1]
    else:
        run = next((r for r in runs if str(r.get("item_id")) == argument), None)
    if not run:
        _clip_say(chat_id, f"ไม่พบงานที่ {telegram_bot._escape(argument)} — /clips ดูรายการ")
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

    lines = [f"🛍 <b>{escape(run.get('name', ''))}</b>"]
    if run.get("highlights"):
        lines.append("\n✨ <b>คุณสมบัติเด่น</b>")
        lines += [f"   {i}. {escape(text)}" for i, text in enumerate(run["highlights"], 1)]
    lines += ["", "🔗 <b>ลิงก์ affiliate</b>", escape(run.get("affiliate_url", ""))]
    if run.get("chat_url"):
        lines += ["", f"💬 แชท GPT: {escape(run['chat_url'])}"]
    if run.get("refused"):
        lines += ["", "⚠️ รอบนั้น ChatGPT ปฏิเสธการสร้างภาพ"]
    _clip_say(chat_id, "\n".join(lines))

    # ส่ง **บทพูด** ไม่ส่งคำสั่งเจนวิดีโอ — คำสั่งยาวและเป็นศัพท์เทคนิค
    # เก็บไว้ในเครื่องแล้วดูในแท็บ 🎬 สตอรีบอร์ด บนหน้าเว็บได้ถ้าอยากอ่าน
    script = run.get("script") or []
    if script:
        lines = [f"🗣 <b>บทพูดในคลิป</b> ({len(script)} ฉาก)", ""]
        lines += [f"<b>{i}.</b> {escape(text)}" for i, text in enumerate(script, 1)]
        for part in _split_text("\n".join(lines), TELEGRAM_TEXT_LIMIT):
            _clip_say(chat_id, part)
    else:
        _clip_say(chat_id, "⚠️ งานนี้ยังไม่มีบทพูดเก็บไว้")

    # ปุ่มเดินต่อ — งานที่หยุดไว้ตอนขั้นเจนปิดอยู่ กดตรงนี้ทำต่อได้เลย
    # ไม่ต้องส่งลิงก์ใหม่และไม่ต้องคุยกับ GPT ซ้ำ
    count = run.get("flow_prompt_count") or 0
    videos = run.get("videos") or []
    rows = []
    # มีคลิปแล้วให้กดดูได้เลย — ไม่ต้องไปเปิดไฟล์ในเครื่องเอง
    if videos:
        rows.append([{
            "text": f"▶️ ดูคลิปที่เจนไว้ ({len(videos)} ไฟล์)",
            "callback_data": f"clip:vid::{run.get('item_id', '')}",
        }])
    if count:
        rows.append([{
            "text": f"🎬 เจนคลิปจากงานนี้ ({count} ฉาก)",
            "callback_data": f"clip:gen::{run.get('item_id', '')}",
        }])
    if rows:
        note = []
        if videos:
            note.append(f"▶️ มีคลิปเก็บไว้ <b>{len(videos)} ไฟล์</b>")
        if count:
            note.append(f"🎥 มีคำสั่งเจนวิดีโอเก็บไว้ <b>{count} ฉาก</b>")
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


def _clip_gen_all(chat_id: str, argument: str) -> None:
    """ไล่ **เจนวิดีโอ** ทุกงานที่ยังไม่มีคลิป และของพร้อมครบแล้ว

    "พร้อมครบ" = มีสตอรีบอร์ด + มีบทพูด + มีคำสั่ง Flow  ขาดข้อไหนไม่เอาเข้าคิว
    แต่รายงานออกมาให้เห็นว่าขาดอะไร ไม่เงียบหาย

    ข้ามงานที่มีคลิปแล้วเสมอ และ **ไม่มีตัวเลือกบังคับทำใหม่** เพราะเจนซ้ำหนึ่ง
    รอบ = จ่ายเครดิต Flow จริง (รอบละ 15) การพิมพ์ผิดครั้งเดียวไม่ควรเผาเครดิต
    ทั้งคิว — ถ้าจะเจนซ้ำจริงๆ ให้สั่งเจาะจงทีละงานด้วย /gen <เลข>

    ของเดิมที่ /genall เคยทำ (ไล่ทำสตอรีบอร์ด) ย้ายไปอยู่ที่ `/genall sb`
    """
    if argument.strip().lower() in ("sb", "storyboard", "สตอรีบอร์ด", "all", "ทั้งหมด", "force"):
        _clip_gen_all_storyboards(
            chat_id, argument.strip().lower() in ("all", "ทั้งหมด", "force")
        )
        return

    runs = clip_store.list_runs(DATA_DIR)
    if not runs:
        _clip_say(chat_id, "ยังไม่มีงานที่เก็บไว้ — ส่งลิงก์ Shopee เข้ามาก่อน")
        return

    escape = telegram_bot._escape
    queued, has_video, not_ready, blocked = [], 0, [], []
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
        note = _clip_start_flow(chat_id, item_id, announce=False)
        (blocked if note != "เข้าคิวเจนคลิปแล้ว ✅" else queued).append(
            f"{name} — {note}" if note != "เข้าคิวเจนคลิปแล้ว ✅" else name
        )

    if queued:
        _clip_log(f"/genall เข้าคิวเจนวิดีโอ {len(queued)} งาน")

    lines = [f"🎥 <b>/genall — เจนวิดีโอ</b> · งานที่เก็บไว้ {len(runs)} ชิ้น"]
    if queued:
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
        lines += ["", "ทำทีละงานตามลำดับ — <code>/queue</code> ดูสถานะ"]
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
    lines = [f"📋 <b>คิวงาน</b> {len(open_jobs)} งาน\n"]
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
    if command == "/clips":
        _clip_list_runs(chat_id)
        return True
    if command == "/clip":
        _clip_show_run(chat_id, argument)
        return True
    if command == "/queue":
        _clip_queue_text(chat_id)
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
        if want in ("on", "เปิด", "1"):
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


def _clip_telegram_button(chat_id: str, data: str, callback: dict) -> str:
    """ปุ่มอนุมัติ/สั่งแก้ในแชทบอทคลิป (คำนำหน้า clip: ถูกตัดออกมาแล้ว)

    ทุกทางต้องคืนข้อความสั้นๆ เสมอ — Telegram ต้องได้คำตอบ ไม่งั้นปุ่มบนมือถือ
    จะหมุนค้างจนผู้ใช้คิดว่าแอปแฮงก์
    """
    # รูปแบบ: <action>:<job_id>[:<arg>] — ปุ่มรายรูปต้องส่งลำดับใบมาด้วย
    action, _, rest = data.partition(":")
    job_id, _, arg = rest.partition(":")

    # ปุ่ม "เจนคลิปจากงานนี้" ผูกกับ **รหัสสินค้า** ไม่ใช่รหัสงานในคิว
    # (งานเดิมจบไปแล้ว จะสร้างงานใหม่ให้) จึงต้องดักก่อนไปหาในคิว
    if action == "gen":
        return _clip_start_flow(chat_id, arg)

    # ปุ่ม "ดูคลิป" ก็ผูกกับรหัสสินค้าเหมือนกัน — งานในคิวจบไปแล้วแต่ไฟล์ยังอยู่
    if action == "vid":
        return _clip_send_videos(chat_id, arg)

    job = clip_jobs.get(job_id)
    if not job:
        return "ไม่พบงานนี้แล้ว"

    if action in ("img_del", "img_swap", "img_add"):
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8866", "http://localhost:8866",
        "http://127.0.0.1:8877", "http://localhost:8877",
    ],
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
    return {"ok": True, "runs": runs}


@app.get("/api/clips/{item_id}")
async def clips_detail(item_id: str) -> dict:
    """งานหนึ่งชิ้นพร้อมของดิบ — คำตอบเต็มของ GPT และรายละเอียดสินค้า"""
    run = await asyncio.to_thread(clip_store.load_run, DATA_DIR, item_id)
    if not run:
        raise HTTPException(status_code=404, detail="ไม่พบงานนี้")
    return {"ok": True, **run}


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
    return {"ok": True, "jobs": jobs, "busy": clip_runner.busy}


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
    "img_ok", "img_del", "img_swap", "img_add",
    "hl_ok", "hl_del",
    "sb_ok", "sc_ok",
    "vid_ok", "vid_edit",
    "tt_post", "tt_skip",
}


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
    return {
        "ok": True, "added": added, "count": len(added),
        "waiting": len(clip_jobs.waiting()),
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
        return {
            "ok": True,
            "job": _job_card(job, run),
            "run": run,
            "max_images": CLIP_MAX_IMAGES,
            "max_highlights": CLIP_MAX_HIGHLIGHTS,
            "flow_enabled": flow_enabled(),
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
        with _web_lock:
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
        with _web_lock:
            return _apply_edit_text(clip_jobs.get(job_id) or job, instruction, target)

    message = await asyncio.to_thread(work)
    return {"ok": True, "message": message}


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
        with _web_lock:
            return _apply_edit_text(clip_jobs.get(job_id) or job, text, f"highlight:{index}")

    message = await asyncio.to_thread(work)
    return {"ok": True, "message": message}


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
    job = _find_job(job_id)
    if job.get("stage") in clip_queue.OPEN_STAGES:
        raise HTTPException(status_code=400, detail="งานนี้ยังไม่จบ ไม่ต้องสั่งใหม่")

    run = await asyncio.to_thread(clip_store.load_run, DATA_DIR, job.get("item_id", ""))
    run = run or {}
    if run.get("flow_prompts"):
        stage, what = clip_queue.STAGE_READY_FLOW, "เริ่มที่ขั้นเจนคลิป"
    elif run.get("images"):
        stage, what = clip_queue.STAGE_READY_STORYBOARD, "เริ่มที่ขั้นทำสตอรีบอร์ด"
    else:
        stage, what = clip_queue.STAGE_QUEUED, "เริ่มใหม่ตั้งแต่ดึงสินค้า"

    clip_jobs.update(job_id, stage=stage, error="", note=f"สั่งใหม่จากหน้าเว็บ — {what}")
    clip_runner.wake()
    _clip_log(f"สั่งงาน {job_id} ใหม่จากหน้าเว็บ — {what}")
    return {"ok": True, "message": f"เข้าคิวแล้ว · {what}", "stage": stage}


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
    append_log("clip", f"เซิร์ฟเวอร์สายคลิปพร้อม — พอร์ต {PORT}")


if __name__ == "__main__":
    import uvicorn

    print(f"Pipeline Studio — สายเจนคลิป v{APP_VERSION} — http://127.0.0.1:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
