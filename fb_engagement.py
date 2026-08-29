"""ตามเก็บยอดโพสต์ของเราเอง + ข้อความคอมเมนต์ — รันบนคอม ไม่แตะมือถือ

**เจ้าของสั่ง 28 ส.ค. 2569** — *"ทำบอทตัวนึงคอย follow up engagement ของโพสต์
ที่โพสต์ไป ยอดไลค์ คอมเมนต์ แชร์ และให้เก็บ text ในคอมเมนต์มา เพื่อเอาไว้เตรียม
ตอบ comment"* แล้วเลือกว่า *"เอาคอมละกัน ... เป็น profile สำหรับเก็บข้อมูลแยก
ต่างหาก ... ทุก 1 ชั่วโมงก่อน"*

---

## ทำไมรันบนคอม ไม่ใช่บนมือถือ

**จอมือถือคือทรัพยากรที่หายากที่สุดในระบบ** และเพิ่งถูกจำกัดหนักขึ้นอีก —
กติกาใหม่วันเดียวกันคือ *ชั่วโมงหนึ่งทำได้เลนเดียว* (โพสต์ หรือ ตอบคอมเมนต์
อย่างใดอย่างหนึ่ง) ถ้าเอางานอ่านยอดไปแย่งจอด้วย มันจะกลายเป็นเลนที่สาม
ที่มาแย่งเวลาจากงานที่ทำเงินจริง

งานอ่านยอดเป็นงาน **ทำซ้ำบ่อย · ไม่เร่ง · อ่านอย่างเดียว** เอาไปแย่งของหายาก
คือการแลกที่ไม่คุ้ม ส่วนบนคอมมันรันค้างได้ทั้งวันโดยไม่ชนกับใคร

**ไม่ขัดกติกาข้อ 2.7** — ข้อนั้นคุม *การโพสต์* ว่าต้องกดจอจริง ไฟล์นี้ไม่โพสต์
ไม่กดไลก์ ไม่คอมเมนต์ **อ่านอย่างเดียว**

## ทำไมใช้บัญชีคนละตัว

เจ้าของสั่งให้ล็อกอินบัญชีอื่นในโปรไฟล์ `Bot11` แยกต่างหาก เพื่อไม่ให้
บัญชีที่โพสต์ (Kp Oo) มีสองที่ล็อกอินพร้อมกัน ซึ่งเสี่ยงโดนตีธง

⚠️ **ข้อแลกที่ต้องรู้** บัญชีเก็บข้อมูล **ต้องเป็นสมาชิกกลุ่มนั้นด้วย** ถึงจะ
เห็นโพสต์ กลุ่มไหนที่ยังไม่ได้เข้าจะอ่านไม่ได้เลย และจะขึ้นเป็น "เข้าไม่ถึง"
ในรายงาน ไม่ใช่ "ยอด 0" — สองอย่างนี้ต้องแยกกันให้ออก ไม่งั้นจะนึกว่าโพสต์
ไม่มีคนสนใจ ทั้งที่แค่มองไม่เห็น

## ทำไมแยกฐานข้อมูลจาก fb_posts.db

`fb_posts.db` โตถึง 1 GB แล้ว และมีตัวเก็บข้อมูลกลุ่มสองตัว (Bot8/Bot9) เขียน
อยู่ตลอด — วัดเมื่อ 28 ส.ค. 2569 พบ `database is locked` **28 ครั้ง** จนงาน
ตายกลางทาง 22 รอบ เอางานใหม่ไปเขียนถังเดียวกันคือเพิ่มคนแย่งเข้าไปอีกราย

ไฟล์นี้จึงมีถังของตัวเอง `data/fb_engagement.db` เล็กและเขียนน้อย

## เก็บอะไรบ้าง

    my_post      ยอดไลก์ · คอมเมนต์ · แชร์ ของโพสต์เราแต่ละใบ ทุกครั้งที่เช็ค
    my_comment   ข้อความคอมเมนต์ทุกอัน + ชื่อคนเขียน + เวลา

**เก็บเป็นประวัติ ไม่ใช่ทับค่าเดิม** — `my_post` มีแถวใหม่ทุกครั้งที่เช็ค
จะได้ตอบได้ว่า "ยอดขึ้นตอนไหน" ไม่ใช่แค่ "ตอนนี้เท่าไร" ซึ่งเป็นคำถามที่
เจ้าของถามจริงเวลาดูว่าโพสต์ไหนเวิร์ก

รัน

    python fb_engagement.py once          เช็ครอบเดียวแล้วจบ
    python fb_engagement.py watch         วนเช็คทุกชั่วโมง
    python fb_engagement.py report        สรุปยอดล่าสุดของทุกโพสต์
    python fb_engagement.py comments      คอมเมนต์ที่ยังไม่ได้ตอบ
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import studio_shared as shared

HERE = Path(__file__).resolve().parent
DB_FILE = shared.DATA_DIR / "fb_engagement.db"
LOG_FILE = shared.DATA_DIR / "logs" / "fb_engagement.log"

# โปรไฟล์เบราว์เซอร์ที่ใช้เก็บข้อมูล — คนละบัญชีกับที่ใช้โพสต์
# เจ้าของเลือกชื่อ Bot11 ให้ต่อจากฟาร์มเดิม (28 ส.ค. 2569)
COLLECTOR_PROFILE = "Bot11"

# บัญชีที่ตามเก็บ — ว่าง = ทุกบัญชีที่มีลิงก์โพสต์เก็บไว้
#
# เจ้าของสั่ง 28 ส.ค. 2569: "ตอนนี้ตามแค่โพสต์ของ Kp Oo"
# เป็นรายการ ไม่ใช่ค่าเดี่ยว — วันที่อยากตามหลายบัญชีจะได้เติมชื่อ ไม่ต้องแก้โค้ด
WATCH_ACCOUNTS: tuple[str, ...] = ("Kp Oo",)

CHECK_EVERY_SECONDS = 3600.0      # เจ้าของสั่ง "ทุก 1 ชั่วโมงก่อน"
PAGE_TIMEOUT_MS = 45_000
BETWEEN_POSTS = (8.0, 16.0)       # พักสุ่มระหว่างโพสต์ — เปิดรัวเสี่ยงโดนจับ

SCHEMA = """
CREATE TABLE IF NOT EXISTS my_post (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_url    TEXT NOT NULL,
    group_id    TEXT,
    group_name  TEXT,
    account     TEXT,
    reactions   INTEGER,
    comments    INTEGER,
    shares      INTEGER,
    reachable   INTEGER NOT NULL DEFAULT 1,   -- 0 = เข้าไม่ถึง (ไม่ใช่ยอด 0)
    note        TEXT,
    checked_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS my_post_url ON my_post(post_url, checked_at);

CREATE TABLE IF NOT EXISTS my_comment (
    comment_key TEXT PRIMARY KEY,             -- post_url + ลำดับ + ชื่อคนเขียน
    post_url    TEXT NOT NULL,
    seq         INTEGER,
    author      TEXT,
    body        TEXT,
    when_text   TEXT,
    reply_to    TEXT,                         -- ตอบต่อคอมเมนต์ของใคร (ว่าง = คอมเมนต์ชั้นบน)
    is_ours     INTEGER NOT NULL DEFAULT 0,   -- คอมเมนต์ของเราเอง ไม่ต้องตอบ
    answered    INTEGER NOT NULL DEFAULT 0,   -- ตอบไปแล้วหรือยัง
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS my_comment_post ON my_comment(post_url);
"""


def log(message: str) -> None:
    line = f"{datetime.now():%d/%m %H:%M:%S} {message}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # WAL + รอคิวนาน — บทเรียนจาก fb_posts.db ที่โดน "database is locked" 28 ครั้ง
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# --------------------------------------------------------- โพสต์ที่ต้องตามเก็บ

def _caption_of(account: str) -> str:
    """แคปชันของงานล่าสุดของบัญชีนั้น — ใช้ยืนยันว่าเปิดถูกโพสต์"""
    try:
        rows = json.loads((shared.account_dir(account) / "fb_jobs.json")
                          .read_text(encoding="utf-8"))
    except OSError:
        return ""
    for job in reversed(rows):
        text = (job.get("caption") or "").strip()
        if text:
            return text
    return ""


def our_posts() -> list[dict]:
    """โพสต์ของเราทุกบัญชีที่มีลิงก์เก็บไว้แล้ว

    อ่านจากทะเบียนกลุ่มรายบัญชี (ที่แยกไว้เมื่อ 28 ส.ค. 2569) ไม่ใช่ไฟล์เดียว
    รวม — ไม่งั้นพอมีบัญชีที่สองจะเก็บของปนกัน
    """
    out: list[dict] = []
    wanted = {name.strip().lower() for name in WATCH_ACCOUNTS if name.strip()}
    for account in shared.known_accounts():
        if wanted and account.strip().lower() not in wanted:
            continue
        try:
            raw = (shared.account_dir(account) / "fb_groups.json").read_text(
                encoding="utf-8")
        except OSError:
            continue
        for group in json.loads(raw):
            link = (group.get("last_link") or "").strip()
            if link:
                out.append({
                    "post_url": link,
                    "caption": _caption_of(account),
                    "group_id": group.get("group_id", ""),
                    "group_name": group.get("name", ""),
                    "account": account,
                })
    return out


# ----------------------------------------------------------------- อ่านหน้าเว็บ

# ตัวเลขยอดบนหน้าเว็บมาในหลายรูปแบบ — "6", "1.2K", "1,234", "ความคิดเห็น 43 รายการ"
_NUM = re.compile(r"([\d,\.]+)\s*([KMkm]?)")


def parse_count(text: str) -> int | None:
    """แปลงข้อความยอดเป็นตัวเลข — คืน None เมื่ออ่านไม่ออก (ต่างจาก 0)

    **ต้องแยก "อ่านไม่ออก" กับ "ศูนย์" ให้ออก** ไม่งั้นหน้าที่โหลดไม่ทันจะถูก
    บันทึกเป็นยอด 0 แล้วกราฟจะเห็นยอดตกฮวบทั้งที่ไม่มีอะไรเกิดขึ้น
    """
    if not text:
        return None
    found = _NUM.search(text.replace(" ", " "))
    if not found:
        return None
    body = found.group(1).replace(",", "")
    try:
        value = float(body)
    except ValueError:
        return None
    unit = found.group(2).lower()
    if unit == "k":
        value *= 1_000
    elif unit == "m":
        value *= 1_000_000
    return int(value)


_CANON_CACHE: dict[str, str] = {}


def canonical_url(share_url: str) -> str:
    """แปลงลิงก์แชร์เป็นที่อยู่โพสต์เต็ม — คืน "" เมื่อแปลงไม่ได้

    `facebook.com/share/p/XXXX/` เด้งกลับหน้าฟีดเมื่อเปิดบนเบราว์เซอร์คอม
    ส่วน `groups/<gid>/posts/<pid>/` เปิดตรงได้ ไม่เด้ง
    """
    if share_url in _CANON_CACHE:
        return _CANON_CACHE[share_url]
    full = ""
    try:
        import fb_auto_post
        gid, pid = fb_auto_post.resolve_post_link(share_url, timeout=25)
        if gid and pid:
            full = f"https://www.facebook.com/groups/{gid}/posts/{pid}/"
    except Exception:
        full = ""
    _CANON_CACHE[share_url] = full
    return full


def read_post(page, url: str, expect: str = "") -> dict:
    """เปิดโพสต์แล้วอ่านยอด + คอมเมนต์ — ไม่กดอะไรที่เปลี่ยนสถานะเลย

    คืน {"reachable": bool, "reactions"|"comments"|"shares": int|None,
         "comments_list": [...], "note": str}
    """
    page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
    page.wait_for_timeout(7000)

    # **ต้องอ่านเฉพาะกล่องของโพสต์ ห้ามอ่านทั้งหน้า**
    #
    # เจอจริง 28 ส.ค. 2569 หลังไล่ผิดทางไปสองรอบ: เว็บ Facebook เวอร์ชันคอม
    # มีเมนูซ้ายมือ ("เมนู Facebook" · "ทางลัดของคุณ" · "สร้างสตอรี่") อยู่ใน
    # ทุกหน้า รวมถึงหน้าโพสต์ด้วย อ่านทั้งหน้าจึงได้เมนูมาก่อนเนื้อโพสต์เสมอ
    # แล้วตัวอ่านยอดไปเจอตัวเลขของเมนูแทน (หรือไม่เจอเลย)
    #
    # ผมเคยสรุปผิดว่า "เด้งไปหน้าฟีด" ทั้งที่ URL เข้าถูกหน้าแล้ว — ตัวชี้ขาด
    # คือ **URL หลังเปิด** ไม่ใช่ข้อความบนหน้า
    #
    # โพสต์เปิดเป็น **หน้าต่างซ้อน** (`div[role="dialog"]`) ไม่ใช่หน้าเต็ม
    # จึงต้องเลือกกล่องที่มีข้อความโพสต์ของเราอยู่จริง
    landed = page.url
    body = ""
    holder_node = None
    for node in page.query_selector_all('div[role="dialog"], div[role="article"]'):
        try:
            text = (node.inner_text() or "").strip()
        except Exception:
            continue
        if expect and expect.strip()[:14] in text:
            body = text
            holder_node = node
            break
    if not body:
        on_post = "/posts/" in landed or "/permalink/" in landed
        return {"reachable": False,
                "note": ("เข้าถึงหน้าโพสต์แล้วแต่หากล่องโพสต์ไม่เจอ" if on_post
                         else f"ไม่ได้อยู่หน้าโพสต์ — {landed[:70]}"),
                "reactions": None, "comments": None, "shares": None,
                "comments_list": []}

    blocked = ("เนื้อหานี้ไม่พร้อมใช้งาน", "content isn't available",
               "คุณต้องเข้าสู่ระบบ", "log in to continue")
    if any(mark.lower() in body.lower() for mark in blocked):
        return {"reachable": False, "note": body.strip().splitlines()[0][:120],
                "reactions": None, "comments": None, "shares": None,
                "comments_list": []}

    # **อ่านยอดจากป้ายบอกของปุ่ม (aria-label) ไม่ใช่จากข้อความบนหน้า**
    #
    # ไล่ผิดทางมาสามรอบก่อนจะเจอ (28 ส.ค. 2569) — บนหน้าเว็บเวอร์ชันคอม
    # ยอดถูกวาดเป็น **ตัวเลขเปล่าๆ ไม่มีคำกำกับ** อยู่ใต้คำว่า "โพสต์ที่แชร์"
    #
    #     'โพสต์ที่แชร์'
    #     '1'          ← ตัวไหนคืออะไร บอกไม่ได้จากข้อความ
    #     '2'
    #
    # ส่วนป้ายบอกของปุ่มเขียนครบ **"ถูกใจ: 1 คน"** — อ่านจากตรงนี้จึงแม่นกว่า
    # และไม่พังเวลา Facebook ขยับตำแหน่งตัวเลข
    counts = {"reactions": None, "comments": None, "shares": None}
    labels = []
    try:
        for element in holder_node.query_selector_all("[aria-label]"):
            text = element.get_attribute("aria-label") or ""
            if text:
                labels.append(text)
    except Exception:
        labels = []
    for text in labels:
        low = text.strip()
        if counts["reactions"] is None and ("ถูกใจ:" in low or "แสดงความรู้สึก" in low
                                            or "reaction" in low.lower()):
            value = parse_count(low)
            if value is not None:
                counts["reactions"] = value
        if counts["comments"] is None and ("ความคิดเห็น" in low and "รายการ" in low):
            counts["comments"] = parse_count(low)
        if counts["shares"] is None and ("แชร์" in low and ("ครั้ง" in low or "คน" in low)):
            counts["shares"] = parse_count(low)

    # **ไม่มีป้ายแชร์ = ยังไม่มีใครแชร์ ไม่ใช่ "อ่านไม่ออก"** (28 ส.ค. 2569)
    #
    # แคปหน้าจริงมาดูแล้ว ในกล่องโพสต์มีแค่ตัวเลขไลก์กับคอมเมนต์
    # **ไม่มีตัวเลขแชร์เลย** เพราะ Facebook วาดยอดแชร์เฉพาะตอนมีคนแชร์จริง
    # (เทียบกับโพสต์อื่นที่มีคนแชร์ จะขึ้นว่า "แชร์ 2 ครั้ง" ชัดเจน)
    #
    # อ่านโพสต์สำเร็จแล้วแต่ไม่เจอป้ายแชร์ จึงแปลว่า 0 ไม่ใช่ None
    # ถ้าคืน None ต่อไป รายงานจะขึ้น "?" ตลอดกาลทั้งที่ความจริงคือยังไม่มีใครแชร์
    if counts["shares"] is None and counts["reactions"] is not None:
        counts["shares"] = 0

    # นับคอมเมนต์จากป้าย "ความคิดเห็นจาก <ชื่อ> เมื่อ ..." ที่มีหนึ่งอันต่อคอมเมนต์
    # เชื่อถือได้กว่าตัวเลขสรุปที่บางทีไม่โผล่เลยเมื่อมีคอมเมนต์น้อย
    if counts["comments"] is None:
        seen_comments = sum(1 for x in labels if x.startswith("ความคิดเห็นจาก"))
        counts["comments"] = seen_comments

    # อ่านคอมเมนต์จากในกล่องโพสต์เท่านั้น — ทั้งหน้ามี `div[role="article"]`
    # หลายกล่องที่เป็นโพสต์คนอื่นในฟีดข้างหลังหน้าต่างซ้อน
    comments = []
    skipped_post = 0
    try:
        for order, node in enumerate(holder_node.query_selector_all(
                'div[role="article"]'), 1):
            head = parse_comment_label(node.get_attribute("aria-label") or "")
            if head is None:
                # ไม่มีป้ายคอมเมนต์ = ตัวโพสต์เอง ไม่ใช่คอมเมนต์ (ดูคำอธิบายข้างบน)
                skipped_post += 1
                continue
            body = clean_comment_body(node.inner_text() or "", head["author"])
            comments.append({
                "seq": order,
                "author": head["author"][:120],
                "body": body[:2000],
                "when_text": head["when_text"][:60],
                "reply_to": head["reply_to"][:120],
            })
    except Exception as error:            # อ่านคอมเมนต์ไม่ได้ ต้องไม่ทำให้ยอดหาย
        log(f"   อ่านคอมเมนต์ไม่ได้: {type(error).__name__}: {error}")

    return {"reachable": True, "note": "", **counts, "comments_list": comments}


# ------------------------------------------------------- แยกคอมเมนต์จากป้ายกำกับ

# **ตัวโพสต์เองก็เป็น `div[role="article"]` เหมือนคอมเมนต์** (28 ส.ค. 2569)
#
# ของเดิมหยิบ `div[role="article"]` ทุกอันมาเป็นคอมเมนต์ ผลคือใน 18 อันที่
# เก็บมาได้ มีคอมเมนต์ของคนอื่นจริงแค่ 2 อัน ที่เหลือเป็นแคปชั่นโพสต์ของเราเอง
# ที่ถูกนับเป็นคอมเมนต์ — และ `author` กลายเป็นชื่อกลุ่มเพราะบรรทัดแรกของโพสต์
# คือชื่อกลุ่ม ไม่ใช่ชื่อคน
#
# นี่คือกติกาข้อ 2.3.1 เป๊ะ: ถามคำถามที่ตอบว่า "ใช่" ได้ทั้งตอนถูกและตอนผิด
#   ถามว่า  "เป็น div[role=article] ไหม"      → โพสต์ก็ใช่ คอมเมนต์ก็ใช่
#   ต้องถาม "มีป้าย aria-label ของคอมเมนต์ไหม" → **มีเฉพาะคอมเมนต์**
#
# แกะจากหน้าจริงแล้วป้ายบอกครบทุกอย่างที่ต้องรู้:
#   ตัวโพสต์      (ไม่มีป้ายเลย)
#   คอมเมนต์      "ความคิดเห็นจาก Pongpat … เมื่อ 4 ชั่วโมงที่แล้ว"
#   คำตอบของเรา   "ข้อความตอบกลับจาก Kp Oo ต่อความคิดเห็นของ Pongpat … เมื่อ …"
#
# บรรทัดสุดท้ายสำคัญมาก — มันบอกว่า **เราตอบใครไปแล้ว** จึงตั้งธง answered
# ได้จากของจริงบนหน้า แทนที่จะเดาหรือปล่อยให้เป็น 0 ตลอดกาล
_LABEL_COMMENT = re.compile(
    r"^(?:ความคิดเห็นจาก|Comment by)\s+(.+?)(?:\s+(?:เมื่อ|on)\s+(.+))?$")
_LABEL_REPLY = re.compile(
    r"^(?:ข้อความตอบกลับจาก|Reply by)\s+(.+?)"
    r"\s+(?:ต่อความคิดเห็นของ|to)\s+(.+?)"
    r"(?:'s comment)?(?:\s+(?:เมื่อ|on)\s+(.+))?$")


def parse_comment_label(label: str) -> dict | None:
    """แกะป้าย aria-label — คืน None ถ้าไม่ใช่ป้ายของคอมเมนต์ (เช่นตัวโพสต์)"""
    text = (label or "").strip()
    if not text:
        return None
    match = _LABEL_REPLY.match(text)
    if match:
        return {"author": match.group(1).strip(),
                "reply_to": match.group(2).strip(),
                "when_text": (match.group(3) or "").strip()}
    match = _LABEL_COMMENT.match(text)
    if match:
        return {"author": match.group(1).strip(), "reply_to": "",
                "when_text": (match.group(2) or "").strip()}
    return None


# บรรทัดที่ไม่ใช่เนื้อคอมเมนต์ — ปุ่มท้ายกล่อง ป้ายสถานะ และตัวคั่น
_JUNK_LINES = {
    "·", "•", "ตอบกลับ", "แชร์", "ถูกใจ", "แก้ไขแล้ว", "ดูคำแปล",
    "Reply", "Share", "Like", "Edited", "See translation",
    "ผู้มีส่วนร่วมดาวเด่น", "Top contributor", "ผู้เขียน", "Author",
    "ผู้ดูแล", "Admin", "สมาชิกใหม่", "New member",
}
_TIME_LINE = re.compile(
    r"^(?:เมื่อสักครู่|Just now|\d+\s*(?:วินาที|นาที|ชั่วโมง|ชม\.?|วัน|สัปดาห์|เดือน|ปี"
    r"|s|m|h|d|w|y|min|mins|hr|hrs|hour|hours|day|days|week|weeks)"
    r"(?:ที่แล้ว| ago)?)$", re.I)
# หัวการ์ดพรีวิวลิงก์ — โดเมนตัวพิมพ์ใหญ่ล้วน เช่น "S.SHOPEE.CO.TH"
# การ์ดอยู่ท้ายคอมเมนต์เสมอ เจอเมื่อไรตัดตั้งแต่ตรงนั้นถึงจบได้เลย
_LINK_CARD = re.compile(r"^[A-Z0-9][A-Z0-9.\-]*\.[A-Z]{2,}$")


def clean_comment_body(text: str, author: str) -> str:
    """เอาเนื้อคอมเมนต์จริงออกมา — ตัดชื่อคน เวลา ปุ่ม และการ์ดพรีวิวลิงก์ทิ้ง"""
    lines = [x.strip() for x in (text or "").splitlines()]
    kept: list[str] = []
    for line in lines:
        if not line:
            continue
        if _LINK_CARD.match(line):     # เจอหัวการ์ดพรีวิว = จบเนื้อคอมเมนต์แล้ว
            break
        if line in _JUNK_LINES or _TIME_LINE.match(line):
            continue
        if author and line == author:
            continue
        kept.append(line)
    return (chr(10).join(kept)).strip()


# --------------------------------------------------------------------- บันทึก

def save(conn: sqlite3.Connection, post: dict, result: dict) -> tuple[int, int]:
    """เก็บผลลงฐาน — คืน (คอมเมนต์ใหม่, คอมเมนต์ทั้งหมดที่เห็น)"""
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO my_post (post_url, group_id, group_name, account,
                                reactions, comments, shares, reachable, note, checked_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (post["post_url"], post["group_id"], post["group_name"], post["account"],
         result.get("reactions"), result.get("comments"), result.get("shares"),
         1 if result.get("reachable") else 0, result.get("note", ""), now))

    items = result.get("comments_list") or []
    me = (post["account"] or "").lower()

    # **ใครถูกเราตอบไปแล้วบ้าง — อ่านจากป้ายบนหน้า ไม่ใช่เดา**
    # ป้ายของคำตอบเขียนว่า "ข้อความตอบกลับจาก <เรา> ต่อความคิดเห็นของ <เขา>"
    # ชื่อ <เขา> ที่โผล่ในนั้นคือคนที่เราตอบไปแล้ว
    answered_names = {
        (item.get("reply_to") or "").lower()
        for item in items
        if item.get("reply_to") and me and me in (item.get("author") or "").lower()
    }
    answered_names.discard("")

    fresh = 0
    for item in items:
        author = item["author"]
        # กุญแจต้องไม่ผูกกับลำดับ — คอมเมนต์ใหม่แทรกเข้ามาแล้วลำดับขยับทั้งแถว
        # ของเดิมใช้ลำดับ จึงนับคอมเมนต์เดิมเป็นของใหม่ทุกครั้งที่มีคนมาคอมเมนต์เพิ่ม
        key = f"{post['post_url']}#{author[:40]}#{(item['body'] or '')[:60]}"
        ours = 1 if (me and me in author.lower()) else 0
        answered = 1 if (not ours and author.lower() in answered_names) else 0
        row = conn.execute(
            "SELECT comment_key, answered FROM my_comment WHERE comment_key=?",
            (key,)).fetchone()
        if row:
            conn.execute(
                """UPDATE my_comment SET last_seen=?, body=?, when_text=?, reply_to=?,
                          answered=MAX(answered, ?) WHERE comment_key=?""",
                (now, item["body"], item.get("when_text", ""),
                 item.get("reply_to", ""), answered, key))
            continue
        conn.execute(
            """INSERT INTO my_comment (comment_key, post_url, seq, author, body,
                                       when_text, reply_to, is_ours, answered,
                                       first_seen, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (key, post["post_url"], item["seq"], author, item["body"],
             item.get("when_text", ""), item.get("reply_to", ""),
             ours, answered, now, now))
        fresh += 1
    conn.commit()
    return fresh, len(items)


# ----------------------------------------------------------------------- รอบเช็ค

# ยอดไม่ขยับนานเท่านี้ = เลิกตามเก็บโพสต์ใบนั้น (เจ้าของสั่ง 28 ส.ค. 2569)
#
#   "ถ้าภายใน 1 วัน ยังมียอดไลค์ หรือ คอมเมนต์เพิ่ม ให้ดูต่อ
#    แต่ถ้าโพสต์ไหนภายใน 1 วัน ยอดไม่มีขึ้นแล้ว ให้ยกเลิกเก็บได้เลย"
QUIET_HOURS = 24.0


def still_worth_watching(conn: sqlite3.Connection, post_url: str) -> tuple[bool, str]:
    """ยังควรตามเก็บโพสต์ใบนี้อยู่ไหม — คืน (เก็บต่อ, เหตุผลถ้าเลิก)

    **ตัดสินจากยอดที่วัดได้จริง ไม่ใช่จากอายุโพสต์** โพสต์ที่ลงมา 3 วันแล้วยัง
    มีคนไลก์เพิ่มก็ยังน่าตาม ส่วนโพสต์ที่ลงมาวันเดียวแล้วเงียบสนิทก็ไม่ต้องตาม
    ถ้าตัดสินจากอายุจะทิ้งโพสต์ที่กำลังมาแรงและตามโพสต์ที่ตายแล้วไปเรื่อยๆ

    **ต้องมีประวัติครอบคลุมเกิน 1 วันก่อนถึงจะตัดสินได้** เพิ่งเก็บวันนี้แล้ว
    เห็นว่ายอดเท่าเดิม 2 รอบ ไม่ได้แปลว่าเงียบ — แปลว่ายังดูไม่นานพอ
    """
    rows = conn.execute(
        """SELECT reactions, comments, checked_at FROM my_post
           WHERE post_url = ? AND reachable = 1
           ORDER BY id DESC LIMIT 400""", (post_url,)).fetchall()
    if len(rows) < 2:
        return True, ""
    newest = rows[0]
    cutoff = datetime.now() - timedelta(hours=QUIET_HOURS)
    older = None
    for row in rows:
        try:
            when = datetime.fromisoformat(row["checked_at"])
        except ValueError:
            continue
        if when <= cutoff:
            older = row
            break
    if older is None:
        return True, ""                 # ยังเก็บไม่ครบ 1 วัน ตัดสินไม่ได้
    same = (newest["reactions"] == older["reactions"]
            and newest["comments"] == older["comments"])
    if same:
        return False, (f"ยอดไม่ขยับมา {QUIET_HOURS:.0f} ชั่วโมง "
                       f"(ไลก์ {newest['reactions']} · คอมเมนต์ {newest['comments']})")
    return True, ""


def check_once() -> dict:
    """เช็คทุกโพสต์หนึ่งรอบ — คืนสรุปเป็น dict"""
    import random

    from playwright.sync_api import sync_playwright

    import fb_mass_finder as mf
    from bot_profiles import ProfileFarm

    posts = our_posts()
    if not posts:
        log("ยังไม่มีโพสต์ที่มีลิงก์เก็บไว้ — ไม่มีอะไรให้เช็ค")
        return {"posts": 0}

    farm = ProfileFarm(shared.DATA_DIR)
    entry = mf.find_bot(farm, COLLECTOR_PROFILE)
    conn = open_db()
    done = blocked = new_comments = quiet = 0
    # เก็บรายละเอียดต่อใบไว้ให้คนเรียกเอาไปประกอบข้อความแจ้งเจ้าของ
    # (ตัว keeper ใน app.py ใช้ตัดสินว่ารอบนี้มีอะไรน่าบอกไหม)
    rows: list[dict] = []
    log(f"เริ่มรอบเช็ค — โพสต์ {len(posts)} ใบ ผ่านโปรไฟล์ {COLLECTOR_PROFILE}")
    with sync_playwright() as playwright:
        browser = mf.launch_bot_browser(playwright, farm, entry)
        page = browser.new_page() if hasattr(browser, "new_page") else browser.pages[0]
        try:
            for post in posts:
                label = f"{post['group_name'][:26]} ({post['account']})"
                keep, why = still_worth_watching(conn, post["post_url"])
                if not keep:
                    quiet += 1
                    log(f"  💤 {label}: เลิกตามแล้ว — {why}")
                    continue
                # ใช้ที่อยู่เต็มถ้าแปลงได้ — ลิงก์แชร์เด้งกลับหน้าฟีด
                target = canonical_url(post["post_url"]) or post["post_url"]
                try:
                    result = read_post(page, target, expect=post.get("caption", ""))
                except Exception as error:
                    log(f"  ❌ {label}: {type(error).__name__}: {str(error)[:90]}")
                    continue
                # ยอดรอบก่อนหน้า — ต้องอ่าน **ก่อน** save ไม่งั้นได้ยอดรอบนี้เอง
                was = conn.execute(
                    """SELECT reactions, comments FROM my_post
                       WHERE post_url = ? AND reachable = 1
                       ORDER BY id DESC LIMIT 1""", (post["post_url"],)).fetchone()
                fresh, total = save(conn, post, result)
                new_comments += fresh
                if result["reachable"]:
                    rows.append({
                        "group": post["group_name"],
                        "url": post["post_url"],
                        "reactions": result.get("reactions"),
                        "comments": result.get("comments"),
                        "shares": result.get("shares"),
                        # None = ยังไม่เคยเก็บใบนี้ ต่างจาก 0 ที่แปลว่าไม่ขยับ
                        "d_reactions": (None if was is None
                                        else (result.get("reactions") or 0)
                                        - (was["reactions"] or 0)),
                        "d_comments": (None if was is None
                                       else (result.get("comments") or 0)
                                       - (was["comments"] or 0)),
                        "fresh": fresh,
                    })
                if result["reachable"]:
                    done += 1
                    log(f"  ✅ {label}: ไลก์ {result['reactions']} · "
                        f"คอมเมนต์ {result['comments']} · แชร์ {result['shares']} "
                        f"· เก็บข้อความ {total} อัน (ใหม่ {fresh})")
                else:
                    blocked += 1
                    log(f"  ⛔ {label}: เข้าไม่ถึง — {result['note'][:60]}")
                time.sleep(random.uniform(*BETWEEN_POSTS))
        finally:
            try:
                browser.close()
            except Exception:
                pass
    conn.close()
    log(f"จบรอบ — อ่านได้ {done} ใบ · เข้าไม่ถึง {blocked} ใบ "
        f"· เลิกตามแล้ว {quiet} ใบ · คอมเมนต์ใหม่ {new_comments} อัน")
    return {"posts": len(posts), "rows": rows, "ok": done, "blocked": blocked,
            "quiet": quiet, "new_comments": new_comments}


def watch() -> None:
    """วนเช็คทุกชั่วโมง — ล้มรอบหนึ่งต้องไม่ทำให้หยุดทั้งตัว"""
    log(f"เริ่มเฝ้า — เช็คทุก {CHECK_EVERY_SECONDS / 60:.0f} นาที")
    while True:
        try:
            check_once()
        except Exception as error:
            log(f"รอบนี้ล้ม: {type(error).__name__}: {error}")
        time.sleep(CHECK_EVERY_SECONDS)


# ------------------------------------------------------------------ รายงานให้คนอ่าน

def report() -> None:
    conn = open_db()
    rows = conn.execute("""
        SELECT post_url, group_name, account, reactions, comments, shares,
               reachable, checked_at
        FROM my_post
        WHERE id IN (SELECT MAX(id) FROM my_post GROUP BY post_url)
        ORDER BY group_name
    """).fetchall()
    if not rows:
        print("ยังไม่มีข้อมูล — รัน `python fb_engagement.py once` ก่อน")
        return
    print(f"{'กลุ่ม':32} {'ไลก์':>6} {'คอมเมนต์':>9} {'แชร์':>6}  เช็คล่าสุด")
    print("-" * 74)
    for row in rows:
        if not row["reachable"]:
            print(f"{row['group_name'][:30]:32} {'เข้าไม่ถึง':>24}  {row['checked_at'][5:16]}")
            continue
        show = lambda v: "?" if v is None else str(v)
        print(f"{row['group_name'][:30]:32} {show(row['reactions']):>6} "
              f"{show(row['comments']):>9} {show(row['shares']):>6}  {row['checked_at'][5:16]}")
    conn.close()


def pending_comments() -> None:
    """คอมเมนต์ของคนอื่นที่ยังไม่ได้ตอบ — ของที่เอาไปเตรียมคำตอบ"""
    conn = open_db()
    rows = conn.execute("""
        SELECT c.author, c.body, c.first_seen, p.group_name
        FROM my_comment c
        LEFT JOIN (SELECT post_url, group_name FROM my_post GROUP BY post_url) p
               ON p.post_url = c.post_url
        WHERE c.is_ours = 0 AND c.answered = 0
        ORDER BY c.first_seen DESC
        LIMIT 50
    """).fetchall()
    if not rows:
        print("ยังไม่มีคอมเมนต์ของคนอื่นที่รอตอบ")
        return
    print(f"คอมเมนต์รอตอบ {len(rows)} อัน\n")
    for row in rows:
        print(f"[{row['group_name'] or '?'}] {row['author']} · {row['first_seen'][5:16]}")
        for line in (row["body"] or "").splitlines()[:3]:
            print("    " + line[:96])
        print()
    conn.close()


def main() -> int:
    what = (sys.argv[1] if len(sys.argv) > 1 else "report").lower()
    if what == "once":
        check_once()
    elif what == "watch":
        watch()
    elif what == "comments":
        pending_comments()
    else:
        report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
