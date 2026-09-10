"""สลับบัญชี Google ของ Flow อัตโนมัติ — ล็อกอินด้วยรหัสที่เก็บไว้

**เจ้าของสั่ง 9–10 ก.ย. 2569** — *"มีตัวเช็คเครดิต ถ้าเหลือน้อยกว่า 15 ให้ทำการ
เปลี่ยน email โดยดึง password จากที่เก็บไว้มาวาง"* และยืนยันว่า
**"เปลี่ยนบัญชีเองทุกครั้ง"** คือต้องล็อกอินใหม่จริง ไม่ได้พึ่งบัญชีที่ Chrome จำไว้

ที่เก็บบัญชี: `flow_accounts.py` · หน้าต่างกรอก: `flow_accounts_window.py`


ทำไมต้องระวังเป็นพิเศษ
---------------------

**Google ล็อกบัญชีที่ดูเหมือนถูกสคริปต์กด** และการปลดล็อกยากกว่าเครดิตหมดมาก
โมดูลนี้จึงออกแบบให้ **ขี้ระแวงมากกว่าขยัน**

    ทุกขั้นต้องยืนยันว่าสำเร็จก่อนไปขั้นถัดไป   ไม่เดาว่าหน้าจอเปลี่ยนแล้ว
    เจออะไรที่ไม่รู้จัก = หยุดทันที + เก็บภาพ   ไม่กดมั่วต่อ
    เจอด่านยืนยันตัวตน = หยุด + เรียกคน        ห้ามพยายามผ่านเอง
    พิมพ์แบบมีจังหวะเหมือนคนพิมพ์               ไม่ยัดทั้งก้อนทีเดียว
    ล้มแล้วไม่ลองซ้ำบัญชีเดิม                    ลองซ้ำ = เข้าใกล้โดนล็อก


สองอย่างที่เรียนจากของจริง (10 ก.ย. 2569)
------------------------------------------

ตอนเดินให้เจ้าของดู พบว่าที่เดาไว้ผิดสองจุด — ทั้งคู่คือเหตุผลที่กติกาข้อ 2.2
ห้ามรายงานว่าเสร็จโดยไม่ทดสอบกับของจริง

1. **ออกจากบัญชีแล้วไม่ได้ไปหน้ากรอกอีเมล** แต่ไปหน้า `accountchooser`
   ที่จำบัญชีเก่าไว้ ทุกใบขึ้นว่า Signed out พร้อมปุ่ม "Use another account"

2. **ช่อง `input[type=email]` ตัวแรกเป็นช่องซ่อน** (`id=hiddenEmail`
   `aria-hidden=true`) ที่มีอีเมลเก่าค้างอยู่ กดไม่ได้เพราะมองไม่เห็น
   ต้องเล็ง `:visible` เท่านั้น


ตัวตรวจว่าสำเร็จ — ดูของที่มีเฉพาะตอนสำเร็จ (กติกาข้อ 2.3.1)
------------------------------------------------------------

**ไม่ใช่** "ออกจากหน้า accounts.google.com แล้วหรือยัง" เพราะออกได้ทั้งตอนสำเร็จ
ตอนกดยกเลิก และตอนโดนเด้ง

**ใช้** "อ่านยอดเครดิตในหน้า Flow ได้จริงไหม" — เลขนี้มีให้อ่านเฉพาะตอนที่
เข้าแอปได้จริงด้วยบัญชีที่ใช้งานได้เท่านั้น


วิธีใช้
-------

    python flow_login.py สถานะ                    ดูว่าตอนนี้เป็นบัญชีไหน เครดิตเท่าไร
    python flow_login.py สอน                      เดินทีละขั้น หยุดให้ดูทุกขั้น
    python flow_login.py สลับ --อีเมล you@gmail.com   สลับไปบัญชีที่ระบุ
    python flow_login.py สลับ                     สลับไปใบถัดไปที่เครดิตยังพอ

⚠️ **โหมดสอนจะไม่ปิดเบราว์เซอร์** ปล่อยค้างไว้ให้เจ้าของดูและสอนต่อได้
"""

from __future__ import annotations

import random
import re
import sys
import time
from pathlib import Path

import flow_accounts
import studio_shared as shared

FLOW_URL = "https://labs.google/fx/tools/flow"
LOGOUT_URL = "https://accounts.google.com/Logout"
SIGNIN_HOST = "accounts.google.com"

# ป้ายบนหน้าจอที่แปลว่า **ต้องให้คนมาทำเอง** — เจอแล้วหยุดทันที
NEEDS_HUMAN = (
    "ยืนยันว่าเป็นคุณ", "verify it", "verify your identity", "2-step", "การยืนยันแบบ 2",
    "รหัสยืนยัน", "verification code", "enter the code", "ป้อนรหัส",
    "unusual activity", "กิจกรรมที่ผิดปกติ", "captcha", "ไม่ใช่หุ่นยนต์",
    "recovery", "กู้คืน", "phone number", "หมายเลขโทรศัพท์",
    "couldn't sign you in", "ลงชื่อเข้าใช้ไม่ได้",
    "this browser or app may not be secure", "เบราว์เซอร์หรือแอปนี้อาจไม่ปลอดภัย",
)

# ป้ายที่แปลว่า **รหัสผ่านผิด** — คนละเรื่องกับด่านยืนยันตัวตน แก้คนละทาง
WRONG_PASSWORD = (
    "wrong password", "รหัสผ่านไม่ถูกต้อง", "incorrect password",
    "couldn't find your google account", "ไม่พบบัญชี google",
)


class LoginBlocked(RuntimeError):
    """ต้องให้คนมาทำเอง — ห้ามลองซ้ำอัตโนมัติ"""


class LoginFailed(RuntimeError):
    """ล็อกอินไม่สำเร็จด้วยเหตุที่ระบบรับมือได้ (เช่นรหัสผิด)"""


def _human_pause(short: float = 0.6, long: float = 1.6) -> None:
    """หยุดแบบไม่เท่ากันทุกครั้ง — จังหวะตายตัวคือสัญญาณว่าเป็นสคริปต์"""
    time.sleep(random.uniform(short, long))


def _page_text(page) -> str:
    try:
        return (page.inner_text("body") or "").lower()
    except Exception:                                        # noqa: BLE001
        return ""


def _shot(page, why: str, note: str = "") -> None:
    """เก็บภาพ + ผังจอไว้ **ห้ามให้การเก็บภาพทำให้งานล้มหนักขึ้น** (ข้อ 2.6.1)"""
    try:
        import evidence                                      # noqa: PLC0415
        evidence.shot(page, why, tag="flow-login", note=note)
    except Exception:                                        # noqa: BLE001
        pass


def _check_screen(page, step: str) -> None:
    """เจอด่านที่คนต้องมาทำเองไหม — เจอแล้วหยุดพร้อมเก็บภาพ

    ⚠️ **ตรวจเฉพาะตอนที่ยังอยู่บนโดเมนล็อกอินของ Google**
    ออกมาถึงหน้า Flow แล้วแปลว่าผ่านด่านมาแล้ว ไม่ต้องตรวจอีก

    ของเดิมตรวจทุกหน้า แล้วไปเจอคำว่า "captcha" ที่ Google ฝังไว้ในสคริปต์
    ของหน้า Flow เอง — รายงานว่าโดนด่านทั้งที่ล็อกอินสำเร็จแล้ว
    (เจอจริง 10 ก.ย. 2569 · กติกาข้อ 2.3.1 ในทางกลับ)
    """
    try:
        if SIGNIN_HOST not in (page.url or ""):
            return
    except Exception:                                        # noqa: BLE001
        pass
    text = _page_text(page)
    for mark in NEEDS_HUMAN:
        if mark.lower() in text:
            _shot(page, f"ต้องให้คนทำเอง-{step}", note=f"เจอคำว่า “{mark}”")
            raise LoginBlocked(
                f"ขั้น “{step}”: Google ขอให้ยืนยันตัวตน (เจอคำว่า “{mark}”) "
                "— ต้องเปิดหน้าต่างแล้วทำเอง ระบบไม่ผ่านด่านนี้ให้")
    for mark in WRONG_PASSWORD:
        if mark.lower() in text:
            _shot(page, f"รหัสผ่านไม่ผ่าน-{step}")
            raise LoginFailed(
                f"ขั้น “{step}”: Google บอกว่ารหัสผ่านหรืออีเมลไม่ถูกต้อง "
                "— แก้รหัสในหน้าต่างเก็บบัญชีแล้วลองใหม่")


def _type_like_human(page, selector: str, text: str) -> None:
    """พิมพ์ทีละตัวแบบมีจังหวะ — **ห้าม log ข้อความที่พิมพ์**"""
    box = page.locator(selector).first
    box.click(timeout=20_000)
    _human_pause(0.3, 0.8)
    for char in text:
        box.type(char, delay=random.uniform(45, 130))
    _human_pause()


def _credits_now(page) -> int | None:
    """อ่านยอดเครดิตจากหน้า Flow — **ตัวตรวจว่าล็อกอินสำเร็จจริง**

    คืน None = อ่านไม่ได้ ซึ่ง **ไม่เท่ากับ** เครดิตเป็นศูนย์
    """
    import flow_driver                                       # noqa: PLC0415
    try:
        return flow_driver.FlowDriver(page, log=lambda *_: None).read_credits()
    except Exception:                                        # noqa: BLE001
        return None


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def account_on_page(page) -> str:
    """หน้านี้กำลังเป็นบัญชีไหนอยู่ — คืน "" ถ้าอ่านไม่ได้

    ⚠️ **"" แปลว่าอ่านไม่ได้ ไม่ใช่แปลว่าไม่ได้ล็อกอิน** (กติกาข้อ 2.3.1 ข้อ 4)
    คนเรียกต้องแยกสองอย่างนี้ออกจากกันเอง

    Google ใส่อีเมลไว้ในป้ายของปุ่มรูปโปรไฟล์มุมขวาบนทุกแอป เช่น
    `aria-label="บัญชี Google: ชื่อ (someone@gmail.com)"` — อ่านจากตรงนั้น
    ก่อนเพราะอยู่บนหน้าเดียวกัน ไม่ต้องเปิดหน้าใหม่ให้ช้า
    """
    try:
        labels = page.evaluate("""() => {
          const out = [];
          document.querySelectorAll('[aria-label],[title],img[alt]').forEach(el => {
            const v = (el.getAttribute('aria-label') || el.getAttribute('title')
                       || el.getAttribute('alt') || '');
            if (v.includes('@')) out.push(v);
          });
          return out.slice(0, 40);
        }""")
    except Exception:                                        # noqa: BLE001
        labels = []
    for value in labels or []:
        found = _EMAIL_RE.search(str(value))
        if found:
            return found.group(0).lower()
    return ""


def profile_check(page, email: str, log=print) -> dict:
    """โปรไฟล์นี้ล็อกอินบัญชีที่ต้องการไว้จริงไหม — **ตรวจของที่มีเฉพาะตอนสำเร็จ**

    ต้องได้ครบ 2 อย่างถึงนับว่าผ่าน (กติกาข้อ 2.3.1)
      1. **อ่านยอดเครดิตบนหน้า Flow ได้เป็นตัวเลข** — เลขนี้ขึ้นเฉพาะตอน
         ล็อกอินแล้วและ Flow ยอมให้ใช้จริง ไม่ใช่แค่ "ไม่เห็นปุ่ม Sign in"
      2. **ชื่อบัญชีบนหน้าตรงกับใบที่ตั้งใจ** — ขาดข้อนี้ โปรไฟล์สองใบ
         อาจเป็นบัญชีเดียวกันทั้งคู่ แล้วการสลับจะไม่ได้อะไรเลย

    คืน `{"ok", "credits", "seen", "why"}` — `seen` ว่างแปลว่า**อ่านชื่อไม่ได้**
    ซึ่งไม่เท่ากับ "บัญชีผิด"
    """
    want = str(email or "").strip().lower()
    try:
        if FLOW_URL.split("//")[-1].split("/")[0] not in (page.url or ""):
            page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=120_000)
            time.sleep(5)
    except Exception as error:                               # noqa: BLE001
        return {"ok": False, "credits": None, "seen": "",
                "why": f"เปิดหน้า Flow ไม่ได้: {error}"[:160]}

    if SIGNIN_HOST in (page.url or ""):
        return {"ok": False, "credits": None, "seen": "",
                "why": "ยังอยู่ที่หน้าล็อกอิน ยังไม่ได้เข้าบัญชี"}

    credits = _credits_now(page)
    seen = account_on_page(page)
    if credits is None:
        return {"ok": False, "credits": None, "seen": seen,
                "why": "อ่านยอดเครดิตไม่ได้ — ยังเข้า Flow ไม่สำเร็จ"}
    if not seen:
        return {"ok": False, "credits": credits, "seen": "",
                "why": "อ่านชื่อบัญชีบนหน้าไม่ได้ (ยังไม่ได้ตรวจ ไม่ใช่ผิด)"}
    if seen != want:
        return {"ok": False, "credits": credits, "seen": seen,
                "why": f"โปรไฟล์นี้เป็นบัญชี {flow_accounts.mask(seen)} "
                       f"ไม่ใช่ {flow_accounts.mask(want)}"}
    return {"ok": True, "credits": credits, "seen": seen, "why": "ผ่าน"}


def setup_profile(email: str, wait_minutes: int = 15, log=print) -> dict:
    """เปิดโปรไฟล์ของบัญชีนี้ค้างไว้ให้เจ้าของล็อกอินเอง แล้วตรวจว่าเข้าจริง

    **ทำครั้งเดียวต่อบัญชี** หลังจากนี้ระบบสลับเองได้ตลอดโดยไม่ต้องมีคนอยู่
    เพราะการสลับกลายเป็นแค่ "เปิด Chrome คนละโฟลเดอร์" ไม่ต้องผ่านด่านอะไร

    ⚠️ **ไม่พิมพ์รหัสผ่านให้** ตั้งใจให้เจ้าของพิมพ์เอง เพราะ reCAPTCHA
    เด้งทุกครั้งอยู่แล้ว (3/3 รอบเมื่อ 10 ก.ย.) พิมพ์ให้ก็ยังต้องรอคนติ๊กอยู่ดี
    """
    from playwright.sync_api import sync_playwright
    from flow_worker import open_browser, flow_gen_profile_dir, FLOW_LOCK

    email = str(email or "").strip()
    if email not in flow_accounts.emails():
        raise LoginFailed(f"ไม่มีบัญชี {email} ในทะเบียน — เพิ่มก่อนด้วยหน้าต่างกรอกบัญชี")

    folder = flow_accounts.profile_dir_of(email)
    folder.mkdir(parents=True, exist_ok=True)
    lock = (FLOW_LOCK if folder == flow_gen_profile_dir()
            else f"flow-acct-{folder.name}")

    log(f"บัญชี  : {flow_accounts.mask(email)}")
    log(f"โฟลเดอร์: {folder}")
    with shared.browser_lock(timeout=180, label=f"ตั้งค่าโปรไฟล์ {flow_accounts.mask(email)}",
                             profile=lock):
        with sync_playwright() as pw:
            browser = open_browser(pw, hidden=False, profile_dir=folder)
            page = browser.pages[0] if browser.pages else browser.new_page()
            got = profile_check(page, email, log)
            if got["ok"]:
                log(f"   ✓ ล็อกอินไว้อยู่แล้ว เครดิต {got['credits']}")
            else:
                log(f"   · {got['why']}")
                log("")
                log("   👉 ล็อกอินในหน้าต่าง Chrome ที่เพิ่งเปิดขึ้นมาได้เลย")
                log(f"      ใช้บัญชี {email}")
                log(f"      ผมรออยู่ {wait_minutes} นาที เช็คให้ทุก 15 วินาที")
                log("")
                deadline = time.time() + wait_minutes * 60
                while time.time() < deadline:
                    time.sleep(15)
                    got = profile_check(page, email, lambda *_: None)
                    if got["ok"]:
                        break
                    left = int((deadline - time.time()) / 60)
                    log(f"   ยังไม่ผ่าน ({got['why']}) · เหลือ {left} นาที")
            browser.close()

    if not got["ok"]:
        flow_accounts.set_ready(email, False, got["why"])
        raise LoginFailed(f"ตั้งค่าโปรไฟล์ {flow_accounts.mask(email)} ไม่สำเร็จ — {got['why']}")

    flow_accounts.set_ready(email, True, f"เครดิต {got['credits']} ตอนตั้งค่า")
    flow_accounts.note_credits(email, got["credits"])
    log(f"   ✓ พร้อมใช้แล้ว — {flow_accounts.mask(email)} เครดิต {got['credits']}")
    return {"ok": True, "email": email, "credits": got["credits"],
            "profile": str(folder)}


def profile_board(log=print) -> dict:
    """โปรไฟล์ของแต่ละบัญชีพร้อมหรือยัง — ไม่เปิดเบราว์เซอร์ ดูจากไฟล์อย่างเดียว"""
    board = flow_accounts.board()
    log(f"โปรไฟล์เก็บที่ {board['profiles_dir']}")
    log("")
    for row in board["accounts"]:
        if row["profile_ready"]:
            mark, note = "✓", f"พร้อม (ตรวจเมื่อ {row['profile_ready_at'][:16]})"
        elif row["profile_used"]:
            mark, note = "!", "มีโฟลเดอร์แล้วแต่ยังไม่ได้ตรวจว่าล็อกอินอยู่"
        else:
            mark, note = "·", "ยังไม่ได้ตั้งค่า — ต้องล็อกอินครั้งแรก"
        log(f" {mark} {row['masked']:<20} {note}")
    log("")
    log(f"พร้อมใช้ {board['ready']} จาก {board['count']} บัญชี")
    return board


# ------------------------------------------------------------------ ทีละขั้น

def step_logout(page, log) -> str:
    """ขั้น 1 — ออกจากบัญชีเดิมก่อน

    **ต้องออกก่อนเสมอ** ถ้าไม่ออก Google จะพาเข้าแอปด้วยบัญชีเดิมทันที
    แล้วเราจะไม่ได้สลับอะไรเลย
    """
    page.goto(LOGOUT_URL, wait_until="domcontentloaded", timeout=90_000)
    time.sleep(3)
    _check_screen(page, "ออกจากบัญชี")
    return f"ออกจากบัญชีเดิมแล้ว (อยู่ที่ {page.url[:60]})"


def step_open_signin(page, log) -> str:
    """ขั้น 2 — เปิด Flow ให้มันเด้งไปหน้าล็อกอิน"""
    page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=120_000)
    time.sleep(4)
    if SIGNIN_HOST not in page.url:
        for label in ("Sign in", "ลงชื่อเข้าใช้", "Create with Google Flow"):
            try:
                page.get_by_text(label, exact=False).first.click(timeout=6_000)
                time.sleep(4)
                break
            except Exception:                                # noqa: BLE001
                continue
    _check_screen(page, "เปิดหน้าล็อกอิน")
    if SIGNIN_HOST not in page.url:
        _shot(page, "ไม่เด้งไปหน้าล็อกอิน")
        raise LoginFailed(f"เปิด Flow แล้วไม่ไปหน้าล็อกอิน (อยู่ที่ {page.url[:70]})")
    return "อยู่หน้าล็อกอิน Google แล้ว"


def step_choose_account(page, email: str, log) -> str:
    """ขั้น 3 — หน้า "เลือกบัญชี" ที่ Google จำบัญชีเก่าไว้

    **ขั้นนี้ของจริงมี แต่ผมเดาไม่ถึง** (เจอ 10 ก.ย. 2569) — ออกจากบัญชีแล้ว
    Google ไม่ได้พาไปหน้ากรอกอีเมล แต่พาไปหน้าที่ลิสต์บัญชีเก่าไว้ให้เลือก

    มีสองทาง
      · บัญชีที่ต้องการอยู่ในลิสต์  → กดเลย **ข้ามขั้นกรอกอีเมลไปเลย**
      · ไม่อยู่ในลิสต์             → กด "ใช้บัญชีอื่น" แล้วค่อยกรอกอีเมล

    คืนข้อความขึ้นต้นด้วย "ข้ามอีเมล" ถ้ากดบัญชีในลิสต์ได้ — ผู้เรียกต้องข้าม
    ขั้นถัดไป **ห้ามกรอกอีเมลซ้ำ** เพราะหน้าถัดไปคือช่องรหัสผ่านแล้ว
    """
    if "accountchooser" not in page.url.lower():
        return "ไม่ได้อยู่หน้าเลือกบัญชี ข้ามขั้นนี้"

    try:
        page.get_by_text(email, exact=False).first.click(timeout=8_000)
        time.sleep(4)
        _check_screen(page, "เลือกบัญชีจากลิสต์")
        return f"ข้ามอีเมล — กดบัญชี {flow_accounts.mask(email)} จากลิสต์ได้เลย"
    except LoginBlocked:
        raise
    except Exception:                                        # noqa: BLE001
        pass

    for label in ("Use another account", "ใช้บัญชีอื่น", "เพิ่มบัญชีอื่น"):
        try:
            page.get_by_text(label, exact=False).first.click(timeout=8_000)
            time.sleep(4)
            _check_screen(page, "กดใช้บัญชีอื่น")
            return "ไม่มีบัญชีนี้ในลิสต์ — กด “ใช้บัญชีอื่น” แล้ว"
        except LoginBlocked:
            raise
        except Exception:                                    # noqa: BLE001
            continue

    _shot(page, "หน้าเลือกบัญชีแต่กดอะไรไม่ได้")
    raise LoginFailed("อยู่หน้าเลือกบัญชี แต่หาทั้งบัญชีที่ต้องการและปุ่ม "
                      "“ใช้บัญชีอื่น” ไม่เจอ")


def step_email(page, email: str, log) -> str:
    """ขั้น 4 — พิมพ์อีเมลแล้วกดถัดไป

    ⚠️ **ต้องเล็งช่องที่มองเห็นเท่านั้น** หน้านี้มีช่องซ่อน `#hiddenEmail`
    ที่มีอีเมลเก่าค้างอยู่ ถ้าเล็ง `input[type=email]` เฉยๆ จะไปโดนช่องนั้น
    แล้วกดไม่ได้เพราะมองไม่เห็น (เจอจริง 10 ก.ย. 2569)
    """
    _type_like_human(page, "input[type=email]:visible", email)
    page.keyboard.press("Enter")
    time.sleep(4)
    _check_screen(page, "กรอกอีเมล")
    try:
        page.wait_for_selector("input[type=password]:visible", timeout=25_000)
    except Exception as error:                               # noqa: BLE001
        _shot(page, "กรอกอีเมลแล้วไม่มีช่องรหัสผ่าน")
        raise LoginFailed(
            "กรอกอีเมลแล้วช่องรหัสผ่านไม่โผล่ — "
            f"หน้าจออาจเป็นอย่างอื่น ({page.url[:70]})") from error
    return f"รับอีเมล {flow_accounts.mask(email)} แล้ว ช่องรหัสผ่านโผล่แล้ว"


def step_password(page, email: str, log) -> str:
    """ขั้น 5 — พิมพ์รหัสผ่านแล้วกดถัดไป

    ⚠️ รหัสผ่านอยู่ในหน่วยความจำสั้นที่สุดเท่าที่ทำได้ **ห้าม log ห้ามส่งต่อ**
    """
    try:
        page.wait_for_selector("input[type=password]:visible", timeout=25_000)
    except Exception as error:                               # noqa: BLE001
        _shot(page, "ไม่เจอช่องรหัสผ่าน")
        raise LoginFailed(f"ไม่เจอช่องรหัสผ่าน ({page.url[:70]})") from error

    secret = flow_accounts.password_for(email)
    try:
        _type_like_human(page, "input[type=password]:visible", secret)
    finally:
        secret = None                # ทิ้งทันทีที่พิมพ์เสร็จ
    page.keyboard.press("Enter")
    time.sleep(6)
    _check_screen(page, "กรอกรหัสผ่าน")
    return "ส่งรหัสผ่านแล้ว"


def step_verify(page, log, tries: int = 10) -> str:
    """ขั้น 6 — ยืนยันว่าเข้า Flow ได้จริง โดย **อ่านยอดเครดิตให้ได้**

    ไม่ใช้ "ออกจากหน้าล็อกอินแล้วหรือยัง" เพราะออกได้ทั้งตอนสำเร็จและตอนล้ม
    """
    for attempt in range(tries):
        time.sleep(5)
        _check_screen(page, "รอเข้าแอป")
        if SIGNIN_HOST in page.url:
            continue
        if "labs.google" not in page.url and "flow.google" not in page.url:
            page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=90_000)
            time.sleep(4)
        credits = _credits_now(page)
        if credits is not None:
            return f"เข้า Flow ได้จริง · เครดิตเหลือ {credits:,} หน่วย"
        log(f"  …ยังอ่านเครดิตไม่ได้ (รอบ {attempt + 1}/{tries})")
    _shot(page, "ล็อกอินแล้วแต่อ่านเครดิตไม่ได้")
    raise LoginFailed(
        "ล็อกอินแล้วแต่ **อ่านยอดเครดิตไม่ได้** — ยังไม่ยืนยันว่าใช้งานได้จริง "
        "จึงไม่นับว่าสำเร็จ")


STEPS = (
    ("1. ออกจากบัญชีเดิม", "logout"),
    ("2. เปิดหน้าล็อกอิน", "signin"),
    ("3. เลือกบัญชี", "chooser"),
    ("4. กรอกอีเมล", "email"),
    ("5. กรอกรหัสผ่าน", "password"),
    ("6. ยืนยันว่าเข้าได้จริง", "verify"),
)


def run_steps(page, email: str, log=print, dry: bool = False,
              pause: float = 0.0) -> list[str]:
    """เดินทุกขั้นบนหน้าเว็บที่เปิดค้างอยู่ — **ไม่เปิดและไม่ปิดเบราว์เซอร์เอง**

    แยกออกมาเพื่อให้เรียกจากเซสชันที่เปิดค้างไว้ได้ เจ้าของจะได้เห็นหน้าจอตลอด
    """
    done: list[str] = []
    skip_email = False
    for label, key in STEPS:
        log(f"» {label}")
        if key == "logout":
            note = step_logout(page, log)
        elif key == "signin":
            note = step_open_signin(page, log)
        elif key == "chooser":
            note = step_choose_account(page, email, log)
            skip_email = note.startswith("ข้ามอีเมล")
        elif key == "email":
            note = ("ข้าม — กดบัญชีจากลิสต์ไปแล้ว" if skip_email
                    else step_email(page, email, log))
        elif key == "password":
            note = ("ข้าม (โหมดลองแห้ง ไม่พิมพ์รหัสจริง)" if dry
                    else step_password(page, email, log))
        else:
            note = ("ข้าม (โหมดลองแห้ง)" if dry else step_verify(page, log))
        log(f"   ✓ {note}")
        done.append(f"{label} — {note}")
        _shot(page, f"หลัง{label}")
        if pause:
            time.sleep(pause)
    return done


def switch(email: str = "", log=print, teach: bool = False,
           dry: bool = False) -> dict:
    """สลับไปบัญชีที่ระบุ — ไม่ระบุ = เลือกใบถัดไปที่เครดิตยังพอ

    `teach=True`  หยุดให้ดูทุกขั้น **และไม่ปิดเบราว์เซอร์**
    `dry=True`    ทำทุกขั้นยกเว้นพิมพ์รหัสผ่านจริง
    """
    from playwright.sync_api import sync_playwright
    from flow_worker import open_browser, flow_gen_profile_dir, FLOW_LOCK

    email = str(email or "").strip()
    if not email:
        pick = flow_accounts.next_account()
        if not pick:
            raise LoginFailed("ไม่มีบัญชีสำรองที่ใช้ได้เลย — "
                              "เพิ่มบัญชีหรือเติมเครดิตก่อน")
        email = pick["email"]
    if email not in flow_accounts.emails():
        raise LoginFailed(f"ไม่มีบัญชี {flow_accounts.mask(email)} ในที่เก็บ")

    log(f"จะสลับไปบัญชี {flow_accounts.mask(email)}")
    with shared.browser_lock(timeout=120, label="สลับบัญชี Google Flow",
                             profile=FLOW_LOCK):
        with sync_playwright() as pw:
            browser = open_browser(pw, hidden=False,
                                   profile_dir=flow_gen_profile_dir())
            page = browser.pages[0] if browser.pages else browser.new_page()
            try:
                done = run_steps(page, email, log, dry=dry,
                                 pause=12.0 if teach else 0.0)
            except (LoginBlocked, LoginFailed) as error:
                flow_accounts.set_disabled(email, True, str(error)[:120])
                log(f"   ✕ {error}")
                if teach:
                    log("   (เปิดเบราว์เซอร์ค้างไว้ให้ดู — ปิดเองเมื่อพร้อม)")
                    time.sleep(600)
                raise
            if teach:
                log("   (เปิดเบราว์เซอร์ค้างไว้ให้ดู 10 นาที)")
                time.sleep(600)
            else:
                browser.close()

    flow_accounts.set_current(email)
    flow_accounts.mark_used(email)
    log(f"สลับสำเร็จ → {flow_accounts.mask(email)}")
    return {"ok": True, "email": email, "steps": done}


def resume(email: str = "", log=print) -> dict:
    """ทำต่อจากหน้าที่ค้างอยู่ — **ไม่ออกจากบัญชี ไม่เริ่มใหม่**

    ใช้ตอนที่เจ้าของเพิ่งผ่านด่าน reCAPTCHA ให้ด้วยมือ แล้วหน้าจอไปต่อได้แล้ว
    เริ่มใหม่ตั้งแต่ต้นจะต้องออกจากบัญชีอีกรอบ = มีโอกาสเจอ reCAPTCHA ซ้ำ

    ดูว่าอยู่หน้าไหนแล้วทำต่อให้ถูกขั้น
      · หน้ารหัสผ่าน    → พิมพ์รหัสแล้วยืนยัน
      · หน้าเลือกบัญชี   → เลือกบัญชี แล้วไปต่อ
      · เข้าแอปแล้ว      → ยืนยันว่าอ่านเครดิตได้จริง
    """
    from playwright.sync_api import sync_playwright
    from flow_worker import open_browser, flow_gen_profile_dir, FLOW_LOCK

    email = str(email or "").strip() or flow_accounts.current()
    if not email:
        raise LoginFailed("ไม่รู้ว่าจะทำต่อด้วยบัญชีไหน — ใส่ --อีเมล มาด้วย")

    with shared.browser_lock(timeout=120, label="ทำต่อจากหน้าล็อกอินที่ค้าง",
                             profile=FLOW_LOCK):
        with sync_playwright() as pw:
            browser = open_browser(pw, hidden=False,
                                   profile_dir=flow_gen_profile_dir())
            page = browser.pages[0] if browser.pages else browser.new_page()
            done = []
            try:
                if "labs.google" not in page.url and "accounts.google" not in page.url:
                    page.goto(FLOW_URL, wait_until="domcontentloaded",
                              timeout=120_000)
                    time.sleep(5)
                log(f"อยู่ที่ {page.url[:80]}")
                _check_screen(page, "ดูหน้าที่ค้าง")

                if "accountchooser" in page.url.lower():
                    note = step_choose_account(page, email, log)
                    log(f"   ✓ {note}")
                    done.append(note)

                has_password = False
                try:
                    page.wait_for_selector("input[type=password]:visible",
                                           timeout=8_000)
                    has_password = True
                except Exception:                            # noqa: BLE001
                    pass

                if has_password:
                    note = step_password(page, email, log)
                    log(f"   ✓ {note}")
                    done.append(note)

                note = step_verify(page, log)
                log(f"   ✓ {note}")
                done.append(note)
            except (LoginBlocked, LoginFailed) as error:
                log(f"   ✕ {error}")
                log("   (เปิดเบราว์เซอร์ค้างไว้ให้ดู 10 นาที)")
                time.sleep(600)
                raise
            log("   (เปิดเบราว์เซอร์ค้างไว้ให้ดู 5 นาที)")
            time.sleep(300)

    flow_accounts.set_current(email)
    flow_accounts.mark_used(email)
    flow_accounts.set_disabled(email, False)
    log(f"ทำต่อจนจบแล้ว → {flow_accounts.mask(email)}")
    return {"ok": True, "email": email, "steps": done}


def status(log=print) -> dict:
    """ตอนนี้ Flow เป็นบัญชีไหน เครดิตเท่าไร — ไม่แตะอะไรทั้งสิ้น"""
    from playwright.sync_api import sync_playwright
    from flow_worker import open_browser, flow_gen_profile_dir, FLOW_LOCK

    with shared.browser_lock(timeout=60, label="ดูสถานะบัญชี Flow",
                             profile=FLOW_LOCK):
        with sync_playwright() as pw:
            browser = open_browser(pw, hidden=True,
                                   profile_dir=flow_gen_profile_dir())
            page = browser.pages[0] if browser.pages else browser.new_page()
            try:
                page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=120_000)
                time.sleep(5)
                credits = _credits_now(page)
                signed = SIGNIN_HOST not in page.url and credits is not None
                return {"signed_in": signed, "credits": credits, "url": page.url}
            finally:
                browser.close()


def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("สถานะ", help="ดูว่าตอนนี้เป็นบัญชีไหน เครดิตเท่าไร")
    p_teach = sub.add_parser("สอน", help="เดินทีละขั้น หยุดให้ดู ไม่ปิดเบราว์เซอร์")
    p_teach.add_argument("--อีเมล", dest="email", default="")
    p_teach.add_argument("--ลองแห้ง", dest="dry", action="store_true",
                         help="ไม่พิมพ์รหัสจริง แค่ดูว่าหน้าจอไปถูกทางไหม")
    p_go = sub.add_parser("สลับ", help="สลับบัญชีจริง")
    p_go.add_argument("--อีเมล", dest="email", default="")
    p_more = sub.add_parser("ต่อ", help="ทำต่อจากหน้าที่ค้างอยู่ ไม่ออกจากบัญชีใหม่")
    p_more.add_argument("--อีเมล", dest="email", default="")
    p_prof = sub.add_parser("โปรไฟล์",
                            help="ตั้งค่าโปรไฟล์แยกต่อบัญชี (ล็อกอินครั้งเดียวต่อใบ)")
    p_prof.add_argument("--อีเมล", dest="email", default="",
                        help="ทำเฉพาะใบนี้ ไม่ใส่ = ไล่ทำทุกใบที่ยังไม่พร้อม")
    p_prof.add_argument("--ดู", dest="show", action="store_true",
                        help="ดูอย่างเดียว ไม่เปิดเบราว์เซอร์")
    p_prof.add_argument("--นาที", dest="minutes", type=int, default=15,
                        help="รอให้ล็อกอินนานสุดกี่นาทีต่อใบ (ค่าตั้งต้น 15)")
    args = parser.parse_args()

    if args.command == "สถานะ":
        got = status()
        print("ล็อกอินอยู่  :", "ใช่" if got["signed_in"] else "ไม่ได้ล็อกอิน")
        print("เครดิต      :", got["credits"] if got["credits"] is not None
              else "อ่านไม่ได้")
        print("บัญชีที่จำไว้ :", flow_accounts.mask(flow_accounts.current())
              or "ยังไม่ได้ตั้ง")
        return 0

    if args.command == "โปรไฟล์":
        if args.show:
            profile_board()
            return 0
        todo = ([args.email] if args.email
                else [e for e in flow_accounts.emails()
                      if not flow_accounts.is_ready(e)])
        if not todo:
            print("ทุกบัญชีพร้อมใช้แล้ว ไม่มีอะไรต้องตั้งค่า")
            profile_board()
            return 0
        print(f"ต้องตั้งค่า {len(todo)} บัญชี — ล็อกอินครั้งเดียวต่อใบ\n")
        done, failed = [], []
        for number, email in enumerate(todo, 1):
            print(f"[{number}/{len(todo)}] ----------------------------------")
            try:
                setup_profile(email, wait_minutes=args.minutes)
                done.append(email)
            except (LoginBlocked, LoginFailed) as error:
                print(f"   ⛔ {error}")
                failed.append(email)
            print("")
        print(f"ตั้งค่าสำเร็จ {len(done)} ใบ · ไม่สำเร็จ {len(failed)} ใบ")
        profile_board()
        return 1 if failed else 0

    if args.command == "ต่อ":
        try:
            resume(args.email)
            return 0
        except (LoginBlocked, LoginFailed) as error:
            print(f"\n⛔ {error}")
            return 1

    if args.command in ("สอน", "สลับ"):
        try:
            switch(args.email, teach=(args.command == "สอน"),
                   dry=getattr(args, "dry", False))
            return 0
        except (LoginBlocked, LoginFailed) as error:
            print(f"\n⛔ {error}")
            return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
