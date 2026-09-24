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

เจ้าของสั่งให้ล็อกอินบัญชีเก็บข้อมูลในโปรไฟล์ `Bot8` แยกต่างหาก เพื่อไม่ให้
บัญชีที่โพสต์ (Kp Oo) มีสองที่ล็อกอินพร้อมกัน ซึ่งเสี่ยงโดนตีธง

⚠️ **ข้อแลกที่ต้องรู้** บัญชีเก็บข้อมูล **ต้องเป็นสมาชิกกลุ่มนั้นด้วย** ถึงจะ
เห็นโพสต์ กลุ่มไหนที่ยังไม่ได้เข้าจะอ่านไม่ได้เลย และจะขึ้นเป็น "เข้าไม่ถึง"
ในรายงาน ไม่ใช่ "ยอด 0" — สองอย่างนี้ต้องแยกกันให้ออก ไม่งั้นจะนึกว่าโพสต์
ไม่มีคนสนใจ ทั้งที่แค่มองไม่เห็น

## ทำไมแยกฐานข้อมูลจาก fb_posts.db

`fb_posts.db` โตถึง 1 GB แล้ว และมีตัวเก็บข้อมูลกลุ่มสองตัว (Bot8/Bot8) เขียน
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
    python fb_engagement.py watch         วนเช็คทุก 6 ชั่วโมง
    python fb_engagement.py report        สรุปยอดล่าสุดของทุกโพสต์
    python fb_engagement.py comments      คอมเมนต์ที่ยังไม่ได้ตอบ
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import evidence
import studio_shared as shared

HERE = Path(__file__).resolve().parent
DB_FILE = shared.DATA_DIR / "fb_engagement.db"
_DB_INIT_LOCK = threading.Lock()
_DB_INITIALIZED: set[str] = set()
LOG_FILE = shared.DATA_DIR / "logs" / "fb_engagement.log"
REPLY_SCHEDULE_FILE = shared.DATA_DIR / "fb_reply_schedule.json"
COLLECT_CYCLE_FILE = shared.DATA_DIR / "fb_engagement_cycle.json"
COLLECT_CYCLE_VERSION = 1
REPLY_GAP_MIN_SECONDS = 10 * 60
REPLY_GAP_MAX_SECONDS = 15 * 60
FOLLOWUP_GAP_MIN_SECONDS = 1 * 60
FOLLOWUP_GAP_MAX_SECONDS = 5 * 60
FOLLOWUP_KEY_SUFFIX = "::followup-2"
REPLY_DAILY_LIMIT = 50
REPLY_DAILY_WINDOW_SECONDS = 24 * 60 * 60

# โปรไฟล์เบราว์เซอร์ที่ใช้เก็บข้อมูล — คนละบัญชีกับที่ใช้โพสต์
#
# 28 ส.ค. 2569 เจ้าของเลือก Bot11 ให้ต่อจากฟาร์มเดิม
# 13 ก.ย. 2569 เจ้าของสั่งเปลี่ยนเป็น Bot10
# 20 ก.ย. 2569 เจ้าของสั่งย้ายตัวเก็บคอมเมนต์จาก Bot10 มา Bot8
#
# ⚠️ เปลี่ยนชื่อตรงนี้อย่างเดียวไม่พอ — โปรไฟล์ใหม่ **ต้องล็อกอินบัญชีที่เป็น
# สมาชิกกลุ่มนั้นไว้แล้ว** ถ้าไม่ได้ล็อกอิน ตัวเก็บจะอ่านไม่เห็นโพสต์เลยและ
# รายงานว่า "เข้าไม่ถึง" ทุกกลุ่ม ซึ่งหน้าตาเหมือนกลุ่มตายไปหมด
# ทุกครั้งที่เปลี่ยนโปรไฟล์ ต้องรันเก็บจริงหนึ่งรอบแล้วดูว่าได้ยอดกลับมาไหม
COLLECTOR_PROFILE = "Bot8"

# บัญชีที่ตามเก็บ — ว่าง = ทุกบัญชีที่มีลิงก์โพสต์เก็บไว้
#
# 28 ส.ค. 2569 เจ้าของสั่ง "ตอนนี้ตามแค่โพสต์ของ Kp Oo"
# 13 ก.ย. 2569 เจ้าของสั่ง "เอาโพสต์เฉพาะจากบัญชี khao fang"
# เป็นรายการ ไม่ใช่ค่าเดี่ยว — วันที่อยากตามหลายบัญชีจะได้เติมชื่อ ไม่ต้องแก้โค้ด
#
# ⚠️ **ค่านี้ต้องตามบัญชีที่ใช้โพสต์จริงเสมอ** พอเจ้าของสลับบัญชีโพสต์แล้วลืม
# แก้ตรงนี้ ตัวเก็บจะไล่ตามโพสต์เก่าของบัญชีเดิมต่อไปเรื่อยๆ แล้วรายงานว่า
# "เข้าไม่ถึง" ทุกใบ ซึ่งหน้าตาเหมือนกลุ่มมีปัญหา ไม่เหมือนตั้งค่าผิด
#
# **เกิดจริงแล้ว** — วัดเมื่อ 13 ก.ย. 2569: อ่านยอดได้สำเร็จครั้งสุดท้าย
# 2 ก.ย. 16:30 แล้วเงียบไป **11 วัน** โดยไม่มีใครรู้ เพราะบัญชีที่โพสต์
# เปลี่ยนเป็น Khao Fang Nichapa แต่ตรงนี้ยังชี้ Kp Oo อยู่
# ค่านี้เป็น **ตัวบังคับ** เอาไว้จำกัดเฉพาะบางบัญชี — ว่างไว้ = ตามทุกบัญชี
# ที่ผูกกับมือถือสายโพสต์จริง ซึ่งเป็นสิ่งที่ถูกต้องกว่าการมานั่งแก้ชื่อทุกครั้ง
# ที่เพิ่มบัญชี (เจ้าของต่อสายที่สอง Preaw Buchakorn เมื่อ 16 ก.ย. 2569)
WATCH_ACCOUNTS: tuple[str, ...] = ()


def watched_accounts() -> list[str]:
    """บัญชีที่ควรตามเก็บคอมเมนต์ — อ่านจากทะเบียนมือถือจริง

    **ห้ามเขียนชื่อบัญชีตายตัวอีก** เพราะเคยพังแบบเงียบมาแล้ว: บัญชีที่โพสต์
    เปลี่ยนเป็น Khao Fang Nichapa แต่ค่านี้ยังชี้ Kp Oo ผลคือเก็บคอมเมนต์
    ไม่ได้เลย **11 วัน** โดยไม่มีอะไรฟ้อง (วัดเมื่อ 13 ก.ย. 2569)

    ผูกกับทะเบียนแทน — เพิ่มบัญชีใหม่แล้วตามเก็บให้เองทันที ไม่ต้องแก้โค้ด
    """
    if WATCH_ACCOUNTS:
        return [x.strip() for x in WATCH_ACCOUNTS if x.strip()]
    try:
        import devices                                          # noqa: PLC0415
        post = set(devices.enabled_serials("post"))
        return sorted(name for name, serials in devices.accounts().items()
                      if name and post.intersection(serials))
    except Exception:                                           # noqa: BLE001
        return []

CHECK_EVERY_SECONDS = 6 * 3600.0  # เจ้าของสั่ง 18 ก.ย. 2569: ทุก 6 ชั่วโมง

# Khao ยังเป็นบัญชีแรกตามลำดับธุรกิจ แต่ใบใหม่สุดของทุกบัญชีต้องได้เข้าคิว
# ก่อน backlog ของบัญชีแรก ไม่เช่นนั้น Preaw และใบ Khao ล่าสุดอาจรอหลายชั่วโมง.
COLLECT_ACCOUNT_PRIORITY = ("Khao Fang Nichapa", "Preaw Buchakorn")


def _collect_job_key(post: dict) -> tuple[str, str]:
    """หน่วยต่อเนื่องของ Bot8; legacy ที่ไม่มี job_id ถือเป็นคนละใบทุก URL."""
    account = str(post.get("account") or "").strip().casefold()
    job_id = str(post.get("job_id") or "").strip()
    identity = job_id or f"legacy:{str(post.get('post_url') or '').strip()}"
    return account, identity


def _collect_job_ends(posts: list[dict], index: int) -> bool:
    """จริงเมื่อโพสต์ index (0-based) เป็นโพสต์สุดท้ายของใบงานนั้น."""
    return index + 1 >= len(posts) or _collect_job_key(posts[index + 1]) != _collect_job_key(posts[index])


def _prioritize_collect_posts(posts: list[dict]) -> list[dict]:
    """Bring each account's newest job forward, then drain its older backlog.

    Keep every job contiguous so the existing 1–5 minute pacing remains a
    per-job pause.  Undated legacy links retain the old account-first order.
    """
    rank = {name.strip().casefold(): index
            for index, name in enumerate(COLLECT_ACCOUNT_PRIORITY)}
    fallback = len(rank)
    first_job: dict[tuple[str, str], int] = {}
    first_account: dict[str, int] = {}
    job_posts: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    job_created: dict[tuple[str, str], float] = {}
    for index, post in enumerate(posts):
        account, _ = _collect_job_key(post)
        first_account.setdefault(account, index)
        key = _collect_job_key(post)
        first_job.setdefault(key, index)
        job_posts.setdefault(key, []).append((index, post))
        raw_created = str(post.get("job_created_at") or "").strip()
        try:
            created = datetime.fromisoformat(raw_created).timestamp()
        except (TypeError, ValueError, OSError):
            created = 0.0
        job_created[key] = max(job_created.get(key, 0.0), created)

    accounts = sorted(
        first_account,
        key=lambda account: (
            rank.get(account, fallback), first_account[account], account,
        ),
    )
    jobs_by_account: dict[str, list[tuple[str, str]]] = {}
    for account in accounts:
        keys = [key for key in job_posts if key[0] == account]
        # Dated jobs are newest-first.  Legacy rows have no trustworthy date;
        # preserve their old order after all dated jobs.
        keys.sort(key=lambda key: (
            0 if job_created[key] else 1,
            -job_created[key] if job_created[key] else first_job[key],
            first_job[key],
        ))
        jobs_by_account[account] = keys

    # One newest job from each dated account goes first.  Afterwards retain the
    # business account priority while draining each account newest-first.
    promoted: list[tuple[str, str]] = []
    for account in accounts:
        keys = jobs_by_account[account]
        if keys and job_created[keys[0]]:
            promoted.append(keys.pop(0))
    ordered_jobs = [
        *promoted,
        *(key for account in accounts for key in jobs_by_account[account]),
    ]
    return [
        post
        for key in ordered_jobs
        for _, post in sorted(job_posts[key], key=lambda item: item[0])
    ]


def _cycle_urls(posts: list[dict]) -> list[str]:
    """URL ไม่ซ้ำตามลำดับคิวจริง ใช้เป็น identity ของ checkpoint."""
    return list(dict.fromkeys(
        str(post.get("post_url") or "").strip() for post in posts
        if str(post.get("post_url") or "").strip()
    ))


def _unfinished_cycle_from_log(posts: list[dict]) -> tuple[str, set[str]]:
    """กู้รอบที่ถูก kill ก่อนมี checkpoint จาก log + snapshot ที่เขียนแล้ว.

    รองรับการเปิดใช้ครั้งแรกด้วย: รอบ Bot8 ที่เริ่มด้วยโค้ดเก่าและถูก restart
    กลางทางยังไม่มีไฟล์ checkpoint แต่ทุกโพสต์ที่จบแล้วมี ``checked_at`` ใน DB.
    ถ้า log ล่าสุดเป็น "เริ่มรอบ" โดยยังไม่มี "จบรอบ" ตามหลัง จึงถือว่าเป็นรอบ
    ค้างและใช้ snapshot หลังเวลาเริ่มเป็นรายการที่ทำเสร็จแล้ว.
    """
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", set()
    starts = list(re.finditer(
        r"(?m)^(\d{2})/(\d{2}) (\d{2}):(\d{2}):(\d{2}) เริ่มรอบเช็ค", text))
    if not starts:
        return "", set()
    newest = starts[-1]
    if text.rfind(" จบรอบ —") > newest.start():
        return "", set()
    now = datetime.now()
    try:
        started = datetime(
            now.year, int(newest.group(2)), int(newest.group(1)),
            int(newest.group(3)), int(newest.group(4)), int(newest.group(5)))
    except ValueError:
        return "", set()
    if started > now + timedelta(days=1):
        started = started.replace(year=now.year - 1)
    current = set(_cycle_urls(posts))
    conn = open_db()
    try:
        rows = conn.execute(
            "SELECT DISTINCT post_url FROM my_post WHERE checked_at>=?",
            (started.isoformat(timespec="seconds"),)).fetchall()
    finally:
        conn.close()
    return started.isoformat(timespec="seconds"), {
        str(row[0]) for row in rows if str(row[0]) in current
    }


def _prepare_collect_cycle(posts: list[dict]) -> tuple[list[dict], dict, bool]:
    """สร้าง/อ่าน checkpoint แล้วคืนเฉพาะโพสต์ที่ยังไม่จบในรอบเดิม."""
    urls = _cycle_urls(posts)
    state = shared.read_json(COLLECT_CYCLE_FILE, {})
    valid = bool(
        isinstance(state, dict)
        and state.get("version") == COLLECT_CYCLE_VERSION
        and state.get("cycle_id")
        and isinstance(state.get("done_urls"), list)
    )
    recovered = False
    if not valid:
        started_at, done = _unfinished_cycle_from_log(posts)
        recovered = bool(started_at)
        state = {
            "version": COLLECT_CYCLE_VERSION,
            "cycle_id": datetime.now().strftime("%Y%m%d-%H%M%S-%f"),
            "started_at": started_at or datetime.now().isoformat(timespec="seconds"),
            "planned_urls": urls,
            "done_urls": [url for url in urls if url in done],
        }
    else:
        planned = list(dict.fromkeys([
            *[str(url) for url in (state.get("planned_urls") or []) if str(url)],
            *urls,
        ]))
        state["planned_urls"] = planned
        current = set(urls)
        # ลิงก์ที่ถูกลบจากทะเบียนระหว่าง restart ไม่ควรค้างรอบไว้ตลอดกาล.
        state["done_urls"] = list(dict.fromkeys([
            str(url) for url in (state.get("done_urls") or [])
            if str(url) in current
        ]))
    done = set(state.get("done_urls") or [])
    pending = [post for post in posts
               if str(post.get("post_url") or "").strip() not in done]
    state.update(
        planned_urls=urls,
        total=len(urls),
        completed=len(urls) - len(pending),
        remaining=len(pending),
        status="waiting",
        current_action="กำลังเตรียมรอบ Bot8",
        updated_at=datetime.now().isoformat(timespec="seconds"),
    )
    shared.write_json_atomic(COLLECT_CYCLE_FILE, state)
    return pending, state, bool(valid or recovered)


def _set_collect_cycle_current(state: dict, post: dict,
                               phase: str, action: str) -> None:
    """เขียนสถานะสดของ Bot8 โดยไม่แตะยอด checkpoint ที่ทำเสร็จแล้ว."""
    if not state or not state.get("cycle_id"):
        return
    current = shared.read_json(COLLECT_CYCLE_FILE, {})
    if current.get("cycle_id") != state.get("cycle_id"):
        return
    now = datetime.now().isoformat(timespec="seconds")
    url = str(post.get("post_url") or "").strip()
    started = (state.get("current_started_at")
               if state.get("current_post_url") == url else now)
    state.update(
        status="running",
        current_phase=str(phase or ""),
        current_action=str(action or ""),
        current_group=str(post.get("group_name") or ""),
        current_account=str(post.get("account") or ""),
        current_post_url=url,
        current_caption=str(post.get("caption") or "").strip()[:500],
        current_started_at=started or now,
        current_updated_at=now,
        updated_at=now,
    )
    shared.write_json_atomic(COLLECT_CYCLE_FILE, state)


def _mark_collect_cycle_done(state: dict, post: dict) -> None:
    """จดหลังจบหนึ่งโพสต์ที่ขอบปลอดภัย; kill กลางโพสต์จะยังไม่ถูกจด."""
    url = str(post.get("post_url") or "").strip()
    done = list(dict.fromkeys([*(state.get("done_urls") or []), url]))
    planned = list(state.get("planned_urls") or [])
    state.update(
        done_urls=done,
        completed=sum(1 for item in planned if item in set(done)),
        remaining=sum(1 for item in planned if item not in set(done)),
        last_post_url=url,
        last_group=str(post.get("group_name") or ""),
        current_phase="saved",
        current_action="บันทึกผลโพสต์นี้แล้ว",
        current_updated_at=datetime.now().isoformat(timespec="seconds"),
        updated_at=datetime.now().isoformat(timespec="seconds"),
    )
    shared.write_json_atomic(COLLECT_CYCLE_FILE, state)


def _finish_collect_cycle(state: dict) -> None:
    """ล้างเฉพาะ checkpoint ของรอบที่ผู้เรียกทำครบ ป้องกันลบรอบใหม่ทับกัน."""
    current = shared.read_json(COLLECT_CYCLE_FILE, {})
    if current.get("cycle_id") != state.get("cycle_id"):
        return
    try:
        COLLECT_CYCLE_FILE.unlink(missing_ok=True)
    except OSError:
        # เหลือ completed=total ไว้ รอบถัดไปจะรู้ว่ารอบเดิมจบแล้วและล้างซ้ำได้.
        state.update(remaining=0, completed=state.get("total", 0), status="complete")
        shared.write_json_atomic(COLLECT_CYCLE_FILE, state)


def collect_cycle_status() -> dict:
    """สถานะ checkpoint เบาสำหรับ API/หน้าเว็บ ไม่แตะ Chrome."""
    state = shared.read_json(COLLECT_CYCLE_FILE, {})
    if not isinstance(state, dict) or not state.get("cycle_id"):
        return {"active": False, "total": 0, "completed": 0, "remaining": 0}
    current_updated_at = str(state.get("current_updated_at") or "")
    working = False
    if state.get("status") == "running" and current_updated_at:
        try:
            working = ((datetime.now() - datetime.fromisoformat(
                current_updated_at)).total_seconds() <= 90)
        except ValueError:
            pass
    return {
        "active": True,
        "working": working,
        "cycle_id": state.get("cycle_id", ""),
        "started_at": state.get("started_at", ""),
        "updated_at": state.get("updated_at", ""),
        "last_group": state.get("last_group", ""),
        "current_phase": state.get("current_phase", ""),
        "current_action": state.get("current_action", ""),
        "current_group": state.get("current_group", ""),
        "current_account": state.get("current_account", ""),
        "current_post_url": state.get("current_post_url", ""),
        "current_caption": state.get("current_caption", ""),
        "current_started_at": state.get("current_started_at", ""),
        "current_updated_at": current_updated_at,
        "total": int(state.get("total") or 0),
        "completed": int(state.get("completed") or 0),
        "remaining": int(state.get("remaining") or 0),
    }

# ตามเก็บทุกโพสต์ที่ใบงานยังมีลิงก์ — **ทุกใบ ไม่ใช่ใบล่าสุดของกลุ่ม**
#
# เจ้าของสั่ง 15 ก.ย. 2569: *"โพสต์ที่โพสต์ไปตั้งแต่วันที่ 12 ให้เก็บคอมเมนต์
# มาให้หมด"*
#
# **ทำไมของเดิมไม่พอ** ของเดิมอ่านจาก `last_link` ของแต่ละกลุ่ม ซึ่งเก็บได้
# ใบเดียว พอลงโพสต์ใหม่ในกลุ่มเดิม ลิงก์เก่าถูกทับทันที โพสต์เก่าจึงหลุดออก
# จากสายตาระบบพร้อมกับคอมเมนต์ที่ยังค้างตอบอยู่บนนั้น
#
# วัดจริง 15 ก.ย.: คอมเมนต์รอตอบ 9 อัน **อยู่บนโพสต์ที่ยังตามอยู่แค่ 1 อัน**
# อีก 8 อันลอยอยู่บนโพสต์ที่ไม่มีใครเปิดดูอีกแล้ว = ธง "ตอบแล้ว" ไม่มีวันถูกตั้ง
# 18 ก.ย. 2569 เจ้าของขยายเป็นทุกโพสต์และให้โพสต์ใหม่เข้าเอง จึงยกเลิก cutoff
# ว่าง = ตามทุกใบงานที่ยังมีลิงก์ ไม่ตัดตามวันที่อีก โพสต์ใหม่จะถูกพบเองทุก
# รอบจาก fb_jobs.json โดยไม่ต้องเพิ่มคิวด้วยมือ
WATCH_SINCE = ""
PAGE_TIMEOUT_MS = 45_000
BETWEEN_POSTS = (60.0, 300.0)     # owner: random 1–5 minutes between work orders

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
    account     TEXT,                         -- เจ้าของโพสต์ แยกคิวคนละโปรไฟล์
    seq         INTEGER,
    author      TEXT,
    body        TEXT,
    when_text   TEXT,
    reply_to    TEXT,                         -- ตอบต่อคอมเมนต์ของใคร (ว่าง = คอมเมนต์ชั้นบน)
    is_ours     INTEGER NOT NULL DEFAULT 0,   -- คอมเมนต์ของเราเอง ไม่ต้องตอบ
    answered    INTEGER NOT NULL DEFAULT 0,   -- ตอบไปแล้วหรือยัง
    reply_draft TEXT,
    reply_saved_at TEXT,
    reply_sent_at TEXT,
    reply_queued_at TEXT,
    reply_attempted_at TEXT,
    reply_error TEXT,
    reply_submitted_at TEXT,
    followup_draft TEXT,
    followup_queued_at TEXT,
    followup_due_at REAL,
    followup_delay_seconds INTEGER,
    followup_attempted_at TEXT,
    followup_submitted_at TEXT,
    followup_sent_at TEXT,
    followup_error TEXT,
    ignored     INTEGER DEFAULT 0,
    ignored_at  TEXT,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS my_comment_post ON my_comment(post_url);

CREATE TABLE IF NOT EXISTS post_watch (
    post_url       TEXT PRIMARY KEY,
    active         INTEGER NOT NULL DEFAULT 1,
    stopped_at     TEXT,
    stopped_by     TEXT,
    keep_until     TEXT,       -- กดเก็บต่อ = ยังไม่เสนอซ้ำอย่างน้อย 24 ชม.
    suggested_at   TEXT,       -- ส่งข้อเสนอเข้า Telegram แล้วเมื่อไร
    decision_at    TEXT
);

-- เพดานตอบคอมเมนต์เป็นรอบคงที่ 24 ชั่วโมง แยกตามเจ้าของโปรไฟล์
-- รอบเริ่มเมื่อคำตอบแรกถูกยืนยันว่าขึ้น Facebook จริง ไม่ใช่ตอนกดเข้าคิว
CREATE TABLE IF NOT EXISTS reply_quota_window (
    account           TEXT PRIMARY KEY,
    window_started_at REAL NOT NULL,
    used              INTEGER NOT NULL DEFAULT 0,
    last_sent_at      TEXT,
    last_comment_key  TEXT
);
-- Independent from refreshable comment rows: one successful reply per identity.
CREATE TABLE IF NOT EXISTS reply_send_receipt (
    account TEXT NOT NULL,
    identity TEXT NOT NULL,
    comment_key TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY(account, identity)
);
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


# ช่องที่เพิ่มทีหลัง — `CREATE TABLE IF NOT EXISTS` ไม่เติมให้กับตารางที่มีอยู่แล้ว
# ต้องไล่เติมเอง ไม่งั้นเครื่องที่มีฐานข้อมูลเก่าจะพังตอนอ่านช่องใหม่
_EXTRA_COLUMNS = {
    "my_comment": {
        "account": "TEXT",
        # คำตอบที่เจ้าของพิมพ์ไว้บนหน้าเว็บ — ยังไม่ได้ส่ง รอบอทเอาไปพิมพ์บนมือถือ
        "reply_draft": "TEXT",
        "reply_saved_at": "TEXT",      # พิมพ์เก็บไว้เมื่อไร
        "reply_sent_at": "TEXT",       # บอทพิมพ์ลง Facebook จริงเมื่อไร ("" = ยังไม่ส่ง)
        # เจ้าของกดปุ่ม "ตอบกลับ" แล้ว = สั่งให้บอทไปพิมพ์ตอบ รอคิวอยู่
        # **ต่างจาก reply_draft** ตรงที่ draft คือพิมพ์ค้างไว้เฉยๆ ยังไม่สั่ง
        "reply_queued_at": "TEXT",
        "reply_attempted_at": "TEXT",  # รอบล่าสุดที่มือถือพยายามทำ
        "reply_submitted_at": "TEXT",  # durable dispatch intent; never blindly resend
        "reply_error": "TEXT",         # เหตุผลที่ยังส่งไม่ได้; ว่าง = ไม่ล้ม
        # comment 2 ใต้ parent เดิม แยกใบรับรองจากคำตอบแรกเพื่อกันส่งซ้ำ
        "followup_draft": "TEXT",
        "followup_queued_at": "TEXT",
        "followup_due_at": "REAL",
        "followup_delay_seconds": "INTEGER",
        "followup_attempted_at": "TEXT",
        "followup_submitted_at": "TEXT",
        "followup_sent_at": "TEXT",
        "followup_error": "TEXT",
        # เจ้าของกดปุ่ม "เพิกเฉย" = ไม่ตอบคอมเมนต์นี้ และไม่ต้องเอามาโชว์อีก
        "ignored": "INTEGER DEFAULT 0",
        "ignored_at": "TEXT",
    },
}


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    db_key = str(Path(DB_FILE).resolve()).casefold()
    try:
        # Schema/migrations are writes. Running them for every read-only web
        # poll makes the feed compete with the collector for SQLite's single
        # writer slot. Initialise once per database/process instead.
        with _DB_INIT_LOCK:
            if db_key not in _DB_INITIALIZED:
                conn.executescript(SCHEMA)
                for table, columns in _EXTRA_COLUMNS.items():
                    have = {row[1] for row in conn.execute(
                        f"PRAGMA table_info({table})")}
                    for name, kind in columns.items():
                        if name not in have:
                            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
                # ฐานเดิมยังไม่มี account ใน my_comment — เติมย้อนหลังครั้งเดียว
                conn.execute(
                    """UPDATE my_comment
                          SET account = COALESCE((
                                SELECT p.account FROM my_post p
                                 WHERE p.post_url = my_comment.post_url
                                 ORDER BY p.id DESC LIMIT 1), '')
                        WHERE COALESCE(account, '') = ''""")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS my_comment_account ON my_comment(account)")
                conn.commit()
                conn.execute("PRAGMA journal_mode=WAL")
                _DB_INITIALIZED.add(db_key)
    except BaseException:
        conn.rollback()
        conn.close()
        raise
    return conn


# --------------------------------------------------------- โพสต์ที่ต้องตามเก็บ

def _captions_by_link(account: str) -> dict[str, str]:
    """แคปชันของ **ใบงานที่สร้างลิงก์นั้นจริง** — จับคู่ ลิงก์ → แคปชัน

    **บั๊กที่ทำให้ตัวเก็บพังเงียบ 11 วัน** (เจอ 13 ก.ย. 2569)

    ``read_post`` ยืนยันว่าเปิดถูกโพสต์ด้วยการเทียบแคปชัน แต่ของเดิมส่ง
    ``_caption_of(account)`` ไปเทียบ ซึ่งคืน **แคปชันของใบงานล่าสุดใบเดียว**
    แล้วเอาไปเทียบกับ **ทุกกลุ่ม** ทั้งที่ลิงก์ของแต่ละกลุ่มมาจากใบงานคนละใบ
    คนละแคปชันกัน

    ผลคือเทียบไม่ตรงสักกลุ่ม แล้วรายงานว่า "เข้าถึงหน้าโพสต์แล้วแต่หากล่อง
    โพสต์ไม่เจอ" ซึ่งอ่านแล้วเหมือนหน้าเว็บมีปัญหา ไม่เหมือนเทียบผิดตัว
    — ไล่หาสาเหตุผิดทางไปหลายชั่วโมง

    วัดจริงตอนเจอ: ทั้ง 6 กลุ่มลิงก์มาจากใบ p194009409 แคปชัน
    "อาหารมื้อละ 20 เดี๋ยวนี้หายากแล้ว…" แต่ระบบเอาแคปชันของใบใหม่กว่า
    ("ช่วงลดนน ของถูกๆ…") ไปเทียบทุกกลุ่ม

    ไล่จาก ``results[].link`` ของทุกใบงาน ซึ่งเป็นที่ที่ตัวโพสต์จดลิงก์จริงไว้
    """
    try:
        raw = (shared.account_dir(account) / "fb_jobs.json").read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        rows = json.loads(raw)
    except ValueError:
        return {}
    if isinstance(rows, dict):
        rows = rows.get("jobs") or []
    out: dict[str, str] = {}
    for job in rows:
        caption = (job.get("caption") or "").strip()
        if not caption:
            continue
        for result in (job.get("results") or []):
            link = str(result.get("link") or "").strip()
            if link:
                out[link] = caption          # ใบใหม่กว่าทับใบเก่าที่ลิงก์ซ้ำกัน
    return out


def _caption_of(account: str) -> str:
    """แคปชันของงานล่าสุดของบัญชีนั้น — ใช้เป็นทางถอยเมื่อจับคู่ลิงก์ไม่ได้"""
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


def our_posts(on_date: str = "") -> list[dict]:
    """โพสต์ของเราทุกบัญชีที่มีลิงก์เก็บไว้แล้ว

    อ่านจากทะเบียนกลุ่มรายบัญชี (ที่แยกไว้เมื่อ 28 ส.ค. 2569) ไม่ใช่ไฟล์เดียว
    รวม — ไม่งั้นพอมีบัญชีที่สองจะเก็บของปนกัน

    ``on_date`` เป็น YYYY-MM-DD = เอาเฉพาะใบงานวันนั้นและ **ไม่บวก** ลิงก์ล่าสุด
    จากทะเบียนกลุ่ม วิธีนี้ใช้กับคำสั่งเก็บคอมเมนต์รายวัน เพื่อไม่ลากโพสต์เก่า
    ของอีกวันเข้ามาปนเพียงเพราะมันยังเป็น ``last_link`` ของกลุ่มนั้นอยู่
    """
    on_date = str(on_date or "").strip()[:10]
    if on_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", on_date):
        raise ValueError("on_date ต้องเป็น YYYY-MM-DD")
    out: list[dict] = []
    seen: set[str] = set()
    wanted = {name.strip().lower() for name in watched_accounts() if name.strip()}
    for account in shared.known_accounts():
        if wanted and account.strip().lower() not in wanted:
            continue
        try:
            raw = (shared.account_dir(account) / "fb_groups.json").read_text(
                encoding="utf-8")
        except OSError:
            continue
        groups = json.loads(raw)
        names = {str(g.get("group_id") or ""): g.get("name", "") for g in groups}
        by_link = _captions_by_link(account)
        fallback = _caption_of(account)

        def add(link: str, group_id: str, caption: str, job_id: str = "",
                job_created_at: str = "") -> None:
            link = (link or "").strip()
            if not link or link in seen:
                return
            seen.add(link)
            out.append({
                "post_url": link,
                # แคปชันของใบที่สร้างลิงก์นี้จริง — จับคู่ไม่ได้ค่อยถอยไปใช้
                # ของใบล่าสุด (ซึ่งอาจไม่ตรง แต่ดีกว่าไม่มีอะไรให้เทียบเลย)
                "caption": caption or by_link.get(link) or fallback,
                "group_id": group_id,
                "group_name": names.get(str(group_id), "") or str(group_id),
                "account": account,
                "job_id": str(job_id or ""),
                "job_created_at": str(job_created_at or ""),
            })

        # ---- ทุกโพสต์ที่ลงตั้งแต่วันที่เจ้าของกำหนด ----
        undated = 0
        for job in _jobs_of(account):
            when = str(job.get("created_at") or job.get("started_at")
                       or job.get("finished_at") or "").strip()
            if not when:
                # **"ไม่รู้วันที่" ไม่ใช่ "เก่ากว่าเส้น"** ต้องดังไว้ก่อน (ข้อ 2.3.1)
                undated += 1
                continue
            job_date = when[:10]
            if on_date and job_date != on_date:
                continue
            if not on_date and WATCH_SINCE and job_date < WATCH_SINCE:
                continue
            caption = (job.get("caption") or "").strip()
            for result in (job.get("results") or []):
                add(str(result.get("link") or ""),
                    str(result.get("link_group_id")
                        or result.get("group_id") or ""), caption,
                    str(job.get("id") or ""), when)
        if undated:
            log(f"⚠️ ใบงานของ {account} ที่ไม่มีวันที่ {undated} ใบ — ข้ามไป "
                f"ตัดสินไม่ได้ว่าลงก่อนหรือหลัง {WATCH_SINCE}")

        # ---- บวกโพสต์ล่าสุดของแต่ละกลุ่มไว้เสมอ (ยกเว้นโหมดเจาะวัน) ----
        # ของเดิมใช้ทางนี้ทางเดียว เก็บไว้เป็นตาข่ายรอง เผื่อใบงานถูกลบทิ้ง
        # หรือลิงก์ถูกเติมเข้าทะเบียนกลุ่มโดยไม่ผ่านใบงาน
        if not on_date:
            for group in groups:
                add(group.get("last_link", ""), group.get("group_id", ""), "", "")
    return out


def _jobs_of(account: str) -> list[dict]:
    """ใบงานโพสต์ทั้งหมดของบัญชีนั้น — อ่านไม่ได้ก็คืนลิสต์ว่าง ไม่ทำให้รอบล้ม"""
    try:
        rows = json.loads((shared.account_dir(account) / "fb_jobs.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(rows, dict):
        rows = rows.get("jobs") or []
    return rows if isinstance(rows, list) else []


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


# ------------------------------------ หลักฐานตอนเปิดโพสต์แล้วหากล่องไม่เจอ

# **ทำไมต้องมี (31 ส.ค. 2569)** ช่วง 14:00–19:30 มีโพสต์เปิดไม่ได้ 9 ครั้ง
# ทุกครั้งบันทึกเหตุผลเดียวกันเป๊ะว่า "เข้าถึงหน้าโพสต์แล้วแต่หากล่องโพสต์ไม่เจอ"
# ซึ่ง **แยกไม่ออก** ว่าเป็นอะไรใน 4 อย่าง: โพสต์ถูกลบ · โดนหน้ากั้น/ให้ล็อกอินใหม่
# · หน้ายังโหลดไม่เสร็จ · แคปชันบนหน้าไม่ตรงกับที่เก็บไว้
#
# ไฟล์นี้เดิม **ไม่มีการเก็บหลักฐานเลยสักจุด** ซึ่งผิดกติกาข้อ 2.6.1 ที่สั่งไว้
# ตั้งแต่ 25 ส.ค. ว่าเจอปัญหาเมื่อไรต้องแคปหน้าจอเก็บทุกครั้ง — ข้อความบรรทัดเดียว
# ในฐานข้อมูลไม่พอให้ตัดสินใจอะไรได้เลย เหมือนเคสชื่อสินค้า "Please Try Again Later"
# ที่เดาได้ว่าโดนบล็อกแต่ตอบไม่ได้ว่าหน้านั้นเขียนว่าอะไร

EVIDENCE_TAG = "engage"

# โพสต์ที่เก็บหลักฐานไปแล้ววันนี้ — {(วันที่, รหัสโพสต์)}
#
# **ทำไมต้องกันเก็บซ้ำ** โพสต์ที่เปิดไม่ได้จะเปิดไม่ได้ทุกชั่วโมง และตัวตามเช็ค
# ทุก 1 ชม. ปล่อยไว้ = 9 โพสต์ × 24 รอบ = 216 ใบต่อวัน ชนเพดาน 300 เหตุการณ์
# ของ evidence.py ภายในวันเดียว แล้ว **ไปลบหลักฐานเรื่องอื่นที่นานๆ เกิดทีทิ้ง**
# ซึ่งย้อนแย้งกับเหตุผลที่มีระบบเก็บหลักฐานตั้งแต่แรก
#
# **ทำไมกันสองชั้น (ความจำ + ชื่อไฟล์)** ขาดอย่างใดอย่างหนึ่งมีรูทันที
#   ความจำ   เร็ว ไม่ต้องแตะดิสก์ทุกรอบ และยังกันได้แม้ตอนเขียนไฟล์ล้มเหลว
#            แต่ว่างเปล่าทุกครั้งที่โปรเซสใหม่ขึ้นมา
#   ชื่อไฟล์  อยู่ข้ามโปรเซส — `python fb_engagement.py once` ที่ถูกเรียกใหม่
#            ทุกชั่วโมงเป็นคนละโปรเซส ความจำจึงกันอะไรไม่ได้เลย
#
# เลือกวันละครั้งเพราะเหตุผลที่ทำให้เปิดไม่ได้ (โพสต์ถูกลบ · ไม่ได้เป็นสมาชิกกลุ่ม
# · แคปชันไม่ตรง) เป็นเรื่องที่ไม่เปลี่ยนรายชั่วโมง เก็บซ้ำจึงได้ภาพเดิม 24 ใบ
_EVIDENCE_SEEN: set[tuple[str, str]] = set()


def _evidence_key(url: str) -> str:
    """รหัสสั้นของโพสต์ที่เอาไปใส่ใน **ชื่อไฟล์** หลักฐาน

    ต้องอยู่ในชื่อไฟล์ ไม่ใช่แค่ในเนื้อไฟล์ เพราะตัวกันเก็บซ้ำข้ามโปรเซสดูจาก
    ชื่อไฟล์อย่างเดียว จะได้ไม่ต้องเปิดอ่านหลักฐานทุกใบทุกรอบ
    """
    numbers = re.findall(r"\d{6,}", url or "")
    if numbers:
        return numbers[-1][-12:]          # เลขโพสต์ท้าย URL — อ่านแล้วรู้ว่าใบไหน
    return hashlib.sha256((url or "").encode("utf-8")).hexdigest()[:10]


def keep_no_body_evidence(page, url: str, landed: str, expect: str,
                          boxes: int, texts: list, group_name: str = "",
                          on_post: bool = False):
    """เก็บภาพ + ผังหน้า + บริบท ตอนเปิดหน้าแล้วหากล่องโพสต์ไม่เจอ

    คืนที่อยู่ไฟล์บริบท หรือ None เมื่อไม่ได้เก็บ (ซ้ำในวันเดียวกัน / เก็บไม่สำเร็จ)

    **ห้ามทำให้งานล้มหนักขึ้น** (กติกาข้อ 2.6.1 ข้อ 2) — ครอบ try ทั้งก้อน
    เก็บไม่ได้ก็แค่ลง log ว่าเก็บไม่ได้ แล้วปล่อยผลลัพธ์เดิม (reachable: False)
    ไหลออกไปตามเดิม ห้ามให้ความล้มเหลวของการแคปบังสาเหตุจริง
    """
    try:
        today = datetime.now().strftime("%Y%m%d")
        key = _evidence_key(url)
        for stale in [item for item in _EVIDENCE_SEEN if item[0] != today]:
            _EVIDENCE_SEEN.discard(stale)         # ของเมื่อวานไม่ต้องจำแล้ว
        if (today, key) in _EVIDENCE_SEEN:
            return None
        _EVIDENCE_SEEN.add((today, key))
        # เก็บ**ก่อน**ลองเขียนจริง — ถ้าเขียนล้มก็ไม่ควรไปลองซ้ำทุกชั่วโมง
        if any(evidence.EVIDENCE_DIR.glob(f"{today}-*#{key}*.txt")):
            return None                           # โปรเซสก่อนหน้าเก็บไปแล้ววันนี้

        wanted = (expect or "").strip()
        head = wanted[:14]                        # ตัวหาใช้ 14 ตัวแรกไปเทียบ

        # **แยกให้ออกว่าเป็นเรื่องอะไร** (กติกาข้อ 2.3.1) — "หาไม่เจอ" เฉยๆ
        # ตอบได้ทั้งตอนหน้าไม่โหลดและตอนโพสต์ถูกลบ ซึ่งแก้คนละทางกันสิ้นเชิง
        if boxes == 0:
            verdict = ("ไม่เจอกล่องโพสต์เลยสักอัน → หน้ายังโหลดไม่เสร็จ "
                       "หรือโดนหน้ากั้น/ให้ล็อกอินใหม่ — ดูภาพประกอบว่าหน้าเขียนว่าอะไร")
        elif not head:
            verdict = ("ไม่มีแคปชันเก็บไว้ให้เทียบ → หาไม่เจอเพราะไม่รู้จะหาอะไร "
                       "ไม่ใช่เพราะหน้าพัง (ไปดู fb_jobs.json ของบัญชีนี้)")
        else:
            verdict = (f"เจอกล่อง {boxes} อัน แต่ไม่มีอันไหนมีข้อความที่ค้น → "
                       "โพสต์อาจถูกลบ · บัญชีเก็บข้อมูลไม่ได้เป็นสมาชิกกลุ่ม "
                       "· หรือแคปชันบนหน้าไม่ตรงกับที่เก็บไว้")

        lines = [
            f"ลิงก์โพสต์ที่สั่งเปิด : {url}",
            f"URL ที่ไปจบจริง      : {landed}",
            "อยู่หน้าโพสต์ไหม     : " + ("ใช่" if on_post else "ไม่ใช่ — โดนพาไปหน้าอื่น"),
            f"กลุ่ม                : {group_name or '(ไม่รู้)'}",
            f"ข้อความที่ใช้ค้นหา    : {head!r}  (แคปชันเต็ม {len(wanted)} ตัวอักษร)",
            f"กล่องที่เจอบนหน้า     : {boxes} กล่อง "
            f"(อ่านข้อความได้ {len(texts)} กล่อง)",
            "",
            f"อ่านยังไง: {verdict}",
        ]
        if texts:
            lines += ["", "ข้อความต้นๆ ของแต่ละกล่อง (ตัวเต็มอยู่ในไฟล์ .txt2 / .html)"]
        for order, one in enumerate(list(texts)[:3], 1):
            flat = " / ".join(x.strip() for x in str(one).splitlines() if x.strip())
            lines.append(f"  กล่อง {order}: {flat[:160] or '(ว่าง)'}")
        if len(texts) > 3:
            lines.append(f"  … อีก {len(texts) - 3} กล่อง")

        why = (f"หากล่องโพสต์ไม่เจอ #{key}" if on_post
               else f"โพสต์เด้งไปหน้าอื่น #{key}")
        return evidence.shot(page, why, tag=EVIDENCE_TAG, note="\n".join(lines))
    except Exception as error:                    # noqa: BLE001
        try:
            log(f"   เก็บหลักฐานไม่ได้: {type(error).__name__}: {str(error)[:80]}")
        except Exception:                         # noqa: BLE001
            pass                                  # log เองก็พังได้ ห้ามลามออกไป
        return None


# ป้ายที่ **มีเฉพาะบนกล่องที่เด้งทับฟีด** และบอกชื่อเจ้าของโพสต์มาด้วย
# (วัดจากผังหน้าจริง 13 ก.ย. 2569 — กล่องที่เด้งมีป้าย
#  "การดำเนินการสำหรับโพสต์นี้โดย Khao Fang Nichapa" และหัวกล่องเขียนว่า
#  "โพสต์ของ Khao Fang Nichapa" ส่วนโพสต์คนอื่นในฟีดข้างหลังไม่มีทั้งสองอย่าง)
_POPUP_OWNER = re.compile(
    r"(?:การดำเนินการสำหรับโพสต์นี้โดย|Actions for this post by)\s*(.+)")
_POPUP_TITLE = re.compile(r"^\s*(?:โพสต์ของ|Post by)\s*(.+)")


def popup_owner(node) -> str:
    """กล่องนี้เป็นกล่องที่เด้งของใคร — ไม่ใช่กล่องที่เด้งก็คืนค่าว่าง

    **ทำไมต้องมี (14 ก.ย. 2569)** เจ้าของเปิดลิงก์เองแล้วเห็นว่าโพสต์
    **ไม่ได้เปิดเป็นหน้าเดี่ยว** แต่เด้งเป็นกล่องทับหน้าฟีดกลุ่ม แล้วสั่งว่า
    *"หาวิธีดูจาก pop-up"*

    ของเดิมหากล่องด้วยการจับข้อความแคปชันอย่างเดียว พอแคปชันที่เก็บไว้ไม่ตรงกับ
    ที่อยู่บนหน้าจอ (แก้โพสต์ · เก็บแคปชันผิดใบ) ก็หาไม่เจอทั้งที่กล่องอยู่ตรงนั้น
    — เงียบไป 11 วันเพราะเหตุนี้

    ตัวนี้จึงถามของที่ **มีเฉพาะตอนเจอกล่องที่ใช่จริงๆ** (ข้อ 2.3.1)
    ไม่ใช่ถามว่า "ไม่เจอแคปชันใช่ไหม"
    """
    try:
        if (node.get_attribute("role") or "") != "dialog":
            return ""
    except Exception:                       # noqa: BLE001
        return ""
    try:
        for element in node.query_selector_all("[aria-label]"):
            found = _POPUP_OWNER.search(element.get_attribute("aria-label") or "")
            if found:
                return found.group(1).strip()
    except Exception:                       # noqa: BLE001
        pass
    try:
        first = ((node.inner_text() or "").strip().splitlines() or [""])[0]
    except Exception:                       # noqa: BLE001
        return ""
    found = _POPUP_TITLE.match(first)
    return found.group(1).strip() if found else ""


# ข้อความที่ Facebook ขึ้นเมื่อโพสต์ถูกลบ หรือเปลี่ยนคนที่มองเห็นได้
# เก็บไว้ที่เดียว เพราะทั้งตัวอ่านและตัวตัดสินว่าจะเลิกตามต้องใช้ตัวเดียวกัน
_GONE_MARKS = ("เนื้อหานี้ไม่พร้อมใช้งาน", "content isn't available",
               "content isnt available")
GONE_NOTE = "โพสต์ถูกลบ หรือเปลี่ยนคนที่มองเห็นได้ — Facebook ขึ้นว่าเนื้อหาไม่พร้อมใช้งาน"


def read_post(page, url: str, expect: str = "",
              group_name: str = "", account: str = "", progress=None,
              require_login: bool = False) -> dict:
    """เปิดโพสต์แล้วอ่านยอด + คอมเมนต์

    **ไม่กดอะไรที่เปลี่ยนสถานะ** — ไม่ถูกใจ ไม่ตอบ ไม่แชร์ สิ่งเดียวที่กดคือ
    ปุ่ม "ดูการตอบกลับอีก N รายการ" เพื่อกางของที่ Facebook พับไว้ ซึ่งเป็น
    การเปิดดูเฉยๆ คนอื่นไม่เห็นและไม่มีอะไรถูกบันทึกฝั่งเขา (ดู expand_hidden)

    คืน {"reachable": bool, "reactions"|"comments"|"shares": int|None,
         "comments_list": [...], "note": str}
    """
    report = progress or (lambda _phase, _action: None)
    report("opening", "กำลังเปิดลิงก์โพสต์")
    page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
    report("loading", "เปิดลิงก์แล้ว · รอหน้า Facebook โหลด")
    page.wait_for_timeout(7000)
    if require_login:
        import fb_collect_gate as gate
        gate.require_login(page, page.context)
    # Public posts can be readable behind Facebook's dismissible login prompt.
    # Never submit credentials or click through a mandatory login wall.
    for dialog in page.query_selector_all('div[role="dialog"]'):
        if not dialog.is_visible():
            continue
        text = dialog.inner_text() or ""
        if "See more on Facebook" in text or "ดูเพิ่มเติมบน Facebook" in text:
            if require_login:
                raise gate.LoginRequired("Bot8 พบหน้าขอเข้าสู่ระบบ — หยุดเก็บจนกว่าจะล็อกอินใหม่")
            close = dialog.query_selector('[role="button"][aria-label="Close"], '
                                          '[role="button"][aria-label="ปิด"]')
            if close is not None:
                close.click(timeout=5000)
                page.wait_for_timeout(1000)
    report("locating", "กำลังหากล่องโพสต์และยืนยันแคปชัน")

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
    # DOM order can put the background feed BEFORE the open post dialog.
    # Matching the same caption there selects covered, unclickable controls.
    dialogs = [node for node in page.query_selector_all('div[role="dialog"]')
               if node.is_visible()]
    boxes = dialogs or page.query_selector_all('div[role="article"]')
    # เก็บข้อความที่อ่านได้ไว้ด้วย — ตอนหาไม่เจอจะได้บอกได้ว่า "ไม่มีกล่องเลย"
    # (หน้าไม่โหลด) หรือ "มีกล่องแต่เนื้อหาคนละเรื่อง" (โพสต์ถูกลบ/แคปชันไม่ตรง)
    seen_texts: list[str] = []
    popup_node = None
    popup_text = ""
    found_by = "แคปชัน"
    want = (account or "").strip().casefold()
    for node in boxes:
        try:
            text = (node.inner_text() or "").strip()
        except Exception:
            continue
        seen_texts.append(text)
        if expect and expect.strip()[:14] in text:
            body = text
            holder_node = node
            break
        # ยังไม่เจอแคปชัน — จำกล่องที่เด้งของบัญชีเราไว้เป็นทางที่สอง
        if popup_node is None and want:
            owner = popup_owner(node).casefold()
            if owner and (want in owner or owner in want):
                popup_node, popup_text = node, text
    if not body and popup_node is not None:
        body, holder_node = popup_text, popup_node
        found_by = "ชื่อบัญชีบนกล่องที่เด้ง"
        log(f"   แคปชันที่เก็บไว้ไม่ตรงกับบนหน้าจอ — อ่านจากกล่องที่เด้ง"
            f"ของ {account} แทน")
    if not body:
        # **"หากล่องไม่เจอ" ไม่ใช่เหตุผล มันคืออาการ** (ข้อ 2.3.1)
        #
        # เจอจริง 15 ก.ย. 2569: โพสต์ในกลุ่ม "อยากมีบ้านโว้ย" ถูกลบไป หน้าเว็บ
        # ขึ้นแผ่นกุญแจว่า "เนื้อหานี้ไม่พร้อมใช้งานในขณะนี้" ซึ่งอ่านแล้วรู้เรื่อง
        # ทันที **แต่ระบบรายงานว่า "เข้าถึงหน้าโพสต์แล้วแต่หากล่องโพสต์ไม่เจอ"**
        # เพราะตัวเช็คคำว่า "ไม่พร้อมใช้งาน" ของเดิมอยู่ **หลัง** จุดที่ต้องเจอ
        # กล่องก่อน — หน้านี้ไม่มีกล่องสักอัน มันจึงไม่เคยได้ทำงาน
        #
        # ผลคือสามเรื่องที่ต้องทำคนละอย่างถูกยุบเป็นข้อความเดียว: โพสต์ถูกลบ ·
        # หน้ายังโหลดไม่เสร็จ · แคปชันที่เก็บไว้ไม่ตรง
        try:
            page_text = (page.inner_text("body") or "").lower()
        except Exception:                        # noqa: BLE001
            page_text = ""
        if any(mark.lower() in page_text for mark in _GONE_MARKS):
            # **ไม่เก็บหลักฐานชุดใหญ่** เพราะไม่มีอะไรให้สืบ หน้าบอกเหตุผลมาแล้ว
            # และสภาพนี้เกิดซ้ำทุกชั่วโมง เก็บไปก็ดันหลักฐานของจริงที่สายอื่น
            # ต้องใช้ตกเพดาน 300 ใบ (ผังหน้าใบละราว 5 MB)
            return {"reachable": False, "note": GONE_NOTE,
                    "reactions": None, "comments": None, "shares": None,
                    "comments_list": []}
        on_post = "/posts/" in landed or "/permalink/" in landed
        # แคปก่อน return เสมอ — ปิดเบราว์เซอร์ไปแล้วแคปไม่ได้อีก (ข้อ 2.6.1 ข้อ 1)
        keep_no_body_evidence(page, url=url, landed=landed, expect=expect,
                              boxes=len(boxes), texts=seen_texts,
                              group_name=group_name, on_post=on_post)
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

    report("metrics", "กำลังอ่านยอดไลก์ คอมเมนต์ และแชร์")
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
    # เช่นเดียวกับยอดถูกใจ: **ปุ่มกดถูกใจมีอยู่ทุกโพสต์ที่อ่านได้** ส่วนป้ายบอก
    # จำนวน ("ถูกใจ: 3 คน") โผล่เฉพาะตอนมีคนกดจริง — เห็นปุ่มแต่ไม่เห็นจำนวน
    # จึงแปลว่า **ศูนย์ ไม่ใช่อ่านไม่ออก** (วัดจากผังหน้าจริง 13 ก.ย. 2569:
    # โพสต์ที่ยังไม่มีใครกด มีป้าย "ถูกใจ" กับ "แสดงความรู้สึก" แต่ไม่มีตัวเลขเลย)
    #
    # ข้อ 2.3.1 ข้อ 4 บังคับให้ "ยังไม่ได้ตรวจ" ต่างจาก "ตรวจแล้วเป็นศูนย์" —
    # ของเดิมคืน None ทั้งสองกรณี หน้าเว็บจึงขึ้น "?" ให้โพสต์ที่ตรวจเรียบร้อย
    can_read = any(("ถูกใจ" in x or "แสดงความรู้สึก" in x
                    or "reaction" in x.lower() or "like" in x.lower())
                   for x in labels)
    if counts["reactions"] is None and can_read:
        counts["reactions"] = 0
    if counts["shares"] is None and counts["reactions"] is not None:
        counts["shares"] = 0

    # นับคอมเมนต์จากป้าย "ความคิดเห็นจาก <ชื่อ> เมื่อ ..." ที่มีหนึ่งอันต่อคอมเมนต์
    # เชื่อถือได้กว่าตัวเลขสรุปที่บางทีไม่โผล่เลยเมื่อมีคอมเมนต์น้อย
    # Public/English layout exposes the total as visible text, not aria-label.
    if counts["comments"] is None:
        total_label = re.search(
            r"(?im)^\s*(?:([\d,]+)\s+comments?|ความคิดเห็น\s*([\d,]+)(?:\s*รายการ)?)\s*$",
            body)
        if total_label:
            counts["comments"] = int((total_label.group(1) or total_label.group(2)).replace(",", ""))
    declared_comment_count = counts["comments"]
    if counts["comments"] is None:
        seen_comments = sum(1 for x in labels if x.startswith("ความคิดเห็นจาก"))
        counts["comments"] = seen_comments

    # **กางคำตอบที่ถูกพับก่อนอ่านเสมอ** ไม่งั้นอ่านได้แค่ที่หน้าจอกางอยู่
    report("expanding", "กำลังกางคอมเมนต์และคำตอบที่ซ่อน")
    expansion = expand_hidden(holder_node, page, log, detailed=True)

    # อ่านคอมเมนต์จากในกล่องโพสต์เท่านั้น — ทั้งหน้ามี `div[role="article"]`
    # หลายกล่องที่เป็นโพสต์คนอื่นในฟีดข้างหลังหน้าต่างซ้อน
    report("comments", "กำลังอ่านข้อความและชื่อผู้คอมเมนต์")
    comments = []
    comments_snapshot_complete = expansion["complete"]
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
        comments_snapshot_complete = False
        log(f"   อ่านคอมเมนต์ไม่ได้: {type(error).__name__}: {error}")

    if declared_comment_count is not None and declared_comment_count > len(comments):
        comments_snapshot_complete = False
        expansion["reason"] = "จำนวนที่อ่านได้น้อยกว่ายอดบนโพสต์"
    if declared_comment_count is None:
        counts["comments"] = len(comments) if comments_snapshot_complete else None
    note = ("" if comments_snapshot_complete else
            "เก็บยังไม่ครบ — " + (expansion.get("reason") or "อ่านคอมเมนต์ไม่สำเร็จ")
            + " · รักษาข้อมูลเดิมไว้")
    report("saving", note or "อ่านโพสต์แล้ว · กำลังบันทึกผล")
    return {"reachable": True, "note": note, "found_by": found_by,
            **counts, "comments_list": comments,
            "comments_snapshot_complete": comments_snapshot_complete}


# ------------------------------------------------------- กางของที่ถูกพับ

# ป้ายปุ่ม "กางเพิ่ม" — **เฉพาะปุ่มที่กางเท่านั้น ห้ามรวมปุ่มที่ยุบ**
# กด "ซ่อนการตอบกลับ" เข้าไปจะยิ่งทำให้มองไม่เห็นของที่เคยเห็น
_SHOW_MORE = re.compile(
    r"^\s*(?:"
    r"ดู(?:การ)?ตอบกลับ"                    # ดูการตอบกลับอีก 1 รายการ · ดูตอบกลับทั้งหมด
    r"|ดู\s*\d+\s*การตอบกลับ"               # ดู 2 การตอบกลับก่อนหน้า
    r"|ดูความคิดเห็น(?:เพิ่มเติม|ก่อนหน้า)"    # ดูความคิดเห็นเพิ่มเติม
    r"|ดูการตอบกลับก่อนหน้า"
    r"|View\s+(?:all\s+)?(?:\d+\s+)?(?:more\s+|previous\s+)?repl(?:y|ies)"
    r"|View\s+(?:\d+\s+)?(?:more|previous)\s+comments?"
    r")", re.IGNORECASE)

MAX_EXPAND_CLICKS = 12      # เพดานกันวนไม่จบบนโพสต์ที่มีคอมเมนต์เป็นร้อย
EXPAND_ROUNDS = 3           # กางชั้นหนึ่งแล้วอาจโผล่ปุ่มชั้นถัดไป


def expand_hidden(holder_node, page, log=None, *, detailed=False):
    """กดปุ่มกางคำตอบ/คอมเมนต์ที่ถูกพับ — คืนจำนวนครั้งที่กดได้จริง

    **ทำไมต้องมี (31 ส.ค. 2569)** ตัวเก็บอ่านเฉพาะสิ่งที่ถูกวาดบนหน้าจอ
    Facebook พับคำตอบไว้หลังปุ่ม "ดูการตอบกลับอีก N รายการ" คำตอบที่พับอยู่
    จึง **ไม่มีอยู่ในสายตาระบบเลย**

    เกิดจริง: เจ้าของตอบคอมเมนต์ "สนใจครับ" ของ "ไอ เสือ ชัช" ไปแล้ว
    (เห็นชัดในภาพหน้าจอ) แต่คำตอบถูกพับ ระบบจึงหาป้าย "ข้อความตอบกลับจาก…"
    ไม่เจอ แล้วรายงานเข้า Telegram ว่า **ยังไม่ได้ตอบ** ซ้ำๆ
    — เจ้าของต้องมาบอกเองว่า "คอมเมนต์นี้ตอบไปแล้วแต่ยังส่งมาแจ้งเตือนอยู่"

    เข้าข่ายข้อ 2.3.1 ตรงๆ: **"ไม่เห็นคำตอบ" ถูกนับเป็น "ยังไม่ได้ตอบ"**
    ทั้งที่สองอย่างนี้ต่างกัน — อันหนึ่งคือยังไม่ได้ทำ อีกอันคือทำแล้วแต่มองไม่เห็น

    **จับปุ่มจากข้อความของตัวปุ่มเอง ไม่ใช่ค้นทั้งหน้า** เพราะคอมเมนต์ของ
    คนอื่นอาจมีคำว่า "ดูการตอบกลับ" อยู่ในเนื้อความได้ (กติกาหน้า 3 ข้อ 2:
    ห้าม selector แบบ *="คำ" ในหน้าที่มีเนื้อหาผู้ใช้ปน)
    """
    say = log or (lambda _: None)
    clicked, stable = 0, 0
    deadline = time.monotonic() + 180
    previous = None
    complete, reason = False, "หมดเวลารอโหลดคอมเมนต์"
    controls = '[role="button"], button, a[role="link"]'

    def state():
        buttons, filtered = [], []
        for node in holder_node.query_selector_all(controls):
            if not node.is_visible():
                continue
            label = re.sub(r"[\u200b-\u200f\ufeff]", "", node.inner_text() or "").strip()
            if len(label) <= 80 and _SHOW_MORE.match(label):
                buttons.append(node)
            if label in {"เกี่ยวข้องมากที่สุด", "Most relevant", "Newest", "ใหม่ล่าสุด"}:
                filtered.append(node)
        signature = tuple(
            (n.get_attribute("aria-label"), n.inner_text())
            for n in holder_node.query_selector_all('div[role="article"]'))
        busy = any(n.is_visible() for n in holder_node.query_selector_all(
            '[role="progressbar"], [aria-busy="true"]'))
        return buttons, filtered, signature, busy

    try:
        while time.monotonic() < deadline and clicked < 200:
            buttons, filtered, signature, busy = state()
            if filtered:
                filtered[0].click(timeout=5000)
                option = page.get_by_text(re.compile(
                    r"^[\s\ufeff]*(?:ความคิดเห็นทั้งหมด|All comments)[\s\ufeff]*$"))
                option.last.click(timeout=5000)
                page.wait_for_timeout(1000)
                if state()[1]:
                    reason = "เปลี่ยนเป็นความคิดเห็นทั้งหมดไม่สำเร็จ"
                    break
                stable = 0
                continue
            if buttons:
                stable = 0
                buttons[0].scroll_into_view_if_needed(timeout=5000)
                buttons[0].click(timeout=5000)
                clicked += 1
                # Button disappearance alone is not evidence that the response loaded.
                changed = False
                for _ in range(20):
                    page.wait_for_timeout(500)
                    after = state()
                    if after[2] != signature and not after[3]:
                        changed = True
                        break
                if not changed:
                    reason = "กดโหลดเพิ่มแล้วข้อมูลไม่เปลี่ยนภายในเวลาที่กำหนด"
                    break
                continue
            # Trigger lazy loading only inside this post's scroll container.
            holder_node.evaluate("""root => {
                const nodes = [root, ...root.querySelectorAll('*')];
                for (const n of nodes) {
                    if (n.scrollHeight > n.clientHeight + 2 &&
                        /auto|scroll/.test(getComputedStyle(n).overflowY)) {
                        n.scrollTop = n.scrollHeight;
                    }
                }
            }""")
            stable = stable + 1 if signature == previous and not busy else 0
            previous = signature
            if stable >= 4:
                complete, reason = True, ""
                break
            page.wait_for_timeout(1000)
        if clicked >= 200:
            reason = "ถึงขีดจำกัดโหลดเพิ่ม 200 ครั้ง ยังไม่ยืนยันว่าครบ"
    except Exception as error:
        say(f"   รายละเอียดโหลดเพิ่ม: {error}")
        reason = f"โหลดเพิ่มไม่สำเร็จ: {type(error).__name__}: {str(error)[:120]}"
    say(f"   กางคอมเมนต์ {clicked} จุด · " + ("โหลดครบ" if complete else reason))
    result = {"clicked": clicked, "complete": complete, "reason": reason}
    return result if detailed else clicked


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


def split_comment_author(value: str) -> tuple[str, str]:
    """Strip only an anchored relative-time suffix, never digits in a name."""
    text = str(value or '').strip()
    found = re.fullmatch(
        r"(.+?)\s+((?:\d+(?:[.,]\d+)?|a|an)\s+"
        r"(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago)",
        text, re.I)
    return (found.group(1).strip(), found.group(2)) if found else (text, '')


def normalize_comment_identity(item: dict) -> dict:
    """Read legacy rows safely without changing keys, drafts or delivery receipts."""
    result = dict(item)
    author, age = split_comment_author(result.get('author', ''))
    result['author'] = author
    if age and not result.get('when_text'):
        result['when_text'] = age
    if 'body' in result:
        result['body'] = clean_comment_body(result['body'], author)
    return result


def parse_comment_label(label: str) -> dict | None:
    """แกะป้าย aria-label — คืน None ถ้าไม่ใช่ป้ายของคอมเมนต์ (เช่นตัวโพสต์)"""
    text = (label or "").strip()
    if not text:
        return None
    match = _LABEL_REPLY.match(text)
    if match:
        author, author_age = split_comment_author(match.group(1))
        target, age = split_comment_author(match.group(2))
        target = re.sub(r"'s comment$", '', target).strip()
        return {"author": author, "reply_to": target,
                "when_text": (match.group(3) or age or author_age).strip()}
    match = _LABEL_COMMENT.match(text)
    if match:
        author, age = split_comment_author(match.group(1))
        return {"author": author, "reply_to": "",
                "when_text": (match.group(2) or age).strip()}
    return None


_COMMENT_AGE = re.compile(
    r"^\s*(?:เมื่อ\s*)?((?:\d+(?:[.,]\d+)?)|a|an)\s*"
    r"(วินาที|นาที|ชั่วโมง|ชม\.?|วัน|สัปดาห์|เดือน|ปี|"
    r"s|m|h|d|w|y|min|mins|hr|hrs|hour|hours|day|days|week|weeks)"
    r"(?:\s*(?:ที่แล้ว|ago))?\s*$", re.I)
_COMMENT_AGE_HOURS = {
    "วินาที": 1 / 3600, "s": 1 / 3600,
    "นาที": 1 / 60, "m": 1 / 60, "min": 1 / 60, "mins": 1 / 60,
    "ชั่วโมง": 1, "ชม": 1, "ชม.": 1, "h": 1, "hr": 1, "hrs": 1,
    "hour": 1, "hours": 1,
    "วัน": 24, "d": 24, "day": 24, "days": 24,
    "สัปดาห์": 24 * 7, "w": 24 * 7, "week": 24 * 7, "weeks": 24 * 7,
    "เดือน": 24 * 30, "ปี": 24 * 365, "y": 24 * 365,
}


def comment_age_hours(when_text: str) -> float | None:
    """แปลงป้ายเวลา Facebook เป็นชั่วโมง; อ่านไม่ได้ต้องคืน None ไม่เดา.

    โหมดลิงก์เจาะจงใช้ค่านี้เพื่อไม่ดึงคอมเมนต์เก่าเข้าคิวโดยบังเอิญ เมื่อ
    Facebook เปลี่ยนข้อความเวลาเป็นรูปแบบที่เราไม่รู้จัก การข้ามปลอดภัยกว่า
    การเหมารวมว่าเป็นคอมเมนต์ใหม่.
    """
    text = " ".join(str(when_text or "").strip().split())
    if not text:
        return None
    if text.casefold() in {"เมื่อสักครู่", "just now", "now"}:
        return 0.0
    if text.casefold() in {"เมื่อวาน", "เมื่อวานนี้", "yesterday"}:
        return 24.0
    found = _COMMENT_AGE.match(text)
    if not found:
        return None
    try:
        raw_amount = found.group(1).casefold()
        amount = 1.0 if raw_amount in {"a", "an"} else float(raw_amount.replace(",", "."))
    except ValueError:
        return None
    unit = found.group(2).casefold()
    return amount * _COMMENT_AGE_HOURS[unit]


# บรรทัดที่ไม่ใช่เนื้อคอมเมนต์ — ปุ่มท้ายกล่อง ป้ายสถานะ และตัวคั่น
_JUNK_LINES = {
    "·", "•", "ตอบกลับ", "แชร์", "ถูกใจ", "แก้ไขแล้ว", "ดูคำแปล",
    "Reply", "Share", "Like", "Edited", "See translation",
    "ติดตาม", "· ติดตาม", "Follow", "· Follow",
    "ผู้มีส่วนร่วมดาวเด่น", "Top contributor", "ผู้เขียน", "Author",
    "ผู้ดูแล", "Admin", "สมาชิกใหม่", "New member",
}
_TIME_LINE = re.compile(
    r"^(?:เมื่อสักครู่|Just now|(?:\d+(?:[.,]\d+)?|a|an)\s*(?:วินาที|นาที|ชั่วโมง|ชม\.?|วัน|สัปดาห์|เดือน|ปี"
    r"|s|m|h|d|w|y|min|mins|hr|hrs|hour|hours|day|days|week|weeks)"
    r"(?:ที่แล้ว| ago)?)$", re.I)
# หัวการ์ดพรีวิวลิงก์ — โดเมนตัวพิมพ์ใหญ่ล้วน เช่น "S.SHOPEE.CO.TH"
# การ์ดอยู่ท้ายคอมเมนต์เสมอ เจอเมื่อไรตัดตั้งแต่ตรงนั้นถึงจบได้เลย
_LINK_CARD = re.compile(r"^[A-Z0-9][A-Z0-9.\-]*\.[A-Z]{2,}$")
_COUNT_LINE = re.compile(r"^\d[\d,]*$")


def clean_comment_body(text: str, author: str) -> str:
    """เอาเนื้อคอมเมนต์จริงออกมา — ตัดชื่อคน เวลา ปุ่ม และการ์ดพรีวิวลิงก์ทิ้ง"""
    author, _ = split_comment_author(author)
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
        # ตัวเลขเดี่ยวท้ายข้อความเป็นยอดความรู้สึก; ถ้าคอมเมนต์จริงมีแค่ "1"
        # จะยังเก็บ เพราะก่อนหน้านั้นยังไม่มีเนื้อหาใน kept
        if kept and _COUNT_LINE.fullmatch(line):
            continue
        kept.append(line)
    return (chr(10).join(kept)).strip()


def _person_key(name: str) -> str:
    """ชื่อสำหรับเทียบเจ้าของคอมเมนต์ โดยไม่สนตัวพิมพ์/ช่องว่างซ้ำ"""
    return " ".join(split_comment_author(name)[0].casefold().split())


def _is_profile_author(author: str, account: str) -> bool:
    """ป้ายชื่อบน Facebook เป็นโปรไฟล์เจ้าของโพสต์นี้หรือไม่"""
    who, me = _person_key(author), _person_key(account)
    return bool(who and me and (who == me or who in me or me in who))


def _comment_signature(author: str, body: str) -> tuple[str, str]:
    """ตัวตนคอมเมนต์สำหรับซิงก์รอบใหม่ โดยตัด metadata ที่ Facebook เปลี่ยนได้.

    Facebook เติม/เอาออกคำว่า ``ติดตาม`` และเลขยอดความรู้สึกใน ``inner_text``
    ได้ตลอดเวลา ถ้าใช้ข้อความดิบนั้นเป็นกุญแจ คอมเมนต์เดียวกันจะกลายเป็นหลาย
    แถวและเวลาเก่าค้างบนหน้าเว็บ จึงต้องทำความสะอาดทั้งข้อมูลใหม่และข้อมูลเก่า
    ก่อนเทียบทุกครั้ง.
    """
    cleaned = clean_comment_body(str(body or ""), str(author or ""))
    return _person_key(author), " ".join(cleaned.casefold().split())


_COMMENT_REPLY_TEXT_COLUMNS = (
    "reply_draft", "reply_saved_at", "reply_sent_at", "reply_queued_at",
    "reply_attempted_at", "reply_error", "ignored_at", "reply_submitted_at",
    "followup_draft", "followup_queued_at", "followup_attempted_at",
    "followup_submitted_at", "followup_sent_at", "followup_error",
)


def _comment_state_score(row: sqlite3.Row | dict) -> tuple[int, ...]:
    """เลือกแถวหลักที่มีสถานะจากคน/มือถือครบที่สุดตอนรวมรายการซ้ำ."""
    return (
        1 if row["followup_sent_at"] else 0,
        1 if row["followup_submitted_at"] else 0,
        1 if row["followup_queued_at"] else 0,
        1 if row["reply_sent_at"] else 0,
        int(bool(row["answered"])),
        1 if row["reply_queued_at"] else 0,
        1 if row["reply_draft"] else 0,
        int(bool(row["ignored"])),
        1 if row["reply_attempted_at"] else 0,
        1 if not split_comment_author(row["author"])[1] else 0,
    )


def _answered_comment_indexes(items: list[dict], account: str) -> set[int]:
    """หาคอมเมนต์ชั้นบนที่โปรไฟล์นี้ตอบแล้วจากลำดับกระทู้บนหน้าจริง

    ป้ายคำตอบของ Facebook ให้เพียงชื่อคนที่ถูกตอบ ไม่มี comment id ดังนั้นต้อง
    ผูกกับคอมเมนต์ชื่อเดียวกันที่อยู่ใกล้ก่อนหน้าที่สุดในกระทู้ ไม่ใช่ทำแบบเดิม
    ที่เห็นคำตอบต่อ ``Alice`` หนึ่งครั้งแล้วเหมาว่าทุกข้อความของ Alice ตอบหมด
    """
    latest: dict[str, int] = {}
    answered: set[int] = set()
    for index, item in enumerate(items):
        author = str(item.get("author") or "")
        reply_to = str(item.get("reply_to") or "")
        if not reply_to:
            if not _is_profile_author(author, account):
                key = _person_key(author)
                if key:
                    latest[key] = index
            continue
        if _is_profile_author(author, account):
            parent = latest.get(_person_key(reply_to))
            if parent is not None:
                answered.add(parent)
    return answered


# --------------------------------------------------------------------- บันทึก

def _save_unprotected(conn: sqlite3.Connection, post: dict, result: dict,
                      max_comment_age_hours: float | None = None) -> tuple[int, int]:
    """เก็บผลลงฐาน — คืน (**คอมเมนต์ของคนอื่น**ที่เพิ่งเห็น, คอมเมนต์ทั้งหมด)

    **นับเฉพาะของคนอื่น** (แก้ 29 ส.ค. 2569) — ของเดิมนับรวมคอมเมนต์ที่บอทเรา
    พิมพ์เอง ผลคือรอบแรกหลังโพสต์แจ้งว่า "คอมเมนต์ใหม่ 10 อัน" ทั้งที่ทั้ง 10 อัน
    เป็นของเราเอง ส่วนของคนอื่นมีแค่ 2 อัน — เจ้าของจะเข้าใจว่ามีคน 10 คน
    รอให้ไปตอบ

    เหตุผลที่ตัวเลขนี้ต้องหมายถึงของคนอื่นเท่านั้น: มันถูกใช้ตัดสินว่า
    "มีอะไรต้องไปตอบไหม" ซึ่งคอมเมนต์ของตัวเองไม่เกี่ยวเลย
    """
    now = datetime.now().isoformat(timespec="seconds")
    if result.get("comments_snapshot_complete") is False:
        result = dict(result)
        result["note"] = result.get("note") or "เก็บยังไม่ครบ — รักษาข้อมูลเดิมไว้"
        previous = conn.execute(
            "SELECT reactions, comments, shares FROM my_post WHERE post_url=? "
            "ORDER BY id DESC LIMIT 1", (post["post_url"],)).fetchone()
        for field in ("reactions", "comments", "shares"):
            result[field] = previous[field] if previous else None
    conn.execute(
        """INSERT INTO my_post (post_url, group_id, group_name, account,
                                reactions, comments, shares, reachable, note, checked_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (post["post_url"], post["group_id"], post["group_name"], post["account"],
         result.get("reactions"), result.get("comments"), result.get("shares"),
         1 if result.get("reachable") else 0, result.get("note", ""), now))

    if result.get("comments_snapshot_complete") is False:
        # A partial observation must not replace text, reply state, or old rows.
        total = conn.execute("SELECT COUNT(*) FROM my_comment WHERE post_url=?",
                             (post["post_url"],)).fetchone()[0]
        conn.commit()
        return 0, total

    items = result.get("comments_list") or []
    for item in items:
        item.update(normalize_comment_identity(item))
    account = str(post.get("account") or "").strip()
    answered_indexes = _answered_comment_indexes(items, account)

    # โหลดภาพเดิมทั้งหมดครั้งเดียว แล้วจับกลุ่มด้วยข้อความที่ทำความสะอาดแล้ว
    # เพื่อให้รอบ 6 ชั่วโมงเป็นการซิงก์/อัปเดต ไม่ใช่สะสม snapshot เก่าซ้ำไปมา.
    existing_rows = conn.execute(
        "SELECT * FROM my_comment WHERE post_url=?",
        (post["post_url"],)).fetchall()
    existing_by_signature: dict[tuple[str, str], list[sqlite3.Row | dict]] = {}
    for old in existing_rows:
        signature = _comment_signature(old["author"], old["body"])
        existing_by_signature.setdefault(signature, []).append(old)

    fresh = 0
    saved_total = 0
    # รายการที่เห็นใน snapshot รอบนี้จริง ๆ ใช้ลบภาพเก่าที่ Facebook ไม่ได้แสดงแล้ว
    # ห้ามใช้ ``last_seen`` เทียบเวลา เพราะสองรอบที่เกิดในวินาทีเดียวกันเป็นไปได้
    # และ key เดิมอาจถูกเลือกเป็น survivor เพื่อรักษาคิวตอบ/ข้อความที่พิมพ์ไว้.
    current_keys: set[str] = set()
    for index, item in enumerate(items):
        age = comment_age_hours(item.get("when_text", ""))
        eligible = (max_comment_age_hours is None
                    or (age is not None and age <= max_comment_age_hours))
        item["_age_eligible"] = eligible
        if not eligible:
            continue
        author = str(item.get("author") or "")
        body = clean_comment_body(str(item.get("body") or ""), author)
        item["body"] = body
        if not body:
            continue
        saved_total += 1
        # กุญแจต้องไม่ผูกกับลำดับ — คอมเมนต์ใหม่แทรกเข้ามาแล้วลำดับขยับทั้งแถว
        # ของเดิมใช้ลำดับ จึงนับคอมเมนต์เดิมเป็นของใหม่ทุกครั้งที่มีคนมาคอมเมนต์เพิ่ม
        key = f"{post['post_url']}#{author[:40]}#{body[:60]}"
        ours = 1 if _is_profile_author(author, account) else 0
        detected_answered = 1 if (not ours and index in answered_indexes) else 0
        signature = _comment_signature(author, body)
        candidates = existing_by_signature.get(signature, [])
        if candidates:
            # สถานะที่ผู้ใช้พิมพ์/สั่งคิว/มือถือส่งแล้วต้องไม่หายเมื่อรวมแถวซ้ำ
            # และ answered ห้ามย้อนจาก 1 เป็น 0 เพียงเพราะ Facebook ซ่อน reply
            # ในรอบล่าสุด.
            survivor = max(candidates, key=_comment_state_score)
            key = str(survivor["comment_key"])
            ordered = sorted(candidates, key=_comment_state_score, reverse=True)
            preserved = {
                column: next((str(row[column] or "") for row in ordered
                              if row[column]), "")
                for column in _COMMENT_REPLY_TEXT_COLUMNS
            }
            followup_due_at = next(
                (float(row["followup_due_at"] or 0) for row in ordered
                 if row["followup_due_at"]), 0.0)
            followup_delay = next(
                (int(row["followup_delay_seconds"] or 0) for row in ordered
                 if row["followup_delay_seconds"]), 0)
            answered = int(bool(
                detected_answered
                or preserved["reply_sent_at"]
                or any(row["answered"] for row in candidates)
            ))
            merged_ours = int(bool(ours or any(row["is_ours"] for row in candidates)))
            if preserved["reply_submitted_at"] and not preserved["reply_sent_at"]:
                answered = 0  # generic collector replies cannot confirm this exact dispatch
            ignored = int(any(row["ignored"] for row in candidates))
            first_seen = min(
                (str(row["first_seen"]) for row in candidates if row["first_seen"]),
                default=now,
            )
            conn.execute(
                """UPDATE my_comment
                      SET last_seen=?, account=?, seq=?, author=?, body=?, when_text=?,
                          reply_to=?, is_ours=?, answered=?, first_seen=?,
                          reply_draft=?, reply_saved_at=?, reply_sent_at=?,
                          reply_queued_at=?, reply_attempted_at=?, reply_error=?,
                          ignored=?, ignored_at=?, reply_submitted_at=?,
                          followup_draft=?, followup_queued_at=?, followup_due_at=?,
                          followup_delay_seconds=?, followup_attempted_at=?,
                          followup_submitted_at=?, followup_sent_at=?, followup_error=?
                    WHERE comment_key=?""",
                (now, account, item.get("seq"), author, body,
                 item.get("when_text", ""), item.get("reply_to", ""),
                 merged_ours, answered, first_seen,
                 preserved["reply_draft"], preserved["reply_saved_at"],
                 preserved["reply_sent_at"], preserved["reply_queued_at"],
                 preserved["reply_attempted_at"], preserved["reply_error"],
                 ignored, preserved["ignored_at"], preserved["reply_submitted_at"],
                 preserved["followup_draft"], preserved["followup_queued_at"],
                 followup_due_at, followup_delay,
                 preserved["followup_attempted_at"],
                 preserved["followup_submitted_at"],
                 preserved["followup_sent_at"], preserved["followup_error"], key))
            duplicate_keys = [str(row["comment_key"]) for row in candidates
                              if str(row["comment_key"]) != key]
            if duplicate_keys:
                conn.executemany(
                    "DELETE FROM my_comment WHERE comment_key=?",
                    [(old_key,) for old_key in duplicate_keys])
            # ถ้าหน้าเดียวกันมีรายการซ้ำจาก DOM รอบนี้ รายการถัดไปต้องอัปเดต
            # แถวที่เพิ่งรวม ไม่ย้อนกลับไปใช้แถว legacy ที่ลบแล้ว.
            current = dict(survivor)
            current.update({
                "comment_key": key, "account": account,
                "seq": item.get("seq"), "author": author, "body": body,
                "when_text": item.get("when_text", ""),
                "reply_to": item.get("reply_to", ""), "is_ours": merged_ours,
                "answered": answered, "first_seen": first_seen,
                "last_seen": now, "ignored": ignored, **preserved,
            })
            existing_by_signature[signature] = [current]
            current_keys.add(key)
            item["_answered"] = bool(answered)
            continue
        answered = detected_answered
        # ให้ผู้เรียกใช้กรองรายการแจ้งเตือนรอบนี้จากผลเดียวกัน ไม่ต้องเดาซ้ำ
        item["_answered"] = bool(answered)
        conn.execute(
            """INSERT INTO my_comment (comment_key, post_url, account, seq, author, body,
                                       when_text, reply_to, is_ours, answered,
                                       first_seen, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (key, post["post_url"], account, item["seq"], author, item["body"],
             item.get("when_text", ""), item.get("reply_to", ""),
             ours, answered, now, now))
        new_row = {
            # A duplicate can appear twice in the same Facebook snapshot.  The
            # second copy immediately becomes a merge candidate, so this
            # in-memory row must have the same state columns as a SQLite row.
            **{column: "" for column in _COMMENT_REPLY_TEXT_COLUMNS},
            "comment_key": key, "post_url": post["post_url"],
            "account": account, "seq": item.get("seq"), "author": author,
            "body": body, "when_text": item.get("when_text", ""),
            "reply_to": item.get("reply_to", ""), "is_ours": ours,
            "answered": answered, "first_seen": now, "last_seen": now,
            "reply_draft": "", "reply_saved_at": "", "reply_sent_at": "",
            "reply_queued_at": "", "reply_attempted_at": "",
            "reply_error": "", "ignored": 0, "ignored_at": "", "reply_submitted_at": "",
            "followup_due_at": 0.0, "followup_delay_seconds": 0,
        }
        existing_by_signature[signature] = [new_row]
        current_keys.add(key)
        if not ours and not answered:
            fresh += 1          # ของเราเองไม่นับ — ไม่มีอะไรต้องไปตอบ

    # รอบรีเฟรชคือ snapshot ของหน้า Facebook ปัจจุบัน ไม่ใช่ event stream.
    # ของเดิมทำแค่ upsert จึงทิ้งแถวจากรอบก่อนค้างถาวร เช่นชื่อเดียวกันถูกอ่านเป็น
    # ``จินดา วิลัยพล 10 hours ago`` และรอบถัดไปเป็น ``... 12 hours ago`` หน้าเว็บ
    # จึงเห็นคนเดียวสองครั้งทั้งที่โพสต์จริงมีครั้งเดียว. เมื่อตัวอ่านทำงานครบ ให้
    # ลบทุกแถวของโพสต์ที่ไม่อยู่ใน snapshot ใหม่ แต่ยังรักษาสถานะของแถวที่ match
    # อยู่ผ่าน survivor ด้านบน. ถ้าเข้าโพสต์ไม่ได้หรืออ่าน DOM ล้ม ห้ามลบ เพราะ
    # นั่นคือ "ยังไม่ได้ข้อมูล" ไม่ใช่ "หน้า Facebook ไม่มีคอมเมนต์".
    snapshot_complete = bool(result.get("reachable")) and bool(
        result.get("comments_snapshot_complete", True))
    if snapshot_complete:
        if current_keys:
            placeholders = ",".join("?" for _ in current_keys)
            conn.execute(
                f"DELETE FROM my_comment WHERE post_url=? "
                f"AND comment_key NOT IN ({placeholders}) "
                "AND NOT (COALESCE(reply_submitted_at,'')<>'' AND COALESCE(reply_sent_at,'')='')",
                (post["post_url"], *sorted(current_keys)),
            )
        else:
            conn.execute("DELETE FROM my_comment WHERE post_url=? "
                         "AND NOT (COALESCE(reply_submitted_at,'')<>'' AND COALESCE(reply_sent_at,'')='')",
                         (post["post_url"],))
    conn.commit()
    return fresh, saved_total


def save(conn: sqlite3.Connection, post: dict, result: dict,
         max_comment_age_hours: float | None = None) -> tuple[int, int]:
    """Save one snapshot and never leave a writer lock behind on failure.

    The collector intentionally reuses one connection across many browser
    pages.  Therefore any exception after the first INSERT must roll back
    before it can escape; otherwise that connection blocks the web feed and
    reply worker until the whole process is restarted.
    """
    try:
        return _save_unprotected(conn, post, result, max_comment_age_hours)
    except BaseException:
        conn.rollback()
        raise


# ----------------------------------------------------------------------- รอบเช็ค

# ยอดไม่ขยับนานเท่านี้ = **เสนอ** ให้เลิกเก็บ แต่ห้ามหยุดเอง
QUIET_HOURS = 24.0
# รวมไลก์+คอมเมนต์+แชร์เพิ่มไม่เกินหนึ่งใน 24 ชั่วโมง ถือว่าเปลี่ยนแปลงน้อย
QUIET_MAX_GROWTH = 1
def post_watch_key(post_url: str) -> str:
    """กุญแจสั้นสำหรับปุ่ม Telegram; ไม่ส่ง URL ยาวเกินเพดาน callback_data."""
    return hashlib.sha256(str(post_url).strip().encode("utf-8")).hexdigest()[:16]


def _watch_control(conn: sqlite3.Connection, post_url: str) -> dict:
    row = conn.execute(
        """SELECT active, stopped_at, stopped_by, keep_until, suggested_at,
                  decision_at
             FROM post_watch WHERE post_url=?""", (post_url,)).fetchone()
    if row is None:
        return {"active": True, "stopped_at": "", "stopped_by": "",
                "keep_until": "", "suggested_at": "", "decision_at": ""}
    out = dict(row)
    out["active"] = bool(out.get("active"))
    return out


def still_worth_watching(conn: sqlite3.Connection, post_url: str) -> tuple[bool, str]:
    """หยุดเฉพาะโพสต์ที่เจ้าของกดเลิกเก็บ; ยอดนิ่งเป็นเพียงข้อเสนอ."""
    state = _watch_control(conn, post_url)
    if state["active"]:
        return True, ""
    return False, (f"เจ้าของกดเลิกเก็บแล้ว {state.get('stopped_at') or ''}".strip())


def watch_status(conn: sqlite3.Connection, post_url: str,
                 now: datetime | None = None) -> dict:
    """สถานะติดตาม + ข้อเสนอจากยอดย้อนหลัง 24 ชม. สำหรับเว็บและ Telegram."""
    now = now or datetime.now()
    state = _watch_control(conn, post_url)
    result = {
        **state,
        "watch_key": post_watch_key(post_url),
        "suggest_stop": False,
        "suggest_reason": "",
        "delta_reactions": None,
        "delta_comments": None,
        "delta_shares": None,
        "span_hours": 0.0,
        "notify_suggestion": False,
    }
    if not state["active"]:
        return result
    try:
        keep_until = datetime.fromisoformat(str(state.get("keep_until") or ""))
    except ValueError:
        keep_until = None
    if keep_until and keep_until > now:
        result["suggest_reason"] = f"ผู้ใช้เลือกเก็บต่อถึง {keep_until:%d/%m %H:%M}"
        return result

    # โพสต์หายสองรอบติด = เสนอให้หยุด แต่ยังไม่หยุดเอง
    latest_any = conn.execute(
        """SELECT reachable, note FROM my_post
           WHERE post_url=? ORDER BY id DESC LIMIT 2""", (post_url,)).fetchall()
    if (len(latest_any) == 2
            and all(not row["reachable"] and (row["note"] or "") == GONE_NOTE
                    for row in latest_any)):
        result.update({"suggest_stop": True,
                       "suggest_reason": "เปิดโพสต์ไม่พบ 2 รอบติดกัน"})
    else:
        rows = conn.execute(
            """SELECT reactions, comments, shares, checked_at FROM my_post
               WHERE post_url=? AND reachable=1
                 AND COALESCE(note, '') NOT LIKE 'เก็บยังไม่ครบ%'
               ORDER BY id DESC LIMIT 400""",
            (post_url,)).fetchall()
        if len(rows) < 2:
            return result
        newest = rows[0]
        try:
            newest_at = datetime.fromisoformat(newest["checked_at"])
        except (ValueError, TypeError):
            return result
        cutoff = newest_at - timedelta(hours=QUIET_HOURS)
        older = None
        older_at = None
        for row in rows[1:]:
            try:
                when = datetime.fromisoformat(row["checked_at"])
            except (ValueError, TypeError):
                continue
            if when <= cutoff:
                older, older_at = row, when
                break
        if older is None or older_at is None:
            return result

        comparable = 0
        growth = 0
        for field in ("reactions", "comments", "shares"):
            new_value, old_value = newest[field], older[field]
            delta = None
            if isinstance(new_value, int) and isinstance(old_value, int):
                delta = new_value - old_value
                comparable += 1
                growth += max(0, delta)
            result[f"delta_{field}"] = delta
        result["span_hours"] = round(
            (newest_at - older_at).total_seconds() / 3600.0, 1)
        if not comparable or growth > QUIET_MAX_GROWTH:
            # ยอดกลับมาขยับจริง ให้ล้างธงแจ้งเก่าเพื่อเสนอใหม่ได้ในอนาคต
            if state.get("suggested_at"):
                conn.execute(
                    "UPDATE post_watch SET suggested_at='' WHERE post_url=?",
                    (post_url,))
                conn.commit()
                result["suggested_at"] = ""
            return result

        owed = conn.execute(
            """SELECT COUNT(*) FROM my_comment
               WHERE post_url=? AND is_ours=0 AND answered=0 AND TRIM(body)<>''
                 AND COALESCE(ignored,0)=0""", (post_url,)).fetchone()[0]
        if owed:
            result["suggest_reason"] = f"ยอดนิ่งแต่ยังมีคอมเมนต์รอตอบ {owed} รายการ"
            return result
        result["suggest_stop"] = True
        result["suggest_reason"] = (
            f"24 ชม. เพิ่มรวม {growth} "
            f"(ไลก์ {result['delta_reactions'] or 0:+d} · "
            f"คอมเมนต์ {result['delta_comments'] or 0:+d} · "
            f"แชร์ {result['delta_shares'] or 0:+d})")

    result["notify_suggestion"] = bool(
        result["suggest_stop"] and not state.get("suggested_at"))
    return result


def set_post_watch(*, post_url: str = "", watch_key: str = "",
                   active: bool, actor: str = "web", account: str = "") -> dict:
    """หยุด/เก็บต่อตามคำสั่งคน โดยไม่ลบประวัติหรือแก้ลิงก์ในใบงาน."""
    url = str(post_url or "").strip()
    key = str(watch_key or "").strip().lower()
    owner = str(account or "").strip()
    conn = open_db()
    try:
        if not url and key:
            candidates = [row[0] for row in conn.execute(
                """SELECT DISTINCT post_url FROM my_post
                    WHERE TRIM(post_url)<>'' AND (?='' OR account=?)""",
                (owner, owner))]
            url = next((item for item in candidates if post_watch_key(item) == key), "")
        if not url:
            raise ValueError("ไม่พบโพสต์ที่จะตั้งค่าการตามเก็บ")
        exists = conn.execute(
            """SELECT 1 FROM my_post WHERE post_url=?
                 AND (?='' OR account=?) LIMIT 1""", (url, owner, owner)).fetchone()
        if exists is None:
            raise ValueError("โพสต์นี้ยังไม่เคยถูก Bot8 เก็บข้อมูล")
        now = datetime.now()
        stopped_at = "" if active else now.isoformat(timespec="seconds")
        keep_until = ((now + timedelta(hours=QUIET_HOURS)).isoformat(timespec="seconds")
                      if active else "")
        conn.execute(
            """INSERT INTO post_watch
                   (post_url, active, stopped_at, stopped_by, keep_until,
                    suggested_at, decision_at)
               VALUES (?,?,?,?,?,'',?)
               ON CONFLICT(post_url) DO UPDATE SET
                   active=excluded.active,
                   stopped_at=excluded.stopped_at,
                   stopped_by=excluded.stopped_by,
                   keep_until=excluded.keep_until,
                   suggested_at='',
                   decision_at=excluded.decision_at""",
            (url, 1 if active else 0, stopped_at, str(actor or "")[:30],
             keep_until, now.isoformat(timespec="seconds")))
        conn.commit()
        return {"post_url": url, **watch_status(conn, url, now=now)}
    finally:
        conn.close()


def mark_suggestions_sent(watch_keys: list[str]) -> int:
    """จดเฉพาะข้อเสนอที่ Telegram ส่งสำเร็จ เพื่อไม่แจ้งซ้ำทุก 6 ชั่วโมง."""
    keys = {str(key).strip().lower() for key in watch_keys if str(key).strip()}
    if not keys:
        return 0
    conn = open_db()
    changed = 0
    stamp = datetime.now().isoformat(timespec="seconds")
    try:
        urls = [row[0] for row in conn.execute(
            "SELECT DISTINCT post_url FROM my_post WHERE TRIM(post_url)<>''")]
        for url in urls:
            if post_watch_key(url) not in keys:
                continue
            conn.execute(
                """INSERT INTO post_watch(post_url, active, suggested_at)
                   VALUES (?,1,?) ON CONFLICT(post_url) DO UPDATE SET
                   suggested_at=excluded.suggested_at""", (url, stamp))
            changed += 1
        conn.commit()
    finally:
        conn.close()
    return changed
def unanswered(limit: int = 20, account: str = "") -> list[dict]:
    """คอมเมนต์ของคนอื่นที่ **ยังไม่ได้ตอบ** พร้อมลิงก์โพสต์ที่มันอยู่

    **เจ้าของสั่ง 30 ส.ค. 2569** — *"คอมเมนต์ไหนที่ยังไม่ได้ตอบให้ส่งลิงก์โพสต์นั้น
    รายงานเข้า telegram"*

    ต่างจาก "คอมเมนต์ใหม่" ตรงที่ **ใบที่ตอบไปแล้วจะไม่โผล่ซ้ำ** — สิ่งที่เจ้าของ
    ต้องรู้คือ "เหลืออะไรให้ทำ" ไม่ใช่ "มีอะไรเข้ามาใหม่" คอมเมนต์ที่มาใหม่แล้ว
    ตอบไปแล้วในรอบเดียวกัน ไม่ควรไปกวนให้เสียเวลาเปิดดู

    ธง answered ตั้งจากป้ายบนหน้าจริง ("ข้อความตอบกลับจาก <เรา> ต่อความคิดเห็น
    ของ <เขา>") ไม่ได้เดา
    """
    conn = open_db()
    try:
        rows = conn.execute(
            """SELECT c.author, c.body, c.when_text, c.post_url,
                      COALESCE(c.account, '') AS account,
                      (SELECT group_name FROM my_post p WHERE p.post_url = c.post_url
                       ORDER BY p.id DESC LIMIT 1) AS group_name
               FROM my_comment c
               WHERE c.is_ours = 0 AND c.answered = 0 AND TRIM(c.body) <> ''
                 AND (? = '' OR c.account = ?)
                 AND COALESCE(c.ignored, 0) = 0
                 AND COALESCE(c.reply_queued_at, '') = ''
               ORDER BY c.first_seen DESC LIMIT ?""",
            (account.strip(), account.strip(), limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def _post_meta_by_link(account: str = "") -> dict[str, dict]:
    """ลิงก์โพสต์ → ของที่อยู่ในใบงานที่สร้างลิงก์นั้น

    เจ้าของสั่ง 15 ก.ย. 2569 — *"หน้าที่โชว์คอมเมนต์ ให้โชว์รูป กับแคปชันด้วย"*

    รูปไม่ได้เก็บอยู่ในแฟ้มคอมเมนต์ (เก็บแต่ข้อความ) จึงต้องย้อนไปหยิบจากใบงาน
    ที่โพสต์ลิงก์นั้นขึ้นไป แล้วส่ง **รหัสใบงานกับจำนวนรูป** ให้หน้าเว็บ ไม่ใช่
    ส่งไฟล์รูป — หน้าเว็บมีที่อยู่สำหรับดึงรูปของใบงานอยู่แล้ว
    (``/api/fb/jobs/<รหัส>/media/post/<ลำดับ>``)
    """
    out: dict[str, dict] = {}
    requested = str(account or "").strip().casefold()
    wanted = {name.strip().lower() for name in watched_accounts() if name.strip()}
    for owner in shared.known_accounts():
        owner_key = owner.strip().casefold()
        if requested and owner_key != requested:
            continue
        if wanted and owner.strip().lower() not in wanted:
            continue
        for job in _jobs_of(owner):
            shots = [x for x in (job.get("images") or [job.get("image", "")]) if x]
            comments = [str(x).strip() for x in
                        (job.get("comments") or [job.get("comment", "")])
                        if str(x or "").strip()]
            groups = []
            for group in (job.get("groups") or []):
                if isinstance(group, dict):
                    identity = str(group.get("group_id") or group.get("id")
                                   or group.get("name") or "").strip()
                else:
                    identity = str(group or "").strip()
                if identity and identity not in groups:
                    groups.append(identity)
            if not groups:
                for result in (job.get("results") or []):
                    identity = str(result.get("link_group_id")
                                   or result.get("group_id")
                                   or result.get("group_name") or "").strip()
                    if identity and identity not in groups:
                        groups.append(identity)
            meta = {
                "job_id": str(job.get("id") or ""),
                # ระบุเจ้าของข้อมูลไว้ใน payload ด้วย แม้ threads() จะกรองบัญชีแล้ว
                # เพื่อให้หน้าเว็บตรวจ/แสดงได้ชัด และกันการนำรายละเอียดข้ามโปรไฟล์.
                "job_account": owner,
                "caption": (job.get("caption") or "").strip(),
                "images": len(shots),
                "comment_images": len([x for x in (job.get("comment_images") or []) if x]),
                "job_status": str(job.get("status") or ""),
                "job_source": str(job.get("source") or ""),
                "job_created_at": str(job.get("created_at") or ""),
                "job_run_at": str(job.get("run_at") or ""),
                "job_started_at": str(job.get("started_at") or ""),
                "job_finished_at": str(job.get("finished_at") or ""),
                "job_comment_count": len(comments),
                "job_comment_texts": comments,
                "job_group_count": len(groups),
            }
            for result in (job.get("results") or []):
                link = str(result.get("link") or "").strip()
                if link:
                    out[link] = meta
    return out


# ใบงานหาไม่เจอ = **ไม่มีรูปให้ดู ไม่ใช่ "มีศูนย์ใบ"** — ส่งค่าว่างไปตรงๆ
# แล้วให้หน้าเว็บเป็นคนบอกเอง ดีกว่าแกล้งทำเป็นว่าโพสต์นั้นไม่มีรูป
_NO_META = {
    "job_id": "", "job_account": "", "caption": "", "images": 0,
    "comment_images": 0, "job_status": "", "job_source": "",
    "job_created_at": "", "job_run_at": "", "job_started_at": "",
    "job_finished_at": "", "job_comment_count": 0,
    "job_comment_texts": [], "job_group_count": 0,
}


def threads(limit: int = 40, only_pending: bool = True,
            account: str = "") -> list[dict]:
    """โพสต์พร้อมคอมเมนต์ใต้โพสต์ — เรียงแบบเดียวกับที่เห็นบน Facebook

    **เจ้าของสั่ง 13 ก.ย. 2569** — *"ช่องพิมพ์อยู่บนหน้าเว็บ ทำคล้ายๆ กับ
    โครงสร้างเฟสบุ๊ค โพสต์ - คอมเมนต์ใต้โพสต์"*

    ต่างจาก ``unanswered()`` ตรงที่ตัวนั้นคืนคอมเมนต์เดี่ยวๆ เรียงตามเวลา ซึ่ง
    เหมาะกับการแจ้งเตือนใน Telegram แต่พออ่านบนหน้าเว็บจะไม่เห็นว่าคอมเมนต์ไหน
    อยู่โพสต์ไหน และคนเดียวกันคอมเมนต์ในหลายกลุ่มจะดูเหมือนคนละคน

    ``only_pending`` จริง = เอาเฉพาะโพสต์ที่ยังมีคอมเมนต์ค้างให้ตอบ
    โพสต์ที่ตอบครบแล้วไม่ต้องมากินที่ — แต่ **คอมเมนต์ที่ตอบแล้วในโพสต์นั้น
    ยังส่งไปด้วย** เพราะต้องเห็นบริบททั้งกระทู้ถึงจะตอบได้ถูก
    """
    conn = open_db()
    try:
        posts = conn.execute(
            """SELECT p.post_url, p.group_id, p.group_name, p.account, p.reactions,
                      p.comments, p.shares, p.checked_at, p.note
                 FROM my_post p
                 JOIN (SELECT post_url, MAX(id) AS latest_id
                         FROM my_post WHERE TRIM(post_url)<>'' GROUP BY post_url) last
                   ON last.latest_id=p.id
                WHERE (?='' OR p.account=?)
                ORDER BY p.checked_at DESC""",
            (account.strip(), account.strip())).fetchall()

        rows = conn.execute(
            """SELECT comment_key, post_url, seq, author, body, when_text,
                      reply_to, is_ours, answered,
                      COALESCE(reply_draft, '')   AS reply_draft,
                      COALESCE(reply_saved_at,'') AS reply_saved_at,
                      COALESCE(reply_sent_at, '')   AS reply_sent_at,
                      COALESCE(reply_queued_at, '') AS reply_queued_at,
                      COALESCE(reply_attempted_at, '') AS reply_attempted_at,
                      COALESCE(reply_error, '') AS reply_error,
                      COALESCE(reply_submitted_at, '') AS reply_submitted_at,
                      COALESCE(followup_draft, '') AS followup_draft,
                      COALESCE(followup_queued_at, '') AS followup_queued_at,
                      COALESCE(followup_due_at, 0) AS followup_due_at,
                      COALESCE(followup_delay_seconds, 0) AS followup_delay_seconds,
                      COALESCE(followup_attempted_at, '') AS followup_attempted_at,
                      COALESCE(followup_submitted_at, '') AS followup_submitted_at,
                      COALESCE(followup_sent_at, '') AS followup_sent_at,
                      COALESCE(followup_error, '') AS followup_error,
                      first_seen
                 FROM my_comment
                WHERE TRIM(body) <> ''
                  AND COALESCE(ignored, 0) = 0
                ORDER BY post_url, seq""").fetchall()
        watch_by_post = {
            post["post_url"]: watch_status(conn, post["post_url"])
            for post in posts
        }
    finally:
        conn.close()

    by_post: dict[str, list[dict]] = {}
    for row in rows:
        by_post.setdefault(row["post_url"], []).append(dict(row))

    meta = _post_meta_by_link(account)

    # ยอดบนหัวกลุ่มต้องนับทุกโพสต์ที่ยังตามเก็บ ไม่ใช่นับเฉพาะโพสต์ที่รอตอบ
    # ซึ่งถูกกรองมาแสดงในโหมด pending เท่านั้น.
    def group_key(post) -> tuple[str, str, str]:
        identity = str(post["group_id"] or post["group_name"] or "").strip()
        job_id = str(meta.get(post["post_url"], _NO_META).get("job_id") or "")
        return str(post["account"] or "").strip(), job_id, identity

    group_totals: dict[tuple[str, str, str], int] = {}
    group_active: dict[tuple[str, str, str], int] = {}
    for post in posts:
        key = group_key(post)
        group_totals[key] = group_totals.get(key, 0) + 1
        state = watch_by_post.get(post["post_url"], {})
        if state.get("active", True):
            group_active[key] = group_active.get(key, 0) + 1

    out: list[dict] = []
    for post in posts:
        items = [normalize_comment_identity(c) for c in by_post.get(post["post_url"], [])]
        # **นับ "ค้าง" จากคอมเมนต์ของคนอื่นที่ยังไม่ได้ตอบเท่านั้น**
        # คอมเมนต์ของเราเองไม่ใช่ของค้าง และใบที่พิมพ์คำตอบไว้แล้วก็ยังค้างอยู่
        # จนกว่าบอทจะพิมพ์ลง Facebook จริง (ดู reply_sent_at)
        # **สามสถานะที่ห้ามยุบรวมกัน** (ข้อ 2.3.1)
        #   ค้าง      = ยังไม่มีใครตัดสินใจอะไรกับมัน  → ต้องทำอะไรสักอย่าง
        #   สั่งตอบแล้ว = เจ้าของกดตอบกลับแล้ว รอบอทไปพิมพ์ → ไม่ต้องทำอะไรต่อ
        #   ตอบแล้ว    = เห็นคำตอบบนหน้าจริงแล้ว
        # ถ้ายุบ "สั่งตอบแล้ว" เข้าไปในค้าง เจ้าของจะกดซ้ำเรื่อยๆ
        # ถ้ายุบเข้าไปในตอบแล้ว จะนึกว่าขึ้น Facebook ไปแล้วทั้งที่ยังไม่ขึ้น
        queued = [c for c in items
                  if not c["is_ours"] and c["reply_queued_at"] and not c["reply_sent_at"]]
        followup_queued = [c for c in items
                           if not c["is_ours"] and c["followup_queued_at"]
                           and not c["followup_sent_at"]]
        pending = [c for c in items
                   if not c["is_ours"] and not c["answered"]
                   and not c["reply_sent_at"] and not c["reply_queued_at"]]
        if only_pending and not pending and not queued and not followup_queued:
            continue
        out.append({
            **{k: post[k] for k in post.keys()},
            **meta.get(post["post_url"], _NO_META),
            **watch_by_post.get(post["post_url"], {}),
            "pending": len(pending),
            "queued": len(queued) + len(followup_queued),
            "group_active_posts": group_active.get(group_key(post), 0),
            "group_total_posts": group_totals.get(group_key(post), 0),
            "drafted": sum(1 for c in items
                           if c["reply_draft"] and not c["reply_sent_at"]
                           and not c["reply_queued_at"]),
            "comments_list": items,
        })
        if len(out) >= limit:
            break
    return out


def tracked_posts(account: str, group_id: str = "", group_name: str = "",
                  job_id: str = "") -> list[dict]:
    """All active snapshots in one account/group, independent of pending/limits.

    Read local data only; do not start collection or return comment drafts.
    Use the same latest-snapshot identity as threads() so its badge agrees.
    """
    account, group_id, group_name, job_id = (
        account.strip(), group_id.strip(), group_name.strip(), job_id.strip())
    conn = open_db()
    try:
        rows = conn.execute(
            """SELECT p.post_url, p.account, p.group_id, p.group_name, p.checked_at
                 FROM my_post p
                 JOIN (SELECT post_url, MAX(id) AS latest_id FROM my_post
                       WHERE TRIM(post_url)<>'' GROUP BY post_url) last
                   ON last.latest_id=p.id
                WHERE TRIM(p.account)=?
                  AND (?='' OR TRIM(COALESCE(NULLIF(p.group_id,''),p.group_name,''))=?)
                ORDER BY p.checked_at DESC""",
            (account, group_id or group_name, group_id or group_name)).fetchall()
        meta = _post_meta_by_link(account)
        result = []
        for row in rows:
            post_meta = meta.get(row["post_url"], _NO_META)
            meta_job = str(post_meta.get("job_id") or "")
            if job_id == "__unlinked__" and meta_job:
                continue
            if job_id and job_id != "__unlinked__" and meta_job != job_id:
                continue
            state = watch_status(conn, row["post_url"])
            if state.get("active", True):
                result.append({**dict(row), **post_meta, **state})
        return result
    finally:
        conn.close()


def set_job_watch(*, account: str, job_id: str, active: bool,
                  actor: str = "web") -> dict:
    """หยุด/เก็บต่อทุกโพสต์ในใบงานเดียวกัน โดยยืนยันเจ้าของบัญชีก่อน."""
    owner, wanted = str(account or "").strip(), str(job_id or "").strip()
    if not owner or not wanted:
        raise ValueError("ต้องระบุบัญชีและรหัสใบงาน")
    posts = tracked_posts(owner, job_id=wanted)
    if not posts and active:
        # tracked_posts คืนเฉพาะ active; ตอนเปิดกลับต้องอ่านรายการที่เคยเก็บทั้งหมด.
        posts = [post for post in threads(500, False, owner)
                 if str(post.get("job_id") or "") == wanted]
    if not posts:
        raise ValueError(f"ไม่พบโพสต์ของใบงาน {wanted} ในบัญชี {owner}")
    changed = []
    for post in posts:
        changed.append(set_post_watch(
            post_url=str(post.get("post_url") or ""), active=active, actor=actor,
            account=owner))
    return {"account": owner, "job_id": wanted, "changed": len(changed),
            "post_urls": [row["post_url"] for row in changed], "active": active}


def save_reply(comment_key: str, text: str) -> dict:
    """เก็บคำตอบที่เจ้าของพิมพ์ไว้ — **ยังไม่ส่ง** รอบอทเอาไปพิมพ์บนมือถือ

    ส่งข้อความว่างมา = ลบคำตอบที่เคยพิมพ์ไว้ทิ้ง

    **ไม่ตั้งธง answered ตรงนี้** เพราะ answered แปลว่า "เห็นคำตอบของเราบน
    หน้าจริงแล้ว" ซึ่งเป็นคนละเรื่องกับ "พิมพ์เตรียมไว้" — ถ้าตั้งตรงนี้
    คอมเมนต์จะหายไปจากรายการค้างทั้งที่ยังไม่มีอะไรขึ้น Facebook เลย
    (กติกาข้อ 2.3.1 — ป้ายสถานะต้องตรงกับความจริง)
    """
    key = str(comment_key or "").strip()
    if not key:
        raise ValueError("ไม่ได้บอกว่าจะตอบคอมเมนต์ไหน")
    body = str(text or "").strip()
    conn = open_db()
    try:
        found = conn.execute(
            "SELECT is_ours, reply_sent_at, reply_submitted_at, reply_draft FROM my_comment WHERE comment_key=?",
            (key,)).fetchone()
        if found is None:
            raise ValueError("ไม่พบคอมเมนต์นี้ — อาจถูกลบไปแล้ว")
        if found["reply_submitted_at"] and body != (found["reply_draft"] or ""):
            raise ValueError("ส่งแล้วแต่ยังยืนยันไม่ได้ — ห้ามแก้คำตอบจนตรวจผลเดิมเสร็จ")
        if found["is_ours"]:
            raise ValueError("คอมเมนต์นี้เป็นของเราเอง ไม่ต้องตอบ")
        if found["reply_sent_at"]:
            raise ValueError("คอมเมนต์นี้ตอบไปแล้วเมื่อ " + found["reply_sent_at"])
        conn.execute(
            """UPDATE my_comment
                  SET reply_draft=?, reply_saved_at=?
                WHERE comment_key=?""",
            (body, datetime.now().strftime("%Y-%m-%d %H:%M:%S") if body else "", key))
        conn.commit()
    finally:
        conn.close()
    return {"comment_key": key, "reply_draft": body,
            "message": "เก็บคำตอบไว้แล้ว — รอบอทเอาไปพิมพ์บนมือถือ"
                       if body else "ลบคำตอบที่เตรียมไว้แล้ว"}


def queue_reply(comment_key: str, text: str) -> dict:
    """เจ้าของกด "ตอบกลับ" — เก็บข้อความแล้ว **สั่งคิวให้บอทไปพิมพ์ตอบ**

    เจ้าของสั่ง 15 ก.ย. 2569 — *"1 ตอบกลับ คือ ไปตอบคอมเมนต์นั้น โดยตอบตามที่
    ผมพิมพ์"*

    **ยังไม่ใช่การส่งขึ้น Facebook** ตัวที่พิมพ์จริงคือบอทมือถือ (ขั้น ③ ตาม
    กติกาข้อ 2.7 ต้องกดบนจอจริงทุกจุด) ซึ่งยังไม่ได้สร้าง — ตรงนี้จดไว้ว่า
    "สั่งแล้ว" เฉยๆ ห้ามตั้ง ``reply_sent_at`` เด็ดขาด ไม่งั้นหน้าเว็บจะขึ้นว่า
    ส่งแล้วทั้งที่ยังไม่มีอะไรขึ้นไปเลย (ข้อ 2.3.1)
    """
    key = str(comment_key or "").strip()
    body = str(text or "").strip()
    if not key:
        raise ValueError("ไม่ได้บอกว่าจะตอบคอมเมนต์ไหน")
    if not body:
        raise ValueError("ยังไม่ได้พิมพ์คำตอบ — พิมพ์ก่อนแล้วค่อยกดตอบกลับ")
    save_reply(key, body)                      # ด่านตรวจทั้งหมดอยู่ในตัวนั้นแล้ว
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = open_db()
    try:
        conn.execute(
            """UPDATE my_comment
                  SET reply_queued_at=?, reply_error='', ignored=0
                WHERE comment_key=?""",
            (now, key))
        found = conn.execute(
            "SELECT COALESCE(account, '') account FROM my_comment WHERE comment_key=?",
            (key,)).fetchone()
        conn.commit()
    finally:
        conn.close()
    account = str(found["account"] or "").strip() if found else ""
    daily = reply_daily_status(account)
    message = ("เข้าคิวแล้ว — รอรอบ 24 ชั่วโมงรีเซ็ต คิวจะไม่หาย"
               if daily["waiting"] else
               "เข้าคิวแล้ว — บอทจะสุ่มตอบทีละรายการและเว้น 10–15 นาที")
    return {"comment_key": key, "reply_draft": body, "reply_queued_at": now,
            "account": account, "reply_daily": daily, "message": message}


def followup_key(comment_key: str) -> str:
    return f"{str(comment_key or '').strip()}{FOLLOWUP_KEY_SUFFIX}"


def _base_comment_key(queue_key: str) -> tuple[str, bool]:
    key = str(queue_key or "").strip()
    if key.endswith(FOLLOWUP_KEY_SUFFIX):
        return key[:-len(FOLLOWUP_KEY_SUFFIX)], True
    return key, False


def queue_followup(comment_key: str, text: str, *, now: float | None = None,
                   delay_seconds: int | None = None) -> dict:
    """Queue one second reply under the same parent, 1-5 minutes after reply 1.

    The random delay is chosen once and persisted.  If reply 1 is not confirmed
    yet, the countdown starts only when it is confirmed, so a restart or a slow
    verification can never make comment 2 overtake comment 1.
    """
    key = str(comment_key or "").strip()
    body = str(text or "").strip()
    if not key:
        raise ValueError("ไม่ได้บอกว่าจะเพิ่ม comment ต่อจากรายการไหน")
    if not body:
        raise ValueError("ยังไม่ได้พิมพ์ comment 2")
    current = time.time() if now is None else float(now)
    if delay_seconds is None:
        delay = random.SystemRandom().randint(
            FOLLOWUP_GAP_MIN_SECONDS, FOLLOWUP_GAP_MAX_SECONDS)
    else:
        delay = int(delay_seconds)
        if not FOLLOWUP_GAP_MIN_SECONDS <= delay <= FOLLOWUP_GAP_MAX_SECONDS:
            raise ValueError("ช่วงพัก comment 2 ต้องอยู่ระหว่าง 1–5 นาที")
    queued_at = datetime.fromtimestamp(current).isoformat(timespec="seconds")
    conn = open_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT is_ours, account, reply_queued_at, reply_sent_at,
                      followup_draft, followup_queued_at, followup_due_at,
                      followup_delay_seconds, followup_submitted_at,
                      followup_sent_at, followup_error
                 FROM my_comment WHERE comment_key=?""", (key,)).fetchone()
        if row is None:
            raise ValueError("ไม่พบคอมเมนต์แรก — อาจถูกลบไปแล้ว")
        if row["is_ours"]:
            raise ValueError("คอมเมนต์นี้เป็นของเราเอง จึงเพิ่มคำตอบต่อไม่ได้")
        if not row["reply_queued_at"] and not row["reply_sent_at"]:
            raise ValueError("ต้องกดตอบกลับ comment แรกเข้าคิวก่อน แล้วจึงเพิ่ม comment 2")
        if row["followup_sent_at"]:
            raise ValueError("comment 2 ส่งขึ้น Facebook แล้วเมื่อ " + row["followup_sent_at"])
        if row["followup_submitted_at"] and body != (row["followup_draft"] or ""):
            raise ValueError("comment 2 ส่งแล้วแต่ยังยืนยันไม่ได้ — ห้ามเปลี่ยนข้อความหรือส่งซ้ำ")
        already_queued = bool(row["followup_queued_at"] and not row["followup_error"])
        if already_queued and body != (row["followup_draft"] or ""):
            raise ValueError("comment 2 เข้าคิวแล้ว — ห้ามเปลี่ยนข้อความระหว่างรอ")
        if already_queued:
            queued_at = row["followup_queued_at"]
            due_at = float(row["followup_due_at"] or 0)
            delay = int(row["followup_delay_seconds"] or delay)
        else:
            due_at = current + delay if row["reply_sent_at"] else 0.0
            conn.execute(
                """UPDATE my_comment
                      SET followup_draft=?, followup_queued_at=?, followup_due_at=?,
                          followup_delay_seconds=?, followup_error=''
                    WHERE comment_key=?""",
                (body, queued_at, due_at, delay, key))
        conn.commit()
        account = str(row["account"] or "").strip()
    finally:
        conn.close()
    daily = reply_daily_status(account)
    return {
        "comment_key": key,
        "followup_key": followup_key(key),
        "followup_draft": body,
        "followup_queued_at": queued_at,
        "followup_due_at": due_at,
        "followup_due_at_text": (
            datetime.fromtimestamp(due_at).isoformat(timespec="seconds") if due_at else ""),
        "followup_delay_seconds": delay,
        "account": account,
        "reply_daily": daily,
        "message": ("เข้าคิว comment 2 แล้ว — จะเริ่มนับสุ่ม 1–5 นาที "
                    "หลัง comment แรกยืนยัน" if not due_at else
                    f"เข้าคิว comment 2 แล้ว — เริ่มได้ประมาณ "
                    f"{datetime.fromtimestamp(due_at):%H:%M:%S}"),
    }


def _collector_reply_confirmation(conn: sqlite3.Connection, row: sqlite3.Row,
                                  draft: str, queued_at: str) -> str:
    """Return positive browser-collector evidence time for one exact reply.

    The collector labels child rows with ``reply_to``.  That name alone is not
    enough when the same person commented twice, so confirmation requires one
    unique parent on the post plus one unique child from this account whose
    full saved text matches and was first seen after the queue request.
    """
    author = str(row['author'] or '').strip()
    expected = " ".join(str(draft or '').casefold().split())
    if not author or not expected:
        return ""
    parent_count = conn.execute(
        """SELECT COUNT(*) FROM my_comment
             WHERE post_url=? AND is_ours=0 AND account=?
               AND LOWER(TRIM(author))=LOWER(TRIM(?))""",
        (row['post_url'], row['account'], author),
    ).fetchone()[0]
    if parent_count != 1:
        return ""
    candidates = conn.execute(
        """SELECT author, body, first_seen
             FROM my_comment
            WHERE post_url=? AND account=? AND is_ours=1
              AND LOWER(TRIM(reply_to))=LOWER(TRIM(?))
            ORDER BY first_seen, comment_key""",
        (row['post_url'], row['account'], author),
    ).fetchall()
    prefix = " ".join(author.casefold().split())
    matches = []
    for child in candidates:
        if not _is_profile_author(str(child['author'] or ''), str(row['account'] or '')):
            continue
        actual = " ".join(str(child['body'] or '').casefold().split())
        if actual.startswith(prefix + " "):
            actual = actual[len(prefix):].strip()
        first_seen = str(child['first_seen'] or '')
        after_queue = not queued_at
        if queued_at and first_seen:
            try:
                after_queue = (datetime.fromisoformat(first_seen.replace(' ', 'T')) >=
                               datetime.fromisoformat(str(queued_at).replace(' ', 'T')))
            except ValueError:
                after_queue = False
        if actual == expected and after_queue:
            matches.append(first_seen)
    return matches[0] if len(matches) == 1 else ""


def retry_saved_reply(comment_key: str, account: str) -> dict:
    """Retry one saved answer atomically; never overwrite it from stale UI text."""
    if not comment_key or not account:
        raise ValueError('ต้องระบุคอมเมนต์และบัญชี')
    queue_key = str(comment_key).strip()
    key, is_followup = _base_comment_key(queue_key)
    conn = open_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM my_comment WHERE comment_key=? AND account=?',
                           (key, account)).fetchone()
        if row is None:
            raise ValueError('ไม่พบคอมเมนต์ในบัญชีนี้')
        if row['is_ours'] or row['ignored']:
            raise ValueError('รายการนี้เป็นของเราเองหรือถูกเพิกเฉยแล้ว')
        if is_followup:
            if not str(row['followup_draft'] or '').strip():
                raise ValueError('ยังไม่มี comment 2 ที่บันทึกไว้')
            if row['followup_sent_at']:
                return {
                    'comment_key': queue_key, 'parent_comment_key': key,
                    'queue_kind': 'followup', 'account': account,
                    'post_url': row['post_url'],
                    'reply_queued_at': row['followup_queued_at'] or '',
                    'reply_sent_at': row['followup_sent_at'],
                    'reply_submitted_at': row['followup_submitted_at'] or '',
                    'verification_only': False,
                    'message': 'comment 2 ยืนยันสำเร็จแล้ว',
                }
            collector_sent_at = _collector_reply_confirmation(
                conn, row, row['followup_draft'], row['followup_queued_at'])
            if collector_sent_at:
                conn.execute(
                    "INSERT OR IGNORE INTO reply_send_receipt VALUES (?, ?, ?, ?)",
                    (account, queue_key, queue_key, collector_sent_at),
                )
                conn.execute(
                    """UPDATE my_comment
                          SET followup_sent_at=?, followup_error=''
                        WHERE comment_key=?""",
                    (collector_sent_at, key),
                )
                conn.commit()
                return {
                    'comment_key': queue_key, 'parent_comment_key': key,
                    'queue_kind': 'followup', 'account': account,
                    'post_url': row['post_url'],
                    'reply_queued_at': row['followup_queued_at'] or '',
                    'reply_sent_at': collector_sent_at,
                    'reply_submitted_at': row['followup_submitted_at'] or '',
                    'verification_only': True, 'collector_confirmed': True,
                    'message': 'ยืนยัน comment 2 จากผลเก็บโพสต์แล้ว — ไม่ส่งซ้ำ',
                }
            queued_at = (row['followup_queued_at']
                         or datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            due_at = float(row['followup_due_at'] or 0)
            if not due_at and row['reply_sent_at']:
                due_at = time.time()
            conn.execute(
                """UPDATE my_comment
                      SET followup_queued_at=?, followup_due_at=?, followup_error=''
                    WHERE comment_key=?""",
                (queued_at, due_at, key),
            )
            conn.commit()
            submitted = row['followup_submitted_at'] or ''
            return {
                'comment_key': queue_key, 'parent_comment_key': key,
                'queue_kind': 'followup', 'account': account,
                'post_url': row['post_url'], 'reply_queued_at': queued_at,
                'reply_sent_at': '', 'reply_submitted_at': submitted,
                'verification_only': bool(submitted),
                'message': ('comment 2 เข้าคิวตรวจผลเท่านั้น ไม่ส่งซ้ำ'
                            if submitted else
                            'comment 2 เข้าคิวทำต่อด้วยข้อความที่บันทึกไว้แล้ว'),
            }
        if not row['reply_sent_at'] and row['answered']:
            collector_sent_at = _collector_reply_confirmation(
                conn, row, row['reply_draft'], row['reply_queued_at'])
            if not collector_sent_at:
                raise ValueError('รายการนี้มีคำตอบแล้ว กรุณาตรวจโพสต์ก่อน ไม่ส่งซ้ำ')
            conn.execute(
                "INSERT OR IGNORE INTO reply_send_receipt VALUES (?, ?, ?, ?)",
                (account, key, key, collector_sent_at),
            )
            conn.execute(
                """UPDATE my_comment
                      SET reply_sent_at=?, reply_error='', answered=1
                    WHERE comment_key=?""",
                (collector_sent_at, key),
            )
            conn.commit()
            return {
                'comment_key': key, 'account': account,
                'post_url': row['post_url'],
                'reply_queued_at': row['reply_queued_at'] or '',
                'reply_sent_at': collector_sent_at,
                'reply_submitted_at': row['reply_submitted_at'] or '',
                'verification_only': True, 'collector_confirmed': True,
                'message': 'ยืนยันคำตอบจากผลเก็บโพสต์แล้ว — ไม่ส่งซ้ำ',
            }
        if not str(row['reply_draft'] or '').strip():
            raise ValueError('ยังไม่มีคำตอบที่บันทึกไว้ กรุณาพิมพ์ในโพสต์ก่อน')
        queued_at = row['reply_queued_at'] or ''
        if not row['reply_sent_at']:
            queued_at = queued_at or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute("UPDATE my_comment SET reply_queued_at=?, reply_error='' WHERE comment_key=?",
                         (queued_at, key))
        conn.commit()
        return {'comment_key': key, 'account': account,
                'post_url': row['post_url'], 'reply_queued_at': queued_at,
                'reply_sent_at': row['reply_sent_at'] or '',
                'reply_submitted_at': row['reply_submitted_at'] or '',
                'verification_only': bool(row['reply_submitted_at']),
                'message': ('ยืนยันสำเร็จแล้ว' if row['reply_sent_at'] else
                            'เข้าคิวตรวจผลเท่านั้น ไม่ส่งซ้ำ' if row['reply_submitted_at'] else
                            'เข้าคิวทำต่อด้วยคำตอบที่บันทึกไว้แล้ว')}
    finally:
        conn.close()


def recover_interrupted_reply_checks() -> int:
    """Recover unfinished dispatches once, verification only; never clear receipts.

    Only an untouched dispatch-intent message is recoverable. A completed failed
    check stays stopped. Mark the attempt before queueing, bounding recovery even
    when the process dies again during verification.
    """
    conn = open_db()
    count = 0
    try:
        conn.execute('BEGIN IMMEDIATE')
        for prefix in ('reply', 'followup'):
            result = conn.execute(f"""
                UPDATE my_comment SET {prefix}_error='', {prefix}_attempted_at=?
                WHERE COALESCE({prefix}_submitted_at,'')<>''
                  AND COALESCE({prefix}_sent_at,'')=''
                  AND COALESCE({prefix}_queued_at,'')<>''
                  AND COALESCE({prefix}_attempted_at,'') < {prefix}_submitted_at
                  AND {prefix}_error IN (?, ?)
                  AND is_ours=0 AND COALESCE(ignored,0)=0
                """, (datetime.now().isoformat(timespec='seconds'),
                       'ส่งแล้วแต่ยังยืนยันไม่ได้ — ตรวจผลก่อน ห้ามส่งซ้ำ',
                       'เริ่มพยายามส่งแล้ว — รอตรวจผล ห้ามส่งซ้ำ'))
            count += result.rowcount
        conn.commit()
        return count
    finally:
        conn.close()


def queued_replies(limit: int = 10, account: str = "") -> list[dict]:
    """คิวที่มือถือยังไม่ได้ส่ง พร้อมตัวระบุคอมเมนต์และเจ้าของโพสต์ครบชุด"""
    conn = open_db()
    try:
        rows = conn.execute(
            """SELECT c.comment_key, c.post_url, c.account, c.author, c.body,
                      c.when_text, c.reply_draft, c.reply_queued_at,
                      COALESCE(c.reply_submitted_at, '') AS reply_submitted_at,
                      COALESCE(c.reply_attempted_at, '') AS reply_attempted_at,
                      COALESCE(c.reply_error, '') AS reply_error,
                      'first' AS queue_kind,
                      c.comment_key AS parent_comment_key,
                      (SELECT p.group_id FROM my_post p
                        WHERE p.post_url=c.post_url ORDER BY p.id DESC LIMIT 1) group_id,
                      (SELECT p.group_name FROM my_post p
                        WHERE p.post_url=c.post_url ORDER BY p.id DESC LIMIT 1) group_name
                 FROM my_comment c
                WHERE COALESCE(c.reply_queued_at, '') <> ''
                  AND COALESCE(c.reply_sent_at, '') = ''
                  AND COALESCE(c.reply_error, '') = ''
                  AND c.is_ours = 0 AND c.answered = 0
                  AND COALESCE(c.ignored, 0) = 0
                  AND (? = '' OR c.account = ?)
                ORDER BY c.reply_queued_at, c.comment_key
                LIMIT ?""", (account.strip(), account.strip(), max(1, int(limit))))
        followups = conn.execute(
            """SELECT (c.comment_key || ?) AS comment_key,
                      c.comment_key AS parent_comment_key,
                      c.post_url, c.account, c.author, c.body, c.when_text,
                      c.followup_draft AS reply_draft,
                      c.followup_queued_at AS reply_queued_at,
                      COALESCE(c.followup_submitted_at, '') AS reply_submitted_at,
                      COALESCE(c.followup_attempted_at, '') AS reply_attempted_at,
                      COALESCE(c.followup_error, '') AS reply_error,
                      'followup' AS queue_kind,
                      COALESCE(c.followup_due_at, 0) AS followup_due_at,
                      COALESCE(c.followup_delay_seconds, 0) AS followup_delay_seconds,
                      (SELECT p.group_id FROM my_post p
                        WHERE p.post_url=c.post_url ORDER BY p.id DESC LIMIT 1) group_id,
                      (SELECT p.group_name FROM my_post p
                        WHERE p.post_url=c.post_url ORDER BY p.id DESC LIMIT 1) group_name
                 FROM my_comment c
                WHERE COALESCE(c.followup_queued_at, '') <> ''
                  AND COALESCE(c.followup_sent_at, '') = ''
                  AND COALESCE(c.followup_error, '') = ''
                  AND COALESCE(c.reply_sent_at, '') <> ''
                  AND (COALESCE(c.followup_submitted_at, '') <> ''
                       OR COALESCE(c.followup_due_at, 0) <= ?)
                  AND c.is_ours = 0 AND COALESCE(c.ignored, 0) = 0
                  AND (? = '' OR c.account = ?)
                ORDER BY c.followup_due_at, c.comment_key
                LIMIT ?""",
            (FOLLOWUP_KEY_SUFFIX, time.time(), account.strip(), account.strip(),
             max(1, int(limit)))).fetchall()
        meta = _post_meta_by_link(account)
        out = []
        for row in [*rows, *followups]:
            item = normalize_comment_identity(dict(row))
            item.update(meta.get(item["post_url"], _NO_META))
            out.append(item)
        out.sort(key=lambda item: (
            str(item.get("reply_queued_at") or ""),
            str(item.get("comment_key") or "")))
        return out[:max(1, int(limit))]
    finally:
        conn.close()


def pick_random_reply(rows: list[dict], chooser=None) -> dict | None:
    """สุ่มหนึ่งรายการจากชุดคิวที่ผ่านด่านบัญชีและเวลาพักแล้ว."""
    if not rows:
        return None
    pick = chooser or random.SystemRandom().choice
    return pick(rows)


def reply_schedule_status(account: str, now: float | None = None) -> dict:
    """คืนเวลาที่โปรไฟล์นี้ส่งคิวถัดไปได้; ค่าอยู่รอดข้ามการรีสตาร์ต."""
    profile = str(account or "").strip()
    current = time.time() if now is None else float(now)
    root = shared.read_json(REPLY_SCHEDULE_FILE, {})
    accounts = root.get("accounts", {}) if isinstance(root, dict) else {}
    state = accounts.get(profile, {}) if isinstance(accounts, dict) else {}
    if not isinstance(state, dict):
        state = {}
    try:
        next_at = float(state.get("next_at") or 0)
    except (TypeError, ValueError):
        next_at = 0.0
    remaining = max(0, math.ceil(next_at - current))
    return {
        **state,
        "account": profile,
        "next_at": next_at,
        "wait_seconds": remaining,
        "waiting": remaining > 0,
    }


def _reply_daily_status_from_conn(conn: sqlite3.Connection, account: str,
                                  now: float | None = None) -> dict:
    """อ่านรอบ 24 ชม. ของโปรไฟล์จากฐานเดียวกับคิว เพื่อไม่ให้ตัวนับหลุดกัน."""
    profile = str(account or "").strip()
    current = time.time() if now is None else float(now)
    row = conn.execute(
        """SELECT window_started_at, used, last_sent_at, last_comment_key
             FROM reply_quota_window WHERE account=?""", (profile,)).fetchone()
    if row is None and profile:
        # เปิดใช้ฟีเจอร์กลางวันต้องไม่ลืมคำตอบที่ส่งสำเร็จไปก่อนรีสตาร์ต:
        # ย้อนเติมจาก reply_sent_at ภายใน 24 ชม. แล้วใช้รายการแรกเป็นต้นรอบ
        cutoff = datetime.fromtimestamp(
            current - REPLY_DAILY_WINDOW_SECONDS).isoformat(timespec="seconds")
        history = conn.execute(
            """SELECT comment_key, reply_sent_at
                 FROM my_comment
                WHERE account=? AND COALESCE(reply_sent_at, '') <> ''
                  AND REPLACE(reply_sent_at, ' ', 'T') >= ?
                ORDER BY REPLACE(reply_sent_at, ' ', 'T'), comment_key""",
            (profile, cutoff)).fetchall()
        if history:
            first_text = str(history[0]["reply_sent_at"] or "").replace(" ", "T")
            try:
                seeded_start = datetime.fromisoformat(first_text).timestamp()
            except ValueError:
                seeded_start = current
            last_text = str(history[-1]["reply_sent_at"] or "")
            last_key = str(history[-1]["comment_key"] or "")
            conn.execute(
                """INSERT OR IGNORE INTO reply_quota_window
                          (account, window_started_at, used, last_sent_at, last_comment_key)
                     VALUES (?, ?, ?, ?, ?)""",
                (profile, seeded_start, len(history), last_text, last_key))
            row = conn.execute(
                """SELECT window_started_at, used, last_sent_at, last_comment_key
                     FROM reply_quota_window WHERE account=?""", (profile,)).fetchone()
    started = float(row["window_started_at"] or 0) if row else 0.0
    used = max(0, int(row["used"] or 0)) if row else 0
    expires = started + REPLY_DAILY_WINDOW_SECONDS if started else 0.0
    if not started or current >= expires:
        # รอบหมดแล้วถือว่าใช้ 0 ทันที แต่ยังไม่เปิดรอบใหม่จนกว่าจะส่งสำเร็จจริง
        started = 0.0
        expires = 0.0
        used = 0
    remaining = max(0, REPLY_DAILY_LIMIT - used)
    wait = max(0, math.ceil(expires - current)) if remaining == 0 else 0
    return {
        "account": profile,
        "limit": REPLY_DAILY_LIMIT,
        "used": used,
        "remaining": remaining,
        "window_started_at": started,
        "window_started_at_text": (
            datetime.fromtimestamp(started).isoformat(timespec="seconds") if started else ""),
        "reset_at": expires,
        "reset_at_text": (
            datetime.fromtimestamp(expires).isoformat(timespec="seconds") if expires else ""),
        "wait_seconds": wait,
        "waiting": wait > 0,
        "last_sent_at": str(row["last_sent_at"] or "") if row and started else "",
        "last_comment_key": str(row["last_comment_key"] or "") if row and started else "",
    }


def reply_daily_status(account: str, now: float | None = None) -> dict:
    """สถานะเพดาน 50 คำตอบ/รอบ 24 ชม. แยกบัญชีและอยู่รอดข้ามรีสตาร์ต."""
    conn = open_db()
    try:
        status = _reply_daily_status_from_conn(conn, account, now)
        conn.commit()  # รวม lazy migration ของคำตอบ 24 ชม. ก่อนเปิดฟีเจอร์
        return status
    finally:
        conn.close()


def _consume_reply_daily(conn: sqlite3.Connection, comment_key: str, account: str,
                         now: float | None = None) -> dict:
    """นับหนึ่งครั้งหลังยืนยันคำตอบจริง; ผู้เรียกต้องอยู่ใน transaction เดียวกัน."""
    profile = str(account or "").strip()
    if not profile:
        raise ValueError("คิวตอบคอมเมนต์ไม่มีชื่อโปรไฟล์ จึงแยกเพดานไม่ได้")
    current = time.time() if now is None else float(now)
    status = _reply_daily_status_from_conn(conn, profile, current)
    if status["waiting"]:
        raise ValueError(
            f"{profile} ตอบครบ {REPLY_DAILY_LIMIT} รายการแล้ว ต้องรอรอบ 24 ชั่วโมงรีเซ็ต")
    started = status["window_started_at"] or current
    used = int(status["used"]) + 1
    sent_at = datetime.fromtimestamp(current).isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO reply_quota_window
                  (account, window_started_at, used, last_sent_at, last_comment_key)
             VALUES (?, ?, ?, ?, ?)
             ON CONFLICT(account) DO UPDATE SET
                  window_started_at=excluded.window_started_at,
                  used=excluded.used,
                  last_sent_at=excluded.last_sent_at,
                  last_comment_key=excluded.last_comment_key""",
        (profile, started, used, sent_at, str(comment_key or "")))
    return _reply_daily_status_from_conn(conn, profile, current)


def schedule_next_reply(comment_key: str, account: str,
                        now: float | None = None,
                        delay_seconds: int | None = None) -> dict:
    """สุ่มและบันทึกช่วงพัก 10–15 นาที แยกตามโปรไฟล์ที่เพิ่งส่งสำเร็จ."""
    profile = str(account or "").strip()
    if not profile:
        raise ValueError("คิวตอบคอมเมนต์ไม่มีชื่อโปรไฟล์")
    current = time.time() if now is None else float(now)
    if delay_seconds is None:
        delay = random.SystemRandom().randint(
            REPLY_GAP_MIN_SECONDS, REPLY_GAP_MAX_SECONDS)
    else:
        delay = int(delay_seconds)
        if not REPLY_GAP_MIN_SECONDS <= delay <= REPLY_GAP_MAX_SECONDS:
            raise ValueError("ช่วงพักตอบคอมเมนต์ต้องอยู่ระหว่าง 10–15 นาที")
    next_at = current + delay
    profile_state = {
        "scheduled_at": datetime.fromtimestamp(current).isoformat(timespec="seconds"),
        "next_at": next_at,
        "next_at_text": datetime.fromtimestamp(next_at).isoformat(timespec="seconds"),
        "delay_seconds": delay,
        "last_comment_key": str(comment_key or ""),
    }

    def update(root):
        if not isinstance(root, dict):
            root = {}
        accounts = root.get("accounts")
        if not isinstance(accounts, dict):
            accounts = {}
            root["accounts"] = accounts
        accounts[profile] = profile_state
        return root

    shared.update_json(
        REPLY_SCHEDULE_FILE, update, default={"accounts": {}},
        label=f"บันทึกเวลาพักตอบคอมเมนต์ {profile}")
    return {**profile_state, "account": profile,
            "wait_seconds": delay, "waiting": True}


def clear_reply_gap(account: str) -> dict:
    """ล้างช่วงพักรายคอมเมนต์ของโปรไฟล์นี้ — ให้คิวถัดไปส่งได้ทันที

    ใช้กับปุ่ม "เริ่มเลย" ที่เจ้าของสั่งเพิ่ม 20 ก.ย. 2569 เพื่อยิงคอมเมนต์แรก
    โดยไม่ต้องรอครบ 10–15 นาที

    **ล้างเฉพาะช่วงพักระหว่างคอมเมนต์ ไม่แตะโควตารายวัน** เพราะโควตาคือเพดาน
    ที่กันบัญชีโดนตีธง ส่วนช่วงพักเป็นแค่จังหวะให้ดูเป็นคนมากขึ้น
    กดข้ามได้เมื่อเจ้าของตัดสินใจเอง แต่เพดานห้ามข้าม
    """
    profile = str(account or "").strip()
    if not profile:
        raise ValueError("ไม่รู้ว่าจะล้างช่วงพักของโปรไฟล์ไหน")

    def update(root):
        if not isinstance(root, dict):
            root = {}
        accounts = root.get("accounts")
        if isinstance(accounts, dict):
            accounts.pop(profile, None)
        return root

    shared.update_json(
        REPLY_SCHEDULE_FILE, update, default={"accounts": {}},
        label=f"ล้างช่วงพักตอบคอมเมนต์ {profile}")
    return reply_schedule_status(profile)


def mark_reply_submitted(comment_key: str, expected_text: str | None = None) -> None:
    key, is_followup = _base_comment_key(comment_key)
    draft_column = "followup_draft" if is_followup else "reply_draft"
    submitted_column = "followup_submitted_at" if is_followup else "reply_submitted_at"
    sent_column = "followup_sent_at" if is_followup else "reply_sent_at"
    error_column = "followup_error" if is_followup else "reply_error"
    conn = open_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if expected_text is not None:
            current = conn.execute(
                f"SELECT {draft_column} AS draft FROM my_comment WHERE comment_key=?",
                (key,)).fetchone()
            if current is None or current["draft"] != expected_text:
                raise ValueError("คำตอบในคิวถูกเปลี่ยนระหว่างทำงาน — ไม่ส่งข้อความเก่า")
        cursor = conn.execute(
            f"UPDATE my_comment SET {submitted_column}=?, {error_column}=? "
            f"WHERE comment_key=? AND COALESCE({submitted_column},'')='' "
            f"AND COALESCE({sent_column},'')=''",
            (datetime.now().isoformat(timespec="seconds"),
             "เริ่มพยายามส่งแล้ว — รอตรวจผล ห้ามส่งซ้ำ", key))
        if cursor.rowcount != 1:
            raise ValueError("รายการนี้เคยเตรียมส่งแล้ว — ต้องตรวจผลก่อน")
        conn.commit()
    finally:
        conn.close()


def mark_reply_result(comment_key: str, sent: bool, error: str = "",
                      now: float | None = None) -> dict:
    """จดผลจากมือถือ; ตั้ง sent เฉพาะหลังตรวจว่าคำตอบขึ้น Facebook จริง"""
    queue_key = str(comment_key or "").strip()
    key, is_followup = _base_comment_key(queue_key)
    sent_column = "followup_sent_at" if is_followup else "reply_sent_at"
    submitted_column = "followup_submitted_at" if is_followup else "reply_submitted_at"
    attempted_column = "followup_attempted_at" if is_followup else "reply_attempted_at"
    error_column = "followup_error" if is_followup else "reply_error"
    current = time.time() if now is None else float(now)
    at = datetime.fromtimestamp(current).isoformat(timespec="seconds")
    conn = open_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        found = conn.execute(
            """SELECT comment_key, COALESCE(account, '') account,
                      COALESCE(reply_sent_at, '') reply_sent_at,
                      COALESCE(reply_submitted_at, '') reply_submitted_at,
                      COALESCE(followup_queued_at, '') followup_queued_at,
                      COALESCE(followup_due_at, 0) followup_due_at,
                      COALESCE(followup_delay_seconds, 0) followup_delay_seconds,
                      COALESCE(followup_sent_at, '') followup_sent_at,
                      COALESCE(followup_submitted_at, '') followup_submitted_at,
                      post_url, author, body, reply_error, followup_error
                 FROM my_comment WHERE comment_key=?""", (key,)).fetchone()
        if not found:
            raise ValueError("ไม่พบคอมเมนต์นี้")
        daily = None
        identity = queue_key
        previous_sent = str(found[sent_column] or "")
        if sent:
            receipt = conn.execute(
                "SELECT sent_at FROM reply_send_receipt WHERE account=? AND identity=?",
                (found["account"], identity)).fetchone()
            # Refresh can delete/recreate a row; its durable receipt prevents a second charge.
            if not previous_sent and receipt is None:
                daily = _consume_reply_daily(
                    conn, queue_key, str(found["account"] or ""), current)
            sent_at = (receipt["sent_at"] if receipt else previous_sent) or at
            conn.execute(
                "INSERT OR IGNORE INTO reply_send_receipt VALUES (?, ?, ?, ?)",
                (found["account"], identity, queue_key, sent_at))
            if is_followup:
                conn.execute(
                    """UPDATE my_comment
                          SET followup_attempted_at=?, followup_sent_at=?, followup_error=''
                        WHERE comment_key=?""", (at, sent_at, key))
            else:
                conn.execute(
                    """UPDATE my_comment
                          SET reply_attempted_at=?, reply_sent_at=?, reply_error='', answered=1
                        WHERE comment_key=?""", (at, sent_at, key))
                # Start comment 2's persisted 1-5 minute clock only after
                # comment 1 is confirmed on Facebook.
                if found["followup_queued_at"] and not found["followup_sent_at"] \
                        and not float(found["followup_due_at"] or 0):
                    delay = int(found["followup_delay_seconds"] or 0)
                    if not FOLLOWUP_GAP_MIN_SECONDS <= delay <= FOLLOWUP_GAP_MAX_SECONDS:
                        delay = random.SystemRandom().randint(
                            FOLLOWUP_GAP_MIN_SECONDS, FOLLOWUP_GAP_MAX_SECONDS)
                    conn.execute(
                        """UPDATE my_comment
                              SET followup_due_at=?, followup_delay_seconds=?
                            WHERE comment_key=?""", (current + delay, delay, key))
        else:
            submitted = str(found[submitted_column] or "")
            previous_error = str(found[error_column] or '')
            if 'FacebookRestricted:' in previous_error and 'FacebookRestricted:' not in str(error):
                cause = previous_error.split('FacebookRestricted:', 1)[1].split(' · ผลตรวจล่าสุด:', 1)[0]
                error = 'FacebookRestricted:' + cause + ' · ผลตรวจล่าสุด: ' + str(error)
            if submitted and not str(error).startswith("ส่งแล้วแต่ยังยืนยันไม่ได้"):
                error = "ส่งแล้วแต่ยังยืนยันไม่ได้ — ตรวจผลก่อน ห้ามส่งซ้ำ" + (f" · {error}" if error else "")
            conn.execute(
                f"""UPDATE my_comment
                       SET {attempted_column}=?, {error_column}=?
                     WHERE comment_key=? AND COALESCE({sent_column}, '')=''""",
                (at, str(error or "ส่งไม่สำเร็จ")[:500], key))
        conn.commit()
        if sent and daily is None:
            daily = _reply_daily_status_from_conn(
                conn, str(found["account"] or ""), current)
        return {"comment_key": queue_key, "parent_comment_key": key,
                "queue_kind": "followup" if is_followup else "first",
                "sent": bool(sent), "at": at,
                "reply_daily": daily,
                "error": "" if sent else str(error or "ส่งไม่สำเร็จ")[:500]}
    finally:
        conn.close()


def reply_states(comment_keys: list[str]) -> list[dict]:
    """สถานะล่าสุดของคอมเมนต์ที่หน้าเว็บกำลังแสดง.

    ใช้เป็น lightweight poll หลังบอทมือถือทำงาน: หน้าเว็บถามเฉพาะ key ที่
    มองเห็นอยู่ ไม่ต้องโหลดโพสต์/รูป/คอมเมนต์ทั้งหมดใหม่จนข้อความที่ผู้ใช้กำลัง
    พิมพ์หาย และยังไม่แตะ Facebook เพราะอ่านจาก SQLite ในเครื่องอย่างเดียว.
    """
    keys = list(dict.fromkeys(
        str(key or "").strip() for key in (comment_keys or [])
        if str(key or "").strip()
    ))[:500]
    if not keys:
        return []
    base_keys = list(dict.fromkeys(_base_comment_key(key)[0] for key in keys))
    placeholders = ",".join("?" for _ in base_keys)
    conn = open_db()
    try:
        rows = conn.execute(
            f"""SELECT comment_key, answered,
                       COALESCE(reply_sent_at, '') AS reply_sent_at,
                       COALESCE(reply_error, '') AS reply_error,
                       COALESCE(reply_submitted_at, '') AS reply_submitted_at,
                       COALESCE(reply_attempted_at, '') AS reply_attempted_at,
                       COALESCE(followup_draft, '') AS followup_draft,
                       COALESCE(followup_queued_at, '') AS followup_queued_at,
                       COALESCE(followup_due_at, 0) AS followup_due_at,
                       COALESCE(followup_delay_seconds, 0) AS followup_delay_seconds,
                       COALESCE(followup_sent_at, '') AS followup_sent_at,
                       COALESCE(followup_error, '') AS followup_error,
                       COALESCE(followup_submitted_at, '') AS followup_submitted_at,
                       COALESCE(followup_attempted_at, '') AS followup_attempted_at,
                       COALESCE(ignored, 0) AS ignored
                  FROM my_comment
                 WHERE comment_key IN ({placeholders})""",
            base_keys,
        ).fetchall()
        by_key = {str(row["comment_key"]): dict(row) for row in rows}
        out = []
        for requested in keys:
            base_key, is_followup = _base_comment_key(requested)
            row = by_key.get(base_key)
            if row is None:
                continue
            if is_followup:
                out.append({
                    "comment_key": requested,
                    "parent_comment_key": base_key,
                    "queue_kind": "followup",
                    "answered": int(bool(row["followup_sent_at"])),
                    "reply_sent_at": row["followup_sent_at"],
                    "reply_error": row["followup_error"],
                    "reply_submitted_at": row["followup_submitted_at"],
                    "reply_attempted_at": row["followup_attempted_at"],
                    "ignored": row["ignored"],
                })
            else:
                out.append(row)
        return out
    finally:
        conn.close()


def ignore_comment(comment_key: str, on: bool = True) -> dict:
    """เจ้าของกด "เพิกเฉย" — ไม่ตอบคอมเมนต์นี้ และไม่ต้องเอามาโชว์อีก

    เจ้าของสั่ง 15 ก.ย. 2569 — *"2 เพิกเฉย ก็คือไม่ต้องทำอะไรกับคอมเมนต์นั้น
    แล้วก็ไม่ต้องโชว์คอมเมนต์นั้นขึ้นมาอีก"*

    **เก็บไว้ในฐานข้อมูล ไม่ได้ลบทิ้ง** เพราะรอบเก็บถัดไปจะอ่านคอมเมนต์เดิม
    เจอใหม่ทุกครั้ง ถ้าลบก็จะกลับมาโผล่อีก — และเผื่อวันหลังเปลี่ยนใจ
    """
    key = str(comment_key or "").strip()
    if not key:
        raise ValueError("ไม่ได้บอกว่าจะเพิกเฉยคอมเมนต์ไหน")
    conn = open_db()
    try:
        found = conn.execute(
            "SELECT is_ours FROM my_comment WHERE comment_key=?", (key,)).fetchone()
        if found is None:
            raise ValueError("ไม่พบคอมเมนต์นี้ — อาจถูกลบไปแล้ว")
        conn.execute(
            "UPDATE my_comment SET ignored=?, ignored_at=? WHERE comment_key=?",
            (1 if on else 0,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S") if on else "", key))
        conn.commit()
    finally:
        conn.close()
    return {"comment_key": key, "ignored": bool(on),
            "message": "เพิกเฉยแล้ว — จะไม่เอาคอมเมนต์นี้มาโชว์อีก" if on
                       else "เอากลับมาโชว์แล้ว"}


def check_once(on_date: str = "", force: bool = False,
               posts_override: list[dict] | None = None,
               max_comment_age_hours: float | None = None,
               stop=None, progress=None) -> dict:
    """เช็คทุกโพสต์หนึ่งรอบ — หยุดที่ขอบโพสต์ได้เมื่อมีงาน Manual แทรก."""
    import random

    from playwright.sync_api import sync_playwright

    import fb_mass_finder as mf
    import fb_collect_gate as gate
    from bot_profiles import ProfileFarm

    if gate.state().get('needs_login') and not force:
        return {"posts": 0, "needs_login": True, "note": gate.state().get('note'),
                "incomplete": True, "retry_after": 3600}
    if not gate.wait_for_turn(stop, lambda message: log(message)):
        return {"posts": 0, "preempted": True, "incomplete": True}

    all_posts = list(posts_override) if posts_override is not None else our_posts(on_date=on_date)
    all_posts = _prioritize_collect_posts(all_posts)
    if not all_posts:
        log("ยังไม่มีโพสต์ที่มีลิงก์เก็บไว้ — ไม่มีอะไรให้เช็ค")
        return {"posts": 0}

    # รอบอัตโนมัติเท่านั้นที่ต้องต่อข้าม restart. คำสั่งเจาะวัน/เจาะลิงก์จากคน
    # เป็นคนละงานและต้องทำรายการที่สั่งครบเอง ไม่เอา checkpoint รอบเฝ้ามาปน.
    durable_cycle = not force and not on_date and posts_override is None
    cycle_state: dict = {}
    resumed_cycle = False
    posts = all_posts
    if durable_cycle:
        posts, cycle_state, resumed_cycle = _prepare_collect_cycle(all_posts)
        if not posts:
            _finish_collect_cycle(cycle_state)
            log("checkpoint รอบเดิมครบทุกโพสต์แล้ว — รอรอบ 6 ชั่วโมงถัดไป")
            return {
                "posts": 0, "rows": [], "ok": 0, "blocked": 0,
                "quiet": 0, "stopped": 0, "suggestions": [],
                "new_comments": 0, "profiles": {}, "on_date": on_date,
                "max_comment_age_hours": max_comment_age_hours,
                "preempted": False, "incomplete": False,
                "resumed_cycle": True, "cycle_total": len(all_posts),
                "remaining": 0,
            }

    farm = ProfileFarm(shared.DATA_DIR)
    entry = mf.find_bot(farm, COLLECTOR_PROFILE)
    conn = open_db()
    done = blocked = new_comments = stopped = 0
    preempted = False
    interrupted = False
    needs_login = False
    # เก็บรายละเอียดต่อใบไว้ให้คนเรียกเอาไปประกอบข้อความแจ้งเจ้าของ
    # (ตัว keeper ใน app.py ใช้ตัดสินว่ารอบนี้มีอะไรน่าบอกไหม)
    rows: list[dict] = []
    suggestions: list[dict] = []
    scope = f"ของวันที่ {on_date}" if on_date else "ตามช่วงเฝ้าปกติ"
    if durable_cycle and resumed_cycle:
        log(f"ต่อ checkpoint รอบเดิม — เหลือ {len(posts)}/{len(all_posts)} โพสต์ "
            f"ผ่านโปรไฟล์ {COLLECTOR_PROFILE}")
    else:
        log(f"เริ่มรอบเช็ค {scope} — โพสต์ {len(posts)} ใบ "
            f"ผ่านโปรไฟล์ {COLLECTOR_PROFILE}")
    job_touched = False

    def pause_after_job(post_index: int, report_progress) -> bool:
        """พักเกณฑ์เดิม 1–5 นาที เฉพาะหลังโพสต์สุดท้ายของใบงาน."""
        if not _collect_job_ends(posts, post_index):
            report_progress(
                "continuing", "บันทึกผลแล้ว · เก็บโพสต์ถัดไปในใบงานเดียวกัน",
                post_index + 1)
            return False
        # ไม่มีใบงานถัดไปก็ไม่มีเหตุให้พัก การพักหลังโพสต์สุดท้ายเคยทำให้คำสั่ง
        # Manual ที่ทำครบแล้วค้างสถานะ running อีก 1–5 นาที และขวางรอบอัตโนมัติ
        # ที่ต้องกลับไปเก็บใบของอีกบัญชี ทั้งที่ไม่มีการกระทำใดเหลืออยู่แล้ว.
        if post_index + 1 >= len(posts):
            report_progress(
                "complete", "เก็บครบทุกโพสต์ในใบงานแล้ว",
                post_index + 1)
            return False
        if not job_touched:
            report_progress(
                "skipped", "จบใบงานแล้ว · ไม่มีโพสต์ที่ต้องเปิดในใบนี้",
                post_index + 1)
            return False
        # งาน Manual ที่มาถึงพอดีหลังจบใบได้คิวทันที ไม่ต้องสร้าง gap ใหม่ขวาง.
        if stop and stop():
            return True
        delay = gate.reserve_gap(random.uniform(*BETWEEN_POSTS), scope="job")
        report_progress(
            "pacing", f"Bot8 พัก {int(delay)} วินาทีก่อนใบงานถัดไป (สุ่ม 1–5 นาที)",
            post_index + 1)
        rest_until = time.monotonic() + delay
        while time.monotonic() < rest_until:
            if stop and stop():
                return True
            time.sleep(min(0.5, max(0.0, rest_until - time.monotonic())))
        return False

    with sync_playwright() as playwright:
        browser = mf.launch_bot_browser(playwright, farm, entry)
        page = browser.new_page() if hasattr(browser, "new_page") else browser.pages[0]
        try:
            for index, post in enumerate(posts, 1):
                if index == 1 or _collect_job_key(posts[index - 2]) != _collect_job_key(post):
                    job_touched = False
                # งาน Manual แทรก: จบโพสต์ที่กำลังอ่านให้ข้อมูลไม่ครึ่งใบ
                # แล้วปิด Bot8 ก่อนเริ่มใบถัดไป คิวรอบนี้กลับมาต่อจาก checkpoint.
                if stop and stop():
                    preempted = True
                    log("  ⏸ พักรอบเก็บคอมเมนต์ที่จุดปลอดภัย — มีงาน Manual แทรก")
                    break
                def report_progress(phase: str, action: str,
                                    completed: int = index - 1) -> None:
                    if progress:
                        progress({
                            "phase": phase, "action": action,
                            "completed": completed, "total": len(posts),
                            "post_url": post.get("post_url", ""),
                            "caption": post.get("caption", ""),
                            "group_id": post.get("group_id", ""),
                            "group_name": post.get("group_name", ""),
                            "account": post.get("account", ""),
                        })

                report_progress("opening", "กำลังเปิดลิงก์โพสต์")
                label = f"{post['group_name'][:26]} ({post['account']})"
                # ปุ่มเลิกเก็บเป็นคำสั่งสูงสุด แม้รอบนี้มาจากคำสั่ง force/manual
                # ก็ห้ามเปิดลิงก์นั้นอีก จนกว่าผู้ใช้จะกดเก็บต่อเอง
                keep, why = still_worth_watching(conn, post["post_url"])
                if not keep:
                    stopped += 1
                    log(f"  💤 {label}: ผู้ใช้ปิดการตามเก็บ — {why}")
                    if durable_cycle:
                        _mark_collect_cycle_done(cycle_state, post)
                    report_progress("skipped", "ข้ามโพสต์ที่เลิกเก็บแล้ว", index)
                    if pause_after_job(index - 1, report_progress):
                        preempted = True
                        break
                    continue
                # ใช้ที่อยู่เต็มถ้าแปลงได้ — ลิงก์แชร์เด้งกลับหน้าฟีด
                target = canonical_url(post["post_url"]) or post["post_url"]
                if durable_cycle:
                    _set_collect_cycle_current(
                        cycle_state, post, "opening", "กำลังเปิดลิงก์โพสต์")
                try:
                    gate.require_login(page, browser)
                    job_touched = True
                    result = read_post(page, target,
                                       require_login=True,
                                       expect=post.get("caption", ""),
                                       group_name=post.get("group_name", ""),
                                       account=post.get("account", ""),
                                       progress=(
                                           lambda phase, action, item=post: (
                                               _set_collect_cycle_current(
                                                   cycle_state, item, phase, action),
                                               report_progress(phase, action),
                                           )
                                       ) if durable_cycle else (
                                           lambda phase, action:
                                           report_progress(phase, action)
                                       ) if progress else None)
                except Exception as error:
                    message = str(error)
                    log(f"  ❌ {label}: {type(error).__name__}: {message[:90]}")
                    if isinstance(error, gate.LoginRequired):
                        needs_login = interrupted = True
                        gate.pause_login(message)
                        if durable_cycle:
                            _set_collect_cycle_current(cycle_state, post, "needs_login", message)
                        report_progress("needs_login", message)
                        break
                    # browser ถูกปิดหรือ network ของ context นี้เสีย = ใบต่อไปไม่มี
                    # ทางสำเร็จ หยุดรอบและคง URL ปัจจุบันใน checkpoint ไว้ลองใหม่.
                    # ห้ามติ๊ก done: เคยเกิด ERR_QUIC ทุก URL แล้วรอบถูกล้างทั้งที่
                    # ไม่ได้อ่านโพสต์สำเร็จแม้แต่ใบเดียว.
                    if ("Target page, context or browser has been closed" in message
                            or type(error).__name__ == "TargetClosedError"
                            or "net::ERR_" in message):
                        interrupted = True
                        gate.failure(message)
                        if durable_cycle:
                            _set_collect_cycle_current(
                                cycle_state, post, "retry_wait",
                                "Chrome/เครือข่ายสะดุด · รอลองโพสต์นี้ใหม่")
                        log("  ⏸ Chrome/เครือข่าย Bot8 สะดุด — เก็บ checkpoint "
                            "แล้วจะลองโพสต์นี้ใหม่อัตโนมัติ")
                        break
                    if durable_cycle:
                        _set_collect_cycle_current(
                            cycle_state, post, "failed",
                            "อ่านโพสต์นี้ไม่สำเร็จ · กำลังไปโพสต์ถัดไป")
                        _mark_collect_cycle_done(cycle_state, post)
                    report_progress("failed", "อ่านโพสต์นี้ไม่สำเร็จ", index)
                    if pause_after_job(index - 1, report_progress):
                        preempted = True
                        log("  ⏸ จบใบงานปัจจุบันแล้ว — คืนคิวให้งาน Manual ก่อน")
                        break
                    continue
                gate.healthy()
                # ยอดรอบก่อนหน้า — ต้องอ่าน **ก่อน** save ไม่งั้นได้ยอดรอบนี้เอง
                was = conn.execute(
                    """SELECT reactions, comments, shares FROM my_post
                       WHERE post_url = ? AND reachable = 1
                       ORDER BY id DESC LIMIT 1""", (post["post_url"],)).fetchone()
                fresh, total = save(
                    conn, post, result,
                    max_comment_age_hours=max_comment_age_hours)
                new_comments += fresh
                if result["reachable"]:
                    rows.append({
                        "new_from_others": [
                            {"author": c["author"], "body": c["body"]}
                            for c in (result.get("comments_list") or [])
                            if (post["account"] or "").lower()
                            not in (c.get("author") or "").lower()
                            and not c.get("_answered")
                            and c.get("_age_eligible", True)
                            and (c.get("body") or "").strip()
                        ][-fresh:] if fresh else [],
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
                        "d_shares": (None if was is None
                                     else (result.get("shares") or 0)
                                     - (was["shares"] or 0)),
                        "fresh": fresh,
                    })
                status = watch_status(conn, post["post_url"])
                if status.get("suggest_stop"):
                    suggestions.append({
                        **status,
                        "url": post["post_url"],
                        "group": post["group_name"],
                        "account": post["account"],
                    })
                if result.get("comments_snapshot_complete") is False:
                    blocked += 1
                    log(f"  ⚠ {label}: {result.get('note') or 'เก็บยังไม่ครบ'}")
                elif result["reachable"]:
                    done += 1
                    log(f"  ✅ {label}: ไลก์ {result['reactions']} · "
                        f"คอมเมนต์ {result['comments']} · แชร์ {result['shares']} "
                        f"· เก็บข้อความ {total} อัน (ใหม่ {fresh})")
                else:
                    blocked += 1
                    log(f"  ⛔ {label}: เข้าไม่ถึง — {result['note'][:60]}")
                if durable_cycle:
                    _mark_collect_cycle_done(cycle_state, post)
                if pause_after_job(index - 1, report_progress):
                    preempted = True
                    log("  ⏸ จบใบงานปัจจุบันแล้ว — คืนคิวให้งาน Manual ก่อน")
                    break
        finally:
            try:
                browser.close()
            except Exception:
                pass
    conn.close()
    remaining = (int(cycle_state.get("remaining") or 0)
                 if durable_cycle else 0)
    incomplete = bool(durable_cycle and (preempted or interrupted or remaining))
    if durable_cycle and not incomplete:
        _finish_collect_cycle(cycle_state)
    log(f"จบรอบ — อ่านได้ {done} ใบ · เข้าไม่ถึง {blocked} ใบ "
        f"· ผู้ใช้ปิดการตามเก็บ {stopped} ใบ · คอมเมนต์ใหม่ {new_comments} อัน "
        f"· เสนอให้พิจารณาหยุด {len(suggestions)} ใบ"
        + (f" · checkpoint เหลือ {remaining} ใบ" if incomplete else ""))
    # ใส่ทุกโปรไฟล์ที่เฝ้า แม้วันนี้ไม่มีโพสต์ เพื่อให้ผลลัพธ์บอก 0 ชัดเจน
    # ไม่ทำให้คนอ่านตีความว่าโปรไฟล์หายหรือข้อมูลสองบัญชีถูกรวมกัน
    profiles: dict[str, dict[str, int]] = {
        account: {"posts": 0, "read": 0, "new_comments": 0}
        for account in watched_accounts()
    }
    for post in posts:
        profiles.setdefault(post["account"], {"posts": 0, "read": 0,
                                               "new_comments": 0})
        profiles[post["account"]]["posts"] += 1
    for row in rows:
        owner = next((p["account"] for p in posts
                      if p["post_url"] == row["url"]), "")
        if owner:
            profiles[owner]["read"] += 1
            profiles[owner]["new_comments"] += int(row.get("fresh") or 0)
    return {"posts": len(posts), "rows": rows, "ok": done, "blocked": blocked,
            "quiet": stopped, "stopped": stopped, "suggestions": suggestions,
            "new_comments": new_comments, "profiles": profiles,
            "on_date": on_date,
            "max_comment_age_hours": max_comment_age_hours,
            "preempted": preempted, "incomplete": incomplete,
            "interrupted": interrupted, "resumed_cycle": resumed_cycle,
            "needs_login": needs_login, "retry_after": gate.status().get('wait_seconds', 0),
            "cycle_total": len(all_posts), "remaining": remaining}
def watch() -> None:
    """วนเช็คทุก 6 ชั่วโมง — ล้มรอบหนึ่งต้องไม่ทำให้หยุดทั้งตัว"""
    log(f"เริ่มเฝ้า — เช็คทุก {CHECK_EVERY_SECONDS / 3600:.0f} ชั่วโมง")
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
          AND COALESCE(c.ignored, 0) = 0
          AND COALESCE(c.reply_queued_at, '') = ''
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
    if what in ("today", "once-today"):
        check_once(on_date=datetime.now().strftime("%Y-%m-%d"), force=True)
    elif what == "once":
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
