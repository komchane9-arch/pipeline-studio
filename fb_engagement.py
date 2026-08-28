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

เจ้าของสั่งให้ล็อกอินบัญชีอื่นในโปรไฟล์ `Collector` แยกต่างหาก เพื่อไม่ให้
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
from datetime import datetime
from pathlib import Path

import studio_shared as shared

HERE = Path(__file__).resolve().parent
DB_FILE = shared.DATA_DIR / "fb_engagement.db"
LOG_FILE = shared.DATA_DIR / "logs" / "fb_engagement.log"

# โปรไฟล์เบราว์เซอร์ที่ใช้เก็บข้อมูล — คนละบัญชีกับที่ใช้โพสต์
COLLECTOR_PROFILE = "Collector"

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

def our_posts() -> list[dict]:
    """โพสต์ของเราทุกบัญชีที่มีลิงก์เก็บไว้แล้ว

    อ่านจากทะเบียนกลุ่มรายบัญชี (ที่แยกไว้เมื่อ 28 ส.ค. 2569) ไม่ใช่ไฟล์เดียว
    รวม — ไม่งั้นพอมีบัญชีที่สองจะเก็บของปนกัน
    """
    out: list[dict] = []
    for account in shared.known_accounts():
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


def read_post(page, url: str) -> dict:
    """เปิดโพสต์แล้วอ่านยอด + คอมเมนต์ — ไม่กดอะไรที่เปลี่ยนสถานะเลย

    คืน {"reachable": bool, "reactions"|"comments"|"shares": int|None,
         "comments_list": [...], "note": str}
    """
    page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    body = page.inner_text("body")[:6000]

    # เข้าไม่ถึง ≠ ยอด 0 — ต้องแยกให้ออก ไม่งั้นจะนึกว่าโพสต์ไม่มีคนสนใจ
    blocked = ("เนื้อหานี้ไม่พร้อมใช้งาน", "content isn't available",
               "คุณต้องเข้าสู่ระบบ", "log in to continue",
               "เข้าร่วมกลุ่มนี้", "join this group")
    if any(mark.lower() in body.lower() for mark in blocked):
        return {"reachable": False, "note": body.strip().splitlines()[0][:120],
                "reactions": None, "comments": None, "shares": None,
                "comments_list": []}

    counts = {"reactions": None, "comments": None, "shares": None}
    for line in body.splitlines():
        low = line.strip()
        if not low:
            continue
        if counts["comments"] is None and ("ความคิดเห็น" in low or "comment" in low.lower()):
            counts["comments"] = parse_count(low)
        if counts["shares"] is None and ("แชร์" in low or "share" in low.lower()):
            counts["shares"] = parse_count(low)
        if counts["reactions"] is None and ("ความรู้สึก" in low or "reaction" in low.lower()):
            counts["reactions"] = parse_count(low)

    comments = []
    try:
        nodes = page.query_selector_all('div[role="article"]')
        for order, node in enumerate(nodes, 1):
            text = (node.inner_text() or "").strip()
            if not text or len(text) < 2:
                continue
            lines = [x for x in text.splitlines() if x.strip()]
            if len(lines) < 2:
                continue
            comments.append({
                "seq": order,
                "author": lines[0][:120],
                "body": "\n".join(lines[1:])[:2000],
            })
    except Exception as error:            # อ่านคอมเมนต์ไม่ได้ ต้องไม่ทำให้ยอดหาย
        log(f"   อ่านคอมเมนต์ไม่ได้: {type(error).__name__}: {error}")

    return {"reachable": True, "note": "", **counts, "comments_list": comments}


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

    fresh = 0
    for item in result.get("comments_list") or []:
        key = f"{post['post_url']}#{item['seq']}#{item['author'][:40]}"
        ours = post["account"].lower() in item["author"].lower()
        row = conn.execute(
            "SELECT comment_key FROM my_comment WHERE comment_key=?", (key,)).fetchone()
        if row:
            conn.execute("UPDATE my_comment SET last_seen=?, body=? WHERE comment_key=?",
                         (now, item["body"], key))
            continue
        conn.execute(
            """INSERT INTO my_comment (comment_key, post_url, seq, author, body,
                                       when_text, is_ours, answered, first_seen, last_seen)
               VALUES (?,?,?,?,?,?,?,0,?,?)""",
            (key, post["post_url"], item["seq"], item["author"], item["body"],
             "", 1 if ours else 0, now, now))
        fresh += 1
    conn.commit()
    return fresh, len(result.get("comments_list") or [])


# ----------------------------------------------------------------------- รอบเช็ค

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
    done = blocked = new_comments = 0
    log(f"เริ่มรอบเช็ค — โพสต์ {len(posts)} ใบ ผ่านโปรไฟล์ {COLLECTOR_PROFILE}")
    with sync_playwright() as playwright:
        browser = mf.launch_bot_browser(playwright, farm, entry)
        page = browser.new_page() if hasattr(browser, "new_page") else browser.pages[0]
        try:
            for post in posts:
                label = f"{post['group_name'][:26]} ({post['account']})"
                try:
                    result = read_post(page, post["post_url"])
                except Exception as error:
                    log(f"  ❌ {label}: {type(error).__name__}: {str(error)[:90]}")
                    continue
                fresh, total = save(conn, post, result)
                new_comments += fresh
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
        f"· คอมเมนต์ใหม่ {new_comments} อัน")
    return {"posts": len(posts), "ok": done, "blocked": blocked,
            "new_comments": new_comments}


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
