"""โพสต์ประจำวัน — ตั้งเวลาไว้แล้วให้หยิบโพสต์เก่ามาลงซ้ำเองทุกวัน

**ต่างจาก `/schedule` ตรงไหน** `/schedule` ตั้งเวลาให้ **งานเดียว** ยิงครั้งเดียว
แล้วจบ ส่วนที่นี่คือ **ตารางประจำ** — 09:00 ลงโพสต์นี้ · 10:00 ลงโพสต์นั้น
วนอย่างนี้ทุกวันโดยไม่ต้องมาสั่งใหม่

**หมุนเวียนได้หลายโพสต์ต่อหนึ่งเวลา** ลงโพสต์เดิมซ้ำทุกวันเวลาเดิมเป๊ะคือรูปแบบที่
ระบบกันสแปมจับง่ายที่สุด ใส่หลายโพสต์ไว้แล้วมันจะไล่ทีละใบ วันนี้ใบ 1 พรุ่งนี้ใบ 2

**ไฟล์นี้ไม่แตะ ADB และไม่รู้จัก app.py** — เก็บตารางกับตอบว่า "ถึงเวลาอันไหนแล้ว"
ส่วนการสร้างงานจริงเป็นหน้าที่ผู้เรียก (ใช้ตัวทำซ้ำงานที่มีอยู่แล้ว)

**ตกรอบแล้วไม่ไล่ย้อน** ถ้าเครื่องดับตอน 09:00 แล้วเปิดมาอีกทีตอน 23:00 จะ
**ไม่ลงย้อนหลัง** เพราะโพสต์ขายของมีจังหวะเวลาของมัน ลงผิดเวลาไปแปดชั่วโมงไม่ได้
ช่วยอะไรนอกจากเสี่ยงโดนตีธง — ยอมได้แค่ `CATCHUP_MINUTES` เท่านั้น
"""

from __future__ import annotations

import re
from datetime import datetime, time as clock, timedelta

import studio_shared

STATE_FILE = studio_shared.post_file("fb_routines.json")

# ถึงเวลาแล้วแต่เพิ่งมาเห็นทีหลัง — ยอมลงช้าได้ไม่เกินเท่านี้ (นาที)
CATCHUP_MINUTES = 120
# กันตั้งเพลินจนกลายเป็นสแปม
MAX_ROUTINES = 12
MAX_SOURCES = 10

_TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{2})$")


class RoutineError(RuntimeError):
    """ตั้งตารางไม่ได้"""


def load() -> dict:
    return studio_shared.read_json(STATE_FILE, {}) or {}


def save(state: dict) -> None:
    studio_shared.write_json_atomic(STATE_FILE, state)


def parse_time(text: str) -> str:
    """รับ `9:00` `09:00` `9.00` → คืน `09:00` — รูปแบบอื่นถือว่าผิด

    รับจุดด้วยเพราะผู้ใช้พิมพ์ "9.00" เป็นปกติในภาษาไทย
    """
    found = _TIME_RE.match((text or "").strip())
    if not found:
        raise RoutineError(f"อ่านเวลา “{text}” ไม่ออก — ใช้แบบ 9:00 หรือ 09.00")
    hour, minute = int(found.group(1)), int(found.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise RoutineError(f"เวลา “{text}” ไม่มีอยู่จริง")
    return f"{hour:02d}:{minute:02d}"


def _as_clock(value: str) -> clock:
    hour, minute = value.split(":")
    return clock(int(hour), int(minute))


def add(times, sources: list[str], chat_id: str = "",
        now: datetime | None = None) -> list[dict]:
    """เพิ่มตารางหนึ่งเวลาหรือหลายเวลาพร้อมกัน คืนรายการที่เพิ่ม"""
    now = now or datetime.now()
    if isinstance(times, str):
        times = [times]
    wanted = [parse_time(t) for t in times if str(t).strip()]
    if not wanted:
        raise RoutineError("ยังไม่ได้บอกเวลา")
    sources = [s.strip() for s in sources if s.strip()][:MAX_SOURCES]
    if not sources:
        raise RoutineError("ยังไม่ได้บอกว่าจะเอาโพสต์ไหนมาลง")

    state = load()
    if len(state) + len(wanted) > MAX_ROUTINES:
        raise RoutineError(
            f"ตั้งได้สูงสุด {MAX_ROUTINES} เวลา (ตอนนี้มี {len(state)})"
        )
    added = []
    for value in wanted:
        if any(r["time"] == value for r in state.values()):
            raise RoutineError(f"มีตารางเวลา {value} อยู่แล้ว")
        # รหัสเรียงตามเวลาอ่านง่าย และไม่ชนกันเองเพราะห้ามเวลาซ้ำอยู่แล้ว
        key = f"r{value.replace(':', '')}"
        record = {
            "id": key, "time": value, "sources": list(sources), "next": 0,
            "enabled": True, "chat_id": chat_id, "last_run": "", "last_job": "",
            "created_at": now.isoformat(timespec="seconds"),
        }
        state[key] = record
        added.append(record)
    save(state)
    return added


def remove(key: str) -> bool:
    state = load()
    if key not in state:
        return False
    state.pop(key)
    save(state)
    return True


def set_enabled(key: str, on: bool) -> dict | None:
    state = load()
    record = state.get(key)
    if record is None:
        return None
    record["enabled"] = bool(on)
    save(state)
    return record


def listing(state: dict | None = None) -> list[dict]:
    """ทุกตาราง เรียงตามเวลา"""
    state = state if state is not None else load()
    return sorted(state.values(), key=lambda r: r["time"])


def by_index(number: int, state: dict | None = None) -> dict | None:
    """หยิบด้วยเลขลำดับที่โชว์ในรายการ (1 = รายการแรก)"""
    items = listing(state)
    return items[number - 1] if 1 <= number <= len(items) else None


def due(now: datetime | None = None, state: dict | None = None) -> list[dict]:
    """ตารางที่ถึงเวลาต้องลงแล้วและยังไม่ได้ลงวันนี้"""
    now = now or datetime.now()
    today = now.date().isoformat()
    ready = []
    for record in listing(state):
        if not record.get("enabled", True) or record.get("last_run") == today:
            continue
        at = datetime.combine(now.date(), _as_clock(record["time"]))
        if now < at:
            continue
        if now - at > timedelta(minutes=CATCHUP_MINUTES):
            continue        # ตกรอบไปไกลแล้ว ปล่อยผ่าน (ตัวเรียกจะทำเครื่องหมายให้)
        ready.append(record)
    return ready


def missed(now: datetime | None = None, state: dict | None = None) -> list[dict]:
    """ตารางที่เลยเวลามาไกลเกินจะลงย้อนหลังแล้ว — ควรทำเครื่องหมายข้ามไว้"""
    now = now or datetime.now()
    today = now.date().isoformat()
    late = []
    for record in listing(state):
        if not record.get("enabled", True) or record.get("last_run") == today:
            continue
        at = datetime.combine(now.date(), _as_clock(record["time"]))
        if now - at > timedelta(minutes=CATCHUP_MINUTES):
            late.append(record)
    return late


def current_source(record: dict) -> str:
    sources = record.get("sources") or []
    if not sources:
        return ""
    return sources[record.get("next", 0) % len(sources)]


def mark_fired(key: str, job_id: str = "", now: datetime | None = None,
               advance: bool = True) -> dict | None:
    """บันทึกว่าลงของวันนี้ไปแล้ว แล้วเลื่อนไปโพสต์ใบถัดไป

    **ต้องเรียกทุกครั้งที่ลงมือจริง** ไม่งั้นตัวเดินงานจะเห็นว่ายังไม่ได้ลง
    แล้วยิงซ้ำทุกรอบที่วนมา (บทเรียนจาก `/pending` 14 ส.ค. ที่ยิงทุก 10 นาที
    เพราะตัวนับไม่เคยถูกเขียน)
    """
    now = now or datetime.now()
    state = load()
    record = state.get(key)
    if record is None:
        return None
    record["last_run"] = now.date().isoformat()
    if job_id:
        record["last_job"] = job_id
    if advance and record.get("sources"):
        record["next"] = (record.get("next", 0) + 1) % len(record["sources"])
    save(state)
    return record


def mark_skipped(key: str, now: datetime | None = None) -> dict | None:
    """ข้ามของวันนี้ไปเลย (ตกรอบ) — ไม่เลื่อนคิวโพสต์ เพราะยังไม่ได้ลงสักใบ"""
    return mark_fired(key, now=now, advance=False)


def summary_text(state: dict | None = None, label=None,
                 now: datetime | None = None) -> str:
    """ข้อความสรุปตารางสำหรับ Telegram"""
    now = now or datetime.now()
    items = listing(state)
    if not items:
        return ("🗓 <b>ยังไม่มีโพสต์ประจำวัน</b>\n"
                "ตั้งด้วย <code>/routine add 9:00 &lt;รหัสงาน&gt;</code>\n"
                "ดูรหัสงานเก่าได้จาก /repost")
    naming = label or (lambda job_id: job_id)
    today = now.date().isoformat()
    lines = [f"🗓 <b>โพสต์ประจำวัน {len(items)} เวลา</b>"]
    for number, record in enumerate(items, 1):
        mark = "✅" if record.get("enabled", True) else "⏸"
        done = " · ลงของวันนี้แล้ว" if record.get("last_run") == today else ""
        sources = record.get("sources") or []
        current = current_source(record)
        lines.append(
            f"{number}. {mark} <b>{record['time']}</b>{done}\n"
            f"     คิวถัดไป: {naming(current)}"
            + (f" (หมุนเวียน {len(sources)} โพสต์)" if len(sources) > 1 else "")
        )
    lines += [
        "",
        "<code>/routine add 9:00,10:00 &lt;รหัสงาน&gt;</code> เพิ่ม",
        "<code>/routine del 1</code> · <code>/routine off 1</code> · "
        "<code>/routine run 1</code>",
    ]
    return "\n".join(lines)
