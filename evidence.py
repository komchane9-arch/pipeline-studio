"""เก็บหลักฐานตอนพัง — ภาพหน้าจอ + ผังจอ + บริบท ไว้เรียกดูย้อนหลัง

**ทำไมต้องมี** (25 ส.ค. 2026 ผู้ใช้สั่ง "ทุกครั้งที่เจอปัญหาให้แคปหน้าจอเก็บไว้
ทุกครั้ง บันทึกในกฎเลย เพื่อจะให้เรียกขึ้นมาดูได้ง่าย")

วันนั้นสายเจนคลิปล้มรวด 8 ใบ ชื่อสินค้าที่ดึงมาได้คือ "Please Try Again Later"
ซึ่งเดาได้ว่าเป็นหน้าบล็อกของ Shopee **แต่ไม่มีภาพสักใบ** จึงตอบไม่ได้ว่า
หน้านั้นเขียนว่าอะไร มีปุ่มให้กดไหม ต้องรอกี่นาที — ข้อมูลที่ตัดสินใจได้จริง
หายไปพร้อมกับเบราว์เซอร์ที่ปิดไปแล้ว

**หลักการ**

    เก็บ 3 อย่างคู่กันเสมอ  ภาพ (.png) · ผังจอ (.html/.xml) · บริบท (.txt)

    ภาพอย่างเดียวไม่พอ — ค้นหาข้อความในภาพไม่ได้ ต้องเปิดดูทีละใบ
    ผังจออย่างเดียวไม่พอ — ยาวเป็นแสนตัวอักษร ไม่มีใครไล่อ่านจริง
    บริบทอย่างเดียวไม่พอ — บอกได้แค่ที่เราคิด ไม่ได้บอกว่าจริงๆ เห็นอะไร

**ห้ามพังงานหลัก** — ทุกฟังก์ชันกลืน exception หมด การเก็บหลักฐานล้มเหลว
ห้ามทำให้งานที่กำลังล้มอยู่แล้วล้มหนักขึ้น หรือบังหน้าสาเหตุจริง

    python evidence.py                ดูหลักฐานล่าสุด 20 รายการ
    python evidence.py list --tag shopee     เฉพาะเรื่องที่สนใจ
    python evidence.py open <ชื่อ>    เปิดภาพนั้นด้วยโปรแกรมดูรูป
    python evidence.py clean          ลบของเก่าที่เกินเพดาน
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

_data_name = os.environ.get("STUDIO_DATA_DIR", "data")
DATA_DIR = Path(_data_name) if Path(_data_name).is_absolute() else BASE_DIR / _data_name
EVIDENCE_DIR = DATA_DIR / "evidence"

# เก็บกี่เหตุการณ์ — เกินนี้ลบใบเก่าสุดทิ้ง
#
# 300 มาจาก: ล้มหนักสุดที่เคยเจอคือ 33 ใบรวดในรอบเดียว เก็บได้ราว 9 รอบแบบนั้น
# ซึ่งครอบคลุมการไล่ย้อนหลังหลายวัน ภาพหนึ่งใบราว 200-400 KB → เต็มที่ ~120 MB
KEEP_EVENTS = 300


def _stamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def _safe(text: str, limit: int = 40) -> str:
    """ทำชื่อให้ Windows รับได้ — ตัดอักขระต้องห้ามและความยาว"""
    keep = []
    for ch in str(text or ""):
        keep.append("-" if ch in '\\/:*?"<>|\n\r\t' else ch)
    return "".join(keep).strip(" .")[:limit] or "ไม่ระบุ"


def _unique(base: str) -> Path:
    """กันชื่อชนกัน — ล้มสองครั้งในวินาทีเดียวกันเกิดขึ้นจริง

    ถ้าปล่อยให้ชนกัน ใบเก่าจะถูกทับเงียบๆ แล้วหลักฐานหายโดยไม่มีใครรู้
    """
    target = EVIDENCE_DIR / base
    if not any(EVIDENCE_DIR.glob(base + ".*")):
        return target
    serial = 2
    while any(EVIDENCE_DIR.glob(f"{base}-{serial}.*")):
        serial += 1
    return EVIDENCE_DIR / f"{base}-{serial}"


def capture(why: str, tag: str = "ทั่วไป", page=None, note: str = "",
            markup: str = "", now: datetime | None = None) -> Path | None:
    """เก็บหลักฐานหนึ่งเหตุการณ์ — คืนที่อยู่ไฟล์บริบท (.txt)

    `why`    เกิดอะไรขึ้น — ขึ้นต้นชื่อไฟล์ ต้องอ่านแล้วรู้เรื่องทันที
    `tag`    หมวด เช่น shopee · flow · telegram · publish  ไว้กรองตอนค้น
    `page`   หน้า Playwright ถ้ามี — จะแคปภาพและเก็บ HTML ให้
    `note`   บริบทเพิ่ม เช่น ลิงก์สินค้า รหัสงาน ค่าที่วัดได้
    `markup` ผังจอที่อ่านมาแล้ว (เช่น uiautomator dump ของมือถือ)
    """
    try:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        stem = _unique(f"{_stamp(now)}-{_safe(tag, 16)}-{_safe(why)}")
        lines = [
            f"เมื่อ   : {(now or datetime.now()):%d/%m/%Y %H:%M:%S}",
            f"หมวด   : {tag}",
            f"เกิดอะไร: {why}",
        ]

        if page is not None:
            try:
                lines.append(f"หน้าเว็บ: {page.url}")
            except Exception:
                pass
            try:
                page.screenshot(path=str(stem.with_suffix(".png")),
                                full_page=False, timeout=15_000)
                lines.append(f"ภาพ    : {stem.name}.png")
            except Exception as error:
                lines.append(f"ภาพ    : แคปไม่ได้ ({type(error).__name__})")
            try:
                stem.with_suffix(".html").write_text(page.content(), encoding="utf-8")
                lines.append(f"ผังหน้า : {stem.name}.html")
            except Exception:
                pass
            try:
                # ข้อความที่คนอ่านได้จริง — ค้นด้วย grep ได้ ต่างจาก .html ที่ยาวเป็นแสนตัว
                text = page.evaluate("() => document.body ? document.body.innerText : ''")
                if text:
                    stem.with_suffix(".txt2").write_text(str(text)[:20000], encoding="utf-8")
                    lines.append(f"ข้อความบนจอ: {stem.name}.txt2")
            except Exception:
                pass

        if markup:
            try:
                stem.with_suffix(".xml").write_text(markup, encoding="utf-8")
                lines.append(f"ผังจอ  : {stem.name}.xml")
            except Exception:
                pass

        if note:
            lines += ["", "บริบทเพิ่มเติม", str(note)]

        target = stem.with_suffix(".txt")
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        prune()
        return target
    except Exception:
        return None            # เก็บหลักฐานล้มเหลว ห้ามบังสาเหตุจริง


def shot(page, why: str, tag: str = "ทั่วไป", note: str = "") -> Path | None:
    """ทางลัดสำหรับกรณีที่มีหน้าเว็บอยู่ในมือ — ใช้บ่อยที่สุด"""
    return capture(why, tag=tag, page=page, note=note)


def events() -> list[dict]:
    """หลักฐานทั้งหมด ใหม่สุดก่อน"""
    if not EVIDENCE_DIR.is_dir():
        return []
    rows = []
    for path in sorted(EVIDENCE_DIR.glob("*.txt"), reverse=True):
        stem = path.stem
        parts = stem.split("-", 3)
        rows.append({
            "stem": stem,
            "when": f"{parts[0][6:8]}/{parts[0][4:6]} {parts[1][:2]}:{parts[1][2:4]}:{parts[1][4:6]}"
                    if len(parts) > 1 and len(parts[0]) == 8 else stem[:15],
            "tag": parts[2] if len(parts) > 2 else "",
            "why": parts[3] if len(parts) > 3 else "",
            "shot": (EVIDENCE_DIR / (stem + ".png")).is_file(),
            "path": path,
        })
    return rows


# ทุกหมวดต้องเหลืออย่างน้อยเท่านี้ ไม่ว่าหมวดอื่นจะท่วมแค่ไหน (28 ส.ค. 2569)
#
# **ทำไมต้องมี** เจ้าของสั่งให้เก็บภาพหน้าจอ **ทุกขั้น** ตอนโพสต์คลิป
# ซึ่งผังหนึ่งมี 22 ขั้น ไล่โพสต์ 10 ใบต่อคืน = 220 เหตุการณ์ในหมวด `publish`
# ชนเพดานรวม 300 ทันที แล้ว**ไปลบหลักฐาน Shopee บล็อกที่เก็บมาก่อนทิ้ง**
#
# ซึ่งย้อนแย้งกับเหตุผลที่มีระบบนี้ตั้งแต่แรก — 25 ส.ค. ล้มรวด 13 ใบแล้ว
# ไม่มีภาพสักใบให้ดู จึงตอบไม่ได้ว่าหน้าบล็อกเขียนว่าอะไร (กติกาข้อ 2.6.1)
#
# หลักฐานของงานประจำที่มีเยอะ ไม่ควรมีสิทธิ์ลบหลักฐานของเหตุการณ์ที่นานๆ เกิดที
KEEP_PER_TAG = 40


def prune(keep: int = KEEP_EVENTS) -> int:
    """ลบของเก่าที่เกินเพดาน — คืนจำนวนเหตุการณ์ที่ลบไป

    **เพดานรวมอย่างเดียวไม่พอ** หมวดที่มีของเยอะจะไล่ลบหมวดที่มีของน้อยจนหมด
    ตัวนี้จึงกันไว้ว่าทุกหมวดต้องเหลืออย่างน้อย `KEEP_PER_TAG` รายการล่าสุดเสมอ
    """
    rows = events()
    if len(rows) <= keep:
        return 0

    # นับถอยหลังจากใหม่ไปเก่า ว่าแต่ละหมวดยังเหลือกี่รายการ
    kept_per_tag: dict[str, int] = {}
    safe = set()
    for index, row in enumerate(rows):
        tag = str(row.get("tag") or "")
        seen = kept_per_tag.get(tag, 0)
        if index < keep or seen < KEEP_PER_TAG:
            safe.add(row["stem"])
            kept_per_tag[tag] = seen + 1

    dropped = 0
    for row in rows:
        if row["stem"] in safe:
            continue
        for path in EVIDENCE_DIR.glob(row["stem"] + ".*"):
            try:
                path.unlink()
            except OSError:
                pass
        dropped += 1
    return dropped


def summary(limit: int = 20, tag: str = "") -> str:
    """สรุปให้คนอ่าน — ใช้ทั้งใน CLI และส่งเข้าแชท"""
    rows = [r for r in events() if not tag or tag.lower() in r["tag"].lower()]
    if not rows:
        return f"ยังไม่มีหลักฐานเก็บไว้ — ที่เก็บ: {EVIDENCE_DIR}"
    head = [f"📸 หลักฐานตอนพัง {len(rows)} เหตุการณ์"
            + (f" (กรอง \"{tag}\")" if tag else ""), ""]
    for row in rows[:limit]:
        head.append(f"{row['when']} · [{row['tag']}] {row['why']}"
                    + ("  📷" if row["shot"] else ""))
    if len(rows) > limit:
        head.append(f"… อีก {len(rows) - limit} รายการ")
    head += ["", f"ที่เก็บ: {EVIDENCE_DIR}"]
    return "\n".join(head)


# ------------------------------------------------------------------ คำสั่ง

def _say(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((message + "\n").encode("utf-8", "replace"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="หลักฐานตอนระบบพัง")
    sub = parser.add_subparsers(dest="cmd")
    p_list = sub.add_parser("list", help="ดูรายการ")
    p_list.add_argument("--tag", default="")
    p_list.add_argument("--limit", type=int, default=20)
    p_open = sub.add_parser("open", help="เปิดภาพของเหตุการณ์นั้น")
    p_open.add_argument("stem")
    sub.add_parser("clean", help="ลบของเก่าที่เกินเพดาน")
    args = parser.parse_args(argv)

    if args.cmd == "open":
        hits = list(EVIDENCE_DIR.glob(f"*{args.stem}*.png"))
        if not hits:
            _say(f"ไม่พบภาพของ {args.stem}")
            return 1
        _say(f"เปิด {hits[0].name}")
        if os.name == "nt":
            os.startfile(str(hits[0]))                       # noqa: S606
        else:
            subprocess.run(["xdg-open", str(hits[0])], check=False)
        return 0
    if args.cmd == "clean":
        _say(f"ลบไป {prune()} เหตุการณ์")
        return 0
    _say(summary(getattr(args, "limit", 20), getattr(args, "tag", "")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
