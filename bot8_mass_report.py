"""Persistent queue and clock for Bot8's read-only popular-post reports.

The Chrome work runs in a separate process.  Keeping the job in one atomic
record lets the page show a truthful queue across server restarts, without
restarting a scan or losing the last finished report.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import re
import uuid

import studio_shared


STATE_FILE = Path(studio_shared.DATA_DIR) / "bot8_mass_report.json"
MODES = {"once", "daily"}
ACTIVE = {"queued", "running"}


def _now(value: datetime | None = None) -> datetime:
    return value or datetime.now()


def _clock(value: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", text):
        raise ValueError("เวลาต้องเป็นรูปแบบ HH:MM")
    hour, minute = (int(part) for part in text.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError("เวลาไม่ถูกต้อง")
    return f"{hour:02d}:{minute:02d}"


def _next_at(clock: str, now: datetime) -> datetime:
    hour, minute = (int(part) for part in _clock(clock).split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


def _read() -> dict:
    state = studio_shared.read_json(STATE_FILE, {})
    return state if isinstance(state, dict) else {}


def schedule_status(now: datetime | None = None) -> dict:
    current = _now(now)
    entry = dict(_read().get("schedule") or {})
    enabled = bool(entry.get("enabled") and entry.get("next_at"))
    try:
        next_at = datetime.fromisoformat(str(entry.get("next_at") or ""))
    except ValueError:
        enabled = False
        next_at = current
    return {
        "enabled": enabled,
        "time": str(entry.get("time") or ""),
        "mode": str(entry.get("mode") or ""),
        "next_at": next_at.isoformat(timespec="seconds") if enabled else "",
        "wait_seconds": max(0, int((next_at - current).total_seconds())) if enabled else 0,
        "due": bool(enabled and next_at <= current),
        "last_run_at": str(entry.get("last_run_at") or ""),
    }


def set_schedule(clock: str, mode: str, now: datetime | None = None) -> dict:
    clock = _clock(clock)
    mode = str(mode or "").strip().lower()
    if mode not in MODES:
        raise ValueError("เลือกได้เฉพาะ 1 ครั้ง หรือทุกวัน")
    current = _now(now)

    def change(state):
        state["schedule"] = {
            "time": clock, "mode": mode, "enabled": True,
            "next_at": _next_at(clock, current).isoformat(timespec="seconds"),
            "created_at": current.isoformat(timespec="seconds"),
            "last_run_at": str((state.get("schedule") or {}).get("last_run_at") or ""),
        }

    studio_shared.update_json(STATE_FILE, change, default={}, label="ตั้งเวลาโพสต์แมส Bot8")
    return schedule_status(current)


def clear_schedule(now: datetime | None = None) -> dict:
    def change(state):
        state["schedule"] = {}

    studio_shared.update_json(STATE_FILE, change, default={}, label="ยกเลิกเวลาโพสต์แมส Bot8")
    return schedule_status(now)


def job_status() -> dict:
    return dict(_read().get("job") or {"status": "idle"})


def status(now: datetime | None = None) -> dict:
    state = _read()
    job = dict(state.get("job") or {"status": "idle"})
    if job.get("status") == "complete" and job.get("report_id"):
        job["report_url"] = f"/api/fb/mass-report/report/{job['report_id']}/report.html"
    latest = str(state.get("latest_report_id") or "")
    if not latest and job.get("status") == "complete":
        latest = str(job.get("report_id") or "")
    return {"job": job, "schedule": schedule_status(now),
            "latest_report_url": (f"/api/fb/mass-report/report/{latest}/report.html"
                                  if latest else "")}


def enqueue(source: str = "manual", now: datetime | None = None) -> tuple[bool, dict]:
    """Accept one job atomically.  A due clock is consumed only on acceptance."""
    if source not in {"manual", "scheduled"}:
        raise ValueError("ไม่รู้จักต้นทางงาน")
    current = _now(now)
    accepted = False

    def change(state):
        nonlocal accepted
        job = dict(state.get("job") or {})
        if job.get("status") in ACTIVE:
            return
        schedule = dict(state.get("schedule") or {})
        if source == "scheduled":
            try:
                due_at = datetime.fromisoformat(str(schedule.get("next_at") or ""))
            except ValueError:
                return
            if not schedule.get("enabled") or due_at > current:
                return
            schedule["last_run_at"] = current.isoformat(timespec="seconds")
            if schedule.get("mode") == "daily":
                schedule["next_at"] = _next_at(schedule["time"], current).isoformat(
                    timespec="seconds")
            else:
                schedule["enabled"] = False
                schedule["next_at"] = ""
            state["schedule"] = schedule
        job_id = uuid.uuid4().hex[:12]
        state["job"] = {
            "id": job_id, "status": "queued", "source": source,
            "queued_at": current.isoformat(timespec="seconds"),
            "updated_at": current.isoformat(timespec="seconds"),
            "current_action": "รอคิว Chrome Bot8", "current_group": "",
            "total": 0, "completed": 0, "found": 0,
            "report_id": "", "error": "",
        }
        accepted = True

    state = studio_shared.update_json(STATE_FILE, change, default={}, label="เข้าคิวโพสต์แมส Bot8")
    return accepted, dict(state.get("job") or {})


def update_job(job_id: str, *, now: datetime | None = None, **changes) -> dict:
    current = _now(now)

    def change(state):
        job = dict(state.get("job") or {})
        if job.get("id") != job_id or job.get("status") not in ACTIVE:
            return
        job.update(changes)
        job["updated_at"] = current.isoformat(timespec="seconds")
        state["job"] = job
        if job.get("status") == "complete" and job.get("report_id"):
            state["latest_report_id"] = job["report_id"]

    state = studio_shared.update_json(STATE_FILE, change, default={}, label="สถานะโพสต์แมส Bot8")
    return dict(state.get("job") or {})


def expire_stale(now: datetime | None = None, max_age_seconds: int = 300) -> dict:
    """Expose an interrupted process as error, never quietly start a duplicate."""
    current = _now(now)

    def change(state):
        job = dict(state.get("job") or {})
        if job.get("status") != "running":
            return
        try:
            updated = datetime.fromisoformat(str(job.get("updated_at") or ""))
        except ValueError:
            updated = current - timedelta(seconds=max_age_seconds + 1)
        if (current - updated).total_seconds() <= max_age_seconds:
            return
        job.update(status="error", error="งานหยุดส่งสถานะเกิน 5 นาที — ไม่เริ่มซ้ำเอง",
                   finished_at=current.isoformat(timespec="seconds"))
        state["job"] = job

    state = studio_shared.update_json(STATE_FILE, change, default={}, label="ตรวจงานโพสต์แมสค้าง")
    return dict(state.get("job") or {})
