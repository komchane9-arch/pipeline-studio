"""ด่านตรวจก่อนเริ่มงานบนมือถือ — ไม่พร้อมก็ไม่เริ่ม ดีกว่าเริ่มแล้วพังกลางทาง

**ทำไมต้องมี** งานที่ล้มกลางคันแพงกว่างานที่ไม่ได้เริ่มมาก โพสต์ค้างครึ่งทาง
ต้องมาไล่ `/followup` `/fiximage` เก็บกวาดเอง บางกลุ่มได้รูปผิด บางกลุ่มได้
คอมเมนต์ไม่ครบ และทุกครั้งที่ยิงซ้ำก็เสี่ยงโดน Facebook ตีธงเพิ่ม

ที่ผ่านมาไม่มีด่านตรวจอะไรเลย งานเริ่มทันทีที่สั่ง แล้วไปเจอปัญหาเอาตอนแตะจอ

**แบ่งเป็นสองชั้นตามที่ตกลงไว้**

    ไม่ผ่าน = ไม่เริ่ม     ADB ต่อไม่ติด · มือถือมีคนใช้อยู่ · เนื้อที่ไม่พอ
    ไม่ผ่าน = แค่เตือน     คีย์บอร์ดค้างที่ ADBKeyboard · เพิ่งโพสต์กลุ่มนี้ไป

เหตุผลที่คีย์บอร์ดเป็นแค่คำเตือน: มันไม่ได้ทำให้งานล้ม (โค้ดสลับคีย์บอร์ดเองอยู่แล้ว)
แต่เป็นสัญญาณว่ารอบก่อนตายกลางทาง — ควรรู้ ไม่ควรถูกห้าม

**ทุกคำสั่งที่แตะมือถือฉีดเข้ามาจากข้างนอกได้** (`shell` / `devices`) เพื่อให้
ทดสอบได้โดยไม่ต้องมีมือถือจริงและไม่ต้องยิง ADB แม้แต่ครั้งเดียว
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import studio_shared

# ต้องมีเนื้อที่เหลืออย่างน้อยเท่านี้ถึงจะเริ่มงานได้
PC_FREE_MIN_MB = 1500          # ฝั่งคอมพิวเตอร์ (รูปที่รับมา · log · ไฟล์สำรอง)
PHONE_FREE_MIN_MB = 400        # ฝั่งมือถือ (รูปที่ push ไปโพสต์ · uiautomator dump)

# เพิ่งโพสต์กลุ่มนี้ไปไม่ถึงกี่นาที = เตือนว่าอาจโดนตีธงสแปม
DUPLICATE_GAP_MINUTES = 45

ADB_KEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"


class PreflightError(RuntimeError):
    """ด่านตรวจไม่ผ่านในข้อที่ห้ามเริ่ม"""


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    blocking: bool = True


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.blocking]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and not c.blocking]

    @property
    def ok(self) -> bool:
        return not self.failures

    def reason(self) -> str:
        """บรรทัดเดียวสำหรับใส่ใน exception / log"""
        return " · ".join(f"{c.name}: {c.detail}" for c in self.failures)

    def warning_text(self) -> str:
        return " · ".join(f"{c.name}: {c.detail}" for c in self.warnings)

    def text(self) -> str:
        """ข้อความเต็มสำหรับตอบใน Telegram"""
        lines = []
        for check in self.checks:
            mark = "✅" if check.ok else ("❌" if check.blocking else "⚠️")
            lines.append(f"{mark} {check.name}" + (f" — {check.detail}" if check.detail else ""))
        head = "🩺 <b>ตรวจความพร้อม</b>"
        if self.failures:
            head = "🚫 <b>ยังเริ่มงานไม่ได้</b>"
        elif self.warnings:
            head = "🩺 <b>เริ่มได้ แต่มีเรื่องต้องรู้</b>"
        return head + "\n" + "\n".join(lines)


# ------------------------------------------------------- ตัวเรียก ADB ปริยาย

def _default_devices(adb: str):
    def call() -> str:
        done = subprocess.run([adb, "devices"], capture_output=True, timeout=20, creationflags=studio_shared.NO_WINDOW)
        return done.stdout.decode("utf-8", errors="replace")
    return call


def _default_shell(adb: str, serial: str):
    def call(command: str) -> str:
        done = subprocess.run(
            [adb, "-s", serial, "shell", command], capture_output=True, timeout=25, creationflags=studio_shared.NO_WINDOW)
        return done.stdout.decode("utf-8", errors="replace")
    return call


# ------------------------------------------------------------------ ด่านย่อย

def check_device(serial: str, devices) -> Check:
    """เครื่องที่จะสั่งต่ออยู่จริงและพร้อมรับคำสั่งไหม"""
    try:
        output = devices()
    except Exception as error:
        return Check("ADB", False, f"เรียก adb ไม่ได้ ({error})")
    states = {}
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            states[parts[0]] = parts[1]
    if not states:
        return Check("ADB", False, "ไม่มีมือถือเชื่อมต่ออยู่เลย")
    state = states.get(serial)
    if state is None:
        return Check("ADB", False,
                     f"ไม่เจอเครื่อง {serial} (ที่ต่ออยู่: {', '.join(states)})")
    if state != "device":
        # unauthorized = ยังไม่ได้กดอนุญาตบนจอ · offline = สายหลวม/หลับ
        return Check("ADB", False, f"เครื่อง {serial} สถานะ {state} ยังสั่งงานไม่ได้")
    return Check("ADB", True, f"{serial} พร้อม")


def check_phone_free(serial: str) -> Check:
    """มือถือเครื่องนี้ว่างไหม — ลองยึดล็อกจริงแล้วปล่อยทันที

    ต้อง**ลองยึดจริง** ไม่ใช่อ่านไฟล์บันทึกผู้ถือ เพราะไฟล์บันทึกค้างได้ถ้าโปรเซส
    ก่อนหน้าตายแบบไม่ได้เก็บกวาด ส่วนล็อกของ OS ปล่อยเองเสมอเมื่อโปรเซสตาย
    """
    try:
        # queue=False — นี่คือแค่ "ถามว่าว่างไหม" ไม่ใช่การขอใช้จริง
        with studio_shared.phone_lock(serial, timeout=0.5, poll=0.2,
                                      label="ตรวจความพร้อม", queue=False):
            return Check("มือถือว่าง", True, serial)
    except studio_shared.PhoneBusy:
        return Check("มือถือว่าง", False, studio_shared.who_holds_phone(serial))
    except Exception as error:
        # ล็อกมีปัญหาเองไม่ควรห้ามงาน แต่ต้องดังพอให้เห็น
        return Check("มือถือว่าง", False, f"เช็คล็อกไม่ได้ ({error})", blocking=False)


def check_pc_space(path: Path | None = None) -> Check:
    target = path or studio_shared.DATA_DIR
    try:
        free_mb = shutil.disk_usage(target).free / 1048576
    except OSError as error:
        return Check("เนื้อที่ในคอม", False, f"อ่านไม่ได้ ({error})", blocking=False)
    if free_mb < PC_FREE_MIN_MB:
        return Check("เนื้อที่ในคอม", False,
                     f"เหลือ {free_mb:.0f} MB (ต้องมีอย่างน้อย {PC_FREE_MIN_MB} MB)")
    return Check("เนื้อที่ในคอม", True, f"เหลือ {free_mb / 1024:.1f} GB")


def parse_df_free_mb(output: str) -> float | None:
    """อ่านเนื้อที่ว่างจากผล `df /sdcard` — คืน None ถ้าอ่านไม่ออก

    รูปแบบต่างกันตามรุ่น Android บางเครื่องมีคอลัมน์ 1K-blocks บางเครื่องเป็น
    Size/Used/Avail แบบมีหน่วยติดมา จึงต้องดูหัวตารางก่อนว่าคอลัมน์ไหนคือ "ว่าง"
    """
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    header = lines[0].split()
    columns = lines[-1].split()
    index = None
    for position, name in enumerate(header):
        if name.lower().startswith(("avail", "free")):
            index = position
            break
    if index is None or index >= len(columns):
        index = 3 if len(columns) > 3 else None
    if index is None:
        return None
    raw = columns[index]
    try:
        if raw[-1:].upper() in "KMGT":
            value = float(raw[:-1])
            return value * {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1048576}[raw[-1].upper()]
        return float(raw) / 1024        # ไม่มีหน่วย = บล็อกละ 1 KB
    except (ValueError, KeyError):
        return None


def check_phone_space(shell) -> Check:
    try:
        output = shell("df /sdcard")
    except Exception as error:
        return Check("เนื้อที่ในมือถือ", False, f"ถามไม่ได้ ({error})", blocking=False)
    free_mb = parse_df_free_mb(output)
    if free_mb is None:
        # อ่านผลไม่ออกเป็นปัญหาของเราเอง ไม่ใช่ของเครื่อง — ห้ามเอาไปห้ามงาน
        return Check("เนื้อที่ในมือถือ", False, "อ่านผล df ไม่ออก", blocking=False)
    if free_mb < PHONE_FREE_MIN_MB:
        return Check("เนื้อที่ในมือถือ", False,
                     f"เหลือ {free_mb:.0f} MB (ต้องมีอย่างน้อย {PHONE_FREE_MIN_MB} MB)")
    return Check("เนื้อที่ในมือถือ", True, f"เหลือ {free_mb / 1024:.1f} GB")


def check_keyboard(shell) -> Check:
    """คีย์บอร์ดค้างที่ ADBKeyboard ไหม — เตือนอย่างเดียว ไม่ห้ามงาน

    ค้างแปลว่ารอบก่อนตายกลางทางก่อนคืนคีย์บอร์ด ผลคือผู้ใช้พิมพ์เองบนเครื่อง
    ไม่ได้จนกว่าจะมีใครคืนให้ งานอัตโนมัติยังทำได้ปกติ จึงไม่ควรห้ามเริ่ม
    """
    try:
        current = shell("settings get secure default_input_method").strip()
    except Exception as error:
        return Check("คีย์บอร์ด", False, f"ถามไม่ได้ ({error})", blocking=False)
    if ADB_KEYBOARD_IME in current:
        return Check("คีย์บอร์ด", False,
                     "ยังค้างที่ ADBKeyboard (รอบก่อนไม่ได้คืน) — พิมพ์เองบนเครื่องไม่ได้",
                     blocking=False)
    return Check("คีย์บอร์ด", True, current.split("/")[0][-28:] or "ปกติ")


# --------------------------------------------------- กันโพสต์ซ้ำกลุ่มเดิมเร็วเกิน

def _job_time(job: dict) -> datetime | None:
    for key in ("finished_at", "started_at", "created_at"):
        raw = (job.get(key) or "").strip()
        if not raw:
            continue
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            continue
    return None


def recent_posts(jobs: list[dict], group_ids, minutes: int = DUPLICATE_GAP_MINUTES,
                 now: datetime | None = None, skip_job: str = "") -> list[dict]:
    """กลุ่มไหนเพิ่งถูกโพสต์ไปไม่ถึงกี่นาที — เรียงจากที่เพิ่งโพสต์สุด

    ดูจาก **ผลจริงที่โพสต์สำเร็จ** ไม่ใช่แค่ว่ามีงานนั้นอยู่ งานที่ล้มหรือถูก
    ยกเลิกไม่นับ เพราะไม่ได้ไปปรากฏในกลุ่มจริง
    """
    now = now or datetime.now()
    limit = timedelta(minutes=minutes)
    wanted = {str(g) for g in group_ids}
    seen: dict[str, dict] = {}
    for job in jobs:
        if skip_job and job.get("id") == skip_job:
            continue
        when = _job_time(job)
        if when is None or now - when > limit or when > now:
            continue
        for result in job.get("results", []):
            group = str(result.get("group_id", ""))
            if group not in wanted or not result.get("posted"):
                continue
            gap = (now - when).total_seconds() / 60
            old = seen.get(group)
            if old is None or gap < old["minutes_ago"]:
                seen[group] = {
                    "group_id": group, "job_id": job.get("id", ""),
                    "minutes_ago": gap,
                }
    return sorted(seen.values(), key=lambda x: x["minutes_ago"])


def check_duplicate(jobs, group_ids, label=None, minutes: int = DUPLICATE_GAP_MINUTES,
                    now: datetime | None = None, skip_job: str = "") -> Check:
    hits = recent_posts(jobs, group_ids, minutes=minutes, now=now, skip_job=skip_job)
    if not hits:
        return Check("ความถี่การโพสต์", True, f"ไม่มีกลุ่มไหนโพสต์ซ้ำใน {minutes} นาที",
                     blocking=False)
    naming = label or (lambda g: g)
    detail = " · ".join(
        f"{naming(h['group_id'])} เพิ่งโพสต์ไป {h['minutes_ago']:.0f} นาที "
        f"(งาน {h['job_id']})"
        for h in hits[:3]
    )
    if len(hits) > 3:
        detail += f" และอีก {len(hits) - 3} กลุ่ม"
    return Check("ความถี่การโพสต์", False, detail, blocking=False)


# --------------------------------------------------------------- ตัวรวมทั้งหมด

def run_checks(serial: str, *, adb: str = "adb", shell=None, devices=None,
               jobs=None, group_ids=(), label=None, now=None,
               minutes: int = DUPLICATE_GAP_MINUTES, skip_job: str = "",
               check_lock: bool = True) -> Report:
    """ตรวจทุกข้อแล้วรวมผล — ไม่โยน exception ผู้เรียกตัดสินใจเองว่าจะห้ามไหม"""
    devices = devices or _default_devices(adb)
    shell = shell or _default_shell(adb, serial)
    report = Report()
    device = check_device(serial, devices)
    report.checks.append(device)
    if check_lock:
        report.checks.append(check_phone_free(serial))
    report.checks.append(check_pc_space())
    # ถามเครื่องต่อเมื่อ ADB ใช้ได้ — ไม่งั้นได้ error ซ้ำสามข้อจากต้นเหตุเดียวกัน
    if device.ok:
        report.checks.append(check_phone_space(shell))
        report.checks.append(check_keyboard(shell))
    if group_ids:
        report.checks.append(check_duplicate(
            jobs or [], group_ids, label=label, minutes=minutes, now=now,
            skip_job=skip_job,
        ))
    return report


def guard(serial: str, *, what: str = "งานนี้", **kwargs) -> Report:
    """ตรวจแล้ว**โยน `PreflightError` ถ้าไม่ผ่านข้อที่ห้ามเริ่ม** — ตัวที่งานจริงเรียก

    คืน Report กลับไปด้วยเมื่อผ่าน เพื่อให้ผู้เรียกเอาคำเตือนไปบอกผู้ใช้ต่อได้
    """
    report = run_checks(serial, **kwargs)
    if not report.ok:
        raise PreflightError(f"{what} เริ่มไม่ได้ — {report.reason()}")
    return report
