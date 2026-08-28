"""ลบโพสต์ของเราเองในกลุ่ม — **ทำลายถาวร กู้คืนไม่ได้**

ใช้สำหรับเก็บกวาดโพสต์เก่าออกจากกลุ่มที่ไม่อยากให้เหลือของเราอยู่

**ทำไมแยกเป็นสคริปต์ต่างหาก ไม่ทำเป็นคำสั่งในบอท**
งานนี้ทำลายของถาวร ต่างจากทุกอย่างในระบบที่ผิดแล้วยังแก้กลับได้ (โพสต์ผิดก็ลบ ·
รูปผิดก็แก้ · คอมเมนต์ผิดก็ลบ) — ทำเป็นปุ่มในบอทแปลว่าวันหนึ่งจะมีคนกดพลาด
ต้องพิมพ์คำสั่งเองพร้อมระบุกลุ่ม และต้องพิมพ์ยืนยันอีกชั้นถึงจะลงมือ

**ลำดับที่ปลอดภัย** (ทำตามนี้เท่านั้น)

    1. `--survey`  เปิดโพสต์แล้วอ่านเมนูมาดูเฉยๆ ไม่แตะอะไร
       → เอาไว้ยืนยันว่าป้ายปุ่มลบบนเครื่องนี้เขียนว่าอะไรจริงๆ
    2. `--limit 1` ลบใบเดียวก่อน แล้วไปดูด้วยตาว่าใบที่หายคือใบที่ตั้งใจ
    3. ลบที่เหลือ

ที่ต้องทำแบบนี้เพราะ **หน้าจอเมนูลบยังไม่เคยเห็นของจริง** — เดาป้ายปุ่มแล้วแตะมั่ว
บนหน้าที่มีทั้ง "ลบโพสต์" และ "รายงานโพสต์" อยู่ใกล้กันคือความเสี่ยงที่ไม่ควรรับ
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import facebook_group_post as fb
import fb_preflight
import fb_auto_post
import studio_shared

def JOBS_FILE():
    """แฟ้มของบัญชีที่กำลังทำงาน — ย้ายมาแยกรายบัญชี 28 ส.ค. 2569

    เดิมเป็นค่าคงที่ชี้แฟ้มใบเดียวที่ทุกบัญชีใช้ร่วมกัน พอมีบัญชีที่สอง
    ข้อมูลจะปนกันเงียบๆ จึงเปลี่ยนเป็นฟังก์ชันที่หาพาธตอนเรียกใช้
    """
    return fb_auto_post.state_file("fb_jobs.json")

# ป้ายปุ่มลบในเมนู "…" ของโพสต์ตัวเอง
#
# เรียงจากเฉพาะเจาะจงที่สุดไปกว้างสุด และ **ห้ามใส่คำว่า "ลบ" เดี่ยวๆ** เพราะ
# `_tap_clickable` เทียบแบบมีคำนี้อยู่ในป้าย — "ลบ" จะไปตรงกับ "ลบรูปภาพออก"
# หรือปุ่มอื่นที่ไม่ได้ตั้งใจ
DELETE_POST_HINTS = (
    "ย้ายไปที่ถังขยะ", "ย้ายไปถังขยะ", "Move to trash",
    "ลบโพสต์", "ลบโพสต์นี้", "Delete post",
)
# ปุ่มยืนยันในกล่องที่เด้งขึ้นมาหลังกดลบ
DELETE_CONFIRM_HINTS = (
    "ย้ายไปที่ถังขยะ", "ย้ายไปถังขยะ", "Move to trash",
    "ลบโพสต์", "Delete post", "ลบ", "Delete", "ตกลง", "OK",
)
# ป้ายที่แปลว่า "เมนูนี้ไม่ใช่โพสต์ของเรา" — เจอแล้วต้องหยุดทันที
NOT_MINE_HINTS = ("รายงานโพสต์", "Report post", "บล็อก", "Block")


def load_jobs() -> list[dict]:
    try:
        return json.loads(JOBS_FILE().read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"อ่าน {JOBS_FILE()} ไม่ได้: {error}")


def targets_of_group(group_id: str, jobs: list[dict]) -> list[dict]:
    """โพสต์ทั้งหมดที่เคยลงกลุ่มนี้สำเร็จ — ใหม่สุดก่อน

    เอาเฉพาะที่ `posted` จริง ส่วนที่ไม่มีลิงก์ก็เก็บมาด้วยเพราะยังลองเปิดจาก
    แจ้งเตือน/ฟีดได้ (`open_own_post` มีทางถอยอยู่แล้ว) แค่โอกาสเจอน้อยกว่า
    """
    rows = []
    for job in jobs:
        for result in job.get("results") or []:
            if str(result.get("group_id")) != str(group_id):
                continue
            if not result.get("posted"):
                continue
            rows.append({
                "job_id": job["id"],
                "group_id": str(group_id),
                "caption": (job.get("caption") or "").strip(),
                "link": result.get("link", ""),
                "post_id": result.get("post_id", ""),
                "when": (job.get("finished_at") or job.get("started_at")
                         or job.get("created_at") or "")[:16].replace("T", " "),
            })
    rows.sort(key=lambda r: r["when"], reverse=True)
    return rows


def open_target(phone: fb.Phone, target: dict) -> bool:
    """เปิดโพสต์ใบนั้นให้ได้ — ลิงก์ก่อน ไม่มีลิงก์ค่อยไล่จากแจ้งเตือน/ฟีด"""
    if target["link"]:
        return fb.open_post_link(phone, target["link"], target["caption"],
                                 target["group_id"], target["post_id"])
    found = fb.open_own_post(phone, target["group_id"], target["caption"])
    return bool(found and found.get("route"))


def menu_labels(phone: fb.Phone) -> list[str]:
    """ป้ายทุกอันในเมนูที่เปิดอยู่ — ใช้สำรวจว่าเครื่องนี้เขียนว่าอะไร"""
    seen = []
    for labels, _, clickable in fb.iter_widgets(phone.dump()):
        for label in labels:
            text = label.strip()
            if text and clickable and text not in seen:
                seen.append(text)
    return seen


def survey(phone: fb.Phone, target: dict) -> list[str]:
    """เปิดโพสต์ + เปิดเมนู แล้วอ่านป้ายมาดู — **ไม่แตะปุ่มลบ**"""
    if not open_target(phone, target):
        phone.log("  เปิดโพสต์ไม่ได้")
        return []
    if not fb._tap_clickable(phone, fb.POST_MENU_HINTS, "ปุ่ม …", wait=2.5):
        return []
    labels = menu_labels(phone)
    phone.shell("input keyevent KEYCODE_BACK")   # ปิดเมนูทิ้ง ไม่ค้างไว้
    time.sleep(1.0)
    return labels


def delete_post(phone: fb.Phone, target: dict) -> str:
    """ลบโพสต์ใบนี้ — คืน "" ถ้าสำเร็จ · ข้อความบอกเหตุถ้าไม่

    ทุกขั้นต้องเจอหมุดจริงถึงไปต่อ ไม่เจอ = หยุดทันที ไม่เดาแล้วแตะมั่ว
    """
    caption = target["caption"]
    if not open_target(phone, target):
        return "เปิดโพสต์ไม่ได้"
    # ยืนยันว่าโพสต์ที่เปิดอยู่คือใบที่ตั้งใจจริงๆ ก่อนจะไปแตะเมนูลบ
    probe = caption.strip()[:12]
    if probe and not fb.screen_has(phone.dump(), probe):
        return "เปิดได้แต่ไม่ใช่โพสต์ที่ตั้งใจ (แคปชันไม่ตรง)"
    if not fb._tap_clickable(phone, fb.POST_MENU_HINTS, "ปุ่ม …", wait=2.5):
        return "หาปุ่ม … ของโพสต์ไม่เจอ"

    labels = menu_labels(phone)
    joined = " | ".join(labels)
    if not any(any(hint in label for label in labels) for hint in DELETE_POST_HINTS):
        # เมนูของโพสต์คนอื่นจะมี "รายงานโพสต์" แต่ไม่มี "ลบ" — กันแตะผิดใบ
        note = "เมนูนี้ไม่มีตัวเลือกลบ"
        if any(any(hint in label for label in labels) for hint in NOT_MINE_HINTS):
            note += " (น่าจะไม่ใช่โพสต์ของเรา)"
        phone.log(f"  ป้ายในเมนู: {joined}")
        phone.shell("input keyevent KEYCODE_BACK")
        return note

    if not fb._tap_clickable(phone, DELETE_POST_HINTS, "เมนูลบโพสต์", wait=3.0):
        return "กดปุ่มลบไม่สำเร็จ"
    # กล่องยืนยัน — บางรุ่นเด้ง บางรุ่นลบเลย เจอก็กด ไม่เจอก็ไปตรวจผลต่อ
    if fb._tap_clickable(phone, DELETE_CONFIRM_HINTS, "ปุ่มยืนยันลบ", wait=4.0):
        phone.log("  กดยืนยันลบแล้ว")
    time.sleep(3.0)

    # ตรวจผลจริง — ห้ามเชื่อว่ากดแล้วต้องสำเร็จ
    if probe and fb.screen_has(phone.dump(), probe):
        return "กดลบแล้วแต่โพสต์ยังอยู่บนจอ"
    return ""


def run(serial: str, adb: str, group_id: str, rows: list[dict], *,
        survey_only: bool, limit: int, log=print) -> list[dict]:
    fb_preflight.guard(serial, what="ลบโพสต์", adb=adb, check_lock=False)
    results = []
    with studio_shared.phone_lock(serial, timeout=120.0,
                                  label=f"ลบโพสต์กลุ่ม {group_id}"):
        phone = fb.Phone(adb, serial, log=log)
        fb.require_network(phone)
        for index, target in enumerate(rows[:limit], 1):
            head = target["caption"].splitlines()[0][:32]
            log(f"[{index}/{min(limit, len(rows))}] {target['when']} · {head}")
            if survey_only:
                labels = survey(phone, target)
                log(f"  ป้ายในเมนู: {' | '.join(labels) or '(อ่านไม่ได้)'}")
                results.append({**target, "labels": labels})
                continue
            error = delete_post(phone, target)
            log("  ✅ ลบแล้ว" if not error else f"  ❌ {error}")
            results.append({**target, "deleted": not error, "error": error})
            time.sleep(4.0)     # เว้นจังหวะ ไม่รัวจนดูเป็นบอท
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ลบโพสต์ของเราในกลุ่มที่ระบุ")
    parser.add_argument("group_id", help="รหัสกลุ่ม")
    parser.add_argument("--serial", default="", help="เครื่องที่จะสั่ง")
    parser.add_argument("--adb", default="", help="พาธ adb (ต้องตรงกับที่ระบบใช้)")
    parser.add_argument("--survey", action="store_true",
                        help="อ่านเมนูมาดูเฉยๆ ไม่ลบอะไร")
    parser.add_argument("--limit", type=int, default=1,
                        help="ทำกี่ใบ (ปริยาย 1 ใบ — ตั้งใจให้ต้องระบุเองถ้าจะเอาเยอะ)")
    parser.add_argument("--yes", action="store_true",
                        help="ยืนยันว่าจะลบจริง (ไม่ใส่ = ไม่ลบ)")
    parser.add_argument("--list", action="store_true", help="ดูรายการเฉยๆ")
    args = parser.parse_args(argv)

    rows = targets_of_group(args.group_id, load_jobs())
    print(f"โพสต์ที่เคยลงกลุ่ม {args.group_id}: {len(rows)} ใบ "
          f"(มีลิงก์ {sum(1 for r in rows if r['link'])})")
    for row in rows:
        print(f"  {row['when']} {row['job_id']} "
              f"{'มีลิงก์' if row['link'] else 'ไม่มีลิงก์'} · "
              f"{row['caption'].splitlines()[0][:40]}")
    if args.list or not rows:
        return 0

    if not args.survey and not args.yes:
        print("\n⚠️ ยังไม่ลบ — ลบจริงต้องใส่ --yes ด้วย (ลบแล้วกู้คืนไม่ได้)")
        return 1

    adb = args.adb or "adb"
    serial = args.serial
    if not serial:
        print("ต้องระบุ --serial")
        return 2
    results = run(serial, adb, args.group_id, rows,
                  survey_only=args.survey, limit=max(1, args.limit))
    if not args.survey:
        done = sum(1 for r in results if r.get("deleted"))
        print(f"\nลบสำเร็จ {done}/{len(results)} ใบ")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
