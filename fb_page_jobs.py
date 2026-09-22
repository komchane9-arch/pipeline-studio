# -*- coding: utf-8 -*-
"""เอาใบงานที่เคยโพสต์ลงกลุ่ม ไปโพสต์ซ้ำลง **เพจ** แล้วจดว่าโพสต์ไปแล้ว

เจ้าของสั่ง 22 ก.ย. 2569 — *"เพิ่มให้มีปุ่ม post facebook แล้วเอาใบงานที่โพสต์
บันทึกว่าโพสต์แล้ว โดยปุ่มโพสต์ facebook จะไปทำการโพสต์ตาม step ที่โพสต์
สำเร็จเมื่อกี้"*

## รูปแบบที่ใช้ — ของที่พิสูจน์แล้วว่าใช้ได้จริง

เจ้าของกำหนดรูปแบบเองตอนทดลองโพสต์ใบแรก

    แคปชันของโพสต์ = แคปชันเดิม
                     (เว้นหนึ่งบรรทัด)
                     คอมเมนต์ที่ 1
                     (เว้นหนึ่งบรรทัด)
                     คอมเมนต์ที่ 2
    แล้ว**ยัง**คอมเมนต์ 1 กับ 2 ใต้โพสต์อีกที + กดไลก์โพสต์ + ไลก์คอมเมนต์

## จดว่าโพสต์แล้ว — จดเมื่อ "ขึ้นจริง" เท่านั้น

ไม่ใช่ตอนกดสั่ง (กติกาข้อ 2.3.1) — สั่งแล้วล้มกลางทางเป็นเรื่องปกติ ถ้าจดตอน
สั่งจะได้ป้าย "โพสต์แล้ว" บนใบที่ไม่เคยขึ้น แล้วไม่มีใครกลับมาโพสต์ให้อีก

    python fb_page_jobs.py list            ใบที่ลงเพจไปแล้ว
    python fb_page_jobs.py show <รหัสใบงาน>  ใบนี้มีอะไรบ้าง ลงได้ไหม
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import studio_shared

STORE = "fb_page_posted.json"


def _file() -> Path:
    return studio_shared.DATA_DIR / STORE


# ------------------------------------------------------------ ทะเบียนที่ลงแล้ว

def posted() -> dict:
    """{รหัสใบงาน: {page, at, liked, comment_count}} — ใบที่ลงเพจไปแล้วจริง"""
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def mark_posted(job_id: str, page: str, result: dict) -> dict:
    """จดว่าใบนี้ลงเพจแล้ว — **เรียกเฉพาะตอนยืนยันได้ว่าโพสต์ขึ้นจริง**

    เขียนผ่าน `update_json` เพราะสองเซิร์ฟเวอร์ใช้ไฟล์ร่วมกัน อ่าน-แก้-เขียนเอง
    เคยทำข้อมูลหาย 4 ใน 5 รอบทดสอบ (กติกาข้อ 7.5)
    """
    row = {
        "page": page,
        "at": time.strftime("%Y-%m-%d %H:%M"),
        "liked": bool(result.get("liked")),
        "comment_count": int(result.get("comment_count") or 0),
        "comment_liked": bool(result.get("comment_liked")),
    }

    def change(data: dict) -> None:
        data[str(job_id)] = row

    studio_shared.update_json(_file(), change, default={})
    return row


def clear_posted(job_id: str) -> bool:
    """ลบบันทึกของใบนี้ออก — ใช้ตอนโพสต์พลาดแล้วอยากลงใหม่"""
    found = [False]

    def change(data: dict) -> None:
        found[0] = data.pop(str(job_id), None) is not None

    studio_shared.update_json(_file(), change, default={})
    return found[0]


# ------------------------------------------------------------ อ่านใบงาน

def _job_files() -> list[Path]:
    root = studio_shared.DATA_DIR / "facebook-post-state" / "accounts"
    return sorted(root.glob("*/fb_jobs.json")) if root.is_dir() else []


def find_job(job_id: str) -> dict | None:
    """หาใบงานจากทุกบัญชี — None เมื่อไม่มีใบนี้"""
    want = str(job_id or "").strip()
    if not want:
        return None
    for path in _job_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = data.get("jobs") if isinstance(data, dict) else data
        rows = rows.values() if isinstance(rows, dict) else (rows or [])
        for job in rows:
            if isinstance(job, dict) and str(job.get("id")) == want:
                job = dict(job)
                job["account_folder"] = path.parent.name
                return job
    return None


def build(job: dict) -> dict:
    """แปลงใบงานเป็นของที่ `facebook_page_post` ใช้ได้ พร้อมบอกว่าติดอะไรบ้าง

    คืน dict ที่มี `blocked` เป็นเหตุผลภาษาคนเมื่อลงไม่ได้ — ว่างแปลว่าลงได้
    **ไม่เดาแทน** รูปหายก็บอกว่ารูปหาย ไม่ใช่ลงไปโดยไม่มีรูป
    """
    caption = str(job.get("caption") or "").strip()
    comments = [str(c).strip() for c in (job.get("comments") or []) if str(c or "").strip()]
    raw = job.get("images") or ([job.get("image")] if job.get("image") else [])
    images = [Path(p) for p in raw if p]
    alive = [p for p in images if p.is_file()]

    blocked = ""
    if not caption:
        blocked = "ใบงานนี้ไม่มีแคปชัน"
    elif images and not alive:
        blocked = (f"รูปของใบงานนี้ไม่อยู่แล้ว ({len(images)} ใบ) "
                   "— ระบบเก็บรูปไว้ 300 ใบล่าสุด ของเก่ากว่านั้นถูกลบไป "
                   "ถ้าจะลงเพจต้องหารูปมาใส่ใหม่")
    elif len(alive) < len(images):
        blocked = f"รูปหายไป {len(images) - len(alive)} จาก {len(images)} ใบ"

    # แคปชันของโพสต์ = แคปชันเดิม + คอมเมนต์ทุกข้อความ คั่นด้วยบรรทัดว่าง
    full = "\n\n".join([caption] + comments) if comments else caption
    return {
        "id": str(job.get("id") or ""),
        "account": str(job.get("account") or job.get("account_folder") or ""),
        "caption": caption,
        "full_caption": full,
        "comments": comments,
        "images": [str(p) for p in alive],
        "images_missing": len(images) - len(alive),
        "blocked": blocked,
    }


def plan(job_id: str) -> dict:
    """ใบนี้ลงเพจได้ไหม + จะลงอะไรบ้าง — ใช้ให้หน้าเว็บโชว์ก่อนกดยืนยัน"""
    job = find_job(job_id)
    if job is None:
        return {"id": str(job_id), "found": False,
                "blocked": f"ไม่พบใบงาน {job_id} ในแฟ้มของบัญชีไหนเลย"}
    got = build(job)
    got["found"] = True
    got["posted"] = posted().get(str(job_id)) or None
    return got


# ---------------------------------------------------------------- คอนโซล

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ใบงานที่เอาไปลงเพจ")
    parser.add_argument("command", choices=["list", "show", "clear"])
    parser.add_argument("job_id", nargs="?", default="")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    if args.command == "list":
        rows = posted()
        if not rows:
            print("ยังไม่มีใบไหนลงเพจเลย")
            return 0
        print(f"ลงเพจไปแล้ว {len(rows)} ใบ")
        for job_id, row in sorted(rows.items(), key=lambda kv: kv[1].get("at", "")):
            print(f"  {job_id}  {row.get('at')}  เพจ {row.get('page')} · "
                  f"ไลก์ {'ติด' if row.get('liked') else 'ไม่ติด'} · "
                  f"คอมเมนต์ {row.get('comment_count')} ข้อความ")
        return 0

    if not args.job_id:
        print("ต้องบอกรหัสใบงานด้วย")
        return 2

    if args.command == "clear":
        print("ลบบันทึกแล้ว" if clear_posted(args.job_id) else "ไม่มีบันทึกของใบนี้")
        return 0

    got = plan(args.job_id)
    if not got.get("found"):
        print(got.get("blocked"))
        return 1
    print(f"ใบงาน {got['id']} · บัญชี {got['account']}")
    print(f"  รูปที่ยังอยู่ : {len(got['images'])} ใบ"
          + (f" (หายไป {got['images_missing']})" if got["images_missing"] else ""))
    print(f"  คอมเมนต์     : {len(got['comments'])} ข้อความ")
    print(f"  ลงเพจแล้วยัง : {got['posted'] or 'ยัง'}")
    print(f"  ลงได้ไหม     : {'❌ ' + got['blocked'] if got['blocked'] else '✅ ลงได้'}")
    print("-" * 60)
    print(got["full_caption"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
