"""ที่เก็บบัญชี Google Flow หลายใบ + ตัวตัดสินว่าเมื่อไรควรสลับไปใบถัดไป

**เจ้าของสั่ง 9 ก.ย. 2569** — *"ในขั้นตอนการเจน google flow ผมต้องการสลับไอดี
ในการทำ 1.สร้างตัวเก็บ user email กับ password ผมจะเป็นคนกรอกเก็บไว้ แล้วเซฟไว้
2.มีตัวเช็คเครดิต ถ้าเหลือน้อยกว่า 15 ให้ทำการเปลี่ยน email โดยดึง password
จากที่เก็บไว้มาวาง 3.ผมจะสอนวิธีการเปลี่ยน user ให้ทำตามทีละขั้น"*

ไฟล์นี้ทำข้อ 1 กับ 2 เท่านั้น — **ขั้นตอนกดเปลี่ยนบัญชีจริง (ข้อ 3) ยังไม่มี**
เจ้าของจะสอนทีละขั้น แล้วค่อยเขียนลงไฟล์แยกต่างหาก ที่นี่จึงมีแค่ "เก็บ" กับ
"ตัดสินใจ" ไม่มีการแตะหน้าจอ


รหัสผ่านเก็บยังไง
-----------------

ใช้ `studio_shared.save_key` / `load_key` **ตัวเดียวกับที่โปรเจกต์ใช้เก็บโทเคน
Telegram และคีย์ Gemini อยู่แล้ว** ไม่สร้างวิธีใหม่ซ้อน

เบื้องหลังคือ DPAPI ของ Windows ซึ่ง**ผูกกับบัญชีผู้ใช้ Windows ที่เข้ารหัส**
ถ้ามีคนก๊อปไฟล์นี้ไปเปิดที่เครื่องอื่นหรือด้วยบัญชี Windows อื่น **ถอดไม่ออก**

**แยกเป็นสองไฟล์โดยตั้งใจ**

    data/flow_accounts.bin    อีเมล + รหัสผ่าน   (เข้ารหัส ต้องถอดถึงจะอ่านได้)
    data/flow_accounts.json   สถานะการใช้งาน    (อ่านได้เปล่าๆ ไม่มีความลับเลย)

เพราะหน้าเว็บกับกระดานต้องรู้ว่า "บัญชีไหนเหลือเครดิตเท่าไร ใช้อยู่ใบไหน"
ตลอดเวลา ถ้ายัดรวมไฟล์เดียว ทุกครั้งที่จะโชว์สถานะต้องถอดรหัสไฟล์ที่มีรหัสผ่าน
อยู่ข้างใน — ยิ่งถอดบ่อยยิ่งมีโอกาสหลุดไปโผล่ใน log


กติกาที่ห้ามละเมิดในไฟล์นี้
--------------------------

1. **ห้ามให้รหัสผ่านออกไปทาง log · ข้อความแชท · หน้าเว็บ · ไฟล์หลักฐาน**
   ฟังก์ชันที่คืนรายชื่อบัญชี (`board`) **ไม่คืนรหัสผ่านเด็ดขาด** บอกได้แค่ว่า
   "มีรหัสเก็บไว้แล้วหรือยัง"
2. **`password_for()` เป็นทางเดียวที่ได้รหัสจริง** ใครเรียกต้องเอาไปวางในช่อง
   ทันที ห้ามเก็บใส่ตัวแปรค้างไว้ ห้ามส่งต่อ
3. **ห้ามใส่รหัสผ่านลงใน URL หรือ query string** ทุกกรณี
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import studio_shared as shared

DATA_DIR = shared.DATA_DIR
SECRET_FILE = DATA_DIR / "flow_accounts.bin"
STATE_FILE = DATA_DIR / "flow_accounts.json"

# เครดิตขั้นต่ำที่ยังเจนได้อีกหนึ่งใบ — หนึ่งคลิปกินเท่านี้พอดี
#
# **เจ้าของกำหนดเลข 15 มาเอง** และเป็นเลขเดียวกับ `clip_app.FLOW_CREDIT_PER_CLIP`
# ไม่ได้ import มาเพราะไฟล์นั้นเป็นเซิร์ฟเวอร์ทั้งตัว จะลากของมาเต็มไปหมด
# **ถ้าวันหนึ่งราคาต่อคลิปเปลี่ยน ต้องแก้ทั้งสองที่** — มีตัวตรวจกันลืมอยู่ใน
# `test_flow_accounts.py`
CREDIT_PER_CLIP = 15


# ---- โปรไฟล์ Chrome แยกต่อบัญชี (เจ้าของสั่ง 10 ก.ย. 2569) -----------------
#
# **หนึ่งบัญชี = หนึ่งโฟลเดอร์โปรไฟล์** ล็อกอินค้างไว้ในนั้นครั้งเดียว
# สลับบัญชี = เปิด Chrome คนละโฟลเดอร์ **ไม่ต้องล็อกอินใหม่ ไม่เจอ reCAPTCHA**
#
# ทำไมถึงเลิกใช้วิธีล็อกอินสลับ: ลองของจริง 10 ก.ย. แล้ว Google เด้ง reCAPTCHA
# **ทุกครั้ง** (เจอ 3 รอบติด) ซึ่งต้องมีคนติ๊กให้ ระบบจึงทำงานกลางคืนเองไม่ได้
#
# ระบบนี้ทำแบบนี้อยู่แล้วกับช่องที่ 2 (`flow_browser_profile2`) ตัวนี้แค่ขยาย
# ให้ครบทุกบัญชี แทนที่จะเขียนชื่อโฟลเดอร์ตายตัวทีละอัน
PROFILES_DIR = DATA_DIR / "flow_profiles"


def profile_slug(email: str) -> str:
    """ชื่อโฟลเดอร์จากอีเมล — ปลอดภัยกับระบบไฟล์ และอ่านออกว่าใบไหน"""
    name = str(email or "").strip().lower().split("@")[0]
    keep = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)
    return keep or "unknown"


def profile_dir_of(email: str) -> Path:
    """โฟลเดอร์โปรไฟล์ Chrome ของบัญชีนี้ (ไม่สร้างให้ แค่บอกว่าอยู่ตรงไหน)

    ตั้งชื่อโฟลเดอร์เองไว้ในทะเบียน = ตัวนั้นชนะ (ใส่พาธเต็มก็ได้)
    ใช้ตอนอยากให้บัญชีหนึ่งไปใช้โฟลเดอร์เดิมที่ล็อกอินค้างอยู่แล้ว
    """
    named = str(((_state().get(str(email)) or {}).get("profile") or "")).strip()
    if named:
        path = Path(named)
        return path if path.is_absolute() else DATA_DIR / named
    return PROFILES_DIR / profile_slug(email)


def set_profile(email: str, folder: str) -> None:
    """ผูกบัญชีนี้กับโฟลเดอร์โปรไฟล์ที่ตั้งชื่อเอง (ค่าว่าง = กลับไปใช้ชื่อจากอีเมล)"""
    def mutate(state: dict):
        state.setdefault(str(email), {})["profile"] = str(folder or "").strip()
        return state

    _update_state(mutate)


def set_ready(email: str, ready: bool, note: str = "") -> None:
    """จดว่าโปรไฟล์ของบัญชีนี้ล็อกอินค้างไว้เรียบร้อยแล้วหรือยัง

    **ต้องจดแยกจาก "มีรหัสผ่านเก็บไว้"** — มีรหัสไม่ได้แปลว่าล็อกอินไว้แล้ว
    ถ้าเอาสองอย่างนี้ไปปนกัน ระบบจะสลับไปโฟลเดอร์ที่ยังว่างเปล่า
    แล้วเจนไม่ได้ทั้งกองโดยไม่มีอะไรฟ้อง

    ⚠️ **ห้ามเรียกตัวนี้เพราะ "เห็นว่าน่าจะล็อกอินแล้ว"** ให้เรียกก็ต่อเมื่อ
    อ่านยอดเครดิตบนหน้า Flow ได้จริง (ของที่มีเฉพาะตอนสำเร็จ — กติกาข้อ 2.3.1)
    """
    def mutate(state: dict):
        entry = state.setdefault(str(email), {})
        entry["profile_ready"] = bool(ready)
        entry["profile_ready_at"] = _now() if ready else ""
        entry["profile_note"] = str(note or "")
        return state

    _update_state(mutate)


def profile_used(email: str) -> bool:
    """โฟลเดอร์นี้เคยถูก Chrome เปิดจริงแล้วหรือยัง

    ดู `Default/Preferences` ซึ่ง Chrome สร้างตอนเปิดโปรไฟล์ครั้งแรก —
    **โฟลเดอร์ว่างที่เราสร้างเองจะไม่มีไฟล์นี้** จึงแยกสองสถานะออกจากกันได้
    """
    return (profile_dir_of(email) / "Default" / "Preferences").is_file()


def is_ready(email: str) -> bool:
    """โปรไฟล์ของบัญชีนี้พร้อมใช้ไหม — **ต้องมีโฟลเดอร์จริงอยู่ด้วย**

    ไม่เชื่อธงในไฟล์อย่างเดียว เพราะโฟลเดอร์ถูกลบทิ้งได้โดยที่ธงยังค้างอยู่
    แล้วระบบจะพาไปเปิด Chrome เปล่าๆ (กติกาข้อ 2.3.1)
    """
    if not (_state().get(str(email)) or {}).get("profile_ready"):
        return False
    return profile_used(email)


def ready_accounts() -> list[str]:
    """บัญชีที่โปรไฟล์พร้อมใช้จริง เรียงตามลำดับที่ใส่ไว้"""
    return [e for e in emails() if is_ready(e)]


class FlowAccountError(RuntimeError):
    """ข้อมูลบัญชีไม่ครบหรือใช้ไม่ได้"""


# --------------------------------------------------------------- ที่เก็บความลับ

def _read_secrets() -> list[dict]:
    """อ่านบัญชีทั้งหมดพร้อมรหัสผ่าน — **ใช้ให้น้อยที่สุด**"""
    raw = shared.load_key(SECRET_FILE)
    if not raw:
        return []
    try:
        rows = json.loads(raw)
    except ValueError:
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("email")]


def _write_secrets(rows: list[dict]) -> None:
    shared.save_key(SECRET_FILE, json.dumps(rows, ensure_ascii=False))


def _state() -> dict:
    return shared.read_json(STATE_FILE, {}) or {}


def _update_state(mutate) -> dict:
    return shared.update_json(STATE_FILE, mutate, default={})


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mask(email: str) -> str:
    """ย่ออีเมลไว้โชว์ใน log — เก็บพอให้รู้ว่าใบไหน แต่ไม่ประกาศเต็ม

    `somebody@gmail.com` → `so…dy@gmail.com`
    """
    email = str(email or "").strip()
    if "@" not in email:
        return email or "(ไม่มีอีเมล)"
    name, host = email.split("@", 1)
    if len(name) <= 4:
        return f"{name[:1]}…@{host}"
    return f"{name[:2]}…{name[-2:]}@{host}"


# ------------------------------------------------------------------ เพิ่ม/ลบ

def add(email: str, password: str, note: str = "", profile: str = "") -> str:
    """เก็บบัญชีหนึ่งใบ — มีอยู่แล้วถือว่าแก้รหัสผ่านใหม่

    `profile` = ชื่อโฟลเดอร์โปรไฟล์ Chrome ที่บัญชีนี้ใช้ (ใส่ทีหลังได้)
    เว้นว่างแปลว่าใช้โปรไฟล์กลางร่วมกับใบอื่น
    """
    email = str(email or "").strip()
    password = str(password or "")
    if "@" not in email:
        raise FlowAccountError("อีเมลไม่ถูกต้อง — ต้องมี @")
    if not password:
        raise FlowAccountError("ต้องมีรหัสผ่าน — เก็บบัญชีที่ไม่มีรหัสไว้ก็สลับไม่ได้")

    rows = _read_secrets()
    found = next((r for r in rows if r.get("email") == email), None)
    if found:
        found["password"] = password
        if note:
            found["note"] = note
        if profile:
            found["profile"] = profile
        what = "แก้รหัสผ่านแล้ว"
    else:
        rows.append({"email": email, "password": password, "note": note,
                     "profile": profile, "added_at": _now()})
        what = "เพิ่มแล้ว"
    _write_secrets(rows)

    def mutate(state: dict):
        entry = state.setdefault(email, {})
        entry.setdefault("added_at", _now())
        entry.setdefault("credits", None)
        entry.setdefault("disabled", False)
        entry["note"] = note or entry.get("note", "")
        entry["profile"] = profile or entry.get("profile", "")
        return state

    _update_state(mutate)
    return f"{what}: {mask(email)}"


def remove(email: str) -> str:
    email = str(email or "").strip()
    rows = _read_secrets()
    left = [r for r in rows if r.get("email") != email]
    if len(left) == len(rows):
        raise FlowAccountError(f"ไม่มีบัญชี {mask(email)} ในที่เก็บ")
    _write_secrets(left)
    _update_state(lambda state: state.pop(email, None) or state)
    return f"ลบแล้ว: {mask(email)}"


def emails() -> list[str]:
    """อีเมลทุกใบที่เก็บไว้ เรียงตามลำดับที่ใส่"""
    return [str(r.get("email")) for r in _read_secrets()]


def password_for(email: str) -> str:
    """รหัสผ่านของบัญชีนี้ — **ทางเดียวที่ได้ของจริง**

    ⚠️ ผู้เรียกต้องเอาไปวางในช่องทันที **ห้าม log ห้ามส่งต่อ ห้ามเก็บค้าง**
    """
    email = str(email or "").strip()
    for row in _read_secrets():
        if row.get("email") == email:
            password = str(row.get("password") or "")
            if not password:
                raise FlowAccountError(f"บัญชี {mask(email)} ไม่มีรหัสผ่านเก็บไว้")
            return password
    raise FlowAccountError(f"ไม่มีบัญชี {mask(email)} ในที่เก็บ")


# --------------------------------------------------------------- สถานะการใช้

def note_credits(email: str, credits: int | None) -> None:
    """จดเครดิตล่าสุดของบัญชีนี้

    **แยก "ยังไม่ได้อ่าน" ออกจาก "อ่านแล้วได้ศูนย์" เสมอ** (กติกาข้อ 2.3.1)
    `None` = ยังไม่รู้ ห้ามเอาไปตัดสินว่าเครดิตหมด
    """
    email = str(email or "").strip()
    if not email:
        return

    def mutate(state: dict):
        entry = state.setdefault(email, {})
        entry["credits"] = None if credits is None else int(credits)
        entry["credits_at"] = _now()
        return state

    _update_state(mutate)


def mark_used(email: str) -> None:
    def mutate(state: dict):
        entry = state.setdefault(str(email), {})
        entry["last_used_at"] = _now()
        entry["uses"] = int(entry.get("uses") or 0) + 1
        return state

    _update_state(mutate)


def set_disabled(email: str, disabled: bool, why: str = "") -> None:
    """พักบัญชีไว้ไม่ให้ถูกเลือก — เช่นโดนขอยืนยันตัวตน หรือรหัสผ่านเปลี่ยน"""
    def mutate(state: dict):
        entry = state.setdefault(str(email), {})
        entry["disabled"] = bool(disabled)
        entry["disabled_why"] = why if disabled else ""
        entry["disabled_at"] = _now() if disabled else ""
        return state

    _update_state(mutate)


def current() -> str:
    """บัญชีที่ใช้อยู่ตอนนี้ — คืน "" ถ้ายังไม่เคยตั้ง"""
    return str(_state().get("__current__", {}).get("email") or "")


def set_current(email: str) -> None:
    def mutate(state: dict):
        state["__current__"] = {"email": str(email or ""), "at": _now()}
        return state

    _update_state(mutate)


# ------------------------------------------------------------ ตัวตัดสินใจสลับ

def should_switch(credits: int | None, minimum: int = CREDIT_PER_CLIP) -> tuple[bool, str]:
    """เครดิตที่เหลือพอเจนอีกใบไหม — ไม่พอ = ต้องสลับบัญชี

    คืน `(ต้องสลับไหม, เหตุผลภาษาคน)`

    ⚠️ **อ่านเครดิตไม่ได้ ไม่ใช่เครดิตหมด** — คืน `False` พร้อมเหตุผล
    ให้ผู้เรียกไปจัดการเอง ถ้าตีความว่าหมดแล้วสลับทิ้ง จะสลับบัญชีทุกครั้งที่
    หน้าเว็บโหลดช้าจนอ่านเลขไม่ทัน (กติกาข้อ 2.3.1 ข้อ 4)
    """
    if credits is None:
        return False, "ยังอ่านเครดิตไม่ได้ — ยังไม่ตัดสินว่าต้องสลับ"
    if credits < minimum:
        return True, f"เครดิตเหลือ {credits:,} หน่วย น้อยกว่า {minimum} ที่ใช้ต่อคลิป"
    return False, f"เครดิตเหลือ {credits:,} หน่วย ยังเจนได้อีก {credits // minimum} ใบ"


def next_account(after: str = "", minimum: int = CREDIT_PER_CLIP) -> dict:
    """บัญชีถัดไปที่ควรสลับไป — **ไม่คืนรหัสผ่าน**

    เลือกจาก
      1. ข้ามใบที่ถูกพักไว้
      2. ข้ามใบที่รู้แน่ว่าเครดิตไม่พอ (`credits` อ่านมาแล้วและน้อยกว่าเกณฑ์)
         **ใบที่ยังไม่เคยอ่าน (`None`) ไม่ข้าม** เพราะยังไม่รู้ว่าพอหรือไม่พอ
      3. เรียงใบที่ยังไม่เคยใช้ก่อน แล้วค่อยใบที่ใช้ล่าสุดนานสุด

    คืน `{}` ถ้าไม่มีใบไหนใช้ได้เลย
    """
    after = str(after or "").strip() or current()
    state = _state()
    picks = []
    for email in emails():
        if email == after:
            continue
        entry = state.get(email) or {}
        if entry.get("disabled"):
            continue
        credits = entry.get("credits")
        if credits is not None and int(credits) < minimum:
            continue
        picks.append({
            "email": email,
            "credits": credits,
            "profile": entry.get("profile") or "",
            "note": entry.get("note") or "",
            "uses": int(entry.get("uses") or 0),
            "last_used_at": entry.get("last_used_at") or "",
        })
    if not picks:
        return {}
    # **ใบที่โปรไฟล์พร้อมใช้มาก่อนเสมอ** — สลับไปใบที่ยังไม่ได้ล็อกอินค้างไว้
    # เท่ากับเปิด Chrome เปล่าๆ แล้วเจนไม่ได้ทั้งกองโดยไม่มีอะไรฟ้อง
    ready = [row for row in picks if is_ready(row["email"])]
    picks = ready or picks
    picks.sort(key=lambda row: (row["uses"], row["last_used_at"]))
    return picks[0]


def board() -> dict:
    """สรุปให้คนอ่าน/หน้าเว็บ — **ไม่มีรหัสผ่านอยู่ในผลลัพธ์เด็ดขาด**"""
    state = _state()
    rows = []
    for email in emails():
        entry = state.get(email) or {}
        credits = entry.get("credits")
        rows.append({
            "email": email,
            "masked": mask(email),
            "has_password": True,          # เก็บได้ก็ต่อเมื่อมีรหัส (add บังคับ)
            "credits": credits,
            "credits_at": entry.get("credits_at") or "",
            "enough": None if credits is None else int(credits) >= CREDIT_PER_CLIP,
            "disabled": bool(entry.get("disabled")),
            "disabled_why": entry.get("disabled_why") or "",
            "profile": entry.get("profile") or "",
            "note": entry.get("note") or "",
            "uses": int(entry.get("uses") or 0),
            "last_used_at": entry.get("last_used_at") or "",
            "is_current": email == current(),
            "profile_ready": is_ready(email),
            "profile_used": profile_used(email),
            "profile_ready_at": entry.get("profile_ready_at") or "",
            "profile_dir": str(profile_dir_of(email)),
        })
    usable = [r for r in rows if not r["disabled"] and r["enough"] is not False]
    ready = [r for r in usable if r["profile_ready"]]
    return {
        "accounts": rows,
        "count": len(rows),
        "usable": len(usable),
        "ready": len(ready),
        "profiles_dir": str(PROFILES_DIR),
        "current": current(),
        "minimum": CREDIT_PER_CLIP,
        "store": str(SECRET_FILE),
        "note": ("รหัสผ่านเข้ารหัสด้วยบัญชี Windows เครื่องนี้ "
                 "ก๊อปไฟล์ไปเครื่องอื่นเปิดไม่ได้"),
    }


# ------------------------------------------------------------------ สั่งจากคอนโซล

def _cli() -> int:
    import argparse
    import getpass

    parser = argparse.ArgumentParser(
        description="ที่เก็บบัญชี Google Flow (รหัสผ่านเข้ารหัสไว้)")
    sub = parser.add_subparsers(dest="command")

    p_add = sub.add_parser("add", help="เพิ่ม/แก้บัญชี — ถามรหัสผ่านแบบไม่โชว์")
    p_add.add_argument("email")
    p_add.add_argument("--note", default="")
    p_add.add_argument("--profile", default="")

    p_del = sub.add_parser("remove", help="ลบบัญชี")
    p_del.add_argument("email")

    sub.add_parser("list", help="ดูบัญชีทั้งหมด (ไม่โชว์รหัสผ่าน)")
    p_next = sub.add_parser("next", help="ถ้าต้องสลับตอนนี้ จะไปใบไหน")
    p_next.add_argument("--after", default="")

    p_check = sub.add_parser("check", help="เครดิตเท่านี้ต้องสลับไหม")
    p_check.add_argument("credits", type=int)

    args = parser.parse_args()

    if args.command == "add":
        # **ถามผ่าน getpass** พิมพ์แล้วไม่ขึ้นบนจอ และไม่ติดไปกับประวัติคำสั่ง
        password = getpass.getpass(f"รหัสผ่านของ {args.email} (พิมพ์แล้วจะไม่เห็น): ")
        print(add(args.email, password, args.note, args.profile))
        return 0

    if args.command == "remove":
        print(remove(args.email))
        return 0

    if args.command == "next":
        pick = next_account(args.after)
        print(f"สลับไป: {mask(pick['email'])} "
              f"(เครดิตล่าสุด {pick['credits'] if pick['credits'] is not None else 'ยังไม่รู้'})"
              if pick else "ไม่มีบัญชีสำรองที่ใช้ได้เลย")
        return 0

    if args.command == "check":
        need, why = should_switch(args.credits)
        print(("ต้องสลับ — " if need else "ยังไม่ต้องสลับ — ") + why)
        return 0

    data = board()
    if not data["count"]:
        print("ยังไม่มีบัญชีเก็บไว้เลย")
        print("เพิ่มด้วย:  python flow_accounts.py add you@gmail.com")
        return 0
    print(f"บัญชี Google Flow {data['count']} ใบ · ใช้ได้ {data['usable']} ใบ "
          f"· เกณฑ์สลับ < {data['minimum']} หน่วย")
    print(f"{'':2}{'อีเมล':<28}{'เครดิต':>10}  สถานะ")
    for row in data["accounts"]:
        credits = "ยังไม่รู้" if row["credits"] is None else f"{row['credits']:,}"
        marks = []
        if row["is_current"]:
            marks.append("ใช้อยู่")
        if row["disabled"]:
            marks.append(f"พักไว้ ({row['disabled_why']})" if row["disabled_why"]
                         else "พักไว้")
        elif row["enough"] is False:
            marks.append("เครดิตไม่พอ")
        if row["profile"]:
            marks.append(f"โปรไฟล์ {row['profile']}")
        print(f"{'▶ ' if row['is_current'] else '  '}{row['masked']:<28}"
              f"{credits:>10}  {' · '.join(marks) or 'พร้อมใช้'}")
    print(f"\n{data['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
