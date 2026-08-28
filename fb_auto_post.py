"""รับงานโพสต์ (แคปชัน + รูป) จาก Telegram แล้วไล่โพสต์ลงกลุ่ม Facebook อัตโนมัติ

แยกจาก facebook_group_post.py เพราะไฟล์นั้นทำงานเดียว: กด UI บนมือถือให้ถูกลำดับ
ส่วนไฟล์นี้เก็บ "จะโพสต์อะไร ลงกลุ่มไหน ไปถึงไหนแล้ว" ซึ่งต้องรอดข้ามการรีสตาร์ต
จึงต้องอยู่ในไฟล์ JSON ไม่ใช่ตัวแปรในหน่วยความจำ

ทำไมรันได้ทีละงาน:
  มือถือมีจอเดียว สองงานยิง ADB พร้อมกันจะแย่งหน้าจอกันจนกดผิดที่ทั้งคู่
  PostRunner จึงกันไว้ที่ระดับโปรแกรม ไม่ปล่อยให้ไปพังตอนกดจริง
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable

import facebook_group_post
import fb_preflight
import studio_shared

# รอสิทธิ์ใช้จอมือถือนานสุดกี่วินาทีก่อนยอมแพ้
#
# สั้นโดยตั้งใจ: งานโพสต์เป็นงานที่ผู้ใช้สั่งมาตรงๆ ส่วนที่มาแย่งจอคืองานเบื้องหลัง
# (fb_engage) ซึ่งถือล็อกทีละโพสต์แล้วปล่อย รอเกินสองนาทีแปลว่ามีอะไรค้างจริง
# ไม่ใช่แค่คิวยาว — ล้มเร็วแล้วบอกให้ชัดดีกว่าค้างเงียบ งานยังอยู่ในรายการ
# กดรันใหม่ได้ทันที
PHONE_LOCK_WAIT = 120.0

JOB_LIMIT = 50              # เก็บงานย้อนหลังเท่านี้พอ ไฟล์จะได้ไม่บวม
# โพสต์ครั้งเดียวหลายกลุ่มเกินไปเข้าข่ายสแปม — จำกัดตายตัวที่ 6 กลุ่มต่อครั้ง
# และชุดกลุ่มหนึ่งชุดก็ถือไม่เกินเท่านี้ จะได้เลือกทั้งชุดแล้วยิงได้เลย
MAX_GROUPS_PER_POST = 6
DEFAULT_SET = "ชุด 1"
LOG_LINES_PER_JOB = 200

# สถานะของงาน — ใช้ชื่อเดียวกันทั้งฝั่งเว็บและฝั่งบอท
STATUS_WAIT_CAPTION = "waiting_caption"   # ได้รูปแล้ว รอแคปชัน
STATUS_WAIT_IMAGE = "waiting_image"       # ได้แคปชันแล้ว รอรูป
STATUS_READY = "ready"                    # ครบแล้ว รอกดโพสต์
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

OPEN_STATUSES = {STATUS_WAIT_CAPTION, STATUS_WAIT_IMAGE, STATUS_READY}


class AutoPostError(RuntimeError):
    """งานโพสต์อัตโนมัติมีปัญหา"""


# ------------------------------------------------------------- อ่านลิงก์กลุ่ม

# รับได้ทุกแบบที่ผู้ใช้ก๊อปมาจริง:
#   https://www.facebook.com/groups/1911903035616571/
#   https://web.facebook.com/groups/1911903035616571/posts/123/?ref=share
#   https://m.facebook.com/groups/ชื่อกลุ่ม
#   fb://group/1911903035616571
#   1911903035616571
#   https://www.facebook.com/share/g/1HkY8Lwyyk/?mibextid=…   ← ปุ่มแชร์ในแอปให้แบบนี้
_GROUP_URL_RE = re.compile(r"facebook\.com/groups/([^/?#\s]+)", re.I)
_GROUP_SCHEME_RE = re.compile(r"fb://group/([^/?#\s]+)", re.I)
_SHARE_URL_RE = re.compile(r"(?:https?://)?(?:[\w-]+\.)?facebook\.com/share/g/[^/?#\s]+", re.I)

# ลิงก์ย่อของแอปตอบ 400 ให้ User-Agent คอมพิวเตอร์ แต่ตอบ 302 พร้อมที่อยู่จริง
# ให้ UA มือถือ — ตรวจจากของจริงแล้ว (desktop=400 · iPhone=302)
_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


class _KeepRedirect(urllib.request.HTTPRedirectHandler):
    """หยุดที่ 302 แล้วอ่านที่อยู่ปลายทางเอง — ไม่ต้องโหลดหน้าเต็มมาทั้งหน้า"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_group_id(text: str) -> str:
    """ดึงรหัสกลุ่มออกจากสิ่งที่ผู้ใช้วางมา คืน "" ถ้าไม่ใช่ลิงก์กลุ่ม

    ไม่ยิงเน็ต — ลิงก์ย่อ /share/g/ ต้องใช้ resolve_group_id ต่อ
    """
    value = (text or "").strip()
    if not value:
        return ""
    if value.isdigit():
        return value
    for pattern in (_GROUP_SCHEME_RE, _GROUP_URL_RE):
        found = pattern.search(value)
        if found:
            return found.group(1).strip()
    return ""


def share_link(text: str) -> str:
    """คืนลิงก์ย่อ /share/g/… ที่เจอในข้อความ (ถ้ามี)"""
    found = _SHARE_URL_RE.search(text or "")
    return found.group(0) if found else ""


def resolve_share_link(link: str, timeout: float = 20.0) -> str:
    """ตามลิงก์ย่อไปหารหัสกลุ่มจริง

    ลิงก์ย่อใช้กับ fb://group/ ไม่ได้ ต้องแปลงเป็นเลขก่อน ไม่งั้นเปิดกลุ่มไม่เจอ
    ตอนโพสต์จริง — ยอมยิงเน็ตครั้งเดียวตอนเพิ่มกลุ่ม ดีกว่าไปพังตอนโพสต์
    """
    if not link.lower().startswith("http"):
        link = "https://" + link.lstrip("/")
    # mbasic เบาสุด ตอบ 302 พร้อม Location เลย ไม่ต้องโหลดหน้า
    link = re.sub(r"//(?:www|m|web)\.facebook\.com", "//mbasic.facebook.com", link, count=1)
    opener = urllib.request.build_opener(_KeepRedirect)
    request = urllib.request.Request(
        link, headers={"User-Agent": _MOBILE_UA, "Accept-Language": "th,en"}
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            target = response.geturl()
            body = response.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        target = error.headers.get("Location") or ""
        body = ""
    except OSError as error:
        raise AutoPostError(f"เปิดลิงก์กลุ่มไม่ได้: {error}") from error

    for source in (target, body):
        found = re.search(r"/groups/(\d{6,})", source or "")
        if found:
            return found.group(1)
    raise AutoPostError(
        "ตามลิงก์ย่อไปหารหัสกลุ่มไม่เจอ — เปิดกลุ่มในเบราว์เซอร์แล้วคัดลอกลิงก์"
        "แบบ facebook.com/groups/<รหัส> มาแทน"
    )


# UA ที่ลิงก์โพสต์ยอมตอบ 302 — UA เบราว์เซอร์โดน 400 ทั้งมือถือและคอม
# (ทดสอบจริง 11 ส.ค.: www/m + chrome/desktop = 400 · curl + facebookexternalhit = 302)
_BOT_UA = "curl/8.0"


def resolve_post_link(link: str, timeout: float = 20.0) -> tuple[str, str]:
    """แปลงลิงก์โพสต์ย่อ /share/p/<โทเคน> เป็น (รหัสกลุ่ม, รหัสโพสต์)

    ลิงก์ย่อที่เก็บมาจากปุ่ม "คัดลอกลิงก์" อ่านไม่ออกว่าเป็นโพสต์ไหนของกลุ่มไหน
    ตามไปหารหัสจริงเก็บไว้ จะได้ผูกโพสต์กับงานได้แน่นอนโดยไม่ต้องเดาจากแคปชัน

    **หมายเหตุสำคัญ**: รหัสที่ได้ใช้เปิดโพสต์บนแอปไม่ได้ — ทดสอบครบแล้วทั้ง
    fb://post/<id> · fb://group/<gid>/permalink/<id> · fb://faceweb · https
    ทุกแบบเด้งไปฟีดหลัก แอปเลิกรับ deep link ระดับโพสต์จากภายนอกแล้ว
    เก็บไว้เพื่อ "อ้างอิงและตรวจสอบ" เท่านั้น

    คืน ("", "") ถ้าแปลงไม่ได้ — ไม่ raise เพราะลิงก์เป็นของแถม ไม่ควรล้มทั้งงาน
    """
    if not link or "/share/p/" not in link:
        found = re.search(r"/groups/(\d{6,})/(?:permalink|posts)/(\d{6,})", link or "")
        return (found.group(1), found.group(2)) if found else ("", "")
    request = urllib.request.Request(link, headers={"User-Agent": _BOT_UA})
    opener = urllib.request.build_opener(_KeepRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            target = response.geturl()
    except urllib.error.HTTPError as error:
        target = error.headers.get("Location") or ""
    except OSError:
        return "", ""
    found = re.search(r"/groups/(\d{6,})/(?:permalink|posts)/(\d{6,})", target or "")
    return (found.group(1), found.group(2)) if found else ("", "")


def resolve_group_id(text: str) -> str:
    """รหัสกลุ่มที่ใช้กับ fb://group/ ได้จริง — ยิงเน็ตต่อเมื่อจำเป็น"""
    direct = parse_group_id(text)
    if direct.isdigit():
        return direct
    link = share_link(text)
    if link:
        return resolve_share_link(link)
    if direct:
        # ลิงก์ชื่อกลุ่ม (vanity) — แปลงเป็นเลขให้ ถ้าแปลงไม่ได้ค่อยใช้ชื่อไปตามเดิม
        try:
            return resolve_share_link(f"https://mbasic.facebook.com/groups/{direct}")
        except AutoPostError:
            return direct
    raise AutoPostError(
        "อ่านรหัสกลุ่มจากลิงก์นี้ไม่ได้ — ใช้ลิงก์แบบ "
        "https://www.facebook.com/groups/<รหัส> หรือปุ่มแชร์ในแอป"
    )


def looks_like_group_link(text: str) -> bool:
    """ข้อความนี้ "ตั้งใจ" จะเป็นลิงก์กลุ่มไหม

    แยกจาก parse_group_id เพราะเลขล้วนก็ผ่าน parse ได้ แต่ถ้าผู้ใช้พิมพ์เลข
    มาลอยๆ ในแชทเราไม่ควรเดาว่าเป็นกลุ่ม (อาจเป็นแคปชันที่มีแต่ตัวเลข)
    """
    value = (text or "").strip().lower()
    return (
        "facebook.com/groups/" in value
        or "facebook.com/share/g/" in value
        or value.startswith("fb://group/")
    )


# --------------------------------------------------------------- ที่เก็บข้อมูล


# ลองเขียนซ้ำกี่ครั้งเมื่อไฟล์ถูกโปรเซสอื่นเปิดค้างอยู่ (รอบละ WRITE_WAIT วินาที)
#
# บน Windows การ rename ทับไฟล์ที่โปรเซสอื่น "เปิดอ่านอยู่" จะล้มทันทีด้วย
# WinError 5 — ตัวสำรองข้อมูลที่ zip ไฟล์ทั้งโฟลเดอร์ก็เข้าข่าย และตัวสแกน
# ไวรัส/ตัวทำดัชนีของ Windows ก็เปิดไฟล์เองโดยไม่บอกใคร ของพวกนี้ถือไฟล์แค่
# เสี้ยววินาที รอนิดเดียวก็ผ่าน — ล้มรอบเดียวแล้วยอมแพ้คือเสียงานทั้งใบฟรีๆ
WRITE_TRIES = 12
WRITE_WAIT = 0.15


class _StoreLock:
    """ล็อกสองชั้น — ในโปรเซส (เธรด) + ข้ามโปรเซส (ไฟล์ล็อก)

    **ทำไมต้องมีชั้นที่สอง** ไฟล์งานถูกอ่าน-แก้-เขียนโดย **4 โปรเซส**
    (app.py · fb_mass_bot · fb_engage_bot · clip_app) ล็อกเธรดกันได้แค่ในบ้าน
    ตัวเอง พอสองโปรเซสอ่านพร้อมกันแล้วเขียนกลับคนละเวอร์ชัน ของที่เขียนทีหลัง
    จะทับของก่อนหน้าหายเกลี้ยง (lost update)

    เกิดจริง 19 ส.ค. 2026 งาน p112585553: โพสต์ขึ้นครบ 5 กลุ่มพร้อมลิงก์ครบ
    แต่ผลในไฟล์เหลือ 0 กลุ่ม แล้วงานล้มทั้งใบด้วย WinError 5 ตอนบันทึกกลุ่ม
    สุดท้าย — ระบบจึงเข้าใจว่าไม่เคยโพสต์ ซึ่งอันตรายกว่าโพสต์ไม่สำเร็จ
    เพราะกดรันซ้ำเมื่อไรคือโพสต์ซ้ำจริงทั้ง 5 กลุ่ม

    นับชั้นเอง ไม่พึ่งคุณสมบัติ reentrant ของ data_lock — เมธอดของ store
    ซ้อนกันได้ (update เรียกภายใต้บล็อกของ add) และเราต้องถือไฟล์ล็อกใบเดียว
    ตลอดทั้งชุด ไม่ใช่ขอ-คืนไปมาระหว่างกลาง
    """

    def __init__(self, name: str) -> None:
        self._thread = threading.RLock()
        self._name = name
        self._depth = 0
        self._file = None

    def __enter__(self):
        self._thread.acquire()
        self._depth += 1
        if self._depth == 1:
            try:
                holder = studio_shared.data_lock(
                    self._name, timeout=20.0, poll=0.1, label="แก้ไฟล์งาน")
                holder.__enter__()
                self._file = holder
            except Exception:
                # ล็อกไฟล์มีปัญหาต้อง **ไม่หยุดงานโพสต์** — ยอมเสี่ยงชนกัน
                # ดีกว่าทำให้ทั้งระบบเขียนอะไรไม่ได้เลย
                self._file = None
        return self

    def __exit__(self, *exc) -> bool:
        if self._depth == 1 and self._file is not None:
            try:
                self._file.__exit__(*exc)
            except Exception:
                pass
            self._file = None
        self._depth -= 1
        self._thread.release()
        return False


# แคชล็อกตามชื่อ — ดูเหตุผลที่ `_JsonStore.lock`
_LOCKS: dict[str, "_StoreLock"] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(name: str) -> "_StoreLock":
    with _LOCKS_GUARD:
        lock = _LOCKS.get(name)
        if lock is None:
            lock = _LOCKS[name] = _StoreLock(name)
        return lock


# ------------------------------------------------- บัญชีที่กำลังทำงานอยู่
#
# **เจ้าของสั่ง 28 ส.ค. 2569** ให้แยกที่เก็บรายบัญชี และตอบว่าจะรู้ว่าบัญชีไหน
# ด้วยการ *"ผูกบัญชีกับมือถือ 1 เครื่อง = 1 บัญชี"* ต่อมาสั่งเพิ่มว่าบอท Telegram
# แต่ละตัวต้อง *"แยกช่องมาเลยต่างหาก"* — รวมกันเป็นกติกาเดียว
#
#     บอท 1 ตัว = บัญชี 1 บัญชี = ที่เก็บ 1 ชุด = ช่องคุย 1 ช่อง
#
# เก็บเป็น **ตัวแปรประจำเธรด** ไม่ใช่ตัวแปรกลางใบเดียว เพราะเซิร์ฟเวอร์รับ
# หลายข้อความพร้อมกัน ถ้าใช้ใบเดียวร่วมกัน ข้อความของบอท A จะไปเปลี่ยนบัญชี
# ใต้เท้าข้อความของบอท B ที่กำลังเขียนอยู่ แล้วงานไปโผล่ผิดบัญชีเงียบๆ
_ACTIVE = threading.local()


def posting_account() -> str:
    """บัญชี Facebook ที่ควรใช้ตอนนี้ — **ห้ามเดา** (CLAUDE.md ข้อ 8)

    ลำดับ
      1. บัญชีของบอทที่รับข้อความเข้ามา (ตั้งไว้โดย `use_account`)
      2. บัญชีที่ผูกไว้กับมือถือสายโพสต์ — เฉพาะตอนมีเครื่องเดียวที่ผูกไว้
      3. ตอบไม่ได้แน่ชัด → โยน error พร้อมบอกชื่อทุกบัญชีให้เลือก

    เหตุผลที่ไม่หยิบตัวแรกมาใช้เมื่อกำกวม: "โพสต์ลงบัญชีผิด" กู้คืนไม่ได้
    ส่วน "งานไม่เริ่มพร้อมเหตุผล" เสียแค่เวลากดใหม่
    """
    account = active_account()
    if account:
        return account
    import devices          # นำเข้าตรงนี้เพื่อไม่ให้ผูกกันตั้งแต่ตอนโหลดไฟล์
    post_serials = set(devices.enabled_serials("post"))
    bound = {name: serials for name, serials in devices.accounts().items()
             if post_serials.intersection(serials)}
    if len(bound) == 1:
        return next(iter(bound))
    if not bound:
        raise studio_shared.AccountMissing(
            "ยังไม่มีมือถือสายโพสต์เครื่องไหนผูกบัญชี Facebook ไว้ — ผูกก่อนด้วย "
            'python devices.py account <serial> "<ชื่อบัญชี>"'
        )
    raise studio_shared.AccountMissing(
        "มีหลายบัญชีในสายโพสต์ (" + " · ".join(sorted(bound))
        + ") — บอกมาว่าจะใช้บัญชีไหน ระบบไม่เดาให้"
    )


def state_file(name: str):
    """พาธแฟ้มสถานะของบัญชีที่กำลังทำงาน — ตัวช่วยที่ทุกโมดูลสายโพสต์เรียกใช้"""
    return studio_shared.account_file(posting_account(), name)


def active_account() -> str:
    """บัญชีที่เธรดนี้กำลังทำงานให้ — ว่าง = ยังไม่ได้ตั้ง"""
    return str(getattr(_ACTIVE, "account", "") or "")


@contextmanager
def use_account(name: str):
    """ทำงานในนามบัญชีนี้ชั่วคราว แล้วคืนค่าเดิมเสมอ

    ต้องคืนค่าเดิม ไม่ใช่ล้างทิ้ง เพราะบล็อกซ้อนกันได้ (งานโพสต์เรียกตัวช่วยที่
    เรียกซ้อนอีกที) ถ้าล้างทิ้ง ชั้นในจะทำให้ชั้นนอกลืมบัญชีไปกลางคัน
    """
    before = getattr(_ACTIVE, "account", "")
    _ACTIVE.account = str(name or "").strip()
    try:
        yield _ACTIVE.account
    finally:
        _ACTIVE.account = before


class _JsonStore:
    """อ่าน/เขียนไฟล์ JSON ก้อนเดียวใต้ล็อก + เขียนแบบสลับไฟล์

    เขียนลง .tmp แล้วค่อย replace เพราะถ้าไฟฟ้าดับกลางเขียน ไฟล์เดิมยังอยู่ครบ
    (แพตเทิร์นเดียวกับ ApprovalStore ใน telegram_bot.py)

    `lock` เป็นล็อกสองชั้น ทุกจุดที่เขียนอยู่ใต้ `with store.lock:` อยู่แล้ว
    จึงกันข้ามโปรเซสได้ครบโดยไม่ต้องไล่แก้ทีละเมธอด

    **การอ่านเฉยๆ ไม่ต้องล็อก** — `replace` เป็นการสลับไฟล์ทั้งใบในจังหวะเดียว
    คนอ่านจึงเห็น "ของเก่าทั้งใบ" หรือ "ของใหม่ทั้งใบ" ไม่มีทางเห็นครึ่งๆ
    และการอ่านเกิดหลายร้อยครั้งต่องาน ถ้าล็อกทุกครั้งจะช้าโดยไม่ได้อะไร
    """

    def __init__(self, path) -> None:
        # **รับได้ทั้งพาธตรงๆ และฟังก์ชันที่คืนพาธ** — แบบหลังคือหัวใจของการแยก
        # ที่เก็บรายบัญชี เพราะ "จะเขียนลงแฟ้มของใคร" รู้ตอนเรียกใช้ ไม่ใช่ตอน
        # สร้างตัวเก็บ (ตัวเก็บสร้างครั้งเดียวตอนเปิดเซิร์ฟเวอร์ แต่บัญชีที่
        # ทำงานเปลี่ยนได้ทุกข้อความที่เข้ามา ตามบอทที่รับสาร)
        #
        # ถ้าฝังพาธตายตอนสร้างแบบเดิม ต้องไล่แก้ทุกจุดที่เรียกใช้ ซึ่งใน app.py
        # อย่างเดียวมี 145 จุด — ไล่มือเมื่อไรก็พลาดเมื่อนั้น
        self._source = path

    @property
    def path(self) -> Path:
        return self._source() if callable(self._source) else self._source

    @property
    def lock(self) -> "_StoreLock":
        """ล็อกของแฟ้มนี้ — **แยกรายบัญชี**

        ⚠️ ต้องเอาชื่อโฟลเดอร์บัญชีมาประกอบเป็นชื่อล็อกด้วย ไม่งั้นบัญชี A
        เขียนแฟ้มของตัวเองอยู่ แล้วไปกันบัญชี B ไม่ให้เขียนแฟ้มคนละใบ ทั้งที่
        ไม่ได้แตะของกันเลย — อาการ "เช็คแยก แต่จดรวมกัน" ตาม CLAUDE.md ข้อ 8

        ต้องแคชตามชื่อ ห้ามสร้างใหม่ทุกครั้งที่เรียก เพราะชั้นกันเธรดของ
        `_StoreLock` เก็บสถานะไว้ในตัวเอง ถ้าได้คนละใบทุกครั้ง สองเธรดจะเข้าไป
        พร้อมกันได้ทั้งคู่ โดยที่ล็อกดูเหมือนทำงานปกติ
        """
        here = self.path
        return _lock_for(f"{here.parent.name}-{here.stem}")

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []

    def _write(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # ชื่อ .tmp ต้องแยกตามโปรเซส+เธรด ไม่งั้นสองฝั่งเขียนไฟล์ชั่วคราวชื่อ
        # เดียวกันทับกันเอง แล้วได้ JSON ที่ปนกันครึ่งๆ ก่อนถึงขั้น replace ด้วยซ้ำ
        temporary = self.path.with_name(
            f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for attempt in range(WRITE_TRIES):
            try:
                temporary.replace(self.path)
                return
            except OSError:
                if attempt == WRITE_TRIES - 1:
                    temporary.unlink(missing_ok=True)
                    raise
                time.sleep(WRITE_WAIT)


class GroupStore:
    """รายการกลุ่มที่จะโพสต์ — เพิ่ม/ลบ/ติ๊กเลือกได้

    เก็บ enabled ไว้ในตัวกลุ่มเอง ไม่ใช่ในงานแต่ละงาน เพราะผู้ใช้ตั้งครั้งเดียว
    แล้วใช้กับทุกงานถัดไป (งานที่สร้างแล้วจะ "ถ่ายสำเนา" รายชื่อ ณ ตอนสร้างไป
    ต่างหาก — แก้รายการกลุ่มทีหลังต้องไม่ไปเปลี่ยนงานที่รออนุมัติอยู่)
    """

    def __init__(self, path: Path) -> None:
        self.store = _JsonStore(path)

    def listing(self) -> list[dict]:
        return self.store._read()

    def get(self, group_id: str) -> dict | None:
        return next((g for g in self.listing() if g["group_id"] == group_id), None)

    def add(self, link: str, name: str = "") -> dict:
        # ยิงเน็ตแปลงลิงก์ย่อ **นอกล็อก** — ล็อกไว้ระหว่างรอเน็ตจะไปค้างคนอื่นด้วย
        group_id = resolve_group_id(link)
        clean_name = (name or "").strip()[:60]
        with self.store.lock:
            items = self.store._read()
            for item in items:
                if item["group_id"] == group_id:
                    # เพิ่มซ้ำ = อัปเดตชื่อให้ ไม่สร้างรายการซ้ำให้รก
                    if clean_name:
                        item["name"] = clean_name
                    self.store._write(items)
                    return {**item, "duplicated": True}
            entry = {
                "group_id": group_id,
                "name": clean_name or f"กลุ่ม {group_id}",
                "set": self.next_free_set(),
                "enabled": True,
                "added_at": datetime.now().isoformat(timespec="seconds"),
                "last_result": "",
            }
            items.append(entry)
            self.store._write(items)
        return entry

    def remove(self, group_id: str) -> bool:
        with self.store.lock:
            items = self.store._read()
            kept = [g for g in items if g["group_id"] != group_id]
            if len(kept) == len(items):
                return False
            self.store._write(kept)
        return True

    def update(self, group_id: str, **changes) -> dict | None:
        with self.store.lock:
            items = self.store._read()
            for item in items:
                if item["group_id"] == group_id:
                    item.update(changes)
                    self.store._write(items)
                    return item
        return None

    def toggle(self, group_id: str) -> dict | None:
        entry = self.get(group_id)
        if entry is None:
            return None
        return self.update(group_id, enabled=not entry.get("enabled", True))

    def enabled_ids(self, set_name: str = "") -> list[str]:
        """รหัสกลุ่มที่ติ๊กไว้ — ระบุชื่อชุดเพื่อเอาเฉพาะชุดนั้น"""
        return [
            g["group_id"] for g in self.listing()
            if g.get("enabled", True)
            and (not set_name or g.get("set", DEFAULT_SET) == set_name)
        ][:MAX_GROUPS_PER_POST]

    def sets(self) -> dict[str, list[dict]]:
        """จัดกลุ่มทั้งหมดตามชุด เรียงตามชื่อชุด"""
        buckets: dict[str, list[dict]] = {}
        for group in self.listing():
            buckets.setdefault(group.get("set", DEFAULT_SET), []).append(group)
        return dict(sorted(buckets.items()))

    def assign_set(self, group_id: str, set_name: str) -> dict:
        """ย้ายกลุ่มไปชุดอื่น — ชุดหนึ่งรับได้ไม่เกิน MAX_GROUPS_PER_POST"""
        clean = (set_name or DEFAULT_SET).strip()[:30] or DEFAULT_SET
        current = self.sets().get(clean, [])
        if len(current) >= MAX_GROUPS_PER_POST and all(
            g["group_id"] != group_id for g in current
        ):
            raise AutoPostError(
                f"ชุด “{clean}” เต็มแล้ว ({MAX_GROUPS_PER_POST} กลุ่ม) — "
                "ย้ายกลุ่มอื่นออกก่อน หรือใช้ชื่อชุดใหม่"
            )
        entry = self.update(group_id, set=clean)
        if entry is None:
            raise AutoPostError("ไม่พบกลุ่มนี้")
        return entry

    def rename_set(self, old: str, new: str) -> int:
        """เปลี่ยนชื่อกลุ่มใหญ่ — คืนจำนวนกลุ่มย่อยที่ย้ายตาม

        ชื่อกลุ่มใหญ่เก็บอยู่ในฟิลด์ set ของกลุ่มย่อยแต่ละตัว ไม่มีตารางแยก
        การเปลี่ยนชื่อจึงคือการแก้ฟิลด์นี้ของทุกกลุ่มในชุดพร้อมกัน

        ตั้งชื่อซ้ำกับชุดที่มีอยู่ = รวมสองชุดเข้าด้วยกัน ซึ่งอาจทะลุเพดาน 6 กลุ่ม
        จึงต้องกันไว้ ไม่งั้นเลือก "ทั้งชุด" แล้วจะโดนตัดทิ้งเงียบๆ
        """
        clean = (new or "").strip()[:30]
        if not clean:
            raise AutoPostError("ต้องใส่ชื่อใหม่ด้วย")
        with self.store.lock:
            items = self.store._read()
            target = [i for i in items if i.get("set", DEFAULT_SET) == old]
            if not target:
                raise AutoPostError(f"ไม่พบกลุ่มใหญ่ “{old}”")
            if clean != old:
                existing = [i for i in items if i.get("set", DEFAULT_SET) == clean]
                if len(existing) + len(target) > MAX_GROUPS_PER_POST:
                    raise AutoPostError(
                        f"รวมกับ “{clean}” แล้วได้ {len(existing) + len(target)} กลุ่ม "
                        f"เกินเพดาน {MAX_GROUPS_PER_POST} กลุ่มต่อกลุ่มใหญ่"
                    )
            for item in target:
                item["set"] = clean
            self.store._write(items)
        return len(target)

    def split_into_sets(self) -> int:
        """แบ่งกลุ่มที่ยังไม่มีชุดออกเป็นชุดละไม่เกิน MAX_GROUPS_PER_POST

        ใช้ครั้งเดียวตอนอัปเกรด — กลุ่มเดิมทั้งหมดไม่มีฟิลด์ชุด ถ้าปล่อยไว้จะกอง
        อยู่ชุดเดียว 9 กลุ่ม แล้วเวลาเลือก "ทั้งชุด" จะโดนตัดทิ้ง 3 กลุ่มเงียบๆ
        """
        with self.store.lock:
            items = self.store._read()
            if all(item.get("set") for item in items):
                return 0
            counts: dict[str, int] = {}
            for item in items:
                if item.get("set"):
                    counts[item["set"]] = counts.get(item["set"], 0) + 1
            changed = 0
            index = 1
            for item in items:
                if item.get("set"):
                    continue
                while counts.get(f"ชุด {index}", 0) >= MAX_GROUPS_PER_POST:
                    index += 1
                name = f"ชุด {index}"
                item["set"] = name
                counts[name] = counts.get(name, 0) + 1
                changed += 1
            self.store._write(items)
        return changed

    def next_free_set(self) -> str:
        """ชื่อชุดที่ยังไม่เต็ม — ใช้ตอนเพิ่มกลุ่มใหม่โดยไม่ระบุชุด"""
        buckets = self.sets()
        index = 1
        while True:
            name = f"ชุด {index}"
            if len(buckets.get(name, [])) < MAX_GROUPS_PER_POST:
                return name
            index += 1

    def label(self, group_id: str) -> str:
        entry = self.get(group_id)
        return entry["name"] if entry else f"กลุ่ม {group_id}"


# ผลที่ "ทำสำเร็จไปแล้ว" — ห้ามให้รอบหลังเขียนทับให้แย่ลง
#
# รอบตามเก็บรอบสองอาจเก็บลิงก์ไม่สำเร็จหรือหาปุ่มถูกใจไม่เจอ แล้วส่ง
# link="" / liked=False กลับมา ถ้าปล่อยให้ทับตรงๆ ของดีที่ได้มาแล้วจะหายไป
# (เจอจริง 11 ส.ค. งาน p419405442: ลิงก์กลุ่ม ช้อปขั้นเทพ หายไปทั้งที่เคยเก็บได้
#  และ liked กลายเป็น False ทั้งที่เปิดดูจริงแล้วยังถูกใจอยู่)
#
# ค่าพวกนี้เป็นการสะสมข้ามรอบ ไม่ใช่ภาพ ณ วินาทีนี้ — ขึ้นได้อย่างเดียว
STICKY_RESULT_FIELDS = (
    "posted", "liked", "commented", "comment_liked", "link", "post_id",
)


def _merge_result(old: dict, new: dict) -> dict:
    """รวมผลเก่ากับใหม่ โดยไม่ให้ค่าที่เคยสำเร็จแล้วถอยกลับ"""
    merged = {**old, **new}
    for key in STICKY_RESULT_FIELDS:
        if old.get(key) and not new.get(key):
            merged[key] = old[key]
    # จำนวนคอมเมนต์เอาค่าสูงสุดที่เคยทำได้
    counts = [x for x in (old.get("comment_count"), new.get("comment_count")) if x]
    if counts:
        merged["comment_count"] = max(counts)
    # ทำสำเร็จแล้วก็ไม่ต้องเก็บข้อความบอกว่าล้มไว้ให้สับสน
    if merged.get("posted") and merged.get("error"):
        merged.pop("error", None)
    return merged


def _trim_jobs(items: list[dict]) -> list[dict]:
    """ตัดงานเก่าให้เหลือ `JOB_LIMIT` — แต่ **งานที่ตรึงไว้ห้ามหลุด**

    งานที่ตารางโพสต์ประจำวันใช้เป็นแม่แบบ (`fb_routine` → `sources`) ถูกอ้างด้วย
    รหัสงานเท่านั้น พอมันถูกตัดตกขอบคิว ตารางจะหาแม่แบบไม่เจอแล้ว**ข้ามเงียบ**
    ทุกรอบ — ผู้ใช้จะรู้ตัวก็ต่อเมื่อทั้งวันไม่มีโพสต์ขึ้นเลย

    วัดจริง 21 ส.ค. 2026: คิวเต็ม 50/50 และแม่แบบ `p194893071` ที่ตารางทั้ง 4 รอบ
    (09:30 · 12:50 · 14:30 · 16:40) ใช้อยู่ ถูกดันมาถึงลำดับที่ 44 แล้ว — เหลืออีก
    แค่ 5 งานใหม่ก็ตกขอบ ซึ่งระบบสร้างเองวันละ 4 งาน = พังภายในไม่ถึงสองวัน

    ตรึงแล้วนับแยก ไม่กินโควตา 50 ของงานปกติ — แม่แบบจึงไม่ไปเบียดงานจริงให้หายเร็วขึ้น
    """
    kept = items[-JOB_LIMIT:]
    if len(kept) == len(items):
        return items
    dropped = items[:-JOB_LIMIT]
    pinned = [job for job in dropped if job.get("pinned")]
    return pinned + kept if pinned else kept


class JobStore:
    """งานโพสต์ที่รับมาจาก Telegram (หรือสร้างจากหน้าเว็บ)"""

    def __init__(self, path: Path) -> None:
        self.store = _JsonStore(path)

    def add(self, **fields) -> dict:
        entry = {
            "id": f"p{int(time.time() * 1000) % 1_000_000_000}",
            "caption": "",
            "comment": "",          # ข้อความแรก (ของเดิมใช้ฟิลด์นี้)
            "comments": [],         # คอมเมนต์ทั้งหมด สูงสุด 2 ข้อความ
            "comment_images": [],   # รูปแนบของคอมเมนต์ เรียงตรงช่องกับ comments
                                    # ("" = ช่องนั้นไม่มีรูป) แยกจาก images ของโพสต์
            "image": "",              # ใบแรก (ของเดิมใช้ฟิลด์นี้)
            "images": [],             # รูปทั้งหมดของงานนี้ เรียงตามที่ส่งมา
            "groups": [],            # สำเนารหัสกลุ่ม ณ ตอนสร้างงาน
            "set": "",               # ชุดกลุ่มที่ใช้ตอนสร้างงาน
            "run_at": "",            # เวลาที่ตั้งให้โพสต์ (ว่าง = โพสต์เมื่อกดเอง)
            "status": STATUS_WAIT_CAPTION,
            "source": "telegram",
            "chat_id": "",
            "message_id": 0,
            "media_group": "",
            "pinned": False,         # ตรึงไว้เป็นแม่แบบ — ห้ามถูกตัดทิ้งตอนคิวเต็ม
            "results": [],
            "log": [],
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "started_at": None,
            "finished_at": None,
            **fields,
        }
        with self.store.lock:
            items = self.store._read()
            items.append(entry)
            self.store._write(_trim_jobs(items))
        return entry

    def update(self, job_id: str, **changes) -> dict | None:
        with self.store.lock:
            items = self.store._read()
            for item in items:
                if item["id"] == job_id:
                    item.update(changes)
                    self.store._write(items)
                    return dict(item)
        return None

    def append_log(self, job_id: str, line: str) -> None:
        with self.store.lock:
            items = self.store._read()
            for item in items:
                if item["id"] == job_id:
                    lines = item.get("log") or []
                    lines.append(f"{datetime.now():%H:%M:%S} {line}")
                    item["log"] = lines[-LOG_LINES_PER_JOB:]
                    self.store._write(items)
                    return

    def upsert_result(self, job_id: str, result: dict) -> None:  # noqa: D401
        """บันทึกผลของกลุ่มหนึ่ง — กลุ่มเดิมทับของเดิม ไม่ต่อท้ายซ้ำ

        รอบตรวจซ้ำส่งผลของกลุ่มเดิมกลับมาอีกครั้ง (พร้อมลิงก์/สถานะถูกใจที่อัปเดตแล้ว)
        ถ้าต่อท้ายทุกครั้งจะได้รายชื่อกลุ่มซ้ำสองรอบในสรุป
        """
        with self.store.lock:
            items = self.store._read()
            for item in items:
                if item["id"] != job_id:
                    continue
                results = item.setdefault("results", [])
                for index, old in enumerate(results):
                    if old.get("group_id") == result.get("group_id"):
                        results[index] = _merge_result(old, result)
                        break
                else:
                    results.append(result)
                self.store._write(items)
                return

    def get(self, job_id: str) -> dict | None:
        return next((j for j in self.store._read() if j["id"] == job_id), None)

    def listing(self) -> list[dict]:
        return list(reversed(self.store._read()))

    def latest_active(self, chat_id: str = "") -> dict | None:
        """งานล่าสุดที่ยัง "ทำอยู่" — ยังไม่ได้โพสต์ หรือกำลังโพสต์

        แยกจาก latest_open เพราะการตั้งคอมเมนต์ต้องทำได้ระหว่างที่กำลังไล่โพสต์ด้วย
        (ตั้งกลางคันแล้วกลุ่มที่เหลือจะได้คอมเมนต์ตามที่เพิ่งตั้ง)
        """
        for job in self.listing():
            if job["status"] not in OPEN_STATUSES and job["status"] != STATUS_RUNNING:
                continue
            if chat_id and job.get("chat_id") and job["chat_id"] != chat_id:
                continue
            return job
        return None

    def latest_open(self, chat_id: str = "") -> dict | None:
        """งานล่าสุดที่ยัง "แก้ไขอยู่" — ใช้ต่อรูปกับแคปชันที่ส่งมาคนละข้อความ

        **ข้ามงานที่ตั้งเวลาไว้แล้ว** (มี run_at) เพราะตั้งเวลาแล้ว = ปิดกล่องแล้ว
        รูปหรือข้อความที่ส่งเข้ามาทีหลังเป็นของงานใหม่ ไม่ใช่ของงานนั้น

        ไม่ข้าม = พิมพ์ข้อความอะไรก็ตามหลังตั้งเวลาไว้ จะไป**ทับแคปชัน**ของงานที่
        รอโพสต์อยู่โดยผู้ใช้ไม่รู้ตัว (ทางรับข้อความตั้งใจให้ "พิมพ์ทับงานที่พร้อม
        โพสต์ = แก้แคปชัน" ซึ่งถูกสำหรับร่าง แต่ผิดสำหรับงานที่สั่งไว้แล้ว)

        อยากแก้งานที่ตั้งเวลาไว้ ให้เรียกด้วยรหัสงานตรงๆ เช่น
        `/caption p616725077 ข้อความใหม่` — ทางนั้นใช้ _fb_pick_job ซึ่งยังเห็น
        งานที่ตั้งเวลาไว้ตามปกติ
        """
        for job in self.listing():
            if job["status"] not in OPEN_STATUSES:
                continue
            if job.get("run_at"):
                continue
            if chat_id and job.get("chat_id") and job["chat_id"] != chat_id:
                continue
            return job
        return None


# ------------------------------------------------------------------ ตัวรันงาน


class PostRunner:
    """รันงานโพสต์ทีละงานใน thread แยก — **หนึ่งตัวต่อมือถือหนึ่งเครื่อง**

    ต้องกันงานซ้อนกันบนเครื่องเดียวกัน: จอมีจอเดียว ถ้าสองงานยิง ADB ใส่เครื่อง
    เดียวกันพร้อมกัน ทั้งคู่จะกดผิดหน้าจอกันหมด (งานที่สองเปิดกลุ่มทับงานแรก
    ที่กำลังพิมพ์อยู่)

    แต่ **คนละเครื่องไม่ต้องรอกัน** — ของเดิมมีตัวรันตัวเดียวทั้งระบบ พอเสียบ
    เครื่องที่สองแล้วสั่งงาน จะโดนตีกลับว่า "กำลังโพสต์งานอื่นอยู่" ทั้งที่เครื่องนั้น
    ว่างสนิท ตอนนี้ `RunnerPool` แจกตัวรันคนละตัวให้แต่ละ serial

    **ห้ามสร้าง `PostRunner()` ขึ้นมาลอยๆ** ให้ขอผ่าน pool เสมอ ไม่งั้นสองที่จะ
    ได้ตัวรันคนละตัวสำหรับเครื่องเดียวกัน แล้วด่านกันงานซ้อนจะมองไม่เห็นกัน —
    กลับไปเป็นบั๊กเดิมที่แย่กว่าเดิม เพราะคราวนี้ไม่มีอะไรบอกว่าชนกัน
    """

    def __init__(self, serial: str = "") -> None:
        self.serial = serial
        self.thread: threading.Thread | None = None
        self.job_id = ""
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()

    @property
    def busy(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def stop(self) -> bool:
        if not self.busy:
            return False
        self.stop_flag.set()
        return True

    def _phone(self, serial: str, what: str, adb: str = "adb"):
        """ขอสิทธิ์ใช้จอมือถือ **เครื่องนั้น** — กันข้ามโปรเซส ไม่ใช่แค่ในโปรเซสนี้

        `PhoneGate` ใน app.py กันได้แค่งานโพสต์กับ Claude CLI ซึ่งอยู่โปรเซส
        เดียวกัน พอมีบอทเบื้องหลัง (fb_engage_bot) ที่ยิง ADB จากอีกโปรเซส
        ล็อกนั้นมองไม่เห็นกันเลย — สองฝั่งจะแตะจอทับกันเละทั้งคู่

        ล็อกแยกรายเครื่อง (ระยะ 2.1) — งานบนมือถือคนละเครื่องจึงไม่ต้องรอกัน
        ตอนไม่มีใครแย่ง จะได้ล็อกทันที พฤติกรรมจึงเหมือนเดิมทุกประการ

        **ตรวจความพร้อมก่อนขอล็อก** งานที่ล้มกลางคันแพงกว่างานที่ไม่ได้เริ่มมาก
        (โพสต์ค้างครึ่งทางต้องมาไล่ /followup /fiximage เก็บกวาดเอง) ตรวจตรงนี้
        จุดเดียวครอบทั้งสี่ทาง — โพสต์ · ตามเก็บ · เก็บยอด · แก้รูป

        ไม่เช็คล็อก (`check_lock=False`) เพราะบรรทัดถัดไปขอล็อกเองอยู่แล้ว
        ถ้าไม่ว่างจะได้ `PhoneBusy` พร้อมข้อความว่าใครถือ ซึ่งตรงกว่า

        **ต้องส่ง `adb` ตัวเดียวกับที่งานใช้เข้ามาด้วย** ห้ามให้ด่านตรวจไปหยิบ
        `adb` จาก PATH เอง — เครื่องนี้มี adb สองตัวคนละที่ (โปรเจกต์ใช้
        `tools\\platform-tools\\adb.exe` ส่วน PATH ชี้ `C:\\adb\\adb.EXE`)
        คนละรุ่นเจอกันเมื่อไรจะไล่ฆ่า adb server ของกันและกันจนสั่งมือถือไม่ได้
        ทั้งเครื่อง — เคยเกิดมาแล้ว และจะยิ่งเจ็บถ้าเกิดกลางงานที่โพสต์ไปครึ่งทาง
        """
        fb_preflight.guard(serial, what=what, adb=adb, check_lock=False)
        return studio_shared.phone_lock(serial, timeout=PHONE_LOCK_WAIT, label=what)

    def start(
        self, *, job: dict, adb: str, serial: str, image: Path,
        gap_range: tuple[float, float], on_log: Callable[[str], None],
        on_result: Callable[[dict], None], on_done: Callable[[list[dict], str], None],
        clipboard=None, comment="", comment_images=None,
    ) -> None:
        with self.lock:
            if self.busy:
                raise AutoPostError(
                    f"กำลังโพสต์งาน {self.job_id} อยู่ — รอให้จบก่อนค่อยสั่งงานใหม่"
                )
            self.stop_flag.clear()
            self.job_id = job["id"]
            self.thread = threading.Thread(
                target=self._run,
                kwargs={
                    "job": job, "adb": adb, "serial": serial, "image": image,
                    "gap_range": gap_range, "on_log": on_log,
                    "on_result": on_result, "on_done": on_done,
                    "clipboard": clipboard,
                    "comment": comment, "comment_images": comment_images,
                },
                daemon=True,
            )
            self.thread.start()

    def start_followup(
        self, *, job_id: str, adb: str, serial: str, caption: str,
        targets: list[dict], comment: str, on_log, on_result, on_done,
        comment_images=None, clipboard=None,
    ) -> None:
        """รอบตามเก็บ: เปิดโพสต์จากแจ้งเตือนแล้วกดถูกใจ/คอมเมนต์

        ใช้ตัวกันงานซ้อนตัวเดียวกับการโพสต์ เพราะใช้หน้าจอมือถือเครื่องเดียวกัน
        """
        with self.lock:
            if self.busy:
                raise AutoPostError(f"กำลังทำงาน {self.job_id} อยู่ — รอให้จบก่อน")
            self.stop_flag.clear()
            self.job_id = job_id
            self.thread = threading.Thread(
                target=self._run_followup,
                kwargs={
                    "adb": adb, "serial": serial, "caption": caption,
                    "targets": targets, "comment": comment, "on_log": on_log,
                    "on_result": on_result, "on_done": on_done,
                    "comment_images": comment_images, "clipboard": clipboard,
                },
                daemon=True,
            )
            self.thread.start()

    def _run_followup(self, *, adb, serial, caption, targets, comment,
                      on_log, on_result, on_done, comment_images=None,
                      clipboard=None) -> None:
        error_text = ""
        results: list[dict] = []
        try:
            with self._phone(serial, f"รอบตามเก็บ {self.job_id}", adb):
                results = facebook_group_post.followup_groups(
                    adb=adb, serial=serial, caption=caption, targets=targets,
                    comment=comment, log=on_log, stop=self.stop_flag.is_set,
                    on_result=on_result, comment_images=comment_images,
                    clipboard=clipboard,
                )
        except studio_shared.PhoneBusy as error:
            error_text = str(error)
            on_log(f"เริ่มไม่ได้ — {error}")
        except Exception as error:
            error_text = str(error)
            on_log(f"งานล้ม: {error}")
        finally:
            self.job_id = ""
            try:
                on_done(results, error_text)
            except Exception as error:
                on_log(f"สรุปผลไม่สำเร็จ: {error}")

    def start_collect(
        self, *, job_id: str, adb: str, serial: str, caption: str,
        targets: list[dict], on_log, on_result, on_done, clipboard=None,
    ) -> None:
        """รอบเก็บสถิติ: เปิดโพสต์จากลิงก์ที่เก็บไว้แล้วอ่านยอดถูกใจ/คอมเมนต์/แชร์

        ใช้ตัวกันงานซ้อนตัวเดียวกับการโพสต์ เพราะใช้หน้าจอมือถือเครื่องเดียวกัน
        """
        with self.lock:
            if self.busy:
                raise AutoPostError(f"กำลังทำงาน {self.job_id} อยู่ — รอให้จบก่อน")
            self.stop_flag.clear()
            self.job_id = job_id
            self.thread = threading.Thread(
                target=self._run_collect,
                kwargs={
                    "adb": adb, "serial": serial, "caption": caption,
                    "targets": targets, "on_log": on_log,
                    "on_result": on_result, "on_done": on_done,
                    "clipboard": clipboard,
                },
                daemon=True,
            )
            self.thread.start()

    def _run_collect(self, *, adb, serial, caption, targets, on_log,
                     on_result, on_done, clipboard=None) -> None:
        error_text = ""
        results: list[dict] = []
        try:
            with self._phone(serial, f"รอบเก็บยอด {self.job_id}", adb):
                results = facebook_group_post.collect_groups(
                    adb=adb, serial=serial, caption=caption, targets=targets,
                    log=on_log, stop=self.stop_flag.is_set, on_result=on_result,
                    clipboard=clipboard,
                )
        except studio_shared.PhoneBusy as error:
            error_text = str(error)
            on_log(f"เริ่มไม่ได้ — {error}")
        except Exception as error:
            error_text = str(error)
            on_log(f"งานล้ม: {error}")
        finally:
            self.job_id = ""
            try:
                on_done(results, error_text)
            except Exception as error:
                on_log(f"สรุปผลไม่สำเร็จ: {error}")

    def start_fiximage(
        self, *, job_id: str, adb: str, serial: str, caption: str,
        targets: list[dict], images: list, on_log, on_result, on_done,
    ) -> None:
        """รอบแก้รูป: เปิดโพสต์ที่ลงไปแล้วจากลิงก์ แล้วเปลี่ยนรูปให้ถูกใบ"""
        with self.lock:
            if self.busy:
                raise AutoPostError(f"กำลังทำงาน {self.job_id} อยู่ — รอให้จบก่อน")
            self.stop_flag.clear()
            self.job_id = job_id
            self.thread = threading.Thread(
                target=self._run_fiximage,
                kwargs={
                    "adb": adb, "serial": serial, "caption": caption,
                    "targets": targets, "images": images, "on_log": on_log,
                    "on_result": on_result, "on_done": on_done,
                },
                daemon=True,
            )
            self.thread.start()

    def _run_fiximage(self, *, adb, serial, caption, targets, images,
                      on_log, on_result, on_done) -> None:
        error_text = ""
        results: list[dict] = []
        try:
            with self._phone(serial, f"รอบแก้รูป {self.job_id}", adb):
                results = facebook_group_post.fix_images_groups(
                    adb=adb, serial=serial, caption=caption, targets=targets,
                    images=images, log=on_log, stop=self.stop_flag.is_set,
                    on_result=on_result,
                )
        except studio_shared.PhoneBusy as error:
            error_text = str(error)
            on_log(f"เริ่มไม่ได้ — {error}")
        except Exception as error:
            error_text = str(error)
            on_log(f"งานล้ม: {error}")
        finally:
            self.job_id = ""
            try:
                on_done(results, error_text)
            except Exception as error:
                on_log(f"สรุปผลไม่สำเร็จ: {error}")

    def _run(
        self, *, job, adb, serial, image, gap_range, on_log, on_result, on_done,
        clipboard, comment, comment_images=None,
    ) -> None:
        error_text = ""
        results: list[dict] = []
        try:
            with self._phone(serial, f"งานโพสต์ {self.job_id}", adb):
                results = facebook_group_post.post_to_groups(
                    adb=adb, serial=serial, image=image, caption=job["caption"],
                    group_ids=job["groups"], gap_range=gap_range,
                    log=on_log, stop=self.stop_flag.is_set, on_result=on_result,
                    clipboard=clipboard, comment=comment,
                    comment_images=comment_images,
                    # กลุ่มที่เปิดโหมด "ถูกปฏิเสธแล้วส่งใหม่เหลือแต่ลิงก์"
                    links_only_groups=job.get("links_only_groups") or (),
                )
        except studio_shared.PhoneBusy as error:
            error_text = str(error)
            on_log(f"เริ่มไม่ได้ — {error}")
        except Exception as error:      # ต้องจับให้หมด ไม่งั้น thread ตายเงียบ
            error_text = str(error)
            on_log(f"งานล้ม: {error}")
        finally:
            self.job_id = ""
            try:
                on_done(results, error_text)
            except Exception as error:
                on_log(f"สรุปผลไม่สำเร็จ: {error}")


class RunnerPool:
    """หัวหน้างานโพสต์คนละคนต่อมือถือหนึ่งเครื่อง — รองรับกี่เครื่องก็ได้

    **ตั้งใจไม่มี `.busy` กับ `.job_id`** ทั้งที่ของเดิมมี เพราะสองชื่อนั้นแปลว่า
    "เครื่องเดียวของระบบยุ่งอยู่ไหม / กำลังทำงานอะไร" ซึ่งเป็นคำถามที่ตอบไม่ได้
    อีกแล้วเมื่อมีหลายเครื่อง ถ้าเก็บชื่อเดิมไว้แล้วให้แปลว่า "เครื่องไหนก็ได้"
    โค้ดเก่าจะยังคอมไพล์ผ่านและ **ทำงานผิดเงียบๆ**: เครื่อง A โพสต์อยู่ แล้วสั่ง
    เครื่อง B จะโดนตีกลับว่าไม่ว่าง ทั้งที่ B ว่าง

    ยอมให้โค้ดเก่าล้มด้วย AttributeError ตรงจุดดีกว่า — ล้มเสียงดังหาที่แก้ได้
    ใน 5 วินาที ส่วนทำงานผิดเงียบๆ ใช้เวลาเป็นวันกว่าจะรู้ตัว
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runners: dict[str, PostRunner] = {}

    def for_device(self, serial: str) -> PostRunner:
        """หัวหน้างานของเครื่องนี้ — ยังไม่มีก็ตั้งให้ (เครื่องที่ 3, 4, ... ก็ได้)"""
        serial = str(serial or "").strip()
        if not serial:
            raise AutoPostError("ต้องระบุว่าจะสั่งงานมือถือเครื่องไหน")
        with self._lock:
            runner = self._runners.get(serial)
            if runner is None:
                runner = self._runners[serial] = PostRunner(serial)
            return runner

    def busy_on(self, serial: str) -> bool:
        """เครื่องนี้ยุ่งอยู่ไหม — คำถามที่ต้องถามก่อนสั่งงานทุกครั้ง"""
        with self._lock:
            runner = self._runners.get(str(serial or "").strip())
        return bool(runner and runner.busy)

    def any_busy(self) -> bool:
        """มีเครื่องไหนยุ่งอยู่บ้างไหม — **ใช้โชว์เท่านั้น ห้ามเอาไปกั้นงาน**

        ชื่อยาวและอ่านแล้วสะดุดโดยตั้งใจ ใครเผลอเอาไปใช้กั้นงานจะเห็นได้จาก
        ชื่อเลยว่าผิด — ต้องใช้ `busy_on(serial)` เสมอ
        """
        return bool(self.running())

    def running(self) -> dict:
        """{serial: job_id} เฉพาะเครื่องที่กำลังทำงานอยู่"""
        with self._lock:
            pairs = list(self._runners.items())
        return {serial: r.job_id for serial, r in pairs if r.busy and r.job_id}

    def job_running(self, job_id: str) -> str:
        """งานนี้กำลังรันอยู่บนเครื่องไหน — คืน "" ถ้าไม่มีเครื่องไหนทำอยู่

        แทนสำนวนเดิม `fb_runner.busy and fb_runner.job_id == job_id` ซึ่งตอนนี้
        ตอบผิดทันทีที่มีสองเครื่อง (งานอยู่บนเครื่อง B แต่ไปถามเครื่องเดียวที่มี)
        """
        job_id = str(job_id or "").strip()
        return next((s for s, j in self.running().items() if j == job_id), "")

    def stop_job(self, job_id: str) -> str:
        """สั่งหยุดงานนี้ไม่ว่าอยู่เครื่องไหน — คืน serial ที่สั่งไป ("" = ไม่เจอ)"""
        serial = self.job_running(job_id)
        if serial and self.for_device(serial).stop():
            return serial
        return ""

    def stop_all(self) -> list[tuple[str, str]]:
        """สั่งหยุดทุกเครื่อง — คืน [(serial, job_id), ...] ที่สั่งไปจริง"""
        out = []
        for serial, job_id in self.running().items():
            if self.for_device(serial).stop():
                out.append((serial, job_id))
        return out


def result_line(entry: dict, label: Callable[[str], str]) -> str:
    """หนึ่งบรรทัดสรุปผลของกลุ่มหนึ่ง (พร้อมลิงก์โพสต์ถ้าเก็บมาได้)

    **ต้องแยก "posted=False" ออกจาก "ไม่มีคีย์ posted เลย"**

    รอบตามเก็บ (`followup_groups`) ตั้งใจไม่ใส่คีย์ `posted` มาเลย เพราะ
    "โพสต์ขึ้นหรือยัง" เป็นผลของรอบโพสต์ ไม่ใช่ของรอบตามเก็บ — รอบตามเก็บ
    เปิดโพสต์ไม่เจอไม่ได้แปลว่าโพสต์ไม่ขึ้น

    ของเดิมเช็ค `not entry.get("posted")` ซึ่ง `None` กับ `False` ให้ผลเหมือนกัน
    รายงานรอบตามเก็บจึงขึ้น "❌ ไม่สำเร็จ" **ทุกกลุ่ม** ทั้งที่ถูกใจกับคอมเมนต์
    ขึ้นครบ (เจอจริง 13 ส.ค. งาน p617465263: จริงๆ สำเร็จ 5/6 แต่แชทขึ้น ❌ หมด)
    ตัวเลขสรุปท้ายข้อความถูกอยู่แล้ว เลยยิ่งขัดกันเองจนอ่านไม่รู้เรื่อง
    """
    name = label(entry.get("group_id", ""))
    if not entry.get("posted") and entry.get("error"):
        return f"❌ {name} — {entry['error']}"
    if "posted" in entry and not entry["posted"]:
        return f"❌ {name} — ไม่สำเร็จ"
    verified = entry.get("verified") or {}
    liked = entry.get("liked") or verified.get("liked")
    # รายงาน 4 อย่างเสมอ: โพสต์ · ถูกใจ · คอมเมนต์ · ถูกใจคอมเมนต์
    line = f"✅ {name}"
    line += "  ❤️ ถูกใจ" if liked else "  🤍 ยังไม่ถูกใจ"
    if entry.get("commented"):
        line += "  💬 คอมเมนต์" + ("❤️" if entry.get("comment_liked") else "🤍")
    if entry.get("link"):
        line += f"\n    {entry['link']}"
    return line


def summarize(results: list[dict], label: Callable[[str], str]) -> str:
    """สรุปผลเป็นข้อความบรรทัดเดียวต่อกลุ่ม ไว้ส่งกลับเข้า Telegram"""
    if not results:
        return "ยังไม่ได้โพสต์กลุ่มไหนเลย"
    lines = [result_line(entry, label) for entry in results]
    total = len(results)
    posted = sum(1 for e in results if e.get("posted"))
    liked = sum(1 for e in results if e.get("liked"))
    commented = sum(1 for e in results if e.get("commented"))
    comment_liked = sum(1 for e in results if e.get("comment_liked"))
    lines.append(
        f"\nโพสต์ {posted}/{total} · ถูกใจ {liked}/{total} · "
        f"คอมเมนต์ {commented}/{total} · ถูกใจคอมเมนต์ {comment_liked}/{total}"
    )
    return "\n".join(lines)


def fix_line(entry: dict, label: Callable[[str], str]) -> str:
    """หนึ่งบรรทัดผลการแก้รูปของกลุ่มหนึ่ง"""
    name = label(entry.get("group_id", ""))
    if entry.get("image_fixed"):
        return f"🖼️ {name} — เปลี่ยนรูปแล้ว"
    return f"❌ {name} — {entry.get('error', 'แก้ไม่สำเร็จ')}"


def summarize_fix(results: list[dict], label: Callable[[str], str]) -> str:
    if not results:
        return "ไม่มีกลุ่มให้แก้รูป"
    lines = [fix_line(entry, label) for entry in results]
    fixed = sum(1 for e in results if e.get("image_fixed"))
    lines.append(f"\nแก้รูปสำเร็จ {fixed}/{len(results)} กลุ่ม")
    return "\n".join(lines)


def collect_line(entry: dict, label: Callable[[str], str]) -> str:
    """หนึ่งบรรทัดสรุปยอดของกลุ่มหนึ่ง"""
    name = label(entry.get("group_id", ""))
    stats = entry.get("stats") or {}
    if not stats:
        return f"❌ {name} — {entry.get('error', 'อ่านยอดไม่ได้')}"
    line = f"✅ {name}  {facebook_group_post.format_stats(stats)}"
    if entry.get("link"):
        line += f"\n    {entry['link']}"
    return line


def summarize_collect(results: list[dict], label: Callable[[str], str]) -> str:
    """สรุปยอดรวมทุกกลุ่ม

    ยอดรวมนับเฉพาะกลุ่มที่**อ่านค่านั้นได้จริง** และบอกด้วยว่านับจากกี่กลุ่ม
    ไม่งั้นผู้ใช้จะอ่านเลขรวมแล้วเข้าใจว่าครบทุกกลุ่ม ทั้งที่บางกลุ่มอ่านไม่ออก
    """
    if not results:
        return "ยังไม่มีโพสต์ให้เก็บยอด"
    lines = [collect_line(entry, label) for entry in results]
    total = len(results)
    read = sum(1 for e in results if e.get("stats"))
    parts = []
    for key, icon in (("reactions", "❤️"), ("comments", "💬"), ("shares", "🔁")):
        values = [
            (e.get("stats") or {}).get(key) for e in results
            if (e.get("stats") or {}).get(key) is not None
        ]
        if values:
            parts.append(f"{icon} {sum(values)} (จาก {len(values)} กลุ่ม)")
        else:
            parts.append(f"{icon} อ่านไม่ได้")
    lines.append(f"\nเก็บยอดได้ {read}/{total} กลุ่ม\n" + " · ".join(parts))
    return "\n".join(lines)
