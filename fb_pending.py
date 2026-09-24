"""ตามโพสต์ที่ยังไม่ขึ้น — กลุ่มที่ตั้งให้ผู้ดูแลอนุมัติก่อน

**ปัญหาที่แก้** กลุ่มส่วนใหญ่ตั้งให้ผู้ดูแลตรวจก่อนโพสต์ขึ้น ตอนกดโพสต์เสร็จ
โพสต์จึงยัง "รออนุมัติ" — กดถูกใจไม่ได้ คอมเมนต์ไม่ได้ เก็บลิงก์ไม่ได้ ต้องรอ
ผู้ดูแลอนุมัติแล้วค่อยกลับมาทำรอบสอง

ที่ผ่านมาต้อง **จำเอาเอง** ว่ากลุ่มไหนยังค้าง แล้วสั่ง `/followup` เองตอนนึกได้
ผลคือค้างจริง — งาน p617465263 กลุ่ม 184764596840853 ค้างข้ามวัน และย้อนดูข้อมูล
จริงพบกลุ่มที่ค้างแบบนี้ตั้งแต่ 8 ส.ค.

**เลิกตามเมื่อไร** เรื่องนี้สำคัญกว่าการตามให้ครบ:
  · เกิน `WINDOW_HOURS` (48 ชม.) — ผู้ดูแลไม่อนุมัติภายในสองวันก็คือไม่อนุมัติ
    และแจ้งเตือน/ฟีดของ Facebook ก็ไม่เหลือให้เปิดหาแล้ว
  · ครบ `MAX_TRIES` ครั้ง — ไล่เท่าไรก็ไม่ขึ้น แปลว่าไม่ใช่เรื่องของเวลา
ไล่ตามไม่เลิกคือเผาเวลาจอมือถือทิ้ง และยิ่งเปิดกลุ่มถี่ยิ่งเสี่ยงโดนตีธง

ไฟล์นี้ **ไม่แตะ ADB และไม่ยุ่งกับ app.py** — รับข้อมูลงานเข้ามา คืนว่า "ควรไล่
อะไรต่อ" ผู้เรียกเป็นคนลงมือ (ใช้ `/followup` ที่มีอยู่แล้ว)
"""

from __future__ import annotations

from datetime import datetime, timedelta

import fb_auto_post
import studio_shared

def STATE_FILE():
    """แฟ้มของบัญชีที่กำลังทำงาน — ย้ายมาแยกรายบัญชี 28 ส.ค. 2569

    เดิมเป็นค่าคงที่ชี้แฟ้มใบเดียวที่ทุกบัญชีใช้ร่วมกัน พอมีบัญชีที่สอง
    ข้อมูลจะปนกันเงียบๆ จึงเปลี่ยนเป็นฟังก์ชันที่หาพาธตอนเรียกใช้
    """
    return fb_auto_post.state_file("fb_pending.json")

# โพสต์เก่ากว่านี้ = เลิกตาม (ชั่วโมง)
WINDOW_HOURS = 48
# หลังโพสต์ต้องรออย่างน้อยเท่านี้ก่อนไล่รอบแรก — ผู้ดูแลไม่ได้นั่งเฝ้าตลอดเวลา
MIN_WAIT_HOURS = 3
# เว้นระหว่างรอบไล่
RETRY_HOURS = 4
# ไล่ได้มากสุดกี่ครั้งต่อกลุ่ม
MAX_TRIES = 4
# สถานะงานที่ไม่ไล่ตามให้เอง (ยังสั่งเองได้)
SKIP_STATUSES = {"cancelled", "failed", "stopped", "manual_done"}


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _job_time(job: dict) -> datetime | None:
    for key in ("finished_at", "started_at", "created_at"):
        found = _parse(job.get(key, ""))
        if found:
            return found
    return None


def load_state() -> dict:
    return studio_shared.read_json(STATE_FILE(), {}) or {}


def save_state(state: dict) -> None:
    studio_shared.write_json_atomic(STATE_FILE(), state)


def key_of(job_id: str, group_id: str) -> str:
    return f"{job_id}:{group_id}"


def is_stuck(result: dict, required_comments: int = 1) -> bool:
    """โพสต์ขึ้นแล้วแต่ขั้นบังคับอย่างน้อยหนึ่งอย่างยังไม่ครบหรือไม่."""
    if not result.get("posted"):
        return False
    return (
        not result.get("link")
        or not result.get("liked")
        or int(result.get("comment_count") or 0) < max(1, required_comments)
        or not result.get("commented")
        or not result.get("comment_liked")
    )


def pending_items(jobs: list[dict], now: datetime | None = None,
                  state: dict | None = None) -> list[dict]:
    """กลุ่มที่ยังค้างทั้งหมด เรียงจากที่ควรไล่ก่อน

    คืนทุกตัวที่ค้าง ไม่ใช่เฉพาะตัวที่ถึงเวลา — หน้าจอต้องเห็นของที่ "รออยู่" กับ
    "เลิกตามแล้ว" ด้วย ไม่งั้นจะดูเหมือนไม่มีอะไรค้างทั้งที่ยังมี
    """
    now = now or datetime.now()
    state = state if state is not None else load_state()
    items: list[dict] = []
    for job in jobs:
        when = _job_time(job)
        if when is None:
            continue
        hours = (now - when).total_seconds() / 3600
        if hours < 0:
            continue
        comments = job.get("comments") or ([job.get("comment", "")] if job.get("comment") else [])
        required_comments = max(1, len([c for c in comments if str(c).strip()]))
        for result in job.get("results", []):
            if not is_stuck(result, required_comments):
                continue
            group_id = str(result.get("group_id", ""))
            record = state.get(key_of(job["id"], group_id), {})
            tries = int(record.get("tries", 0))
            last = _parse(record.get("last_try", ""))
            since_try = (now - last).total_seconds() / 3600 if last else None
            if job.get("status") in SKIP_STATUSES or job.get("manual_completed"):
                # งานที่ผู้ใช้สั่งยกเลิก/ล้มไปแล้ว **ห้ามไล่เอง**
                #
                # ผลของมันมีโพสต์ที่ขึ้นจริงอยู่ (ยกเลิกกลางคัน) แต่การที่ระบบ
                # ไปเปิดงานที่เจ้าของสั่งหยุดแล้วขึ้นมาทำต่อเองคือพฤติกรรมที่
                # เซอร์ไพรส์เจ้าของ — ยังสั่งเองได้ด้วย /pending <รหัสงาน>
                # (ข้อมูลจริง 14 ส.ค.: งานยกเลิก p551626124 มี 5 กลุ่มเข้าเงื่อนไข
                #  ถึงเวลาไล่ทันที ทั้งที่โพสต์อายุ 38 ชม.แล้ว)
                status = "skipped"
                if job.get("manual_completed") or job.get("status") == "manual_done":
                    note = "ผู้ใช้กดจบงานแล้ว"
                else:
                    note = f"งาน{'ถูกยกเลิก' if job['status'] == 'cancelled' else 'ล้ม'}"
            elif hours > WINDOW_HOURS:
                status, note = "expired", f"เกิน {WINDOW_HOURS} ชม.แล้ว เลิกตาม"
            elif tries >= MAX_TRIES:
                status, note = "expired", f"ไล่ครบ {MAX_TRIES} ครั้งแล้วยังไม่ขึ้น"
            elif hours < MIN_WAIT_HOURS:
                status, note = "waiting", f"เพิ่งโพสต์ {hours:.1f} ชม. รอผู้ดูแลก่อน"
            elif since_try is not None and since_try < RETRY_HOURS:
                status, note = "waiting", f"เพิ่งไล่ไป {since_try:.1f} ชม."
            else:
                status, note = "due", "ถึงเวลาไล่"
            items.append({
                "job_id": job["id"], "group_id": group_id,
                "caption": (job.get("caption") or "")[:60],
                "hours": hours, "tries": tries, "status": status, "note": note,
                "chat_id": job.get("chat_id", ""),
            })
    order = {"due": 0, "waiting": 1, "skipped": 2, "expired": 3}
    return sorted(items, key=lambda x: (order[x["status"]], x["hours"]))


def due_items(items: list[dict]) -> list[dict]:
    return [x for x in items if x["status"] == "due"]


def next_job(items: list[dict]) -> str:
    """งานไหนควรไล่รอบนี้ — ทีละงานเท่านั้น

    ตัวเดินงาน (`PostRunner`) ทำได้ทีละงานอยู่แล้ว และการเปิดหลายงานรวดเดียว
    ทำให้จอมือถือถูกยึดยาว งานที่ผู้ใช้สั่งเองต้องรอ — เลือกงาน **ใหม่สุด**
    ที่ถึงเวลา เพราะโอกาสที่โพสต์ยังเปิดเจอสูงกว่างานเก่า
    """
    due = due_items(items)
    return due[0]["job_id"] if due else ""


def mark_tried(job_id: str, group_ids, now: datetime | None = None) -> dict:
    """บันทึกว่าไล่ไปแล้วหนึ่งรอบ — ต้องเรียกทุกครั้งที่ลงมือจริง

    ไม่บันทึก = ตัวนับไม่ขยับ = ไล่ซ้ำทุกๆ รอบตลอดไป ซึ่งคือสิ่งที่ตั้งใจกัน
    """
    now = now or datetime.now()
    state = load_state()
    for group_id in group_ids:
        key = key_of(job_id, str(group_id))
        record = state.setdefault(key, {"tries": 0})
        record["tries"] = int(record.get("tries", 0)) + 1
        record["last_try"] = now.isoformat(timespec="seconds")
    save_state(state)
    return state


def forget(job_id: str = "") -> int:
    """ล้างตัวนับ — ใช้ตอนอยากเริ่มไล่ใหม่ (เช่นเพิ่งได้รับอนุมัติ)"""
    state = load_state()
    if not job_id:
        count = len(state)
        save_state({})
        return count
    remove = [k for k in state if k.startswith(f"{job_id}:")]
    for key in remove:
        state.pop(key, None)
    save_state(state)
    return len(remove)


def cleanup(jobs: list[dict], now: datetime | None = None) -> int:
    """ลบบันทึกของกลุ่มที่ไม่ค้างแล้ว — กันไฟล์บวมและกันตัวเลขเก่าค้างหลอกตา"""
    now = now or datetime.now()
    alive = {
        key_of(item["job_id"], item["group_id"])
        for item in pending_items(jobs, now=now, state={})
    }
    state = load_state()
    dropped = [key for key in state if key not in alive]
    if dropped:
        for key in dropped:
            state.pop(key, None)
        save_state(state)
    return len(dropped)


def summary_text(items: list[dict], label=None) -> str:
    """ข้อความสรุปสำหรับ Telegram"""
    if not items:
        return "✅ ไม่มีโพสต์ที่ค้างรออนุมัติ"
    naming = label or (lambda g: g)
    icon = {"due": "🔄", "waiting": "⏳", "skipped": "✋", "expired": "🚫"}
    lines = [f"📋 <b>โพสต์ที่ยังไม่ขึ้น {len(items)} กลุ่ม</b>"]
    for item in items[:12]:
        lines.append(
            f"{icon[item['status']]} {naming(item['group_id'])} · งาน {item['job_id']}\n"
            f"     โพสต์ไป {item['hours']:.0f} ชม. · ไล่แล้ว {item['tries']} ครั้ง"
            f" · {item['note']}"
        )
    if len(items) > 12:
        lines.append(f"…และอีก {len(items) - 12} กลุ่ม")
    ready = len(due_items(items))
    if ready:
        lines.append(f"\nถึงเวลาไล่ {ready} กลุ่ม — สั่ง <code>/pending run</code> ได้เลย")
    return "\n".join(lines)
