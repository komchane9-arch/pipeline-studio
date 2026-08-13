"""บอท Telegram สายหาโพสต์แมส (@NewestBoyBot) — โปรเซสแยกของตัวเอง

ทำไมต้องแยกโปรเซส: getUpdates ของโทเคนหนึ่งตัวมีตัวอ่านได้ตัวเดียว (อ่านซ้อน
= 409 Conflict ข้อความหายสลับไปมา — บทเรียนเดียวกับบอทสายคลิปที่แยกไป
clip_app.py) บอทตัวนี้จึงตั้ง role เป็น "mass" ซึ่ง app.py (8866) จะไม่เฝ้า
แล้วโปรเซสนี้เฝ้าเองทั้งตัว

คำสั่ง:
    /find            เริ่มสแกนหาโพสต์แมสทุกกลุ่มทันที
    /add <ลิงก์>     กดเข้าร่วมกลุ่ม + เพิ่มเข้า list ค้นหา
    /groups          ดูกลุ่มทั้งหมด กดปุ่มลบได้
    /set             ดู/ปรับเกณฑ์ (ไลค์ แชร์ คอมเมนต์ รอบเลื่อนฟีด)

รัน: python fb_mass_bot.py   (ต้องรันค้างไว้เหมือน app.py/clip_app.py)
"""

from __future__ import annotations

import html
import msvcrt
import re
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import fb_mass_finder as mf          # พ่วง utf-8 guard ของ stdout มาด้วย
import studio_shared
import telegram_bot
from bot_profiles import FarmError

LOCK_FILE = mf.DATA_DIR / "fb_mass_bot.lock"
LOG_FILE = studio_shared.LOG_DIR / "fb_mass.log"
LOG_LIMIT = studio_shared.LOG_LIMIT_BYTES

HELP = "\n".join([
    "🤖 <b>บอทหาโพสต์แมส</b>",
    "/find — เริ่มหาโพสต์แมสทุกกลุ่มตอนนี้",
    "/add ลิงก์กลุ่ม — เข้าร่วมกลุ่ม + เพิ่มเข้า list",
    "/groups — ดูกลุ่มทั้งหมด เลือกลบได้",
    "/set — ดู/ปรับเกณฑ์คัดโพสต์",
])

# ชื่อเกณฑ์ที่ /set รับ — รับทั้งไทย/อังกฤษ (พิมพ์แบบไหนก็ต้องเข้าใจ)
SET_FIELDS = {
    # เกณฑ์หลักคือ engagement รวม — รับทั้งคำใหม่และคำเก่า "ไลค์" (คนชินคำเดิม)
    "min_likes": ("engagement", "เอนเกจ", "แมส", "ไลค์", "ไลก์", "like", "likes"),
    "min_shares": ("แชร์", "share", "shares"),
    "min_comments": ("คอมเมนต์", "คอมเม้น", "comment", "comments"),
    "max_posts": ("โพสต์", "จำนวนโพสต์", "post", "posts"),
    "scrolls": ("เลื่อน", "scroll", "scrolls"),
}

# งานเบราว์เซอร์ (สแกน/เข้ากลุ่ม) ทำทีละอย่าง — Bot10 มีตัวเดียว
_busy = threading.Lock()


def log(message: str) -> None:
    """เขียน log ลงไฟล์ (หมุนเองที่ 90% ของเพดาน) + สะท้อนขึ้นจอ"""
    print(f"{datetime.now():%H:%M:%S} {message}", flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.is_file() and LOG_FILE.stat().st_size >= LOG_LIMIT * 0.9:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            LOG_FILE.replace(LOG_FILE.with_name(f"fb_mass-{stamp}.log"))
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now():%H:%M:%S} {message}\n")
    except OSError:
        pass


def say(token: str, chat_id: str, text: str, keyboard: dict | None = None) -> None:
    try:
        telegram_bot.send_message(token, chat_id, text, keyboard)
    except telegram_bot.TelegramError as error:
        log(f"ส่งข้อความไม่ได้: {error}")


# ------------------------------------------------------------------- คำสั่ง

def groups_card(config: dict) -> tuple[str, dict | None]:
    groups = config.get("groups", [])
    if not groups:
        return "ยังไม่มีกลุ่มใน list — เพิ่มด้วย /add ลิงก์กลุ่ม", None
    lines = [f"📋 <b>กลุ่มที่ค้นหา ({len(groups)} กลุ่ม)</b>", ""]
    rows = []
    for index, group in enumerate(groups, 1):
        name = group.get("name") or group.get("url", "")
        lines.append(f"{index}. {html.escape(name[:60])}")
        rows.append([{
            "text": f"🗑 ลบ {index}. {name[:24]}",
            "callback_data": f"md:{index - 1}",
        }])
    lines += ["", "กดปุ่มด้านล่างเพื่อลบกลุ่มออกจาก list"]
    return "\n".join(lines), {"inline_keyboard": rows}


def do_find(token: str, chat_id: str) -> None:
    if not _busy.acquire(blocking=False):
        say(token, chat_id, "⏳ มีงานเบราว์เซอร์ค้างอยู่ — รอให้เสร็จก่อนแล้วสั่งใหม่")
        return

    def work() -> None:
        try:
            config = mf.load_config()
            say(token, chat_id,
                f"🔎 เริ่มสแกน {len(config.get('groups', []))} กลุ่ม "
                f"(~35 วิ/กลุ่ม) — เจอโพสต์ใหม่จะส่งมาทีละกลุ่ม")
            summary = mf.run(use_telegram=True, log=log)
            log(f"สแกนเสร็จ ส่งใหม่ {summary['sent_new']} ลิงก์")
        except (mf.MassFinderError, FarmError) as error:
            say(token, chat_id, f"❌ {error}")
            log(f"สแกนล้ม: {error}")
        except Exception:
            say(token, chat_id, "❌ สแกนล้มกลางทาง — ดูรายละเอียดใน log")
            log(f"สแกนล้มกลางทาง:\n{traceback.format_exc()}")
        finally:
            _busy.release()

    threading.Thread(target=work, daemon=True).start()


def do_add(token: str, chat_id: str, url: str) -> None:
    if not re.match(r"https?://(www\.|web\.|m\.)?facebook\.com/", url):
        say(token, chat_id,
            "ต่อท้ายด้วยลิงก์กลุ่ม Facebook เช่น\n"
            "<code>/add https://www.facebook.com/share/g/xxxx/</code>")
        return
    if not _busy.acquire(blocking=False):
        say(token, chat_id, "⏳ มีงานเบราว์เซอร์ค้างอยู่ — รอให้เสร็จก่อนแล้วสั่งใหม่")
        return

    def work() -> None:
        try:
            say(token, chat_id, "🚪 กำลังเปิดกลุ่มด้วยโปรไฟล์บอท…")
            result = mf.join_group(url, log=log)
            status = {
                "joined-request": "กดเข้าร่วมแล้ว (ถ้ากลุ่มปิดต้องรอแอดมินอนุมัติ)",
                "already": "เป็นสมาชิกอยู่แล้ว",
                "pending": "เคยส่งคำขอไว้แล้ว — รอแอดมินอนุมัติ",
            }[result["status"]]
            note = ("เพิ่มเข้า list ค้นหาแล้ว ✅" if result["added"]
                    else "มีอยู่ใน list แล้ว ไม่เพิ่มซ้ำ")
            say(token, chat_id,
                f"✅ <b>{html.escape(result['name'] or url)}</b>\n{status}\n{note}")
            log(f"/add {url} → {result['status']} added={result['added']}")
        except (mf.MassFinderError, FarmError) as error:
            say(token, chat_id, f"❌ {error}")
            log(f"/add ล้ม: {error}")
        except Exception:
            say(token, chat_id, "❌ เข้าร่วมกลุ่มไม่สำเร็จ — ดูรายละเอียดใน log")
            log(f"/add ล้มกลางทาง:\n{traceback.format_exc()}")
        finally:
            _busy.release()

    threading.Thread(target=work, daemon=True).start()


def do_set(token: str, chat_id: str, argument: str) -> None:
    config = mf.load_config()
    if not argument:
        say(token, chat_id, mf.settings_text(config))
        return
    parts = argument.split()
    value = parts[-1] if parts and parts[-1].lstrip("-").isdigit() else None
    field = next(
        (key for key, aliases in SET_FIELDS.items()
         if any(alias in argument.lower() for alias in aliases)),
        None)
    if field is None or value is None:
        say(token, chat_id, "ไม่เข้าใจคำสั่ง — ดูวิธีปรับ:\n\n" + mf.settings_text(config))
        return
    number = max(0, int(value))
    if field == "min_likes" and number == 0:
        say(token, chat_id, "เกณฑ์ engagement ปิดไม่ได้ — ใส่ค่ามากกว่า 0")
        return
    if field == "scrolls":
        number = max(1, min(30, number))
    config[field] = number
    mf.save_config(config)
    log(f"/set {field} = {number}")
    say(token, chat_id, "บันทึกแล้ว ✅\n\n" + mf.settings_text(config))


def on_command(token: str, chat_id: str, text: str) -> None:
    command, _, argument = text.partition(" ")
    command = command.lower().split("@")[0]
    argument = argument.strip()
    if command in ("/start", "/help"):
        say(token, chat_id, HELP)
    elif command == "/find":
        do_find(token, chat_id)
    elif command == "/add":
        do_add(token, chat_id, argument)
    elif command == "/groups":
        message, keyboard = groups_card(mf.load_config())
        say(token, chat_id, message, keyboard)
    elif command == "/set":
        do_set(token, chat_id, argument)
    else:
        say(token, chat_id, "ไม่รู้จักคำสั่งนี้\n\n" + HELP)


def on_callback(token: str, callback: dict) -> None:
    data = str(callback.get("data") or "")
    chat_id = str(((callback.get("message") or {}).get("chat") or {}).get("id", ""))
    answer = ""
    if data.startswith("mr:"):
        # ผู้ใช้กด "ไม่เอาโพสต์นี้" — เข้าบัญชีดำถาวร รอบหน้าไม่นับไม่ส่งอีก
        post_id = data[3:]
        entry = mf.reject_post(post_id)
        answer = "ตัดโพสต์นี้แล้ว — จะหาโพสต์อื่นมาแทนในรอบถัดไป"
        log(f"ไม่เอาโพสต์ {post_id} ({entry.get('likes', 0)} ไลค์ "
            f"จาก {entry.get('group') or 'ไม่ทราบกลุ่ม'})")
        message = callback.get("message") or {}
        original = message.get("text", "")
        if message.get("message_id"):
            # ขีดฆ่าข้อความเดิม + ปุ่มหายไปเอง (editMessageText ไม่ส่ง keyboard)
            try:
                telegram_bot.call(token, "editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message["message_id"],
                    "text": f"🚫 ตัดแล้ว\n<s>{html.escape(original)}</s>",
                    "parse_mode": "HTML",
                })
            except telegram_bot.TelegramError as error:
                log(f"ขีดฆ่าข้อความไม่สำเร็จ: {error}")
    elif data.startswith("md:"):
        config = mf.load_config()
        index = int(data[3:])
        if 0 <= index < len(config["groups"]):
            removed = config["groups"].pop(index)
            mf.save_config(config)
            name = removed.get("name") or removed.get("url", "")
            answer = f"ลบ {name[:40]} แล้ว"
            log(f"ลบกลุ่มออกจาก list: {name}")
            message, keyboard = groups_card(config)
            say(token, chat_id, message, keyboard)
        else:
            answer = "รายการนี้ถูกลบไปแล้ว — ดูรายการล่าสุดด้านล่าง"
            message, keyboard = groups_card(mf.load_config())
            say(token, chat_id, message, keyboard)
    try:
        telegram_bot.call(token, "answerCallbackQuery", {
            "callback_query_id": callback.get("id", ""), "text": answer[:180],
        })
    except telegram_bot.TelegramError as error:
        log(f"ตอบปุ่มไม่สำเร็จ: {error}")


# --------------------------------------------------------------------- ลูปหลัก

def main() -> int:
    # กันเปิดสองตัว — getUpdates ซ้อนกัน = 409 ข้อความหายสลับไปมา
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = open(LOCK_FILE, "a+b")
    try:
        msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("❌ fb_mass_bot.py เปิดอยู่แล้วอีกตัว — ห้ามรันซ้อน (getUpdates ชนกัน)")
        return 1

    config = mf.load_config()
    token, home_chat = mf.telegram_target(config)
    log(f"บอทหาโพสต์แมสเริ่มทำงาน (chat {home_chat})")
    say(token, home_chat, "🟢 บอทหาโพสต์แมสพร้อมทำงาน\n\n" + HELP)

    offset = 0
    while True:
        try:
            updates = telegram_bot.call(token, "getUpdates", {
                "timeout": telegram_bot.POLL_TIMEOUT, "offset": offset,
            }, timeout=telegram_bot.POLL_REQUEST_TIMEOUT)
        except telegram_bot.TelegramError as error:
            log(f"อ่านข้อความไม่ได้: {error}")
            time.sleep(15)
            continue
        for update in updates:
            offset = max(offset, update.get("update_id", 0) + 1)
            try:
                callback = update.get("callback_query")
                if callback:
                    on_callback(token, callback)
                    continue
                message = update.get("message") or {}
                chat_id = str((message.get("chat") or {}).get("id", ""))
                text = (message.get("text") or "").strip()
                if not chat_id or not text:
                    continue
                if chat_id != str(home_chat):
                    # คุยกับเจ้าของคนเดียว — คนอื่นเจอบอทแล้วสั่งไม่ได้
                    log(f"เมินข้อความจาก chat แปลกหน้า {chat_id}")
                    continue
                if text.startswith("/"):
                    on_command(token, chat_id, text)
                else:
                    say(token, chat_id, HELP)
            except Exception:
                # ข้อความเดียวพังต้องไม่ฆ่าลูป — แต่ต้องลง log เสมอ (กติกา 2.4)
                log(f"จัดการข้อความไม่สำเร็จ:\n{traceback.format_exc()}")


if __name__ == "__main__":
    raise SystemExit(main())
