"""ตัวกันคอมเมนต์ตอนโดน Facebook บล็อก

**ปัญหาที่แก้** 16 ส.ค. 2026 คอมเมนต์ขึ้นปกติ 58 ครั้งตั้งแต่เที่ยงคืนถึง 14:14:14
แล้ว **ล้มรวด 32 ครั้งติดกัน 5 ชั่วโมง 15 นาที ไม่สำเร็จแม้แต่ครั้งเดียว** —
ครอบคลุมข้อความ 3 แบบ ทั้งแนบรูปและไม่แนบ ครบทั้ง 6 กลุ่ม 3 งานคนละใบ
โค้ดชุดเดิม เครื่องเดิม ไม่มีการรีสตาร์ตคั่น = ฝั่ง Facebook ตัดการคอมเมนต์

สิ่งที่แย่กว่าตัวการโดนบล็อกคือ **ระบบไม่รู้ตัวเลย** ไม่มีตัวนับความล้มเหลว
ล้มแล้วรอบตามเก็บก็ยิงซ้ำต่อ (18:57 และ 19:29) ซึ่งนอกจากไม่ได้อะไรกลับมา
ยังเผาเวลาจอไปราว 75 นาที และตอกให้บล็อกยืดออกไปอีก

ไฟล์นี้จึงทำสามอย่าง:

  1. **ดักข้อความบล็อกบนจอ** — เจอปุ๊บพักยาว `BLOCK_COOLDOWN_HOURS`
  2. **นับล้มติดกัน** — ครบ `CONSECUTIVE_LIMIT` พักทั้งระบบ `COOLDOWN_HOURS`
     ต่อให้ Facebook ไม่ขึ้นข้อความอะไรเลย (ของจริงคือเงียบสนิท)
  3. **เพดานรายวัน** — ตัวจุดชนวนคือยอดรวมทั้งวัน (58 ครั้ง เทียบเมื่อวาน 20)
     เพดานรายชั่วโมงที่มีอยู่เดิม 12 ครั้งผ่านฉลุยตลอด จับไม่ได้

**เก็บหลักฐานทุกครั้งที่ล้ม** เพราะตอนนี้ยังแยกไม่ออกว่า "โดนบล็อก" หรือ
"Facebook เปลี่ยนหน้าจอจนหาปุ่มไม่เจอ" — สองอย่างนี้แก้คนละทางกันคนละเรื่อง
`BLOCK_HINTS` เป็นการเดาจากข้อความที่ Facebook ใช้ทั่วไป ยังไม่เคยเห็นของจริง
บนจอเครื่องนี้ พอมีไฟล์หลักฐานสักใบจะเติมคำที่ถูกต้องเข้าไปได้

ไฟล์นี้ **ไม่แตะ ADB** — รับ xml ที่ผู้เรียก dump มาแล้ว คืนคำตัดสินอย่างเดียว
"""

from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import fb_limits
import fb_auto_post
import studio_shared

def STATE_FILE():
    """แฟ้มของบัญชีที่กำลังทำงาน — ย้ายมาแยกรายบัญชี 28 ส.ค. 2569

    เดิมเป็นค่าคงที่ชี้แฟ้มใบเดียวที่ทุกบัญชีใช้ร่วมกัน พอมีบัญชีที่สอง
    ข้อมูลจะปนกันเงียบๆ จึงเปลี่ยนเป็นฟังก์ชันที่หาพาธตอนเรียกใช้
    """
    return fb_auto_post.state_file("fb_comment_guard.json")
EVIDENCE_DIR = studio_shared.POST_EVIDENCE / "comment_blocks"

# ล้มติดกันกี่ครั้งถึงถือว่าโดนบล็อก
#
# ทำไม 3: ล้มเดี่ยวๆ เกิดได้จากจอโหลดช้า/เลื่อนพลาด แต่ล้ม 3 ครั้งติดหมายถึง
# ทุกกลุ่มล้มเหมือนกันหมด ซึ่งไม่ใช่เรื่องบังเอิญแล้ว ของจริงวันที่ 16 ส.ค.
# ถ้ามีตัวนี้จะหยุดตั้งแต่ครั้งที่ 3 (14:30) แทนที่จะลากยาวถึงครั้งที่ 32 (19:34)
CONSECUTIVE_LIMIT = 3
# พักนานแค่ไหนเมื่อล้มติดกันครบเกณฑ์ (ชั่วโมง)
COOLDOWN_HOURS = 6.0
# พักนานแค่ไหนเมื่อเห็นข้อความบล็อกจาก Facebook ตรงๆ (ชั่วโมง)
#
# ทำไมนานกว่า: ครั้งที่เจอชัดเจน 11 ส.ค. ล้มตอน 16:17 แล้วกลับมาคอมเมนต์ได้
# อีกทีวันรุ่งขึ้น 13:06 — ห่างกัน 21 ชั่วโมง พัก 12 ชั่วโมงจึงยังเป็นการเดาที่
# ระวังตัวน้อยกว่าของจริงด้วยซ้ำ
BLOCK_COOLDOWN_HOURS = 12.0
# เพดานคอมเมนต์ต่อวัน — นับเฉพาะที่ขึ้นจริง
#
# **ตัวเลขจริงย้ายไปตั้งที่ fb_limits แล้ว ตั้งแยกรายบัญชีได้** เพราะ Facebook
# ให้เพดานไม่เท่ากันในแต่ละบัญชี ค่าคงที่ตัวนี้เหลือไว้เป็นค่าตั้งต้นเท่านั้น
# ที่มาของเลข 50 กับหลักฐานทั้งหมดที่เคยอยู่ตรงนี้ ย้ายไปอยู่ในหัวไฟล์ fb_limits
DAILY_LIMIT = fb_limits.DEFAULTS["per_day"]


def daily_limit(account: str = "") -> int:
    """เพดานต่อวันของบัญชีนั้น — ตั้งได้ที่ fb_limits"""
    return fb_limits.per_day(account)
# เก็บไฟล์หลักฐานไว้กี่ใบ
KEEP_EVIDENCE = 40

# ข้อความที่ Facebook ขึ้นเวลาบล็อก — จับแบบ "มีคำนี้อยู่ในจอ"
#
# **ยังไม่ยืนยันกับจอจริง** ทั้งหมดนี้มาจากข้อความมาตรฐานของ Facebook ภาษาไทย
# และอังกฤษ ตัวที่เคยเห็นบนเครื่องนี้จริงยังไม่มีสักคำ เพราะรอบที่โดนไม่ได้เก็บจอ
# ไว้เลย — พอไฟล์หลักฐานใบแรกเข้ามาให้เอาคำจริงมาเติม แล้วลบคำที่ไม่ได้ใช้ทิ้ง
#
# เลี่ยงคำสั้นอย่าง "สแปม" หรือ "spam" เดี่ยวๆ เด็ดขาด — โพสต์ในกลุ่มพูดถึงคำ
# พวกนี้ได้ตามปกติ จับแล้วจะพักคอมเมนต์ทั้งระบบทั้งที่ไม่ได้โดนอะไร
BLOCK_HINTS: tuple[tuple[str, str], ...] = (
    ("ถูกบล็อกชั่วคราว", "Facebook บล็อกชั่วคราว"),
    ("บล็อกชั่วคราวจากการใช้ฟีเจอร์นี้", "Facebook บล็อกฟีเจอร์นี้ชั่วคราว"),
    ("คุณถูกบล็อกจากการใช้ฟีเจอร์นี้", "Facebook บล็อกฟีเจอร์นี้"),
    ("การกระทำนี้ถูกบล็อก", "Facebook บล็อกการกระทำนี้"),
    ("ใช้ฟีเจอร์นี้ไม่ได้ในขณะนี้", "Facebook ปิดฟีเจอร์นี้ชั่วคราว"),
    ("คุณทำแบบนี้เร็วเกินไป", "Facebook เตือนว่าทำเร็วเกินไป"),
    ("โพสต์เร็วเกินไป", "Facebook เตือนว่าโพสต์เร็วเกินไป"),
    ("ลองใหม่อีกครั้งในภายหลัง", "Facebook ให้รอแล้วลองใหม่"),
    ("ขัดต่อมาตรฐานชุมชน", "Facebook แจ้งว่าขัดมาตรฐานชุมชน"),
    ("ไม่เป็นไปตามมาตรฐานชุมชน", "Facebook แจ้งว่าขัดมาตรฐานชุมชน"),
    ("ความคิดเห็นของคุณถูกซ่อน", "คอมเมนต์ถูกซ่อน"),
    ("ลิงก์นี้ถูกบล็อก", "Facebook บล็อกลิงก์"),
    ("temporarily blocked", "Facebook บล็อกชั่วคราว"),
    ("blocked from using this feature", "Facebook บล็อกฟีเจอร์นี้"),
    ("this action was blocked", "Facebook บล็อกการกระทำนี้"),
    ("action blocked", "Facebook บล็อกการกระทำนี้"),
    ("you're going too fast", "Facebook เตือนว่าทำเร็วเกินไป"),
    ("posting too quickly", "Facebook เตือนว่าโพสต์เร็วเกินไป"),
    ("try again later", "Facebook ให้รอแล้วลองใหม่"),
    ("community standards", "Facebook แจ้งว่าขัดมาตรฐานชุมชน"),
    ("your comment is hidden", "คอมเมนต์ถูกซ่อน"),
)

_lock = threading.Lock()
_TEXT_RE = re.compile(r'text="([^"]*)"')


# =================================================================== สถานะ

def _blank() -> dict:
    return {"fails": 0, "blocked_until": "", "reason": "", "daily": {},
            "alert": "", "last_fail": "", "last_success": ""}


def load() -> dict:
    """อ่านสถานะจากไฟล์ — พังยังไงก็ต้องคืน dict ที่ใช้ได้"""
    try:
        raw = json.loads(STATE_FILE().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _blank()
    if not isinstance(raw, dict):
        return _blank()
    state = _blank()
    state.update({k: v for k, v in raw.items() if k in state})
    if not isinstance(state["daily"], dict):
        state["daily"] = {}
    return state


def save(state: dict) -> None:
    try:
        STATE_FILE().parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE().write_text(json.dumps(state, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except OSError:
        pass                          # เขียนไม่ได้ต้องไม่ล้มทั้งงาน


# ============================================================ ดักข้อความ

def screen_texts(xml: str) -> list[str]:
    """ดึงเฉพาะข้อความที่มองเห็นบนจอออกมาจาก dump"""
    return [t for t in _TEXT_RE.findall(xml or "") if t.strip()]


def detect_block(xml: str) -> str:
    """เจอข้อความบล็อกบนจอไหม — คืนคำอธิบายเหตุผล ไม่เจอคืนค่าว่าง

    จับจากข้อความที่มองเห็นเท่านั้น ไม่ใช่ทั้ง xml — ชื่อคลาสหรือ resource-id
    ของ Facebook มีคำว่า block/blocked อยู่เต็มไปหมด จับทั้ง xml จะเจอทุกจอ
    """
    haystack = " \n ".join(screen_texts(xml)).lower()
    if not haystack:
        return ""
    for needle, reason in BLOCK_HINTS:
        if needle.lower() in haystack:
            return reason
    return ""


def save_evidence(xml: str, now: datetime | None = None,
                  directory: Path | None = None) -> Path | None:
    """เก็บจอตอนคอมเมนต์ล้มไว้ดูย้อนหลัง — คืนที่อยู่ไฟล์

    เก็บสองใบคู่กัน: `.xml` ของดิบไว้ค้นซ้ำ และ `.txt` เฉพาะข้อความบนจอ
    ซึ่งเปิดอ่านด้วยตาได้เลย ตอนตามหาว่า Facebook ขึ้นข้อความว่าอะไรกันแน่
    การเปิด xml ดิบยาวเป็นแสนตัวอักษรแล้วไล่หาเองคือทางที่ไม่มีใครทำจริง
    """
    if not xml:
        return None
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    # รับโฟลเดอร์ปลายทางได้ เพราะฝั่งโพสต์ก็ต้องเก็บจอตอนล้มเหมือนกัน
    # (คนละโฟลเดอร์กับของคอมเมนต์ จะได้ไม่ปนกันตอนไล่ดูย้อนหลัง)
    EVIDENCE_DIR_ = directory or EVIDENCE_DIR
    try:
        EVIDENCE_DIR_.mkdir(parents=True, exist_ok=True)
        # ล้มสองครั้งในวินาทีเดียวกันได้จริง (ทางที่หาช่องพิมพ์ไม่เจอจบเร็วมาก)
        # ชื่อชนกันแล้วใบเก่าจะถูกทับเงียบๆ — หลักฐานหายไปโดยไม่มีใครรู้
        if (EVIDENCE_DIR_ / f"{stamp}.xml").exists():
            serial = 2
            while (EVIDENCE_DIR_ / f"{stamp}-{serial}.xml").exists():
                serial += 1
            stamp = f"{stamp}-{serial}"
        target = EVIDENCE_DIR_ / f"{stamp}.xml"
        target.write_text(xml, encoding="utf-8")
        (EVIDENCE_DIR_ / f"{stamp}.txt").write_text(
            "\n".join(screen_texts(xml)), encoding="utf-8")
        keep = sorted(EVIDENCE_DIR_.glob("*.xml"))[-KEEP_EVIDENCE:]
        for old in EVIDENCE_DIR_.glob("*.*"):
            if old.stem not in {p.stem for p in keep}:
                old.unlink(missing_ok=True)
        return target
    except OSError:
        return None


# ============================================================ คำตัดสิน

def _clock(when: datetime) -> str:
    """เวลาแบบอ่านง่าย — ประกอบเอง ไม่ผ่าน strftime ที่มีตัวอักษรไทย"""
    return f"{when.hour:02d}:{when.minute:02d} น. วันที่ {when.day}/{when.month}"


def hold_reason(now: datetime | None = None, account: str = "") -> str:
    """ตอนนี้ห้ามคอมเมนต์เพราะอะไร — ว่างแปลว่าคอมเมนต์ได้

    `account` มีผลกับ **เพดานรายวัน** เท่านั้น ส่วนสถานะ "โดนบล็อก" ยังเป็นของ
    ทั้งระบบร่วมกัน เพราะตัวจับบล็อกอ่านจากหน้าจอ ไม่ได้แยกว่าเป็นบัญชีไหน
    """
    now = now or datetime.now()
    state = load()
    until = state.get("blocked_until") or ""
    if until:
        try:
            edge = datetime.fromisoformat(until)
        except ValueError:
            edge = None
        if edge and now < edge:
            left = (edge - now).total_seconds() / 60
            reason = state.get("reason") or "ล้มติดกันหลายครั้ง"
            # ห้ามใส่ตัวอักษรไทยลงใน strftime — บน Windows ตัว locale codec
            # เข้ารหัสไม่ได้แล้วโยน UnicodeEncodeError ทั้งที่แค่จะจัดรูปเวลา
            return (f"พักคอมเมนต์อยู่ ({reason}) — เปิดอีกที "
                    f"{_clock(edge)} อีก {left / 60:.1f} ชม.")
    used = daily_used(now, state)
    cap = daily_limit(account)
    if used >= cap:
        return f"ครบเพดานวันละ {cap} คอมเมนต์แล้ว (วันนี้ {used})"
    return ""


def daily_used(now: datetime | None = None, state: dict | None = None) -> int:
    now = now or datetime.now()
    state = state if state is not None else load()
    return int(state.get("daily", {}).get(now.date().isoformat(), 0))


def daily_left(now: datetime | None = None, account: str = "") -> int:
    """วันนี้เหลือคอมเมนต์ได้อีกกี่ครั้งตามเพดานของบัญชีนั้น

    **ตัวนับรายวันยังเป็นถังรวมของทุกบัญชี** ส่วนเพดานแยกรายบัญชีแล้ว — สายนี้มี
    มือถือเครื่องเดียวจึงให้ผลเท่ากันเป๊ะ วันที่เพิ่มเครื่องที่สองจะกลายเป็น
    **รัดกว่าความจริง** (นับของอีกบัญชีเป็นของตัวเอง) ซึ่งเป็นทางที่ปลอดภัย
    ไม่ใช่ทางที่ยิงเกิน แต่ต้องมาแยกถัง (`state["daily"]` เป็นคีย์รายวันล้วน)
    """
    return max(0, daily_limit(account) - daily_used(now))


def note_success(now: datetime | None = None) -> None:
    """คอมเมนต์ขึ้นจริงหนึ่งครั้ง — ล้างตัวนับล้ม แล้วบวกยอดรายวัน"""
    now = now or datetime.now()
    with _lock:
        state = load()
        state["fails"] = 0
        state["last_success"] = now.isoformat(timespec="seconds")
        daily = state.setdefault("daily", {})
        key = now.date().isoformat()
        daily[key] = int(daily.get(key, 0)) + 1
        _prune_daily(daily, now)
        save(state)


def note_failure(xml: str = "", now: datetime | None = None,
                 keep_evidence: bool = True) -> str:
    """คอมเมนต์ไม่ขึ้นหนึ่งครั้ง — คืนข้อความเตือนถ้าถึงเกณฑ์พัก

    เจอข้อความบล็อกบนจอ = พักทันทีไม่ต้องรอครบ 3 ครั้ง เพราะนั่นคือคำตอบแล้ว
    ไม่มีเหตุผลให้ลองต่ออีกสองครั้งเพื่อยืนยันสิ่งที่ Facebook บอกมาตรงๆ
    """
    now = now or datetime.now()
    hint = detect_block(xml)
    path = save_evidence(xml, now) if (keep_evidence and xml) else None
    with _lock:
        state = load()
        state["fails"] = int(state.get("fails", 0)) + 1
        state["last_fail"] = now.isoformat(timespec="seconds")
        fails = state["fails"]
        already_held = bool(state.get("blocked_until")) and \
            _still_held(state, now)
        note = ""
        if hint:
            hours = BLOCK_COOLDOWN_HOURS
            reason = hint
        elif fails >= CONSECUTIVE_LIMIT:
            hours = COOLDOWN_HOURS
            reason = f"คอมเมนต์ไม่ขึ้น {fails} ครั้งติด"
        else:
            hours = 0.0
            reason = ""
        if hours:
            edge = now + timedelta(hours=hours)
            # **ห้ามต่อเวลาพักเพราะล้มซ้ำระหว่างพัก**
            #
            # เจอจากเทส: ล้มครั้งที่ 4 ตอนกำลังพักอยู่ ดันเลื่อนเส้นตายออกไป
            # อีก 6 ชั่วโมงนับจากตอนนั้น ถ้ามีอะไรมาลองเรื่อยๆ เวลาพักจะไม่มี
            # วันหมด — กลายเป็นบล็อกตัวเองถาวรทั้งที่ Facebook ปลดไปนานแล้ว
            # ยกเว้นเพิ่งเห็นข้อความบล็อกของจริง ซึ่งเป็นข้อมูลใหม่ที่หนักกว่าเดิม
            old = _held_until(state)
            if old and now < old:
                edge = max(old, edge) if hint else old
            if edge > (old or edge) or not old or now >= old:
                state["reason"] = reason
            state["blocked_until"] = edge.isoformat(timespec="seconds")
            if not already_held:
                note = (
                    f"🛑 <b>หยุดคอมเมนต์ทั้งระบบแล้ว</b>\n"
                    f"เหตุผล: {reason}\n"
                    f"เปิดอีกที {_clock(edge)} (พัก {hours:.0f} ชม.)\n"
                )
                if path:
                    note += f"หลักฐานหน้าจอ: <code>{path.name}</code>\n"
                note += "ปลดเองได้ด้วย /uncomment"
                state["alert"] = note
        save(state)
    return note


def _held_until(state: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(state.get("blocked_until") or "")
    except ValueError:
        return None


def _still_held(state: dict, now: datetime) -> bool:
    edge = _held_until(state)
    return bool(edge and now < edge)


def _prune_daily(daily: dict, now: datetime) -> None:
    """เก็บยอดรายวันไว้ 14 วันพอ — ไฟล์นี้ไม่ควรโตไปเรื่อยๆ"""
    edge = (now.date() - timedelta(days=14)).isoformat()
    for key in [k for k in daily if k < edge]:
        daily.pop(key, None)


def release(now: datetime | None = None) -> str:
    """ปลดพักเอง — ใช้ตอนตรวจแล้วรู้ว่าไม่ได้โดนบล็อกจริง"""
    now = now or datetime.now()
    with _lock:
        state = load()
        was = state.get("reason") or ""
        held = bool(state.get("blocked_until")) and _still_held(state, now)
        state["fails"] = 0
        state["blocked_until"] = ""
        state["reason"] = ""
        state["alert"] = ""
        save(state)
    return f"ปลดพักคอมเมนต์แล้ว (เดิม: {was})" if held else "ตอนนี้ไม่ได้พักอยู่"


def take_alert() -> str:
    """ดึงข้อความเตือนที่ยังไม่ได้ส่ง แล้วล้างทิ้ง — กันส่งซ้ำทุกรอบ"""
    with _lock:
        state = load()
        note = state.get("alert") or ""
        if note:
            state["alert"] = ""
            save(state)
    return note


def plan_shortfall(needed: int, account: str = "",
                   now: datetime | None = None) -> str:
    """งานนี้ต้องใช้คอมเมนต์กี่ครั้ง เทียบกับที่เหลือ — คืนคำเตือน ว่าง = พอ

    **ต้องรู้ก่อนออกตัว ไม่ใช่ไปรู้ตอนตันกลางทาง** เจอจริง 18 ส.ค. งาน p52020438:
    โพสต์ขึ้นครบ 5 กลุ่มแต่ไม่มีคอมเมนต์เลยสักอัน เพราะโควตาชั่วโมงเต็มตั้งแต่
    กลุ่มแรก ระบบไล่เปิดแผงคอมเมนต์ครบทั้ง 5 กลุ่มแล้วข้ามทีละกลุ่มอย่างเงียบๆ
    เสียเวลาจอไปเปล่าๆ และได้โพสต์ที่ไม่มีลิงก์ร้านอยู่ใต้โพสต์ครบทั้ง 5 ใบ

    เตือนอย่างเดียว ไม่ห้ามโพสต์ — โพสต์ที่ไม่มีคอมเมนต์ยังมีค่ากว่าไม่ได้โพสต์
    และผู้ใช้อาจตั้งใจให้ไปเติมคอมเมนต์ทีหลังด้วย /followup อยู่แล้ว
    """
    if needed <= 0:
        return ""
    now = now or datetime.now()
    left_day = daily_left(now, account=account)
    if left_day >= needed:
        return ""
    if left_day <= 0:
        return (f"⚠️ โควตาคอมเมนต์วันนี้เต็มแล้ว ({daily_used(now)}/"
                f"{account_daily_limit(account)}) — งานนี้จะได้โพสต์อย่างเดียว "
                f"ไม่มีคอมเมนต์เลย")
    return (f"⚠️ โควตาคอมเมนต์วันนี้เหลือ {left_day} แต่งานนี้ต้องใช้ {needed} "
            f"— จะได้คอมเมนต์ไม่ครบทุกกลุ่ม")


def account_daily_limit(account: str = "") -> int:
    """เพดานรายวันของบัญชีนั้น — เผื่ออีกฝั่งตั้งแยกรายเครื่องไว้"""
    try:
        return int(fb_limits.per_day(account))
    except Exception:
        return DAILY_LIMIT


def summary_text(now: datetime | None = None, account: str = "") -> str:
    """สรุปสถานะไว้แปะใน /health"""
    now = now or datetime.now()
    state = load()
    hold = hold_reason(now, account)
    used = daily_used(now, state)
    lines = ["💬 <b>คอมเมนต์</b>"]
    lines.append(f"   วันนี้ {used}/{daily_limit(account)} · ล้มติดกัน "
                 f"{int(state.get('fails', 0))}/{CONSECUTIVE_LIMIT}")
    if hold:
        lines.append(f"   🛑 {hold}")
    else:
        lines.append("   ✅ คอมเมนต์ได้ตามปกติ")
    if state.get("last_success"):
        lines.append(f"   ขึ้นจริงล่าสุด {state['last_success'][11:16]} น.")
    try:
        shots = sorted(EVIDENCE_DIR.glob("*.txt"))
    except OSError:
        shots = []
    if shots:
        lines.append(f"   หลักฐานจอที่เก็บไว้ {len(shots)} ใบ "
                     f"(ล่าสุด {shots[-1].name})")
    return "\n".join(lines)
