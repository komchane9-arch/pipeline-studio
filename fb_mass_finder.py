"""หาโพสต์แมสในกลุ่ม Facebook — ขับผ่านโปรไฟล์บอทจากฟาร์ม แล้วส่งลิงก์เข้า Telegram

หลักการ (ตาม CLAUDE.md ของโปรเจกต์):
- ใช้โปรไฟล์บอทจากฟาร์ม (ค่าปริยาย Bot10) เป็นเบราว์เซอร์ — ล็อกอิน Facebook
  ค้างอยู่ในโปรไฟล์นั้น คนละโฟลเดอร์ = คนละโปรเซส ไม่ชนกับงานอื่นของสตูดิโอ
- **ไม่เดา DOM ของ Facebook** — ยอดรีแอคชันอ่านจาก JSON ที่ฟีดโหลดจริง
  (GraphQL ตอน scroll + JSON ที่ฝังมากับ HTML หน้าแรก) ซึ่ง key `reaction_count`
  นิ่งกว่า DOM ที่ถูก obfuscate ใหม่แทบทุก deploy
- เก็บหลักฐานดิบเมื่อกลุ่มไหนอ่านไม่ออก (หน้า HTML ล่าสุด) — ไล่ย้อนได้ ไม่ต้องเดา
- โพสต์ที่ส่งเข้า Telegram แล้วจดไว้ใน fb_mass_seen.json — รันซ้ำไม่สแปมลิงก์เดิม
- ตรวจล็อกอินจากของจริง: cookie `c_user` ต้องมี และต้องไม่โดนเด้งไปหน้า login

วิธีใช้:
    python fb_mass_finder.py                 # สแกนทุกกลุ่ม แล้วส่ง Telegram
    python fb_mass_finder.py --no-telegram   # สแกนอย่างเดียว พิมพ์ผล + เซฟไฟล์
    python fb_mass_finder.py --groups 1      # สแกนแค่กลุ่มแรก (ไว้ทดสอบ)
    python fb_mass_finder.py --scrolls 3     # เลื่อนฟีดกี่รอบต่อกลุ่ม (ปริยาย 8)

ตั้งค่า: data/fb_mass_config.json (สร้างให้อัตโนมัติรอบแรก)
โทเคน Telegram: data/telegram_mass_token.bin (DPAPI) — ยังไม่มีจะถอยไปใช้บอทหลัก
  ปลอดภัยเพราะโมดูลนี้ **ส่งอย่างเดียว** ไม่เรียก getUpdates จึงไม่ชนกับตัวอ่านเดิม
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import studio_shared
import telegram_bot
from bot_profiles import ProfileFarm, FarmError

# stdout เป็น pipe (รันผ่านสคริปต์/เซิร์ฟเวอร์) Windows ใช้ cp1252 ซึ่งพิมพ์
# ภาษาไทยแล้ว UnicodeEncodeError ตายทั้งโปรเซส — กันที่ระดับ import ไม่ใช่แค่
# main() เพราะสคริปต์อื่นที่ import โมดูลนี้ไปพิมพ์ผลก็ตายแบบเดียวกัน (เจอจริง
# 12 ส.ค. 2026: one-off script ตายหลังส่ง Telegram ไปแล้วครึ่งเดียว)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

DATA_DIR = studio_shared.DATA_DIR
CONFIG_FILE = DATA_DIR / "fb_mass_config.json"
SEEN_FILE = DATA_DIR / "fb_mass_seen.json"
# โพสต์ที่ผู้ใช้กด "ไม่เอา" — บัญชีดำถาวร แยกจาก seen เพราะความหมายคนละอย่าง
# (seen = เคยส่งแล้วกันส่งซ้ำ · rejected = ผู้ใช้ตัดทิ้ง ห้ามโผล่อีกตลอดไป)
REJECT_FILE = DATA_DIR / "fb_mass_rejected.json"
RESULT_FILE = DATA_DIR / "fb_mass_results.json"
RAW_DIR = DATA_DIR / "fb_mass_raw"
MASS_TOKEN_FILE = DATA_DIR / "telegram_mass_token.bin"

# กลุ่มตั้งต้นตามที่ผู้ใช้สั่ง (12 ส.ค. 2026) — แก้เพิ่ม/ลดได้ใน fb_mass_config.json
DEFAULT_GROUPS = [
    "https://www.facebook.com/share/g/1C3n3j4rxy/",
    "https://www.facebook.com/share/g/1Ggsvh4MKW/",
    "https://www.facebook.com/share/g/1Au1mZREPG/",
    "https://www.facebook.com/share/g/1DV2zRB8QQ/",
    "https://www.facebook.com/share/g/19EpSd6wM1/",
    "https://www.facebook.com/share/g/1FH6rp3JgX/",
    "https://www.facebook.com/share/g/19EbHH7fhY/",
]

DEFAULT_CONFIG = {
    "bot_profile": "Bot10",     # ชื่อหรือ id ของโปรไฟล์ในฟาร์ม
    "min_likes": 100,
    "min_shares": 0,            # 0 = ไม่ใช้เกณฑ์นี้
    "min_comments": 0,          # 0 = ไม่ใช้เกณฑ์นี้
    "max_posts": 5,             # ส่งกี่โพสต์ต่อกลุ่ม (เอาตัวยอดสูงสุด) · 0 = ไม่จำกัด
    # ความลึกสูงสุดที่เลื่อนต่อกลุ่ม — กลุ่มที่มีของครบจะหยุดเองก่อนถึงเลขนี้
    # ตั้งสูงได้ถ้าอยากขุดลึก (กลุ่ม engagement ต่ำจะเลื่อนจนครบเลขนี้ ~4 วิ/รอบ)
    "scrolls": 25,
    # ชื่อ/username/id ของบอทในทะเบียน extra_bots (หน้า Studio) ที่ให้ส่งรายงาน
    # ว่าง = ถอยไปใช้โทเคนไฟล์ mass → บอทหลัก ตามลำดับ
    "telegram_bot": "NewestBoyBot",
    "mass_chat_id": "",         # ว่าง = ใช้ chat id ของบอทที่เลือก/บอทหลัก
    "groups": [{"url": u, "canonical": "", "name": ""} for u in DEFAULT_GROUPS],
}

# JSON ของ Facebook escape เครื่องหมาย / เป็น \/ — normalize ก่อนค่อย match
# key ทุกตัวพิสูจน์จากดัมพ์ฟีดจริง 12 ส.ค. 2026 (probe 7.5MB จากกลุ่มจริง):
#   "reaction_count":{"count":62,...}  และแบบเปลือย  "reaction_count":62
#   "share_count":{"count":64}
#   "comments":{"total_count":173}  และ  "total_comment_count":173
POST_URL_RE = re.compile(
    r"https://www\.facebook\.com/groups/([^/\"\\\s]+)/(?:posts|permalink)/(\d+)")
REACTION_RE = re.compile(r'"reaction_count"\s*:\s*(?:\{\s*"count"\s*:\s*)?(\d+)')
SHARE_RE = re.compile(r'"share_count"\s*:\s*\{\s*"count"\s*:\s*(\d+)')
COMMENT_RE = re.compile(
    r'"(?:comments"\s*:\s*\{\s*"total_count|total_comment_count)"\s*:\s*(\d+)')
# ระยะที่ยอมให้ตัวเลขอยู่ห่างจากลิงก์โพสต์ใน JSON ก้อนเดียวกัน
# (story หนึ่งก้อนยาวหลักพันตัวอักษร — แคบไปจับไม่เจอ กว้างไปจับข้ามโพสต์)
PAIR_WINDOW = 6000


class MassFinderError(RuntimeError):
    """ข้อผิดพลาดที่ตั้งใจให้ผู้ใช้อ่านแล้วรู้ว่าต้องทำอะไรต่อ"""


# ------------------------------------------------------------------ ตั้งค่า

def load_config() -> dict:
    if not CONFIG_FILE.is_file():
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return json.loads(json.dumps(DEFAULT_CONFIG))
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    # เติม key ที่ขาดจากค่าปริยาย — config เก่าต้องไม่พังเมื่อโค้ดใหม่เพิ่ม key
    for key, value in DEFAULT_CONFIG.items():
        config.setdefault(key, value)
    return config


def save_config(config: dict) -> None:
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def load_seen() -> dict:
    try:
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_seen(seen: dict) -> None:
    SEEN_FILE.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")


def load_rejected() -> dict:
    try:
        return json.loads(REJECT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_rejected(rejected: dict) -> None:
    REJECT_FILE.write_text(
        json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")


def reject_post(post_id: str) -> dict:
    """จดโพสต์เข้าบัญชีดำ — ดึงรายละเอียด (ลิงก์กลุ่ม/ยอด) จาก seen ถ้ามี"""
    rejected = load_rejected()
    if post_id in rejected:
        return rejected[post_id]
    info = load_seen().get(post_id, {})
    entry = {
        "url": info.get("url", ""),
        "group": info.get("group", ""),
        "likes": info.get("likes", 0),
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    rejected[post_id] = entry
    save_rejected(rejected)
    return entry


# ------------------------------------------------------------- เบราว์เซอร์บอท

def find_bot(farm: ProfileFarm, name_or_id: str) -> dict:
    state = farm.list_profiles()
    entry = next(
        (p for p in state["profiles"]
         if p["id"] == name_or_id
         or p["name"].casefold() == name_or_id.casefold()),
        None)
    if entry is None:
        raise MassFinderError(
            f"ไม่พบโปรไฟล์บอท \"{name_or_id}\" ในฟาร์ม — เช็คชื่อใน data/bot_profiles/registry.json")
    if entry.get("running"):
        # ห้ามฆ่าเอง (กติกา 2.5) — Chrome เปิดโปรไฟล์เดียวกันซ้อนไม่ได้
        raise MassFinderError(
            f"Chrome ของ {entry['name']} เปิดอยู่ — ปิดหน้าต่างนั้นก่อนแล้วสั่งใหม่ "
            "(เปิดซ้อนจะไล่ตัวเดิมหลุดกลางคัน)")
    return entry


def launch_bot_browser(playwright, farm: ProfileFarm, entry: dict):
    """เปิด Chrome ของโปรไฟล์บอท — คืน context (ผู้เรียกต้องปิดเอง)"""
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(farm.user_data_dir(entry["id"])),
        channel="chrome",
        headless=False,   # Facebook ตรวจ headless — เปิดจริงเท่านั้น
        no_viewport=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1280,900",
        ],
    )


def ensure_logged_in(page, context) -> str:
    """ยืนยันว่าโปรไฟล์นี้ล็อกอิน Facebook อยู่จริง — คืน user id

    เช็คสองชั้น (บทเรียน _is_signed_in ที่เคยโกหกทั้งระบบ):
    1. cookie `c_user` ต้องมี (Facebook ใส่ให้เฉพาะตอนล็อกอินแล้วเท่านั้น)
    2. URL ปัจจุบันต้องไม่ใช่หน้า login/checkpoint
    """
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded",
              timeout=60_000)
    page.wait_for_timeout(3_000)
    cookies = {c["name"]: c["value"]
               for c in context.cookies("https://www.facebook.com")}
    user_id = cookies.get("c_user", "")
    url = page.url
    if not user_id or "login" in url or "checkpoint" in url:
        raise MassFinderError(
            "โปรไฟล์บอทนี้ยังไม่ได้ล็อกอิน Facebook — เปิดบอทจากหน้า Studio "
            "แล้วล็อกอิน facebook.com ในหน้าต่างนั้นหนึ่งครั้ง จากนั้นปิดแล้วสั่งใหม่")
    return user_id


# ------------------------------------------------------------- แกะโพสต์จาก JSON

def _nearest(values: list[tuple[int, int]], anchor: int) -> int | None:
    """ค่าที่ตำแหน่งใกล้ anchor ที่สุดภายใน PAIR_WINDOW — ไม่มีคืน None"""
    best, best_distance = None, PAIR_WINDOW + 1
    for position, count in values:
        distance = abs(position - anchor)
        if distance < best_distance:
            best, best_distance = count, distance
    return best


def harvest(text: str, bucket: dict[str, dict]) -> None:
    """ดึง (ลิงก์โพสต์, ไลค์, แชร์, คอมเมนต์) จาก JSON/HTML ของ Facebook

    จับลิงก์โพสต์ทุกตัวก่อน แล้วหาตัวเลขแต่ละชนิดที่อยู่ใกล้ที่สุดในระยะ
    PAIR_WINDOW ตัวอักษร — story ก้อนเดียวกันค่าพวกนี้อยู่ติดกันเสมอ
    (พิสูจน์แล้ว: ค่าของโพสต์อื่นอยู่ห่างเกิน 147K ตัวอักษร)
    เจอโพสต์เดิมหลายรอบ (หน้าแรก + GraphQL) เก็บค่าสูงสุดของแต่ละช่องไว้
    """
    text = text.replace("\\/", "/")
    reactions = [(m.start(), int(m.group(1))) for m in REACTION_RE.finditer(text)]
    shares = [(m.start(), int(m.group(1))) for m in SHARE_RE.finditer(text)]
    comments = [(m.start(), int(m.group(1))) for m in COMMENT_RE.finditer(text)]
    for match in POST_URL_RE.finditer(text):
        group_key, post_id = match.group(1), match.group(2)
        likes = _nearest(reactions, match.start())
        if likes is None:
            continue
        found = {
            "id": post_id,
            "url": f"https://www.facebook.com/groups/{group_key}/posts/{post_id}/",
            "likes": likes,
            "shares": _nearest(shares, match.start()) or 0,
            "comments": _nearest(comments, match.start()) or 0,
        }
        known = bucket.get(post_id)
        if known is None:
            bucket[post_id] = found
        else:
            for field in ("likes", "shares", "comments"):
                known[field] = max(known[field], found[field])


def engagement(post: dict) -> int:
    """คะแนน engagement รวม = ไลค์ + คอมเมนต์ + แชร์

    วัดความ "แมส" ดีกว่าไลค์อย่างเดียว — พิสูจน์จากของจริง 13 ส.ค. 2026:
    กลุ่มรีวิวมีโพสต์ไลค์ 3 แต่คอมเมนต์ 299 (คนแห่ทัก) = แมสจริง แต่เกณฑ์
    ไลค์อย่างเดียวมองข้าม · กลุ่มที่มีโพสต์เกิน 100 เพิ่มจาก 0-3 เป็น 5-21 อัน
    """
    return post.get("likes", 0) + post.get("shares", 0) + post.get("comments", 0)


def passes(post: dict, config: dict) -> bool:
    """โพสต์ผ่านเกณฑ์ที่ตั้งไว้ครบทุกข้อไหม (เกณฑ์ที่เป็น 0 = ปิด ไม่ตรวจ)

    เกณฑ์หลัก = engagement รวม เกิน min_likes (ค่าเดิม 100)
    min_shares/min_comments = พื้นขั้นต่ำเสริมรายช่อง ถ้าอยากคัดละเอียด (0=ปิด)
    """
    if engagement(post) <= int(config.get("min_likes", 100)):
        return False
    min_shares = int(config.get("min_shares", 0))
    if min_shares and post.get("shares", 0) <= min_shares:
        return False
    min_comments = int(config.get("min_comments", 0))
    if min_comments and post.get("comments", 0) <= min_comments:
        return False
    return True


# เมื่อยังหาโพสต์ใหม่ไม่ครบโควตา จะเลื่อนต่อจนกว่าจะครบ — ไม่มีเพดาน "จำนวนรอบ"
# ตายตัว แต่มีจุดหยุดจริง 2 อย่างกันค้างชั่วนิรันดร์:
#   1. ฟีดหมดจริง — โหลดไม่ขึ้นโพสต์ใหม่ครบ IDLE_LIMIT รอบติด
#   2. เพดานกันลูปหลุด HARD_CAP_SCROLLS — เผื่อกลุ่มใหญ่ที่โพสต์ใหม่ไหลไม่หยุด
#      แต่ไม่มีอันไหนถึงเกณฑ์ (ถ้าไม่มีเพดานจะเลื่อนไม่จบ) หยุดแล้วรายงานตามจริง
# เลื่อนแล้วโหลดไม่ขึ้นโพสต์ใหม่กี่รอบติด ถือว่าฟีดหมดจริง (กันรอฟีดช้าเผลอหยุดเร็ว)
IDLE_LIMIT = 4


def scan_group(page, share_url: str, scrolls: int, log, enough=None) -> dict:
    """เปิดกลุ่มหนึ่ง เลื่อนฟีด แล้วคืนโพสต์ทั้งหมดที่อ่านยอดได้

    โพสต์ชุดแรกฝังมากับ HTML (อ่านจาก page.content()) แต่โพสต์ที่โหลดเพิ่ม
    ตอนเลื่อนมากับ GraphQL เท่านั้น — พิสูจน์แล้ว 12 ส.ค. 2026: ไม่อ่าน GraphQL
    จะเห็นแค่ 4 โพสต์แรก เลื่อนกี่รอบก็ไม่เพิ่ม

    ⚠ ห้ามเรียก sync API (เช่น response.text()) **ข้างใน** event handler ของ
    Playwright sync — greenlet ชนกันแล้วโปรเซสตายเงียบทั้งตัวโดยไม่มี traceback
    (เจอมาแล้ว: ฆ่ารันเต็มทั้งรอบ เหลือแต่ EPIPE ของ node driver)
    handler จึงทำแค่จด response ลง list แล้วค่อยอ่านตัวหนังสือนอก handler
    """
    bucket: dict[str, dict] = {}
    pending: list = []

    def on_response(response):
        if "/api/graphql" in response.url:
            pending.append(response)     # ห้ามอ่าน body ตรงนี้ — จดไว้เฉยๆ

    def drain() -> None:
        """อ่าน body ของ response ที่จดไว้ (เรียกจาก greenlet หลักเท่านั้น)"""
        for response in pending:
            try:
                harvest(response.text(), bucket)
            except Exception:
                pass   # body ถูกทิ้งไปแล้ว/ไม่ใช่ข้อความ — ข้ามตัวนั้นได้
        pending.clear()

    page.on("response", on_response)
    try:
        page.goto(share_url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(5_000)
        canonical = page.url.split("?")[0]
        name = re.sub(r"\s*\|\s*Facebook\s*$", "", page.title()).strip()
        log(f"  เปิดแล้ว: {name or canonical}")
        harvest(page.content(), bucket)          # โพสต์ชุดแรกฝังมากับ HTML
        drain()

        # ความลึก = scrolls (ปุ่มเดียวคุมความลึก ปรับผ่าน /set เลื่อน N)
        # หยุดเมื่อ: ได้ครบโควตา · ฟีดหมดจริง · หรือครบความลึกที่ตั้งไว้
        idle_rounds = 0
        round_number = 0
        stop_reason = ""
        while round_number < scrolls:
            if enough and enough(bucket):
                stop_reason = "ได้โพสต์ใหม่ครบโควตาแล้ว — หยุดเลื่อน"
                break
            round_number += 1
            before = len(bucket)
            page.keyboard.press("End")
            page.wait_for_timeout(3_000)
            drain()
            harvest(page.content(), bucket)
            log(f"  เลื่อนรอบ {round_number}/{scrolls} — เจอแล้ว {len(bucket)} โพสต์")
            # ฟีดไม่โหลดเพิ่ม IDLE_LIMIT รอบติด = ฟีดหมดจริง ไม่เผาเวลาต่อ
            idle_rounds = idle_rounds + 1 if len(bucket) == before else 0
            if idle_rounds >= IDLE_LIMIT:
                stop_reason = "ฟีดหมดแล้ว (โหลดไม่ขึ้นโพสต์ใหม่)"
                break
        else:
            if enough:
                stop_reason = f"ครบความลึก {scrolls} รอบแล้ว (ยังไม่ครบโควตา)"
        if stop_reason:
            log(f"  {stop_reason}")
    finally:
        page.remove_listener("response", on_response)

    # เรียงตาม engagement รวม (ไลค์+คอมเมนต์+แชร์) — โพสต์แมสที่สุดอยู่บนสุด
    posts = sorted(bucket.values(), key=lambda p: -engagement(p))
    result = {"share_url": share_url, "canonical": canonical, "name": name,
              "posts": posts, "error": ""}
    if not posts:
        # อ่านไม่ออกต้องทิ้งหลักฐานไว้ ไม่ใช่เงียบ (กติกา 2.4)
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dump = RAW_DIR / f"empty-{stamp}.html"
        dump.write_text(page.content(), encoding="utf-8")
        body_text = page.evaluate(
            "() => (document.body ? document.body.innerText : '').slice(0, 800)")
        joined = any(word in body_text for word in
                     ("เข้าร่วมกลุ่ม", "Join group", "Join Group"))
        result["error"] = (
            "ยังไม่ได้เป็นสมาชิกกลุ่มนี้ (มีปุ่มเข้าร่วมกลุ่ม)" if joined
            else f"อ่านโพสต์ไม่ได้ — เก็บหน้าไว้ที่ {dump.name}")
        log(f"  ⚠ {result['error']}")
    return result


# ------------------------------------------------------------------ Telegram

def telegram_target(config: dict) -> tuple[str, str]:
    """(โทเคน, chat id) ปลายทางรายงาน

    ลำดับ: บอทที่ตั้งใน "telegram_bot" (จากทะเบียน extra_bots ของ Studio)
    → ไฟล์ telegram_mass_token.bin → บอทหลัก
    บอทที่ตั้งชื่อไว้แต่ใช้ไม่ได้ = พังดังๆ ไม่ถอยเงียบ (จะได้ไม่ส่งผิดบอท)
    """
    studio = studio_shared.read_config()
    wanted = str(config.get("telegram_bot") or "").strip()
    if wanted:
        bot = next(
            (b for b in (studio.get("extra_bots") or [])
             if wanted.casefold() in (str(b.get("name", "")).casefold(),
                                      str(b.get("username", "")).casefold(),
                                      str(b.get("id", "")).casefold())),
            None)
        if bot is None:
            raise MassFinderError(
                f"ไม่พบบอท \"{wanted}\" ในทะเบียนบอทเพิ่มเติมของ Studio "
                "— เพิ่มในหน้าตั้งค่าก่อน หรือแก้ \"telegram_bot\" ใน fb_mass_config.json")
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", str(bot["id"]))[:40]
        token = studio_shared.load_key(DATA_DIR / "bots" / f"{safe}.bin") or ""
        chat_id = str(config.get("mass_chat_id") or bot.get("chat_id")
                      or studio.get("telegram_chat_id") or "")
        if not token:
            raise MassFinderError(
                f"บอท \"{bot['name']}\" ยังไม่มีโทเคนบันทึกไว้ — ใส่โทเคนในหน้าตั้งค่า Studio ก่อน")
        if not chat_id:
            raise MassFinderError(
                f"ยังไม่รู้ chat id ของบอท \"{bot['name']}\" — ทักข้อความหาบอทหนึ่งครั้ง "
                "แล้วให้ Studio จำ หรือใส่ mass_chat_id ใน fb_mass_config.json")
        return token, chat_id

    token = studio_shared.load_key(MASS_TOKEN_FILE) or \
        studio_shared.load_telegram_token() or ""
    chat_id = str(config.get("mass_chat_id") or
                  studio.get("telegram_chat_id") or "")
    if not token or not chat_id:
        raise MassFinderError(
            "ยังตั้งค่า Telegram ไม่ครบ — ตั้ง \"telegram_bot\" ใน fb_mass_config.json "
            "หรือมีโทเคน (telegram_mass_token.bin/บอทหลัก) + chat id")
    return token, chat_id


def send_report(token: str, chat_id: str, group: dict, fresh: list[dict],
                min_likes: int) -> None:
    """ส่งหัวกลุ่มหนึ่งข้อความ แล้วตามด้วยโพสต์ละข้อความพร้อมปุ่ม 🚫

    แยกข้อความละโพสต์เพื่อให้ปุ่ม "ไม่เอาโพสต์นี้" ผูกกับโพสต์ชัดๆ
    (กดแล้ว fb_mass_bot ขีดฆ่าข้อความนั้นทิ้ง) และแนบชื่อกลุ่มไว้ในทุก
    ข้อความ — เลื่อนดูย้อนหลังแล้วยังรู้ว่าโพสต์ไหนมาจากกลุ่มไหน
    """
    name = html.escape(group["name"] or group["canonical"])
    telegram_bot.send_message(
        token, chat_id,
        f"🔥 <b>{name}</b>\nengagement เกิน {min_likes:,}: {len(fresh)} โพสต์ใหม่")
    for index, post in enumerate(fresh, 1):
        total = engagement(post)
        stats = (f"{index}. 🔥 {total:,} = ❤️ {post['likes']:,}"
                 f" · 💬 {post.get('comments', 0):,} · ↗ {post.get('shares', 0):,}")
        keyboard = {"inline_keyboard": [[
            {"text": "🚫 ไม่เอาโพสต์นี้", "callback_data": f"mr:{post['id']}"},
        ]]}
        telegram_bot.send_message(
            token, chat_id, f"{stats}\n📍 {name}\n{post['url']}", keyboard)


# ----------------------------------------------------------- เข้าร่วมกลุ่ม (/add)

# ป้ายปุ่มรับสองภาษา (กติกาโปรเจกต์: UI ตามภาษาบัญชี บังคับด้วย URL ไม่ได้)
JOIN_LABEL = re.compile(r"เข้าร่วมกลุ่ม|Join group", re.I)
PENDING_LABEL = re.compile(r"ยกเลิกคำขอ|รอการอนุมัติ|Cancel request|Requested", re.I)
# สถานะ "เป็นสมาชิกแล้ว" — กลุ่มสาธารณะกดเข้าปุ๊บเปลี่ยนเป็นอันนี้ (ไม่ใช่ pending)
MEMBER_LABEL = re.compile(r"เข้าร่วมแล้ว|^Joined$", re.I)


def _join_state(page) -> str:
    """อ่านสถานะการเป็นสมาชิกจากปุ่มจริงบนหน้า

    pending = ส่งคำขอแล้วรออนุมัติ · member = เป็นสมาชิกแล้ว
    can-join = มีปุ่มเข้าร่วมให้กด · unknown = ไม่เจอปุ่มพวกนี้ (มักแปลว่าเป็น
    สมาชิกแล้วและเห็นฟีด — ปุ่มเข้าร่วมหายไป)
    """
    if page.get_by_role("button", name=PENDING_LABEL).count():
        return "pending"
    if page.get_by_role("button", name=MEMBER_LABEL).count():
        return "member"
    if page.get_by_role("button", name=JOIN_LABEL).count():
        return "can-join"
    return "unknown"


def join_group(url: str, log=print) -> dict:
    """เปิดกลุ่มด้วยโปรไฟล์บอทแล้วกดเข้าร่วม + เพิ่มเข้า list หาโพสต์แมส

    คืน {status, name, canonical, added}
    status: joined-request (กดแล้ว รออนุมัติ/เข้าแล้ว) · already (เป็นสมาชิกอยู่แล้ว)
            · pending (เคยขอไว้ก่อนแล้ว)
    """
    config = load_config()
    farm = ProfileFarm(DATA_DIR)
    entry = find_bot(farm, str(config.get("bot_profile") or "Bot10"))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = launch_bot_browser(playwright, farm, entry)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            ensure_logged_in(page, context)
            log(f"เปิดกลุ่ม: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(5_000)
            canonical = page.url.split("?")[0]
            name = re.sub(r"\s*\|\s*Facebook\s*$", "", page.title()).strip()

            state = _join_state(page)
            if state == "pending":
                status = "pending"
                log("เคยส่งคำขอไว้แล้ว — รอแอดมินอนุมัติ")
            elif state in ("member", "unknown"):
                status = "already"
                log("เป็นสมาชิกกลุ่มนี้อยู่แล้ว")
            else:  # can-join
                page.get_by_role("button", name=JOIN_LABEL).first.click()
                # กลุ่มสาธารณะเปลี่ยนเป็น "เข้าร่วมแล้ว" ช้ากว่า 4 วิได้ · กลุ่มปิด
                # เด้ง pending · บางกลุ่มมีป๊อปอัปคำถาม → ปุ่มค้าง ต้องกรอกเอง
                # poll จนสถานะเปลี่ยนจริง สูงสุด 15 วิ (กติกา 2.3: เชื่อผลจริง)
                status = "stuck"
                for _ in range(15):
                    page.wait_for_timeout(1_000)
                    now = _join_state(page)
                    if now == "pending":
                        status = "pending"
                        log("ส่งคำขอเข้ากลุ่มแล้ว — รอแอดมินอนุมัติ")
                        break
                    if now in ("member", "unknown"):
                        status = "joined-request"
                        log("เข้าร่วมกลุ่มสำเร็จ")
                        break
                if status == "stuck":
                    log("กดแล้วแต่ยังไม่เปลี่ยนสถานะใน 15 วิ — "
                        "อาจมีคำถามสมาชิกให้กรอก (เพิ่มเข้า list ไว้ก่อน)")
        finally:
            context.close()

    # เพิ่มเข้า list (กันซ้ำด้วย id กลุ่มใน URL จริง ไม่ใช่เทียบ string ลิงก์แชร์)
    added = False
    key = canonical.rstrip("/").rsplit("/", 1)[-1]
    known = {g.get("canonical", "").rstrip("/").rsplit("/", 1)[-1]
             for g in config["groups"] if g.get("canonical")}
    if key not in known:
        config["groups"].append(
            {"url": url, "canonical": canonical, "name": name})
        added = True
    save_config(config)
    return {"status": status, "name": name, "canonical": canonical, "added": added}


# ------------------------------------------------- สแกนเจาะลึก N โพสต์ (/test)

# เพดานรอบเลื่อนตอนเจาะลึก — 1000 โพสต์ใช้ ~190-220 รอบ (พิสูจน์แล้ว 13 ส.ค.)
DEEP_MAX_SCROLLS = 250


def _collect_deep(page, share_url: str, target: int, log) -> dict:
    """เก็บโพสต์ย้อนหลังสูงสุด target โพสต์จากกลุ่มเดียว แล้วคืนสถิติ engagement

    ใช้ page ที่เปิดไว้แล้ว (เรียกวนหลายกลุ่มโดยไม่เปิด/ปิดเบราว์เซอร์ซ้ำ)
    ดักอ่าน GraphQL แบบเดียวกับ scan_group (จด response แล้ว drain นอก handler)
    """
    bucket: dict[str, dict] = {}
    pending: list = []

    def on_response(response):
        if "/api/graphql" in response.url:
            pending.append(response)

    def drain() -> None:
        for response in pending:
            try:
                harvest(response.text(), bucket)
            except Exception:
                pass
        pending.clear()

    page.on("response", on_response)
    try:
        page.goto(share_url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(5_000)
        canonical = page.url.split("?")[0]
        name = re.sub(r"\s*\|\s*Facebook\s*$", "", page.title()).strip()
        log(f"  เปิดแล้ว: {name or canonical}")
        harvest(page.content(), bucket)
        drain()

        idle_rounds = 0
        for round_number in range(1, DEEP_MAX_SCROLLS + 1):
            if len(bucket) >= target:
                break
            before = len(bucket)
            page.keyboard.press("End")
            page.wait_for_timeout(3_000)
            drain()
            harvest(page.content(), bucket)
            if round_number % 10 == 0:
                log(f"  เลื่อน {round_number} รอบ — {len(bucket)} โพสต์")
            idle_rounds = idle_rounds + 1 if len(bucket) == before else 0
            if idle_rounds >= IDLE_LIMIT:
                log(f"  ฟีดหมดที่ {len(bucket)} โพสต์")
                break
    finally:
        page.remove_listener("response", on_response)

    feed = list(bucket.values())         # ลำดับที่เห็นในฟีด (ใหม่→เก่า)
    posts = sorted(feed, key=lambda p: -engagement(p))
    return {"share_url": share_url, "canonical": canonical, "name": name,
            "posts": posts, "feed": feed}


def _depth_stats(feed: list[dict], min_eng: int, bands: int = 10) -> tuple:
    """engagement เฉลี่ยรายช่วงความลึก + โพสต์เกินเกณฑ์สะสม (ตามลำดับฟีด)

    ใช้ทำกราฟ /test — เห็น pattern ว่ายิ่งลึก engagement ยิ่งตกไหม
    """
    total = len(feed)
    if not total:
        return [], []
    step = max(1, total // bands)
    band_avg = []
    for i in range(bands):
        seg = feed[i * step:(i + 1) * step] if i < bands - 1 else feed[i * step:]
        band_avg.append(round(sum(engagement(p) for p in seg) / len(seg), 1)
                        if seg else 0)
    cum = []
    for i in range(1, bands + 1):
        upto = feed[:i * step] if i < bands else feed
        cum.append(sum(1 for p in upto if engagement(p) > min_eng))
    return band_avg, cum


def deep_scan_groups(groups: list[dict], target: int, log=print) -> list[dict]:
    """เปิดเบราว์เซอร์บอทครั้งเดียว แล้วเจาะลึกทีละกลุ่มตามรายการที่เลือก

    คืน list ของสถิติต่อกลุ่ม: {name, canonical, count, over, avg, top, error}
    ใช้กับคำสั่ง /test — เลือกได้หลายกลุ่ม
    """
    config = load_config()
    min_eng = int(config.get("min_likes", 100))
    farm = ProfileFarm(DATA_DIR)
    entry = find_bot(farm, str(config.get("bot_profile") or "Bot10"))
    log(f"ใช้โปรไฟล์บอท: {entry['name']} — เจาะลึกสูงสุด {target:,} โพสต์/กลุ่ม")

    from playwright.sync_api import sync_playwright

    results: list[dict] = []
    with sync_playwright() as playwright:
        context = launch_bot_browser(playwright, farm, entry)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            ensure_logged_in(page, context)
            for number, group in enumerate(groups, 1):
                gname = group.get("name") or group.get("url", "")
                log(f"[{number}/{len(groups)}] {gname}")
                started = time.perf_counter()
                try:
                    raw = _collect_deep(page, group["url"], target, log)
                    posts = raw["posts"]
                    over = [p for p in posts if engagement(p) > min_eng]
                    avg = (sum(engagement(p) for p in posts) / len(posts)
                           if posts else 0)
                    band_avg, cum = _depth_stats(raw["feed"], min_eng)
                    results.append({
                        "name": raw["name"] or gname,
                        "canonical": raw["canonical"],
                        "count": len(posts),
                        "over": len(over),
                        "avg": round(avg, 1),
                        "bands": band_avg,
                        "cum": cum,
                        "top": [{"eng": engagement(p), "likes": p["likes"],
                                 "comments": p.get("comments", 0),
                                 "shares": p.get("shares", 0), "url": p["url"]}
                                for p in posts[:5]],
                        "seconds": round(time.perf_counter() - started, 1),
                        "error": "",
                    })
                    r = results[-1]
                    log(f"  ✅ {r['count']} โพสต์ · เกิน {min_eng} = {r['over']} · "
                        f"เฉลี่ย {r['avg']} ({r['seconds']} วิ)")
                except Exception as error:      # กลุ่มเดียวพังต้องไม่ล้มทั้งชุด
                    results.append({
                        "name": gname, "canonical": "", "count": 0, "over": 0,
                        "avg": 0, "bands": [], "cum": [], "top": [], "seconds": 0,
                        "error": f"{type(error).__name__}: {error}"})
                    log(f"  ❌ {results[-1]['error']}")
        finally:
            context.close()
    # เก็บผลไว้ debug/ทำกราฟซ้ำได้
    try:
        (DATA_DIR / "fb_mass_test_last.json").write_text(
            json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "min_eng": min_eng, "results": results},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return results


# ------------------------------------------------------- กราฟผล /test (PNG)

TEST_CHART_FILE = DATA_DIR / "fb_mass_test_chart.png"
# ฟอนต์ที่รองรับไทย — เบราว์เซอร์เลือกตัวแรกที่มี
_CHART_FONT = ('"Leelawadee UI","Tahoma","Sarabun","Noto Sans Thai",'
               "system-ui,sans-serif")
# สเกลสูงสุดของแท่ง engagement (ค่าเกินมีตัวเลขกำกับ) — เท่ากับ proof เดิม
_CHART_CAP = 60


def _chart_bars_svg(bands: list, color: str) -> str:
    """สร้าง SVG แท่ง engagement รายช่วงความลึก (ตื้น→ลึก)"""
    if not bands:
        return ""
    width, height, base, top = 460, 96, 78, 10
    bw = (width - 12) / len(bands)
    parts = [f'<svg width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}">']
    for tick in (20, 40, 60):
        ty = base - (min(tick, _CHART_CAP) / _CHART_CAP) * (base - top)
        parts.append(f'<line x1="6" y1="{ty:.0f}" x2="{width-6}" y2="{ty:.0f}" '
                     f'stroke="#e2e6ec" stroke-width="1"/>')
        parts.append(f'<text x="7" y="{ty-2:.0f}" font-size="8" '
                     f'fill="#8b98ab">{tick}</text>')
    for i, value in enumerate(bands):
        x = 6 + i * bw + 2
        y = base - (min(value, _CHART_CAP) / _CHART_CAP) * (base - top)
        parts.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{bw-4:.0f}" '
                     f'height="{base-y:.0f}" rx="2" fill="{color}" opacity="0.85"/>')
        if value >= _CHART_CAP:
            parts.append(f'<text x="{x+(bw-4)/2:.0f}" y="{top-2}" font-size="8.5" '
                         f'text-anchor="middle" font-weight="700" '
                         f'fill="{color}">{round(value)}</text>')
    parts.append(f'<line x1="6" y1="{base}" x2="{width-6}" y2="{base}" '
                 f'stroke="#c6cfda" stroke-width="1"/>')
    parts.append(f'<text x="6" y="{height-2}" font-size="8.5" fill="#8b98ab">'
                 f'ตื้น (ใหม่)</text>')
    parts.append(f'<text x="{width-6}" y="{height-2}" font-size="8.5" '
                 f'text-anchor="end" fill="#8b98ab">ลึก (เก่า)</text>')
    parts.append("</svg>")
    return "".join(parts)


def _chart_html(results: list, min_eng: int) -> str:
    """หน้า HTML กราฟเปรียบเทียบกลุ่ม — เรียง engagement เฉลี่ยมาก→น้อย"""
    ok = sorted([r for r in results if not r.get("error")],
                key=lambda r: -r["avg"])
    cards = []
    for r in ok:
        live = r["over"] >= 5
        color = "#0f9e88" if live else "#b8524a"
        badge = ("✅ มีชีวิต" if live else "❌ เงียบ")
        cards.append(
            f'<div style="margin-bottom:18px">'
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'<b style="font-size:15px;flex:1;min-width:0;overflow:hidden;'
            f'white-space:nowrap;text-overflow:ellipsis">'
            f'{html.escape(r["name"][:44])}</b>'
            f'<span style="flex:none;font-size:12px;font-weight:700;'
            f'padding:2px 9px;border-radius:20px;border:1px solid {color};'
            f'color:{color};background:{color}1a">{badge}</span></div>'
            f'<div style="font-size:13px;color:#5c6a7e;margin:2px 0 6px">'
            f'อ่าน {r["count"]:,} · เกิน {min_eng} = '
            f'<b style="color:{color}">{r["over"]}</b> · เฉลี่ย {r["avg"]}</div>'
            f'{_chart_bars_svg(r.get("bands", []), color)}</div>')
    return (
        f'<html><head><meta charset="utf-8"></head>'
        f'<body style="margin:0;background:#fff">'
        f'<div id="chart" style="width:520px;padding:20px;'
        f'font-family:{_CHART_FONT};color:#182233">'
        f'<div style="font-size:19px;font-weight:800;margin-bottom:2px">'
        f'🔬 ผลเจาะลึก {ok[0]["count"] if ok else 0:,} โพสต์ล่าสุด</div>'
        f'<div style="font-size:12.5px;color:#5c6a7e;margin-bottom:16px">'
        f'engagement เฉลี่ยตามความลึกฟีด (ตื้น=โพสต์ใหม่) · เกณฑ์แมส &gt; {min_eng}</div>'
        f'{"".join(cards)}</div></body></html>')


def render_test_chart(results: list, min_eng: int, log=print) -> "Path | None":
    """เจนกราฟผล /test เป็น PNG (ผ่าน headless chrome — ฟอนต์ไทยขึ้นครบ)

    ใช้ chrome แบบไม่มีโปรไฟล์ (ไม่แตะ Bot10) render HTML แล้ว screenshot
    """
    if not any(not r.get("error") for r in results):
        return None
    page_html = _chart_html(results, min_eng)
    tmp = DATA_DIR / "fb_mass_test_chart.html"
    tmp.write_text(page_html, encoding="utf-8")
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page(viewport={"width": 560, "height": 800},
                                        device_scale_factor=2)
                page.goto(tmp.as_uri())
                page.wait_for_timeout(400)
                element = page.query_selector("#chart")
                element.screenshot(path=str(TEST_CHART_FILE))
            finally:
                browser.close()
        return TEST_CHART_FILE
    except Exception as error:
        log(f"เจนกราฟไม่สำเร็จ: {error}")
        return None


def settings_text(config: dict) -> str:
    """ข้อความสรุปการตั้งค่าปัจจุบัน (ใช้ตอบ /set)"""
    def gate(value: int, unit: str) -> str:
        return f"มากกว่า {value:,} {unit}" if value else "ปิด (ไม่ใช้เกณฑ์นี้)"

    return "\n".join([
        "⚙️ <b>ตั้งค่าหาโพสต์แมส</b>",
        f"1. เกณฑ์ engagement (ไลค์+คอมเมนต์+แชร์): "
        f"{gate(int(config.get('min_likes', 100)), '')}".rstrip(),
        f"2. พื้นแชร์ขั้นต่ำ (เสริม): {gate(int(config.get('min_shares', 0)), 'แชร์')}",
        f"3. พื้นคอมเมนต์ขั้นต่ำ (เสริม): {gate(int(config.get('min_comments', 0)), 'คอมเมนต์')}",
        (f"4. จำนวนโพสต์ต่อกลุ่ม: "
         + (f"{int(config.get('max_posts', 5))} โพสต์ (เอายอดสูงสุด)"
            if int(config.get('max_posts', 5)) else "ไม่จำกัด")),
        f"5. กลุ่มที่ค้นหา: {len(config.get('groups', []))} กลุ่ม (ดู/ลบที่ /groups)",
        f"6. ความลึกที่ขุด (สูงสุด): {int(config.get('scrolls', 25))} รอบ"
        " — กลุ่มที่ของครบหยุดเองก่อน · เพิ่มเลขนี้เพื่อขุดลึกขึ้น",
        "",
        "วิธีปรับ: <code>/set engagement 100</code> · <code>/set โพสต์ 5</code>",
        "<code>/set แชร์ 50</code> · <code>/set คอมเมนต์ 20</code> · <code>/set เลื่อน 8</code>",
        "ใส่ 0 = ปิดเกณฑ์นั้น/ไม่จำกัด (engagement ปิดไม่ได้)",
    ])


# ---------------------------------------------------------------------- main

def run(groups_limit: int = 0, scrolls: int = 0, use_telegram: bool = True,
        log=print) -> dict:
    config = load_config()
    seen = load_seen()
    rejected = load_rejected()
    # เคยส่งแล้ว + ผู้ใช้ตัดทิ้ง = ไม่นับเป็นโพสต์ใหม่ทั้งคู่
    excluded = set(seen) | set(rejected)
    min_likes = int(config.get("min_likes", 100))
    max_posts = int(config.get("max_posts", 5))
    scrolls = scrolls or int(config.get("scrolls", 25))
    groups = config["groups"][:groups_limit] if groups_limit else config["groups"]

    # เช็คปลายทาง Telegram ก่อนเปิดเบราว์เซอร์ — พังเรื่องตั้งค่าต้องพังตั้งแต่ต้น
    token = chat_id = ""
    if use_telegram:
        token, chat_id = telegram_target(config)

    farm = ProfileFarm(DATA_DIR)
    entry = find_bot(farm, str(config.get("bot_profile") or "Bot10"))
    log(f"ใช้โปรไฟล์บอท: {entry['name']} ({entry['id']})")

    from playwright.sync_api import sync_playwright

    results: list[dict] = []
    with sync_playwright() as playwright:
        context = launch_bot_browser(playwright, farm, entry)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            user_id = ensure_logged_in(page, context)
            log(f"ล็อกอิน Facebook แล้ว (uid {user_id})")

            def enough(bucket: dict) -> bool:
                """โพสต์ใหม่ (ผ่านเกณฑ์ + ไม่เคยส่ง + ไม่ถูกตัด) ครบโควตาหรือยัง"""
                count = sum(1 for p in bucket.values()
                            if passes(p, config) and p["id"] not in excluded)
                return count >= max_posts

            for number, group in enumerate(groups, 1):
                log(f"[{number}/{len(groups)}] กลุ่ม: {group['url']}")
                started = time.perf_counter()
                try:
                    result = scan_group(page, group["url"], scrolls, log,
                                        enough if max_posts else None)
                except Exception as error:      # กลุ่มเดียวพังต้องไม่ล้มทั้งคิว
                    result = {"share_url": group["url"], "canonical": "",
                              "name": group.get("name", ""), "posts": [],
                              "error": f"{type(error).__name__}: {error}"}
                    log(f"  ❌ {result['error']}")
                result["seconds"] = round(time.perf_counter() - started, 1)
                # จำชื่อ/URL จริงไว้ใน config — รอบหน้าไม่ต้องเดาใหม่
                if result.get("canonical"):
                    group["canonical"] = result["canonical"]
                    group["name"] = result["name"]
                results.append(result)

                passed = [p for p in result["posts"] if passes(p, config)]
                fresh = [p for p in passed if p["id"] not in excluded]
                # ส่งแค่ตัวท็อปตามที่ตั้งไว้ — posts เรียงตาม engagement มาก→น้อยแล้ว
                if max_posts:
                    fresh = fresh[:max_posts]
                log(f"  อ่านได้ {len(result['posts'])} โพสต์ · engagement เกิน "
                    f"{min_likes} = {len(passed)} · ใหม่ {len(fresh)} ({result['seconds']} วิ)")
                result["over_threshold"] = len(passed)
                result["fresh"] = fresh
                if use_telegram and fresh:
                    send_report(token, chat_id, result, fresh, min_likes)
                    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    for post in fresh:
                        # จดลิงก์โพสต์ + ลิงก์กลุ่มไว้ด้วย — ตอนกด "ไม่เอา"
                        # จะได้รู้ว่าโพสต์นั้นคืออะไรมาจากกลุ่มไหน
                        seen[post["id"]] = {
                            "likes": post["likes"],
                            "sent": stamp,
                            "url": post["url"],
                            "group": result.get("canonical")
                                     or group.get("canonical", ""),
                        }
                        excluded.add(post["id"])
                    save_seen(seen)
        finally:
            context.close()

    save_config(config)
    summary = {
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "min_likes": min_likes,
        "groups": results,
        "sent_new": sum(len(r.get("fresh", [])) for r in results),
        "failed": [r["share_url"] for r in results if r.get("error")],
    }
    RESULT_FILE.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if use_telegram:
        failures = "\n".join(f"⚠ {u}" for u in summary["failed"])
        telegram_bot.send_message(token, chat_id, (
            f"สแกนเสร็จ {len(results)} กลุ่ม · ส่งโพสต์ใหม่ {summary['sent_new']} ลิงก์"
            + (f"\nกลุ่มที่อ่านไม่ได้:\n{failures}" if failures else "")))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="หาโพสต์แมสในกลุ่ม Facebook")
    parser.add_argument("--groups", type=int, default=0,
                        help="สแกนแค่ N กลุ่มแรก (ไว้ทดสอบ)")
    parser.add_argument("--scrolls", type=int, default=0,
                        help="เลื่อนฟีดกี่รอบต่อกลุ่ม (ปริยายตาม config)")
    parser.add_argument("--no-telegram", action="store_true",
                        help="ไม่ส่ง Telegram — พิมพ์ผลอย่างเดียว")
    args = parser.parse_args()
    try:
        summary = run(groups_limit=args.groups, scrolls=args.scrolls,
                      use_telegram=not args.no_telegram)
    except (MassFinderError, FarmError) as error:
        print(f"❌ {error}")
        return 1
    print(f"\nผลเต็มอยู่ที่ {RESULT_FILE}")
    for group in summary["groups"]:
        top = group["posts"][:5]
        print(f"\n{group['name'] or group['share_url']}"
              + (f"  ⚠ {group['error']}" if group.get("error") else ""))
        for post in top:
            print(f"  ❤️ {post['likes']:,}  {post['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
