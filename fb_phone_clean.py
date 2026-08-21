"""ล้างเครื่องมือถือทุกเที่ยงคืน — ไฟล์ที่บอททิ้งไว้ + แคช + โปรเซสเบื้องหลัง

**วัดของจริงก่อนเขียน** (เครื่อง 7a95129e · 18 ส.ค. 2026 · uptime 7 วัน 16 ชม.)

    เนื้อที่ /sdcard   เหลือ 192 GB จาก 224 GB (ใช้ไป 15%)
    ไฟล์ค้างของบอท    65 ใบ รวม 7.4 MB
    แรมก่อนล้าง       ว่าง 3.71 GB · ใช้ 3.97 GB (status moderate)
    แรมหลังล้าง       ว่าง 4.36 GB · ใช้ 2.95 GB   ← คืนมา 1.0 GB

**เนื้อที่ไม่ใช่ปัญหาเลย แรมต่างหาก** — Facebook กินอยู่ตัวเดียว 780 MB และมี
โปรเซสของแอปอื่นอีกสามสิบกว่าตัวค้างจากการที่ไม่ได้รีสตาร์ตเครื่องมาเกินสัปดาห์
การล้างไฟล์ 7.4 MB ไม่ได้ช่วยอะไรจริง ตัวที่ช่วยคือปิดโปรเซสกับล้างแคช

**เวลาที่ใช้จริงต่อเครื่อง วัดแล้ว = ไม่ถึง 1 วินาที** (คำสั่งระบบ 3 ตัวรวม 0.46 วิ)
บวกวัดผลก่อน/หลังอีกราว 3 วินาที รวมทั้งรอบ **ต่ำกว่า 5 วินาที** ไม่ใช่นาที

**ห้ามใช้ `pm clear com.facebook.katana` เด็ดขาด**
`pm clear` ล้าง **ข้อมูลแอปทั้งก้อน** ไม่ใช่แค่แคช = ล็อกเอาต์ Facebook ทันที
ระบบทั้งหมดนี้ยืนอยู่บนบัญชีที่ล็อกอินค้างไว้ในแอป ล้างเมื่อไรคือทุกอย่างหยุด
จนกว่าจะมีคนไปล็อกอินใหม่บนมือถือด้วยมือ (และเสี่ยงโดนถามยืนยันตัวตนอีก)
`pm trim-caches` ล้างเฉพาะแคชซึ่งปลอดภัย ใช้ตัวนี้เท่านั้น

ไฟล์นี้ **ฉีดคำสั่งเข้ามาจากข้างนอกได้** (`shell`) จึงทดสอบได้โดยไม่แตะ ADB จริง
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from datetime import datetime, timedelta

import fb_screen
import studio_shared

STATE_FILE = studio_shared.post_file("fb_phone_clean.json")

# เวลาที่ตั้งให้ล้าง (ชั่วโมง, นาที)
RUN_AT = (0, 1)
# ถ้าเซิร์ฟเวอร์ไม่ได้เปิดตอนเที่ยงคืน ยังตามล้างย้อนหลังได้ภายในกี่ชั่วโมง
#
# ทำไมต้องมี: ตัวตั้งเวลาเดินอยู่ในเซิร์ฟเวอร์ ถ้ารีสตาร์ตตอน 00:05 พอดี
# รอบของวันนั้นจะหายไปเงียบๆ โดยไม่มีใครรู้ — ตามล้างทีหลังดีกว่าข้ามทั้งวัน
CATCHUP_HOURS = 6
# หมดเวลาต่อคำสั่ง — ADB หลุดต้องไม่ค้างเธรดตัวตั้งเวลาทั้งเส้น
CMD_TIMEOUT = 25.0
# แคชที่สั่งให้ล้าง (ตัวเลขคือ "เคลียร์จนเหลือที่ว่างเท่านี้" = ล้างให้มากที่สุด)
TRIM_TARGET = "8G"
# แพ็กเกจที่ปิดหลังล้าง — ปิดแล้วเปิดใหม่เองตอนงานถัดไป ไม่เสียข้อมูลอะไร
FORCE_STOP = ("com.facebook.katana",)
# โฟลเดอร์/ไฟล์ที่ "บอทเป็นคนสร้าง" เท่านั้น — ห้ามใส่ของผู้ใช้ลงมาเด็ดขาด
OWN_PATHS = (
    "/sdcard/Pictures/pipeline",
    "/sdcard/Movies/autopost",
)
OWN_FILES = (
    "/sdcard/window_dump.xml",
)

_lock = threading.Lock()
_FREE_RE = re.compile(r"Free RAM:\s*([\d,]+)K")
_USED_RE = re.compile(r"Used RAM:\s*([\d,]+)K")


# ------------------------------------------------------------------ คำสั่ง

def make_shell(serial: str, adb: str = "adb"):
    """ตัวยิงคำสั่งเข้าเครื่องจริง — แยกออกมาให้เทสสลับของปลอมเข้าแทนได้"""
    def call(command: str) -> str:
        done = subprocess.run(
            [adb, "-s", serial, "shell", command],
            capture_output=True, timeout=CMD_TIMEOUT,
            creationflags=studio_shared.NO_WINDOW,
        )
        return done.stdout.decode("utf-8", errors="replace")
    return call


def read_ram(shell) -> tuple[int, int]:
    """แรมว่าง/แรมที่ใช้ หน่วย MB — อ่านไม่ออกคืน (0, 0)

    ใช้ `dumpsys meminfo` ไม่ใช่ `free -m` เพราะ `free` บนแอนดรอยด์นับแคชเป็น
    "ใช้แล้ว" ทั้งก้อน อ่านแล้วเห็นว่างเหลือ 70 MB ทั้งที่ของจริงว่าง 3.7 GB
    — ตัดสินใจจากตัวเลขนั้นจะเข้าใจผิดว่าเครื่องใกล้ตายทั้งที่ยังสบาย
    """
    try:
        out = shell("dumpsys meminfo")
    except Exception:
        return (0, 0)
    free = _FREE_RE.search(out or "")
    used = _USED_RE.search(out or "")
    to_mb = lambda m: int(m.group(1).replace(",", "")) // 1024 if m else 0
    return (to_mb(free), to_mb(used))


def read_free_mb(shell) -> int:
    """เนื้อที่ว่างใน /sdcard หน่วย MB"""
    try:
        out = shell("df /sdcard")
    except Exception:
        return 0
    for line in (out or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 4 and parts[3].isdigit():
            return int(parts[3]) // 1024
    return 0


def count_own_files(shell) -> int:
    """ไฟล์ที่บอททิ้งไว้มีกี่ใบ"""
    total = 0
    for path in OWN_PATHS:
        try:
            out = shell(f"ls {path} 2>/dev/null | wc -l")
        except Exception:
            continue
        digits = re.search(r"\d+", out or "")
        if digits:
            total += int(digits.group())
    return total


# ------------------------------------------------------------------ ล้าง

def clean(serial: str, *, adb: str = "adb", shell=None, log=None,
          now: datetime | None = None) -> dict:
    """ล้างเครื่องหนึ่งเครื่อง — คืนรายงานว่าทำอะไรไปบ้าง

    **ทุกขั้นตอนทำซ้ำได้ไม่เสียหาย (idempotent)** ลบไฟล์ที่ไม่มีอยู่แล้วก็แค่ผ่าน
    ปิดแอปที่ปิดอยู่แล้วก็แค่ผ่าน จึงไม่ต้องมีกลไก "ทำต่อจากที่ค้าง" ให้ซับซ้อน
    — เครื่องดับหรือ ADB หลุดกลางทางก็แค่ล้างใหม่รอบหน้า

    **ลำดับสำคัญ** เรียงจากปลอดภัยสุดไปกระทบมากสุด ถ้าขาดกลางทางของที่ทำไปแล้ว
    จะเป็นของที่ปลอดภัยเสมอ และของที่ยังไม่ได้ทำคือของที่ "ไม่ทำก็ไม่พัง"
    """
    now = now or datetime.now()
    shell = shell or make_shell(serial, adb)
    say = log or (lambda _: None)
    report = {"serial": serial, "at": now.isoformat(timespec="seconds"),
              "steps": [], "failed": [], "ok": False}

    free_before, used_before = read_ram(shell)
    disk_before = read_free_mb(shell)
    files_before = count_own_files(shell)

    def step(name: str, command: str) -> None:
        try:
            shell(command)
            report["steps"].append(name)
        except Exception as error:
            # ขั้นเดียวล้มต้องไม่ทำให้ขั้นที่เหลือไม่ได้ทำ — เก็บไว้แล้วเดินต่อ
            report["failed"].append(f"{name}: {error}")
            say(f"  ข้าม {name} — {error}")

    # 1. ไฟล์ของบอทเอง (ปลอดภัยสุด ไม่แตะของผู้ใช้)
    for path in OWN_PATHS:
        step(f"ลบไฟล์ใน {path}", f"rm -rf {path}/* 2>/dev/null; mkdir -p {path}")
        step(f"สแกนสื่อใหม่ {path}",
             f"content call --uri content://media --method scan_file --arg {path}")
    for path in OWN_FILES:
        step(f"ลบ {path}", f"rm -f {path} 2>/dev/null")

    # 2. แคชของทุกแอป — ล้างเฉพาะแคช ไม่แตะข้อมูลผู้ใช้และไม่หลุดล็อกอิน
    step("ล้างแคชแอปทั้งเครื่อง", f"pm trim-caches {TRIM_TARGET}")

    # 3. โปรเซสเบื้องหลัง — คืนแรมได้มากที่สุดในบรรดาทั้งหมด (วัดได้ ~1 GB)
    step("ปิดโปรเซสเบื้องหลัง", "am kill-all")
    for package in FORCE_STOP:
        step(f"ปิด {package}", f"am force-stop {package}")
    # แอปของผู้ใช้ที่ไม่เกี่ยวกับงานแต่ค้างกินแรม (Netflix · Line · ChatGPT ·
    # Bolt · Notion) เจ้าของสั่งให้ปิดถาวร — `am kill-all` ไม่พอเพราะมันเว้น
    # โปรเซสที่ระบบถือว่าสำคัญไว้ ต้อง force-stop ทีละตัว
    for package in fb_screen.IDLE_APPS:
        step(f"ปิด {package}", f"am force-stop {package}")

    # 4. กันจอติดค้างเพราะเสียบชาร์จ — ตั้งซ้ำทุกวันเผื่อมีอะไรไปเปิดกลับ
    step("ปิด stay_on_while_plugged_in",
         "settings put global stay_on_while_plugged_in 0")

    free_after, used_after = read_ram(shell)
    disk_after = read_free_mb(shell)
    report.update({
        "ram_free_before": free_before, "ram_free_after": free_after,
        "ram_used_before": used_before, "ram_used_after": used_after,
        "disk_before": disk_before, "disk_after": disk_after,
        "files_removed": files_before,
        "ram_freed": max(0, used_before - used_after),
        "ok": not report["failed"],
    })
    say(f"ล้างเครื่อง {serial} — ลบไฟล์ {files_before} ใบ · "
        f"คืนแรม {report['ram_freed']} MB")
    return report


def clean_all(serials: list[str], *, adb: str = "adb", shell_for=None,
              log=None, now: datetime | None = None) -> list[dict]:
    """ล้างทีละเครื่องจนครบ — เครื่องหนึ่งล้มต้องไม่ทำให้เครื่องที่เหลือไม่ได้ล้าง"""
    out = []
    for serial in serials:
        maker = shell_for(serial) if shell_for else None
        try:
            out.append(clean(serial, adb=adb, shell=maker, log=log, now=now))
        except Exception as error:
            out.append({"serial": serial, "ok": False,
                        "failed": [f"ล้างไม่สำเร็จ: {error}"], "steps": []})
    return out


# ------------------------------------------------------------------ ตารางเวลา

def load() -> dict:
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except OSError:
        pass


def due(now: datetime | None = None) -> bool:
    """ถึงเวลาล้างของวันนี้แล้วหรือยัง (และยังไม่ได้ล้าง)"""
    now = now or datetime.now()
    start = now.replace(hour=RUN_AT[0], minute=RUN_AT[1], second=0, microsecond=0)
    if now < start:
        return False
    if now > start + timedelta(hours=CATCHUP_HOURS):
        return False                  # เลยหน้าต่างตามเก็บแล้ว ข้ามไปวันหน้า
    return load().get("last_date", "") != now.date().isoformat()


def mark_done(reports: list[dict], now: datetime | None = None) -> None:
    now = now or datetime.now()
    with _lock:
        state = load()
        state["last_date"] = now.date().isoformat()
        state["last_at"] = now.isoformat(timespec="seconds")
        state["last_reports"] = reports
        save(state)


def summary_text(now: datetime | None = None) -> str:
    """สรุปไว้แปะใน /health"""
    now = now or datetime.now()
    state = load()
    lines = ["🧹 <b>ล้างเครื่องอัตโนมัติ</b>"]
    if not state.get("last_at"):
        lines.append("   ยังไม่เคยล้าง")
        return "\n".join(lines)
    lines.append(f"   ล้างล่าสุด {state['last_at'][:16].replace('T', ' ')}")
    for report in state.get("last_reports", []):
        mark = "✅" if report.get("ok") else "⚠️"
        lines.append(
            f"   {mark} {report.get('serial', '?')} · ลบไฟล์ "
            f"{report.get('files_removed', 0)} ใบ · คืนแรม "
            f"{report.get('ram_freed', 0)} MB"
        )
        for bad in report.get("failed", [])[:2]:
            lines.append(f"      ↳ {bad[:70]}")
    return "\n".join(lines)


def report_text(reports: list[dict]) -> str:
    """ข้อความรายงานเข้าแชทหลังล้างเสร็จ"""
    lines = ["🧹 <b>ล้างเครื่องประจำวันแล้ว</b>"]
    for report in reports:
        mark = "✅" if report.get("ok") else "⚠️"
        lines.append(
            f"{mark} <code>{report.get('serial', '?')}</code>\n"
            f"   ลบไฟล์ที่บอททิ้งไว้ {report.get('files_removed', 0)} ใบ\n"
            f"   แรมว่าง {report.get('ram_free_before', 0)} → "
            f"{report.get('ram_free_after', 0)} MB "
            f"(คืนมา {report.get('ram_freed', 0)} MB)"
        )
        for bad in report.get("failed", []):
            lines.append(f"   ⚠️ {bad[:90]}")
    return "\n".join(lines)
