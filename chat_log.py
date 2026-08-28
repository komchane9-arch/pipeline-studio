"""บันทึกบทสนทนา Telegram ลงไฟล์ — ข้อความ · รูป · คลิป ครบทุกทิศทาง

**ทำไมต้องมี** (25 ส.ค. 2026 ผู้ใช้สั่ง "ให้ทำการเก็บ log ทั้งหมด ทั้งข้อความ
รูปภาพ วีดีโอ ไว้ใน google drive ให้ลิ้งกัน") — ก่อนหน้านี้ระบบไม่เก็บบทสนทนา
ไว้ที่ไหนเลย ทั้งที่การอนุมัติทุกครั้งเกิดในแชท พอเลื่อนแชทขึ้นไปไกลก็ตอบไม่ได้
ว่าใครกดอนุมัติคลิปไหนตอนกี่โมง และคลิปที่กดอนุมัติคือไฟล์ไหน

**จุดดัก** — `telegram_bot.call()` เป็นทางผ่านเดียวของ Bot API ทั้งหมด
(sendMessage · editMessageText · answerCallbackQuery · getUpdates) ส่วนไฟล์
ใหญ่ที่ไม่ผ่าน call() คือ sendVideo/sendPhoto/sendMediaGroup ซึ่งประกอบ
multipart เอง จึงต้องดักเพิ่มอีก 3 จุด รวมเป็น 4 จุด — ครบทั้งระบบ

**ไม่คัดลอกไฟล์สื่อซ้ำ** — รูปกับคลิปมีตัวจริงอยู่ใน `shopee_products/` แล้ว
และถูกยกขึ้น Drive โดย `clip_drive.py` อยู่แล้ว บันทึกนี้เก็บแค่ **พาธ + ขนาด**
แล้วชี้ไปหาตัวจริง ไม่งั้นคลิป 10 MB จะถูกเก็บสามชุด (เครื่อง · Drive · log)

**ห้ามพังงานหลัก** — ทุกจุดที่เรียกเข้ามาห่อ try/except ไว้หมด ถ้าเขียน log
ไม่ได้ต้องปล่อยให้ข้อความยังส่งออกไปได้ตามปกติ การบันทึกล้มเหลวไม่ใช่เหตุผล
ที่จะทำให้พี่ไม่ได้รับคลิป

**ห้ามเก็บโทเคน** — เก็บแค่เลขหน้าโทเคน (`123456789` จาก `123456789:AAE...`)
ซึ่งเป็นเลขประจำบอทที่เปิดเผยได้ ส่วนหางที่เป็นรหัสลับตัดทิ้งเสมอ

    python chat_log.py today             ดูบทสนทนาวันนี้
    python chat_log.py show 2026-08-24   ดูวันที่ระบุ
    python chat_log.py render            สร้างไฟล์อ่านง่าย (.md) ของทุกวัน
    python chat_log.py stat              มีกี่วัน กี่ข้อความ กินที่เท่าไร
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# ชื่อโฟลเดอร์ data รับ STUDIO_DATA_DIR เหมือนโมดูลอื่น เพื่อให้เทสแยกที่เก็บได้
_data_name = os.environ.get("STUDIO_DATA_DIR", "data")
DATA_DIR = Path(_data_name) if Path(_data_name).is_absolute() else BASE_DIR / _data_name
LOG_DIR = DATA_DIR / "logs" / "telegram"

# กันสองเธรดเขียนบรรทัดทับกัน — บอทหลายตัวส่งข้อความพร้อมกันได้จริง
_LOCK = threading.Lock()

# เลขบอท -> ชื่อที่คนอ่านออก ลงทะเบียนผ่าน label() ตอนบอทเริ่มทำงาน
_NAMES: dict[str, str] = {}

# เมธอดที่ไม่ต้องบันทึก — ถามสถานะเฉยๆ ไม่ใช่บทสนทนา
# เมธอดที่ขึ้นต้นด้วย get ทั้งหมดถือเป็นการถาม ไม่ใช่การพูด (เจอจริง: getChat
# ถูกบันทึกเป็นแถวเปล่าตอนบอทเริ่มทำงาน ทำให้บันทึกรกโดยไม่ได้ข้อมูลอะไร)
QUIET_METHODS = {"setMyCommands", "deleteWebhook", "setWebhook", "close", "logOut"}

TEXT_LIMIT = 4000        # ตัดข้อความยาวมากกันไฟล์บวม (ข้อความ Telegram ยาวสุด 4096)


# ------------------------------------------------------------------ ที่อยู่

def day_stamp(when: datetime | None = None) -> str:
    return (when or datetime.now()).strftime("%Y-%m-%d")


def raw_path(day: str = "") -> Path:
    """ของดิบรายวัน — หนึ่งบรรทัดหนึ่งเหตุการณ์ เครื่องอ่าน"""
    return LOG_DIR / f"{day or day_stamp()}.jsonl"


def text_path(day: str = "") -> Path:
    """ฉบับอ่านง่ายรายวัน — คนอ่าน"""
    return LOG_DIR / f"{day or day_stamp()}.md"


def bot_id(token: str) -> str:
    """เลขประจำบอทจากโทเคน — **ตัดหางที่เป็นรหัสลับทิ้งเสมอ**"""
    return (token or "").split(":")[0][:20]


def names_path() -> Path:
    return LOG_DIR / "bots.json"


def _load_names() -> None:
    """อ่านชื่อบอทที่เคยรู้จักกลับมา — ทำครั้งเดียวตอนโมดูลถูกใช้ครั้งแรก"""
    if _NAMES:
        return
    try:
        _NAMES.update(json.loads(names_path().read_text(encoding="utf-8")))
    except Exception:
        pass


def label(token: str, name: str) -> None:
    """ตั้งชื่อที่คนอ่านออกให้บอทตัวนี้ แล้วจำไว้ข้ามการรีสตาร์ต

    ไม่ต้องเรียกเอง — `outgoing()` เรียนรู้ชื่อจากผลที่ Telegram ตอบกลับมาให้
    (ผลของ sendMessage มีฟิลด์ `from` ที่เป็นตัวบอทเอง) จึงไม่เปลืองคำขอเพิ่ม
    """
    key = bot_id(token) if ":" in str(token) else str(token or "")
    if not key or not name or _NAMES.get(key) == name:
        return
    _NAMES[key] = name
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        names_path().write_text(json.dumps(_NAMES, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    except Exception:
        pass


def bot_name(key: str) -> str:
    _load_names()
    return _NAMES.get(key) or key or "ไม่ทราบบอท"


# ------------------------------------------------------------------ บันทึก

def _shorten(text: str) -> str:
    text = str(text or "")
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + " …(ตัดที่ %d ตัว)" % len(text)


def _file_note(path) -> dict:
    """ข้อมูลไฟล์สื่อ — เก็บพาธ ไม่คัดลอกตัวไฟล์"""
    try:
        p = Path(path)
        return {"path": str(p), "name": p.name,
                "bytes": p.stat().st_size if p.is_file() else 0,
                "missing": not p.is_file()}
    except Exception:
        return {"path": str(path), "name": "", "bytes": 0, "missing": True}


def write(entry: dict) -> None:
    """เขียนหนึ่งเหตุการณ์ — **ห้ามโยน exception ออกไปเด็ดขาด**"""
    try:
        entry.setdefault("at", datetime.now().isoformat(timespec="seconds"))
        line = json.dumps(entry, ensure_ascii=False)
        with _LOCK:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with io.open(raw_path(), "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:
        pass          # บันทึกล้มเหลวห้ามทำให้ข้อความส่งไม่ออก


def outgoing(token: str, method: str, payload: dict, result=None) -> None:
    """ของที่บอทส่งออก — ข้อความ · การแก้ข้อความ · ป๊อปอัปตอบปุ่ม"""
    if method in QUIET_METHODS or method.startswith("get"):
        return
    payload = payload or {}
    text = payload.get("text") or payload.get("caption") or ""
    if method == "answerCallbackQuery":
        text = payload.get("text") or ""
        if not text:
            return                      # ตอบปุ่มแบบไม่มีข้อความ ไม่ใช่บทสนทนา
    if method == "getUpdates":
        return                          # ขาเข้ามีตัวจัดการของตัวเองด้านล่าง
    entry = {
        "dir": "out",
        "bot": bot_id(token),
        "method": method,
        "chat": str(payload.get("chat_id") or ""),
        "text": _shorten(text),
    }
    if payload.get("reply_markup"):
        entry["buttons"] = _button_labels(payload["reply_markup"])
    if payload.get("message_id"):
        entry["edits"] = payload["message_id"]
    if isinstance(result, dict) and result.get("message_id"):
        entry["message_id"] = result["message_id"]
    # เรียนรู้ชื่อบอทฟรีๆ — ผลที่ Telegram ตอบกลับมี `from` เป็นตัวบอทเอง
    sender = (result or {}).get("from") if isinstance(result, dict) else None
    if isinstance(sender, dict) and sender.get("is_bot"):
        _load_names()
        label(entry["bot"], sender.get("username") or sender.get("first_name") or "")
    write(entry)


def outgoing_media(token: str, method: str, chat_id: str, files, caption: str = "",
                   keyboard=None, message_ids=None) -> None:
    """ของที่บอทส่งออกแบบมีไฟล์ — รูป · คลิป · อัลบั้ม"""
    if not isinstance(files, (list, tuple)):
        files = [files]
    entry = {
        "dir": "out",
        "bot": bot_id(token),
        "method": method,
        "chat": str(chat_id or ""),
        "text": _shorten(caption),
        "files": [_file_note(f) for f in files],
    }
    if keyboard:
        entry["buttons"] = _button_labels(keyboard)
    if message_ids:
        entry["message_id"] = message_ids
    write(entry)


def incoming(token: str, updates) -> None:
    """ของที่เข้ามาจากผู้ใช้ — พิมพ์ข้อความ · กดปุ่ม · ส่งรูป/คลิปเข้ามา"""
    if not updates:
        return
    for update in updates if isinstance(updates, list) else [updates]:
        try:
            _one_update(token, update)
        except Exception:
            pass


def _one_update(token: str, update: dict) -> None:
    query = update.get("callback_query") or {}
    message = update.get("message") or update.get("edited_message") or {}
    if query:
        card = query.get("message") or {}
        write({
            "dir": "in",
            "bot": bot_id(token),
            "method": "กดปุ่ม",
            "chat": str((card.get("chat") or {}).get("id") or ""),
            "who": _who(query.get("from")),
            "text": _shorten(query.get("data") or ""),
            "on_message": card.get("message_id") or 0,
        })
        return
    if not message:
        return
    kinds = []
    for key in ("photo", "video", "document", "voice", "audio", "sticker"):
        if message.get(key):
            kinds.append(key)
    text = message.get("text") or message.get("caption") or ""
    if not text and not kinds:
        return                         # อัปเดตที่ไม่มีเนื้อหา เช่นคนเข้ากลุ่ม
    entry = {
        "dir": "in",
        "bot": bot_id(token),
        "method": "ข้อความ" if not kinds else "+".join(kinds),
        "chat": str((message.get("chat") or {}).get("id") or ""),
        "who": _who(message.get("from")),
        "text": _shorten(text),
        "message_id": message.get("message_id") or 0,
    }
    if kinds:
        entry["file_ids"] = _file_ids(message)
    write(entry)


def _who(sender) -> str:
    sender = sender or {}
    name = " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x)
    handle = sender.get("username")
    return (f"{name} (@{handle})" if name and handle else name or
            (f"@{handle}" if handle else str(sender.get("id") or "")))


def _file_ids(message: dict) -> list[str]:
    found = []
    photos = message.get("photo") or []
    if photos:
        found.append(str(photos[-1].get("file_id") or ""))   # ใบใหญ่สุด
    for key in ("video", "document", "voice", "audio", "sticker"):
        item = message.get(key)
        if isinstance(item, dict) and item.get("file_id"):
            found.append(str(item["file_id"]))
    return [x for x in found if x]


def _button_labels(markup) -> list[str]:
    """ชื่อปุ่มที่ติดมากับข้อความ — เก็บไว้เพื่อให้ย้อนดูได้ว่าตอนนั้นกดอะไรได้บ้าง"""
    try:
        if isinstance(markup, str):
            markup = json.loads(markup)
        rows = (markup or {}).get("inline_keyboard") or (markup or {}).get("keyboard") or []
        names = []
        for row in rows:
            for button in row:
                if isinstance(button, dict):
                    names.append(str(button.get("text") or ""))
                else:
                    names.append(str(button))
        return [x for x in names if x][:40]
    except Exception:
        return []


# ------------------------------------------------------------ อ่าน/แปลงเป็นข้อความ

def days() -> list[str]:
    """วันที่มีบันทึก เรียงจากเก่าไปใหม่"""
    if not LOG_DIR.is_dir():
        return []
    found = [p.stem for p in LOG_DIR.glob("*.jsonl")
             if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)]
    return sorted(found)


def load(day: str = "") -> list[dict]:
    path = raw_path(day)
    if not path.is_file():
        return []
    rows = []
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue          # บรรทัดพังข้ามไป ไม่ทิ้งทั้งวัน
    return rows


def _human_size(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f} MB"
    if count >= 1000:
        return f"{count / 1000:.0f} KB"
    return f"{count} B"


def render(day: str = "", link_base: str = "") -> str:
    """แปลงบันทึกหนึ่งวันเป็นข้อความอ่านง่าย

    `link_base` = พาธนำหน้าสำหรับลิงก์ไฟล์สื่อ ใช้ตอนยกขึ้น Drive เพื่อให้
    กดจากบันทึกไปหาคลิปตัวจริงได้ ถ้าเว้นว่างจะใส่เป็นพาธในเครื่อง
    """
    day = day or day_stamp()
    rows = load(day)
    head = [f"# บทสนทนา Telegram — {day}", ""]
    if not rows:
        return "\n".join(head + ["ไม่มีบันทึกของวันนี้", ""])

    bots = sorted({r.get("bot", "") for r in rows})
    sent = sum(1 for r in rows if r.get("dir") == "out")
    got = len(rows) - sent
    media = [f for r in rows for f in (r.get("files") or [])]
    head += [
        f"บอท {', '.join(bot_name(b) for b in bots)} · "
        f"บอทส่งออก {sent} · ผู้ใช้ส่งเข้า {got} · ไฟล์สื่อ {len(media)} ชิ้น",
        "",
        "| เวลา | ทิศทาง | ชนิด | เนื้อหา |",
        "|---|---|---|---|",
    ]
    lines = []
    for row in rows:
        stamp = str(row.get("at") or "")[11:19]
        arrow = "🤖 ส่งออก" if row.get("dir") == "out" else "👤 เข้ามา"
        kind = _kind_name(row)
        lines.append(f"| {stamp} | {arrow} | {kind} | {_cell(row, link_base)} |")

    body = ["", "---", "", "## เนื้อหาเต็ม", ""]
    for row in rows:
        stamp = str(row.get("at") or "")[11:19]
        arrow = "🤖" if row.get("dir") == "out" else "👤"
        who = row.get("who") or bot_name(row.get("bot", ""))
        body.append(f"### {stamp} {arrow} {who} · {_kind_name(row)}")
        text = row.get("text") or ""
        if text:
            body.append("")
            body.append("```")
            body.append(text)
            body.append("```")
        for note in row.get("files") or []:
            body.append(f"- 📎 {_media_link(note, link_base)} · {_human_size(note.get('bytes') or 0)}"
                        + ("  ⚠️ ไม่พบไฟล์" if note.get("missing") else ""))
        if row.get("buttons"):
            body.append("- ปุ่มที่กดได้ตอนนั้น: " + " · ".join(row["buttons"]))
        body.append("")
    return "\n".join(head + lines + body) + "\n"


def _kind_name(row: dict) -> str:
    method = row.get("method") or ""
    names = {
        "sendMessage": "ข้อความ", "editMessageText": "แก้ข้อความเดิม",
        "answerCallbackQuery": "ป๊อปอัปตอบปุ่ม", "sendVideo": "🎬 คลิป",
        "sendPhoto": "🖼 รูป", "sendMediaGroup": "🖼 อัลบั้มรูป",
        "sendDocument": "📄 ไฟล์",
        # ขาเข้า — ชนิดของที่ผู้ใช้ส่งมา ชื่อดิบมาจาก Telegram จึงต้องแปลเอง
        "photo": "🖼 รูปที่ส่งเข้ามา", "video": "🎬 คลิปที่ส่งเข้ามา",
        "document": "📄 ไฟล์ที่ส่งเข้ามา", "voice": "🎤 ข้อความเสียง",
        "audio": "🔊 ไฟล์เสียง", "sticker": "😀 สติกเกอร์",
    }
    if method in names:
        return names[method]
    # ส่งมาหลายชนิดพร้อมกัน เช่น "photo+document"
    if "+" in method:
        return " + ".join(names.get(part, part) for part in method.split("+"))
    return method


def _cell(row: dict, link_base: str) -> str:
    """ช่องสรุปในตาราง — ตัดสั้นและกัน | ไม่ให้ทำตารางแตก"""
    text = (row.get("text") or "").replace("\n", " ").replace("|", "／")
    text = re.sub(r"<[^>]+>", "", text).strip()
    if len(text) > 90:
        text = text[:90] + "…"
    names = [n.get("name", "") for n in (row.get("files") or [])]
    if names:
        tag = " ".join(f"`{n}`" for n in names[:3])
        text = (tag + " " + text).strip()
    return text or "—"


def _media_link(note: dict, link_base: str) -> str:
    name = note.get("name") or "ไฟล์"
    if link_base:
        return f"[{name}]({link_base}/{name})"
    return f"`{note.get('path') or name}`"


def write_text(day: str = "", link_base: str = "") -> Path:
    """เขียนฉบับอ่านง่ายลงข้างๆ ของดิบ"""
    day = day or day_stamp()
    path = text_path(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(day, link_base), encoding="utf-8")
    return path


# ------------------------------------------------------------------ คำสั่ง

def _say(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((message + "\n").encode("utf-8", "replace"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="บันทึกบทสนทนา Telegram")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("today", help="ดูบทสนทนาวันนี้")
    show = sub.add_parser("show", help="ดูวันที่ระบุ")
    show.add_argument("day")
    render_cmd = sub.add_parser("render", help="สร้างไฟล์อ่านง่ายของทุกวัน")
    render_cmd.add_argument("--day", default="")
    sub.add_parser("stat", help="สรุปว่ามีกี่วัน กี่ข้อความ")
    args = parser.parse_args(argv)

    if args.cmd == "show":
        _say(render(args.day))
    elif args.cmd == "render":
        targets = [args.day] if args.day else days()
        for day in targets:
            _say(f"เขียนแล้ว: {write_text(day)}")
        if not targets:
            _say("ยังไม่มีบันทึก")
    elif args.cmd == "stat":
        found = days()
        if not found:
            _say("ยังไม่มีบันทึก — ที่เก็บ: %s" % LOG_DIR)
            return 0
        total = 0
        size = 0
        for day in found:
            rows = load(day)
            total += len(rows)
            size += raw_path(day).stat().st_size
        _say(f"📒 บันทึกบทสนทนา Telegram")
        _say(f"   ที่เก็บ    : {LOG_DIR}")
        _say(f"   มีทั้งหมด  : {len(found)} วัน ({found[0]} ถึง {found[-1]})")
        _say(f"   เหตุการณ์  : {total} รายการ · กินที่ {_human_size(size)}")
    else:
        _say(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
