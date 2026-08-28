"""ส่งจุดขายที่ Gemini คัดไว้ไปให้อนุมัติทาง Telegram

ทำไมใช้ getUpdates ไม่ใช่ webhook:
  webhook ต้องมี URL สาธารณะ + HTTPS ซึ่งเครื่องในบ้านไม่มี (ต้องเปิดพอร์ต/ทำ tunnel
  ซึ่งเป็นช่องให้คนนอกยิงเข้ามาด้วย) ส่วน getUpdates เป็นการ "ถามออกไป" ฝ่ายเดียว
  ไม่ต้องเปิดอะไรทิ้งไว้เลย — ช้ากว่าไม่กี่วินาที แลกกับไม่ต้องเปิดบ้านให้ใคร

การรออนุมัติเป็นแบบไม่บล็อก: บันทึกคำขอลงไฟล์แล้วจบ request ทันที
มี thread เดียวคอยอ่าน getUpdates แล้วอัปเดตผลลงไฟล์ หน้าเว็บถามสถานะเอาเอง
(ถ้าให้ request ค้างรอผู้ใช้กดในแอป Telegram = เว็บค้างเป็นนาที)
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import chat_log
import studio_shared

API_BASE = "https://api.telegram.org/bot"
# long polling — Telegram ค้างสายให้จนกว่าจะมีอะไรใหม่
#
# ลดจาก 25 → 10 เพื่อ**เพิ่มส่วนเผื่อความหน่วงเน็ต** ไม่ใช่เพื่อความเร็ว
#   เดิม  25 + เผื่อ 45 = 70
#   ใหม่  10 + เผื่อ 60 = 70
# ข้อความที่เข้ามายังได้รับทันทีเหมือนเดิม (Telegram ตอบกลับทันทีเมื่อมีของ
# ไม่รอครบเวลา) แค่รอบที่ "ไม่มีอะไร" จบเร็วขึ้น แลกกับถามถี่ขึ้น
# ~3,400 → ~8,600 ครั้ง/วัน ซึ่งยังห่างเพดานของ Telegram มาก
POLL_TIMEOUT = 10
REQUEST_TIMEOUT = 40
# getUpdates ต้องใช้ timeout ของตัวเอง ห้ามใช้ค่าเดียวกับคำขอทั่วไป
#
# Telegram ค้างสายไว้ถึง POLL_TIMEOUT วินาทีก่อนตอบ ถ้า socket timeout เป็น 40
# จะเหลือส่วนเผื่อความหน่วงของเน็ตแค่ 15 วินาที — วัดจริง 10 ส.ค. เส้นทางไป
# api.telegram.org หน่วงเป็นช่วงๆ ถึง 22.6 วินาที (ปกติ 1.4 วินาที) พอชนกัน
# ทุกรอบที่หน่วงจะ read timeout แล้ว watcher นอน 15 วินาที = หูหนวก 55 วินาทีต่อครั้ง
#
# ต้องเป็น "ส่วนเผื่อคงที่" ไม่ใช่คำนวณจาก POLL_TIMEOUT — ไม่งั้นพอลด POLL_TIMEOUT
# ตัวนี้หดตามด้วย ส่วนเผื่อเท่าเดิม ไม่ได้อะไรขึ้นมาเลย (พลาดมาแล้ว 12 ส.ค.)
POLL_NETWORK_SLACK = 60
POLL_REQUEST_TIMEOUT = POLL_TIMEOUT + POLL_NETWORK_SLACK
APPROVAL_LIMIT = 100

# ปุ่มที่ส่งไปกับข้อความ — callback_data ขึ้นต้นด้วย id ของคำขอเสมอ
ACTION_APPROVE = "ok"
ACTION_REJECT = "no"
ACTION_EDIT = "edit"

# คำนำหน้าที่จองไว้ให้ปุ่มของงานอื่น — เจอคำนำหน้าพวกนี้แล้วส่งต่อให้ on_callback
# ไม่ต้องไปหาใน store ของคำขออนุมัติ (ซึ่งหาไม่เจอแล้วปุ่มจะหมุนค้าง)
CALLBACK_PREFIXES = ("fb:", "clip:")


TELEGRAM_HOSTS = ("api.telegram.org",)
_real_getaddrinfo = socket.getaddrinfo


def _ipv4_only_getaddrinfo(host, port, family=0, *args, **kwargs):
    """บังคับให้ต่อ Telegram ผ่าน IPv4 เท่านั้น

    **วัดจริง 13 ส.ค. บนเครื่องนี้**
      api.telegram.org ผ่าน IPv6 → ต่อไม่ติด หมดเวลาที่ 21.02 วินาที
      api.telegram.org ผ่าน IPv4 → ต่อได้ใน 0.21 วินาที

    ชื่อนี้ตอบทั้ง IPv6 และ IPv4 และ Python ไล่ตามลำดับที่ได้มา = ลอง IPv6 ก่อน
    เสมอ ทุกการเชื่อมต่อใหม่จึงทิ้งเวลาไป 21 วินาทีก่อนถอยมา IPv4 — นี่คือที่มา
    ของ "หน่วงเป็นช่วงๆ ถึง 22.6 วินาที" ที่จดไว้ข้างบน ซึ่งตอนนั้นแก้ด้วยการ
    เพิ่มส่วนเผื่อ timeout (แก้ที่อาการ) เพราะยังไม่รู้สาเหตุ

    กรองเฉพาะโฮสต์ของ Telegram — ไม่ไปยุ่งกับ Shopee/Google/ที่อื่นในโปรเซส
    ถ้าวันหนึ่งเครื่องนี้มี IPv6 ใช้ได้จริง โค้ดนี้ก็ยังทำงานถูก (Telegram มี IPv4)
    """
    if host in TELEGRAM_HOSTS:
        family = socket.AF_INET
    return _real_getaddrinfo(host, port, family, *args, **kwargs)


socket.getaddrinfo = _ipv4_only_getaddrinfo


class TelegramError(RuntimeError):
    """คุยกับ Telegram ไม่สำเร็จ"""


def call(token: str, method: str, payload: dict | None = None,
         timeout: float | None = None) -> dict:
    """เรียก Bot API หนึ่งเมธอด (timeout=None = ใช้ค่ามาตรฐาน)"""
    url = f"{API_BASE}{token}/{method}"
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(
            request, timeout=timeout or REQUEST_TIMEOUT
        ) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")[:200]
        raise TelegramError(f"Telegram ตอบ {error.code}: {body}") from error
    except OSError as error:
        raise TelegramError(f"ต่อ Telegram ไม่ได้: {error}") from error
    if not result.get("ok"):
        raise TelegramError(result.get("description", "Telegram ปฏิเสธคำขอ"))
    payload_out = result.get("result", {})
    # บันทึกบทสนทนา — จุดดักหลักของทั้งระบบ ครอบทุกเมธอดที่ส่งเป็น JSON
    # ห่อ try ไว้เพราะการบันทึกล้มเหลวห้ามทำให้ข้อความส่งไม่ออก
    try:
        if method == "getUpdates":
            chat_log.incoming(token, payload_out)
        else:
            chat_log.outgoing(token, method, payload or {}, payload_out)
    except Exception:
        pass
    return payload_out


def describe_bot(token: str) -> dict:
    """เช็คว่าโทเคนใช้ได้ไหม — ใช้ตอนกดปุ่มทดสอบในหน้าตั้งค่า"""
    me = call(token, "getMe")
    return {"username": me.get("username", ""), "name": me.get("first_name", "")}


def find_chat_id(token: str) -> str:
    """หา chat id จากข้อความล่าสุดที่คนทักบอทมา

    ผู้ใช้ไม่ต้องไปหาเลข chat id เอง แค่ทัก /start ให้บอทครั้งเดียวก็พอ
    """
    updates = call(token, "getUpdates", {"timeout": 0, "limit": 20})
    for update in reversed(updates):
        message = update.get("message") or update.get("callback_query", {}).get("message")
        chat = (message or {}).get("chat") or {}
        if chat.get("id"):
            return str(chat["id"])
    return ""


# ------------------------------------------------------------- คิวคำขออนุมัติ


class ApprovalStore:
    """คำขออนุมัติทั้งหมด เก็บเป็นไฟล์เดียว อ่าน/เขียนใต้ล็อก"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()

    def _guard(self, what: str):
        """ล็อก**ข้ามโปรเซส** ตอนอ่าน-แก้-เขียน

        ไฟล์นี้ถูกเปิดจากสองเซิร์ฟเวอร์พร้อมกัน — app.py และ clip_app.py ต่างสร้าง
        ApprovalStore ชี้ `data/approvals.json` ไฟล์เดียวกัน ส่วน `self.lock` เป็น
        RLock ในโปรเซส มองไม่เห็นอีกฝั่งเลย สองฝั่งอ่านพร้อมกัน แก้คนละรายการ
        แล้วเขียนทับกัน ผลคือผลการกดอนุมัติในแชทหายไปเฉยๆ โดยไม่มี error
        """
        return studio_shared.data_lock(self.path.name, label=what)

    def _read(self) -> list[dict]:
        return studio_shared.read_json(self.path, [])

    def _write(self, items: list[dict]) -> None:
        # เดิมใช้ชื่อไฟล์ชั่วคราว approvals.tmp เหมือนกันทั้งสองโปรเซส เขียนพร้อมกัน
        # เมื่อไรมีสิทธิ์ replace ไฟล์ที่อีกฝั่งเขียนค้างครึ่งทางทับของจริง
        studio_shared.write_json_atomic(self.path, items[-APPROVAL_LIMIT:])

    def add(self, product: str, highlights: list[str], extra: dict | None = None) -> dict:
        entry = {
            "id": f"a{int(time.time() * 1000) % 1_000_000_000}",
            "product": product,
            "highlights": highlights,
            "status": "pending",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "decided_at": None,
            "message_id": None,
            **(extra or {}),
        }
        with self.lock, self._guard("เพิ่มคำขออนุมัติ"):
            items = self._read()
            items.append(entry)
            self._write(items)
        return entry

    def update(self, approval_id: str, **changes) -> dict | None:
        with self.lock, self._guard(f"อัปเดตคำขอ {approval_id}"):
            items = self._read()
            for entry in items:
                if entry["id"] == approval_id:
                    entry.update(changes)
                    self._write(items)
                    return entry
        return None

    def get(self, approval_id: str) -> dict | None:
        return next((e for e in self._read() if e["id"] == approval_id), None)

    def listing(self) -> list[dict]:
        return list(reversed(self._read()))

    def pending_ids(self) -> set[str]:
        return {e["id"] for e in self._read() if e["status"] == "pending"}


def format_message(product: str, highlights: list[str]) -> str:
    lines = [f"🧾 <b>{_escape(product[:120])}</b>", "", "จุดขายที่คัดมา:"]
    lines += [f"{index}. {_escape(text)}" for index, text in enumerate(highlights, 1)]
    lines += ["", "อนุมัติให้เอาไปทำคลิปไหม?"]
    return "\n".join(lines)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


MAX_UPLOAD_BYTES = 50 * 1024 * 1024      # เพดานอัปโหลดของ Bot API


def send_video(
    token: str, chat_id: str, video: Path, caption: str = "",
    keyboard: dict | None = None,
) -> int:
    """ส่งไฟล์คลิปเข้าแชท — ตัวส่งจริงตัวเดียวของทั้งระบบ

    ใช้ร่วมกันทั้งตอนขออนุมัติคลิปที่เพิ่งเจน และตอนเปิดดูคลิปเก่าย้อนหลัง
    จะได้ไม่มีพฤติกรรมสองแบบ (เช่นตัวหนึ่งรองรับไฟล์ใหญ่ อีกตัวเงียบหาย)

    ไฟล์เกิน 50 MB ส่งไม่ได้ตามข้อจำกัดของ Bot API — ส่งเป็นข้อความบอก path
    แทน เพื่อให้ยังกดปุ่มต่อได้ ไม่ใช่เงียบหายไปเฉยๆ
    """
    size = video.stat().st_size if video.is_file() else 0
    if not video.is_file() or size > MAX_UPLOAD_BYTES:
        reason = ("ไม่พบไฟล์คลิป" if not video.is_file()
                  else f"คลิปใหญ่ {size / 1e6:.0f} MB ส่งเข้าแชทไม่ได้")
        body = {
            "chat_id": chat_id,
            "text": f"{caption}\n\n({reason})\nไฟล์: <code>{_escape(str(video))}</code>",
            "parse_mode": "HTML",
        }
        if keyboard:
            body["reply_markup"] = keyboard
        return call(token, "sendMessage", body).get("message_id", 0)

    fields = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    if keyboard:
        fields["reply_markup"] = json.dumps(keyboard)
    payload = _multipart(fields, ("video", video))
    request = urllib.request.Request(
        f"{API_BASE}{token}/sendVideo", data=payload["body"],
        headers={"Content-Type": payload["content_type"]},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.loads(response.read().decode("utf-8"))
    except OSError as error:
        raise TelegramError(f"ส่งคลิปไม่สำเร็จ: {error}") from error
    if not result.get("ok"):
        raise TelegramError(result.get("description", "Telegram ปฏิเสธคลิป"))
    sent_id = result["result"].get("message_id", 0)
    try:
        chat_log.outgoing_media(token, "sendVideo", chat_id, [video], caption,
                                keyboard, sent_id)
    except Exception:
        pass
    return sent_id


def send_video_approval(
    token: str, chat_id: str, entry: dict, video: Path,
    keyboard: dict | None = None,
) -> int:
    """ส่งคลิปที่เจนเสร็จเข้า Telegram ให้ดูแล้วกดอนุมัติก่อนโพสต์

    ต้องส่งเป็น multipart เพราะ sendVideo รับไฟล์จริง ไม่ใช่ JSON
    ไฟล์เกิน 50 MB ส่งไม่ได้ตามข้อจำกัดของ Bot API — ส่งเป็นข้อความบอก path แทน
    เพื่อให้ยังกดอนุมัติได้ ไม่ใช่เงียบหายไปเฉยๆ

    ผู้เรียกส่ง `keyboard` ของตัวเองเข้ามาได้ — งานที่ไม่ได้ใช้ store ของคำขออนุมัติ
    (เช่นคิวเจนคลิป) ต้องใช้ปุ่มคำนำหน้า clip: ของตัวเอง ถ้าใช้ปุ่มปริยายจะกดแล้ว
    ขึ้น "ไม่พบคำขอนี้แล้ว" ทุกครั้ง เพราะไปหา id ในคนละที่เก็บ
    """
    keyboard = keyboard or {
        "inline_keyboard": [[
            {"text": "✅ อนุมัติ โพสต์เลย", "callback_data": f"{entry['id']}:{ACTION_APPROVE}"},
            {"text": "❌ ไม่เอา", "callback_data": f"{entry['id']}:{ACTION_REJECT}"},
        ]]
    }
    caption = f"🎬 <b>{_escape(entry['product'][:120])}</b>\n\nคลิปเจนเสร็จแล้ว โพสต์ได้ไหม?"
    return send_video(token, chat_id, video, caption, keyboard)


def _multipart(
    fields: dict[str, str], file_field: tuple[str, Path], mime: str = "video/mp4"
) -> dict:
    """ประกอบ multipart/form-data เอง — เลี่ยงการพึ่งไลบรารีเพิ่มสำหรับงานเดียว"""
    boundary = "----PipelineStudio" + str(int(time.time() * 1000))
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{value}\r\n".encode("utf-8")
        )
    name, path = file_field
    chunks.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
        f'filename="{path.name}"\r\nContent-Type: {mime}\r\n\r\n'.encode("utf-8")
    )
    chunks.append(path.read_bytes())
    chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return {
        "body": b"".join(chunks),
        "content_type": f"multipart/form-data; boundary={boundary}",
    }


# ------------------------------------------------------ ส่ง/แก้ข้อความทั่วไป
# ใช้กับงานโพสต์อัตโนมัติ (fb_auto_post) ที่ต้องคุยกับผู้ใช้หลายจังหวะ


def send_message(
    token: str, chat_id: str, text: str, keyboard: dict | None = None,
    preview: bool = True,
) -> int:
    """ส่งข้อความ · preview=False เมื่อไม่อยากให้ Telegram กางการ์ดตัวอย่างลิงก์

    ลิงก์สินค้าที่แปะไว้ให้ก๊อป ไม่ได้มีไว้ให้ดู — ปล่อยให้กางการ์ดจะดันเนื้อหา
    ที่ต้องตรวจจริงตกจอไปหมด
    """
    payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = keyboard
    if not preview:
        payload["disable_web_page_preview"] = True
    return call(token, "sendMessage", payload).get("message_id", 0)


def send_media_group(
    token: str, chat_id: str, photos: list[Path], caption: str = "",
) -> list[int]:
    """ส่งรูปหลายใบเป็น **อัลบั้มเดียว** ไม่ใช่ทีละข้อความ

    ส่งทีละใบทำให้แชทยาวเป็นหางว่าว และผู้ใช้เลื่อนดูทีละใบจนลืมว่ากำลังตรวจอะไร
    อัลบั้มเห็นครบในกรอบเดียว เทียบกันได้ทันที (Telegram จำกัด 2–10 ใบต่ออัลบั้ม)
    """
    files = [Path(p) for p in photos if Path(p).is_file()][:10]
    if not files:
        return []
    if len(files) == 1:
        return [send_photo(token, chat_id, files[0], caption)]

    boundary = "----PipelineStudioAlbum" + str(int(time.time() * 1000))
    media, chunks = [], []
    for index, path in enumerate(files):
        name = f"file{index}"
        item = {"type": "photo", "media": f"attach://{name}"}
        if index == 0 and caption:
            item.update({"caption": caption[:1000], "parse_mode": "HTML"})
        media.append(item)
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
            f'filename="{path.name}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode("utf-8")
        )
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")
    head = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n'
        f"{chat_id}\r\n".encode("utf-8"),
        f'--{boundary}\r\nContent-Disposition: form-data; name="media"\r\n\r\n'
        f"{json.dumps(media, ensure_ascii=False)}\r\n".encode("utf-8"),
    ]
    body = b"".join(head + chunks) + f"--{boundary}--\r\n".encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}{token}/sendMediaGroup", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.loads(response.read().decode("utf-8"))
    except OSError as error:
        raise TelegramError(f"ส่งอัลบั้มรูปไม่สำเร็จ: {error}") from error
    if not result.get("ok"):
        raise TelegramError(result.get("description", "Telegram ปฏิเสธอัลบั้ม"))
    sent_ids = [item.get("message_id", 0) for item in result.get("result", [])]
    try:
        chat_log.outgoing_media(token, "sendMediaGroup", chat_id, files, caption,
                                None, sent_ids)
    except Exception:
        pass
    return sent_ids


def edit_message(
    token: str, chat_id: str, message_id: int, text: str, keyboard: dict | None = None
) -> None:
    """แก้ข้อความเดิมแทนการส่งใหม่

    ใช้กับการ์ดเลือกกลุ่ม: ติ๊กทีละกลุ่มแล้วส่งการ์ดใหม่ทุกครั้งจะได้แชทยาวเป็นหาง
    แก้ข้อความเดิมทำให้เห็นสถานะล่าสุดที่เดียว
    ข้อความที่ไม่เปลี่ยนเลย Telegram จะตอบ error "message is not modified"
    ซึ่งไม่ใช่ปัญหาจริง จึงกลืนทิ้ง
    """
    payload: dict = {
        "chat_id": chat_id, "message_id": message_id,
        "text": text, "parse_mode": "HTML",
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        call(token, "editMessageText", payload)
    except TelegramError as error:
        if "not modified" not in str(error).lower():
            raise


def send_photo(
    token: str, chat_id: str, photo: Path, caption: str = "",
    keyboard: dict | None = None,
) -> int:
    """ส่งรูปกลับเข้าแชท — ใช้ยืนยันว่ารูปที่ระบบรับไว้คือใบที่ผู้ใช้ตั้งใจส่ง"""
    fields = {"chat_id": chat_id, "caption": caption[:1000], "parse_mode": "HTML"}
    if keyboard:
        fields["reply_markup"] = json.dumps(keyboard)
    payload = _multipart(fields, ("photo", photo), mime="image/jpeg")
    request = urllib.request.Request(
        f"{API_BASE}{token}/sendPhoto", data=payload["body"],
        headers={"Content-Type": payload["content_type"]},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except OSError as error:
        raise TelegramError(f"ส่งรูปไม่สำเร็จ: {error}") from error
    if not result.get("ok"):
        raise TelegramError(result.get("description", "Telegram ปฏิเสธรูป"))
    sent_id = result["result"].get("message_id", 0)
    try:
        chat_log.outgoing_media(token, "sendPhoto", chat_id, [photo], caption,
                                keyboard, sent_id)
    except Exception:
        pass
    return sent_id


def download_file(token: str, file_id: str, destination: Path) -> Path:
    """ดาวน์โหลดไฟล์ที่ผู้ใช้ส่งเข้าบอทมาเก็บไว้ในเครื่อง

    ต้องถาม getFile ก่อนเพื่อเอา file_path ชั่วคราว แล้วค่อยโหลดจากโดเมนไฟล์
    (คนละ path กับ Bot API ปกติ) — file_path มีอายุประมาณ 1 ชั่วโมง
    """
    info = call(token, "getFile", {"file_id": file_id})
    remote = info.get("file_path", "")
    if not remote:
        raise TelegramError("Telegram ไม่ได้บอก path ของไฟล์")
    url = f"https://api.telegram.org/file/bot{token}/{remote}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=180) as response:
            destination.write_bytes(response.read())
    except OSError as error:
        raise TelegramError(f"โหลดไฟล์จาก Telegram ไม่สำเร็จ: {error}") from error
    return destination


def send_approval(token: str, chat_id: str, entry: dict) -> int:
    """ส่งข้อความพร้อมปุ่ม คืน message_id ไว้ใช้แก้ข้อความทีหลัง"""
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ อนุมัติ", "callback_data": f"{entry['id']}:{ACTION_APPROVE}"},
            {"text": "✏️ ขอแก้", "callback_data": f"{entry['id']}:{ACTION_EDIT}"},
            {"text": "❌ ไม่เอา", "callback_data": f"{entry['id']}:{ACTION_REJECT}"},
        ]]
    }
    result = call(token, "sendMessage", {
        "chat_id": chat_id,
        "text": format_message(entry["product"], entry["highlights"]),
        "parse_mode": "HTML",
        "reply_markup": keyboard,
    })
    return result.get("message_id", 0)


# ------------------------------------------------------ ตัวเฝ้าคำตอบเบื้องหลัง


class ApprovalWatcher:
    """thread เดียวคอยอ่าน getUpdates แล้วบันทึกผลลงคิว

    ต้องมีตัวเดียวในระบบ — เรียก getUpdates พร้อมกันหลายที่จะแย่ง offset กัน
    แล้วอัปเดตหายสลับไปมา
    """

    def __init__(self, store: ApprovalStore, get_token, log=print) -> None:
        self.store = store
        self.get_token = get_token
        self.log = log
        self.offset = 0
        self.thread: threading.Thread | None = None
        self.stop_flag = threading.Event()
        # ใครกด "ขอแก้" ค้างไว้บ้าง — ข้อความถัดไปของคนนั้นคือจุดขายชุดใหม่
        self.awaiting_edit: dict[str, str] = {}   # chat_id -> approval_id
        # chat id ล่าสุดที่เห็น — ต้องให้ watcher เป็นคนจำ
        #
        # getUpdates ใช้ offset ร่วมกันทั้งบอท พอ watcher อ่านไปแล้ว Telegram
        # ถือว่ายืนยันแล้วและลบทิ้ง ใครเรียกทีหลังจะไม่เห็นข้อความนั้นอีก
        # ถ้าปล่อยให้ฝั่งตั้งค่าไปเรียก getUpdates เองจะแย่งกันจนหา chat id ไม่เจอ
        self.last_chat_id = ""
        self.on_chat_seen = None      # ให้ฝั่งเรียกใช้บันทึกลง config ได้ทันที
        # จุดต่อสำหรับงานอื่นที่ใช้บอทตัวเดียวกัน (ตอนนี้คือโพสต์ Facebook อัตโนมัติ)
        #
        # ต้องต่อผ่าน hook ไม่ใช่เขียนตรงในนี้ เพราะ getUpdates มีตัวอ่านได้ตัวเดียว
        # ทั้งบอท (offset ใช้ร่วมกัน) ใครอยากได้ข้อความต้องมารับต่อจากตัวนี้เท่านั้น
        self.on_photo = None          # (chat_id, file_id, caption, media_group) -> None
        self.on_command = None        # (chat_id, text) -> bool  (จัดการแล้วหรือยัง)
        self.on_text = None           # (chat_id, text) -> None  (ข้อความธรรมดา)
        self.on_callback = None       # (chat_id, data, callback) -> str  (ข้อความตอบปุ่ม)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_flag.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_flag.set()

    def _loop(self) -> None:
        while not self.stop_flag.is_set():
            token = self.get_token()
            if not token:
                time.sleep(10)      # ยังไม่ตั้งค่าบอท ไม่ต้องรีบถาม
                continue
            try:
                updates = call(token, "getUpdates", {
                    "timeout": POLL_TIMEOUT, "offset": self.offset,
                }, timeout=POLL_REQUEST_TIMEOUT)
            except TelegramError as error:
                self.log(f"อ่านข้อความ Telegram ไม่ได้: {error}")
                time.sleep(15)
                continue
            for update in updates:
                self.offset = max(self.offset, update.get("update_id", 0) + 1)
                try:
                    self._handle(token, update)
                except TelegramError as error:
                    self.log(f"ตอบกลับ Telegram ไม่สำเร็จ: {error}")
                except Exception as error:
                    # ต้องจับให้หมดจริงๆ — ข้อความเดียวที่ทำ hook พังจะฆ่า thread นี้
                    # ทั้งตัว แล้วบอทเงียบไปเฉยๆ โดยไม่มีอะไรฟ้อง (หายากมาก)
                    self.log(f"จัดการข้อความไม่สำเร็จ: {type(error).__name__}: {error}")

    def _remember_chat(self, chat_id: str) -> None:
        if not chat_id or chat_id == self.last_chat_id:
            return
        self.last_chat_id = chat_id
        if self.on_chat_seen:
            try:
                self.on_chat_seen(chat_id)
            except Exception as error:      # บันทึกไม่ได้ต้องไม่ทำให้ลูปตาย
                self.log(f"บันทึก chat id ไม่สำเร็จ: {error}")

    def _handle(self, token: str, update: dict) -> None:
        callback = update.get("callback_query")
        if callback:
            self._handle_button(token, callback)
            return
        message = update.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        self._remember_chat(chat_id)
        if not chat_id:
            return

        # รูปที่ผู้ใช้ส่งเข้ามา — ส่งแบบบีบอัด (photo) หรือแบบไฟล์ (document) ก็รับ
        # ต้องดักก่อนเช็ค text เพราะข้อความรูปไม่มีฟิลด์ text มีแต่ caption
        photos = message.get("photo") or []
        document = message.get("document") or {}
        if photos or str(document.get("mime_type", "")).startswith("image/"):
            if self.on_photo:
                # photo เรียงจากเล็กไปใหญ่ — เอาใบใหญ่สุดเสมอ ไม่งั้นได้ thumbnail
                file_id = photos[-1]["file_id"] if photos else document["file_id"]
                self.on_photo(
                    chat_id, file_id, (message.get("caption") or "").strip(),
                    str(message.get("media_group_id") or ""),
                )
            return

        text = (message.get("text") or "").strip()
        if not text:
            return
        if text.startswith("/"):
            if self.on_command and self.on_command(chat_id, text):
                return
            if text.startswith("/start"):
                call(token, "sendMessage", {
                    "chat_id": chat_id,
                    "text": "เชื่อมต่อ Pipeline Studio แล้ว ✅\n"
                            "จากนี้จุดขายที่คัดเสร็จจะส่งมาให้กดอนุมัติที่นี่",
                })
            return
        # กำลังรอข้อความแก้จากคนนี้อยู่ — เอาข้อความนั้นเป็นจุดขายชุดใหม่
        approval_id = self.awaiting_edit.pop(chat_id, "")
        if not approval_id and self.on_text:
            self.on_text(chat_id, text)
            return
        if approval_id:
            lines = [
                line.strip(" -•\t0123456789.")
                for line in text.splitlines() if line.strip()
            ]
            self.store.update(
                approval_id, status="approved", highlights=lines or [text],
                edited=True, decided_at=datetime.now().isoformat(timespec="seconds"),
            )
            call(token, "sendMessage", {
                "chat_id": chat_id,
                "text": f"รับจุดขายชุดใหม่แล้ว {len(lines or [text])} ข้อ ✅",
            })
            self.log(f"อนุมัติพร้อมแก้ข้อความ: {approval_id}")

    def _handle_button(self, token: str, callback: dict) -> None:
        data = callback.get("data", "")
        chat_id = str((callback.get("message", {}).get("chat") or {}).get("id", ""))
        self._remember_chat(chat_id)

        # ปุ่มของงานอื่นที่ใช้บอทตัวเดียวกัน — จองคำนำหน้าไว้ให้ชัด
        # ไม่งั้น partition(":") จะเอา "fb" ไปเป็น approval_id แล้วหาไม่เจอทุกครั้ง
        prefix = next((p for p in CALLBACK_PREFIXES if data.startswith(p)), "")
        if prefix:
            note = ""
            if self.on_callback:
                try:
                    note = self.on_callback(chat_id, data[len(prefix):], callback) or ""
                except Exception as error:      # ปุ่มพังต้องไม่ทำให้ลูปตาย
                    note = f"ทำไม่สำเร็จ: {error}"
                    self.log(f"ปุ่ม {data} ล้มเหลว: {error}")
            call(token, "answerCallbackQuery", {
                "callback_query_id": callback.get("id"), "text": note[:200],
            })
            return

        approval_id, _, action = data.partition(":")
        entry = self.store.get(approval_id)
        # ตอบ callback ทุกครั้ง ไม่งั้นปุ่มบนมือถือจะหมุนค้าง
        note = ""
        if entry is None:
            note = "ไม่พบคำขอนี้แล้ว"
        elif action == ACTION_APPROVE:
            self.store.update(approval_id, status="approved",
                              decided_at=datetime.now().isoformat(timespec="seconds"))
            note = "อนุมัติแล้ว ✅"
        elif action == ACTION_REJECT:
            self.store.update(approval_id, status="rejected",
                              decided_at=datetime.now().isoformat(timespec="seconds"))
            note = "ไม่เอาแล้ว ❌"
        elif action == ACTION_EDIT:
            self.awaiting_edit[chat_id] = approval_id
            note = "พิมพ์จุดขายชุดใหม่มาได้เลย (บรรทัดละข้อ)"
        call(token, "answerCallbackQuery", {
            "callback_query_id": callback.get("id"), "text": note,
        })
        if note and entry is not None and action != ACTION_EDIT:
            call(token, "sendMessage", {"chat_id": chat_id, "text": note})
        self.log(f"ผลอนุมัติ {approval_id}: {note}")
