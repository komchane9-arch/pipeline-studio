"""Persistent clock schedules for Bot8 comment collection.

Each Facebook account owns one schedule.  A schedule may fire once or every
day.  This module only decides *when* a schedule is due; ``app.py`` remains the
single place that selects posts and starts Bot8, so scheduled and manual work
share the same lock and cannot run over each other.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import re

import studio_shared


STATE_FILE = Path(studio_shared.DATA_DIR) / "fb_engagement_schedule.json"
LOCK_NAME = "fb-engagement-schedule"
MODES = {"once", "daily"}


def _now(value: datetime | None = None) -> datetime:
    return value or datetime.now()


def _clock(value: str) -> tuple[int, int, str]:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", text):
        raise ValueError("เวลาต้องเป็นรูปแบบ HH:MM")
    hour, minute = (int(part) for part in text.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError("เวลาไม่ถูกต้อง")
    return hour, minute, f"{hour:02d}:{minute:02d}"


def _next_at(clock: str, now: datetime) -> datetime:
    hour, minute, _ = _clock(clock)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _read() -> dict:
    payload = studio_shared.read_json(STATE_FILE, {})
    schedules = payload.get("schedules") if isinstance(payload, dict) else {}
    return dict(schedules) if isinstance(schedules, dict) else {}


def _write(schedules: dict) -> None:
    studio_shared.write_json_atomic(STATE_FILE, {"schedules": schedules})


def set_schedule(account: str, clock: str, mode: str,
                 now: datetime | None = None) -> dict:
    account = str(account or "").strip()
    if not account:
        raise ValueError("ต้องระบุบัญชี Facebook")
    mode = str(mode or "").strip().lower()
    if mode not in MODES:
        raise ValueError("เลือกได้เฉพาะเก็บ 1 ครั้ง หรือเก็บทุกวัน")
    _, _, clock = _clock(clock)
    current = _now(now)
    next_at = _next_at(clock, current)
    entry = {
        "account": account,
        "time": clock,
        "mode": mode,
        "enabled": True,
        "next_at": next_at.isoformat(timespec="seconds"),
        "created_at": current.isoformat(timespec="seconds"),
        "last_run_at": "",
    }
    with studio_shared.data_lock(LOCK_NAME, label="บันทึกเวลาของ Bot8"):
        schedules = _read()
        schedules[account] = entry
        _write(schedules)
    return status(account, now=current)


def clear_schedule(account: str, now: datetime | None = None) -> dict:
    account = str(account or "").strip()
    with studio_shared.data_lock(LOCK_NAME, label="ยกเลิกเวลาของ Bot8"):
        schedules = _read()
        schedules.pop(account, None)
        _write(schedules)
    return status(account, now=_now(now))


def status(account: str, now: datetime | None = None) -> dict:
    account = str(account or "").strip()
    current = _now(now)
    entry = dict(_read().get(account) or {})
    enabled = bool(entry.get("enabled") and entry.get("next_at"))
    try:
        next_at = datetime.fromisoformat(str(entry.get("next_at") or ""))
    except ValueError:
        enabled = False
        next_at = current
    wait_seconds = max(0, int((next_at - current).total_seconds())) if enabled else 0
    return {
        "account": account,
        "enabled": enabled,
        "time": str(entry.get("time") or ""),
        "mode": str(entry.get("mode") or ""),
        "next_at": (next_at.isoformat(timespec="seconds") if enabled else ""),
        "wait_seconds": wait_seconds,
        "due": bool(enabled and next_at <= current),
        "last_run_at": str(entry.get("last_run_at") or ""),
    }


def due(now: datetime | None = None) -> list[dict]:
    current = _now(now)
    return [item for account in _read()
            if (item := status(account, now=current)).get("due")]


def mark_started(account: str, now: datetime | None = None) -> dict:
    """Consume a due slot only after Bot8 accepted the work."""
    account = str(account or "").strip()
    current = _now(now)
    with studio_shared.data_lock(LOCK_NAME, label="เลื่อนเวลารอบถัดไปของ Bot8"):
        schedules = _read()
        entry = dict(schedules.get(account) or {})
        if not entry:
            return status(account, now=current)
        entry["last_run_at"] = current.isoformat(timespec="seconds")
        if entry.get("mode") == "daily":
            entry["enabled"] = True
            entry["next_at"] = _next_at(str(entry.get("time") or ""), current).isoformat(
                timespec="seconds")
        else:
            entry["enabled"] = False
            entry["next_at"] = ""
        schedules[account] = entry
        _write(schedules)
    return status(account, now=current)
