"""สำรองไฟล์สถานะใน data/ เป็น zip — ของที่หายแล้วสร้างใหม่ไม่ได้

**ทำไมต้องมี** 12 ส.ค. 2026 โน้ตในโปรเจกต์ถูกลบไปทั้งชุดเพราะสคริปต์เขียนทับ
ไฟล์ผิดตัว กู้กลับมาได้ด้วย "Previous Versions" ของ Windows ซึ่งเป็นความบังเอิญ
ล้วนๆ — จุดคืนค่าอาจปิดอยู่ หรืออาจไม่มีจุดที่ใกล้พอก็ได้ ที่ผ่านมามีสำรองแค่
โปรไฟล์บอทกับโทเคน ส่วน `fb_jobs.json` `config.json` `fb_groups.json`
**ไม่มีอะไรสำรองเลยสักตัว** ทั้งที่เป็นของที่หายแล้วเจ็บที่สุด

**เลือกสำรองเฉพาะของที่สร้างใหม่ไม่ได้**

    ไฟล์สถานะ .json      งาน · กลุ่ม · ตั้งค่า · ผลเก็บยอด
    โทเคน .bin           ต้องไปขอ BotFather ใหม่ทั้งชุดถ้าหาย
    พิกัดที่ train ไว้    ต้องนั่งจิ้มใหม่ทีละจุด (แพงที่สุดในแง่เวลา)

ไม่สำรอง: รูป · คลิป · โปรไฟล์เบราว์เซอร์ · log — ใหญ่และสร้างใหม่ได้

**เขียนแบบ atomic** zip ลง `.tmp` แล้วค่อยเปลี่ยนชื่อ เพราะไฟล์สำรองที่เขียน
ค้างครึ่งทางอันตรายกว่าไม่มีไฟล์สำรอง — ตอนต้องใช้จริงจะเปิดไม่ออกโดยไม่มีใครรู้
ล่วงหน้า
"""

from __future__ import annotations

import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import studio_shared

DATA_DIR = studio_shared.DATA_DIR
BACKUP_DIR = DATA_DIR / "backup"

# เก็บย้อนหลังกี่วัน — 14 วันพอสำหรับ "เพิ่งรู้ตัวว่าของหาย"
KEEP_DAYS = 14
# ต่อให้เก่ากว่ากำหนดก็ต้องเหลือขั้นต่ำเท่านี้เสมอ
#
# กันเคสที่เจ็บที่สุด: เครื่องปิดไปสองสัปดาห์ พอเปิดมาปุ๊บตัวตัดอายุลบทิ้งหมด
# ทั้งที่ยังไม่ได้สำรองตัวใหม่เลย = ช่วงหนึ่งไม่มีสำรองอยู่เลยสักไฟล์
KEEP_MIN = 5
# ไฟล์เดี่ยวใหญ่เกินนี้ = ข้าม แล้วรายงานว่าข้ามอะไร (ไม่เงียบ)
MAX_FILE_BYTES = 5 * 1024 * 1024
# ทั้งก้อนใหญ่เกินนี้ = หยุดเก็บเพิ่มแล้วรายงาน — สำรองต้องเบาพอที่จะทำทุกวัน
MAX_TOTAL_BYTES = 60 * 1024 * 1024

# อะไรบ้างที่ต้องสำรอง (เทียบกับ DATA_DIR)
#
# ใช้ glob ไม่ใช่ชื่อไฟล์ตายตัว เพราะมีไฟล์สถานะเพิ่มเรื่อยๆ ตามฟีเจอร์ใหม่
# (fb_engage_config.json / fb_mass_*.json เพิ่งมีเมื่อสัปดาห์ที่แล้ว) ระบุชื่อ
# ตายตัวแล้วของใหม่จะไม่ถูกสำรองโดยไม่มีใครรู้จนกว่าจะหาย
PATTERNS = (
    "*.json",                 # สถานะทั้งหมดของทุกสาย
    "*.bin",                  # โทเคนบอทหลัก (เข้ารหัสด้วย DPAPI อยู่แล้ว)
    # สถานะสายโพสต์เก็บ local-first ใต้โฟลเดอร์นี้ตั้งแต่ 18 ก.ย. 2569
    # ต้องใช้ ** เพื่อเก็บทั้ง _index และไฟล์แยกรายบัญชี ไม่เช่นนั้นกลุ่มหายแล้ว
    # backup ก่อนรีสตาร์ตก็ยังไม่มี fb_groups.json ให้กู้เหมือนเหตุการณ์ Preaw
    "facebook-post-state/**/*.json",
    "bots/*.bin",             # โทเคนบอทเพิ่มเติม
    "publish_positions/*.json",   # พิกัดที่ train ไว้ — จิ้มใหม่แพงที่สุด
    "publish_flows/*.json",
    "shopee_positions/*.json",
)


class BackupError(RuntimeError):
    """สำรองไม่สำเร็จ"""


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now()


def collect_files() -> tuple[list[Path], list[str]]:
    """หาไฟล์ที่ต้องสำรอง — คืน (รายการไฟล์, รายการที่ข้ามพร้อมเหตุผล)"""
    found: list[Path] = []
    skipped: list[str] = []
    total = 0
    for pattern in PATTERNS:
        for path in sorted(DATA_DIR.glob(pattern)):
            if not path.is_file():
                continue
            try:
                size = path.stat().st_size
            except OSError as error:
                skipped.append(f"{path.name} (อ่านไม่ได้: {error})")
                continue
            if size > MAX_FILE_BYTES:
                skipped.append(f"{path.name} ({size / 1048576:.1f} MB ใหญ่เกิน)")
                continue
            if total + size > MAX_TOTAL_BYTES:
                skipped.append(f"{path.name} (เกินเพดานรวม)")
                continue
            found.append(path)
            total += size
    return found, skipped


def make_backup(reason: str = "manual", now: datetime | None = None) -> dict:
    """สร้างไฟล์สำรองหนึ่งชุด คืนสรุปว่าเก็บอะไรไปบ้าง

    `reason` ไปอยู่ในชื่อไฟล์ ("restart" / "daily" / "manual") เพื่อให้ตอนต้องกู้
    จริงเลือกได้ว่าจะเอาชุดก่อนรีสตาร์ตรอบไหน
    """
    stamp = _now(now).strftime("%Y%m%d-%H%M%S")
    safe = "".join(c for c in reason if c.isalnum() or c in "-_") or "manual"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"{stamp}-{safe}.zip"
    temporary = target.with_suffix(".zip.tmp")

    files, skipped = collect_files()
    if not files:
        raise BackupError(f"ไม่เจอไฟล์ที่ต้องสำรองใน {DATA_DIR}")

    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, arcname=str(path.relative_to(DATA_DIR)))
        # ตรวจว่าไฟล์ที่เพิ่งเขียนเปิดได้จริงก่อนรับเข้าเป็นของจริง
        #
        # ไฟล์สำรองที่เสียแต่ยังอยู่ในรายการ แย่กว่าไม่มีไฟล์ เพราะจะรู้ตัวตอน
        # ต้องใช้เท่านั้น ซึ่งสายไปแล้ว
        with zipfile.ZipFile(temporary) as check:
            broken = check.testzip()
            if broken:
                raise BackupError(f"ไฟล์สำรองเสียที่ {broken}")
            inside = len(check.namelist())
        temporary.replace(target)
    except (OSError, zipfile.BadZipFile) as error:
        temporary.unlink(missing_ok=True)
        raise BackupError(f"เขียนไฟล์สำรองไม่สำเร็จ: {error}") from error

    return {
        "path": target,
        "files": inside,
        "bytes": target.stat().st_size,
        "skipped": skipped,
        "reason": safe,
    }


def listing() -> list[Path]:
    """ไฟล์สำรองทั้งหมด เรียงใหม่สุดก่อน"""
    if not BACKUP_DIR.is_dir():
        return []
    return sorted(BACKUP_DIR.glob("*.zip"), key=lambda p: p.name, reverse=True)


def latest() -> Path | None:
    items = listing()
    return items[0] if items else None


def prune(now: datetime | None = None) -> list[str]:
    """ลบไฟล์สำรองที่เกินอายุ — คืนรายชื่อที่ลบ

    เรียงใหม่สุดก่อนแล้วเก็บ KEEP_MIN ชุดแรกไว้เสมอ ที่เหลือค่อยตัดตามอายุ
    """
    cutoff = _now(now) - timedelta(days=KEEP_DAYS)
    removed: list[str] = []
    for index, path in enumerate(listing()):
        if index < KEEP_MIN:
            continue
        try:
            if datetime.fromtimestamp(path.stat().st_mtime) >= cutoff:
                continue
            path.unlink()
            removed.append(path.name)
        except OSError:
            continue        # ลบไม่ได้ก็ปล่อยไว้ ไม่ใช่เรื่องที่ต้องทำให้งานล้ม
    return removed


def age_hours(now: datetime | None = None) -> float | None:
    """ไฟล์สำรองล่าสุดเก่ากี่ชั่วโมงแล้ว — None = ยังไม่เคยสำรองเลย"""
    newest = latest()
    if newest is None:
        return None
    try:
        made = datetime.fromtimestamp(newest.stat().st_mtime)
    except OSError:
        return None
    return (_now(now) - made).total_seconds() / 3600.0


def due(every_hours: float = 20.0, now: datetime | None = None) -> bool:
    """ถึงเวลาสำรองรอบใหม่หรือยัง

    ตั้ง 20 ชั่วโมงไม่ใช่ 24 เพราะถ้าเทียบ 24 เป๊ะ รอบที่ช้าไปนิดเดียวจะเลื่อน
    ออกไปอีกวันเต็มๆ แล้ววันหนึ่งจะกลายเป็น "สำรองวันเว้นวัน" โดยไม่มีใครสังเกต
    """
    age = age_hours(now)
    return age is None or age >= every_hours


def run_daily(now: datetime | None = None) -> dict | None:
    """สำรองถ้าถึงเวลา แล้วตัดของเก่าทิ้ง — ตัวที่ตัวตั้งเวลาเรียก

    คืน None ถ้ายังไม่ถึงเวลา (ผู้เรียกจะได้ไม่ต้องรู้กติกาเรื่องเวลาเอง)
    """
    if not due(now=now):
        return None
    result = make_backup("daily", now=now)
    result["pruned"] = prune(now=now)
    return result


def summary_text() -> str:
    """ข้อความสรุปสถานะไฟล์สำรอง — ใช้ตอบใน Telegram"""
    items = listing()
    if not items:
        return "🗄 ยังไม่มีไฟล์สำรองเลย"
    total = sum(p.stat().st_size for p in items) / 1048576
    age = age_hours()
    lines = [
        f"🗄 <b>ไฟล์สำรอง {len(items)} ชุด</b> · รวม {total:.1f} MB",
        f"ล่าสุด {items[0].name} ({age:.1f} ชม.ที่แล้ว)" if age is not None
        else f"ล่าสุด {items[0].name}",
    ]
    lines += [f"· {p.name}" for p in items[1:6]]
    if len(items) > 6:
        lines.append(f"…และอีก {len(items) - 6} ชุด")
    return "\n".join(lines)
