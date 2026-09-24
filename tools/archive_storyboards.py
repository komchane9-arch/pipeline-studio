"""ย้ายสตอรีบอร์ดเก่าไปเก็บ ก่อนสั่งให้ ChatGPT วาดชุดใหม่

**เจ้าของสั่ง 9 ก.ย. 2569** — *"รันสร้างสตอรี่บอร์ดใหม่ทั้งหมดโดยมี presenter
เป็นผู้หญิงที่ผมแนบ **แต่เก็บ storyboard เก่าไว้ด้วยนะ**"*

ตัวนี้ทำ **ขั้นที่ 1 ของแผน** อย่างเดียว — เก็บของเก่าให้ปลอดภัย
**ไม่เรียก ChatGPT ไม่เจนอะไรทั้งสิ้น**

แผนเต็ม: `note/2026-09-09-แผนเจนสตอรีบอร์ดใหม่ทั้งกอง-ใส่พรีเซนเตอร์.md`


ทำไมต้องมีตัวนี้ ทำมือไม่ได้เหรอ
--------------------------------

ตรวจโค้ดแล้ว **ของเดิมถูกทับทิ้งหมดโดยไม่มีอะไรเตือน**

    clip_store.save_storyboard()   เขียนทับ run["storyboard"] ทั้งช่อง
    chatgpt_driver                 ดาวน์โหลดภาพใหม่ลง storyboard/ ชื่อขึ้นต้น
                                   storyboard- เหมือนเดิมทุกประการ

ทับแล้ว **กู้ไม่ได้** เพราะภาพต้นฉบับอยู่บนเซิร์ฟเวอร์ ChatGPT ซึ่งลิงก์หมดอายุ

และต้องเก็บ **สามอย่างพร้อมกัน** ไม่ใช่แค่ภาพ — ภาพ · คำสั่ง Flow · บทพูด
สามอย่างนี้ผูกกันเป็นชุดเดียว เก็บแค่ภาพแล้ววันหนึ่งอยากย้อนกลับ จะย้อนไม่ได้


วิธีใช้
-------

    python tools/archive_storyboards.py --scope not-generated          ← ดูก่อน (ไม่แก้)
    python tools/archive_storyboards.py --scope not-generated --apply  ← ทำจริง

ขอบเขต
    not-posted      ใบที่ยังไม่ได้โพสต์ที่ไหนเลย
    not-generated   ใบที่ยังไม่ได้เจนคลิป      (แนะนำ)
    all             ทุกใบ
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import clip_store  # noqa: E402
import studio_shared as shared  # noqa: E402

REASON = "ทำสตอรีบอร์ดใหม่เพื่อใส่พรีเซนเตอร์ (เจ้าของสั่ง 9 ก.ย. 2569)"
POST_TARGETS = ("shopee_video", "facebook_reels", "tiktok")


def posted_anywhere(run: dict) -> bool:
    publish = run.get("publish") or {}
    return any((publish.get(t) or {}).get("status") == "posted" for t in POST_TARGETS)


def candidates(root: Path, scope: str) -> list[dict]:
    """ใบที่เข้าขอบเขต **และมีสตอรีบอร์ดเก่าให้เก็บจริง**

    ใบที่ยังไม่มีสตอรีบอร์ดไม่ต้องเก็บอะไร — ข้ามไปเลย ไม่ใช่ error
    """
    rows: list[dict] = []
    for bucket in clip_store.ALL_DIRS:
        base = root / bucket
        if not base.is_dir():
            continue
        for folder in sorted(base.iterdir(), key=lambda p: p.name):
            run_file = folder / clip_store.RUN_FILE
            if not folder.is_dir() or not run_file.is_file():
                continue
            run = clip_store._read_json(run_file)  # noqa: SLF001
            if not run:
                continue
            if scope == "not-posted" and posted_anywhere(run):
                continue
            if scope == "not-generated" and run.get("videos"):
                continue

            sb_dir = folder / clip_store.STORYBOARD_DIR
            images = []
            if sb_dir.is_dir():
                images = sorted(p for p in sb_dir.iterdir()
                                if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
            if not images and not run.get("storyboard"):
                continue                      # ไม่มีของเก่าให้เก็บ

            # ⛔ **ข้ามใบที่เก็บไปแล้วในรอบนี้**
            #
            # พอใบหนึ่งทำสตอรีบอร์ดใหม่เสร็จ มันจะ "มีสตอรีบอร์ด" อีกครั้ง
            # ถ้าไม่กันไว้ รอบถัดไปจะเอา**ของใหม่ที่เพิ่งทำ**ไปเก็บเป็นของเก่า
            # แล้วงานที่เสร็จแล้วหายทั้งใบ (เจอจริง 10 ก.ย. 2569 — เกือบโดน 5 ใบ)
            if any(str(row.get("why") or "") == REASON
                   for row in (run.get("storyboard_history") or [])):
                continue

            rows.append({
                "item_id": str(run.get("item_id") or folder.name),
                "name": str(run.get("name") or "")[:60],
                "folder": folder,
                "run_file": run_file,
                "run": run,
                "sb_dir": sb_dir,
                "images": images,
            })
    return rows


def backup_zip(root: Path, rows: list[dict], stamp: str) -> Path:
    """สำรองทั้งกองเป็นไฟล์เดียวก่อนแตะอะไร — ชั้นกันพลาดชั้นนอกสุด"""
    target = root / "backup" / f"storyboard-ก่อนใส่พรีเซนเตอร์-{stamp}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            rel_run = row["run_file"].relative_to(root).as_posix()
            zf.write(row["run_file"], rel_run)
            for image in row["images"]:
                zf.write(image, image.relative_to(root).as_posix())
            manifest.append({
                "item_id": row["item_id"],
                "name": row["name"],
                "run_file": rel_run,
                "images": [p.relative_to(root).as_posix() for p in row["images"]],
                "flow_prompts": row["run"].get("flow_prompts") or [],
                "script": row["run"].get("script") or [],
            })
        zf.writestr("manifest.json", json.dumps({
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "reason": REASON,
            "count": len(rows),
            "items": manifest,
        }, ensure_ascii=False, indent=2))
    return target


def archive_one(root: Path, row: dict, stamp: str) -> dict:
    """ย้ายของเก่าของใบเดียว + จดประวัติลงใบงาน

    **ย้าย ไม่ใช่ก๊อป** — ก๊อปแล้วโฟลเดอร์เดิมยังมีภาพเก่าค้าง พอ ChatGPT วาด
    ชุดใหม่ที่มีจำนวนฉากไม่เท่าเดิม จะเหลือภาพเก่าปนกับภาพใหม่ในโฟลเดอร์เดียวกัน
    แล้วไม่มีใครแยกออกว่าใบไหนของรอบไหน
    """
    folder: Path = row["folder"]
    old_name = f"{clip_store.STORYBOARD_DIR}-เก่า-{stamp}"
    old_dir = folder / old_name

    moved = 0
    if row["sb_dir"].is_dir():
        if old_dir.exists():
            raise RuntimeError(f"{row['item_id']}: มีโฟลเดอร์ {old_name} อยู่แล้ว")
        shutil.move(str(row["sb_dir"]), str(old_dir))
        moved = len([p for p in old_dir.iterdir() if p.is_file()])

    # เก็บสำเนาใบงานก่อนแก้ไว้ข้างๆ ของเก่า — อ่านย้อนได้โดยไม่ต้องแตะ zip
    (old_dir if old_dir.is_dir() else folder).mkdir(parents=True, exist_ok=True)
    if old_dir.is_dir():
        (old_dir / "run-เก่า.json").write_text(
            json.dumps(row["run"], ensure_ascii=False, indent=1), encoding="utf-8")

    run = clip_store._read_json(row["run_file"])  # noqa: SLF001
    # กันชนกับงานอื่นที่อาจแก้ใบนี้ระหว่างเราทำ dry-run อยู่
    if run.get("storyboard") != row["run"].get("storyboard"):
        raise RuntimeError(f"{row['item_id']}: ใบงานถูกแก้ระหว่างทาง — ยกเลิก")

    history = list(run.get("storyboard_history") or [])
    history.append({
        "at": datetime.now().isoformat(timespec="seconds"),
        "folder": old_name,
        "frames": list(run.get("storyboard") or []),
        "flow_prompts": list(run.get("flow_prompts") or []),
        "script": list(run.get("script") or []),
        "chat_url": str(run.get("chat_url") or ""),
        "why": REASON,
    })
    run["storyboard_history"] = history
    # **ล้างช่องของรอบใหม่ให้ว่าง** เพื่อให้ด่านขั้นที่ 3 (ต้องมีภาพจริงถึงจะผ่าน)
    # ทำงานได้ตามปกติ ถ้าปล่อยค่าเก่าไว้ ระบบจะนึกว่าใบนี้มีสตอรีบอร์ดแล้ว
    for key in ("storyboard", "storyboard_count", "storyboard_at"):
        run.pop(key, None)
    clip_store._write_json(row["run_file"], run)  # noqa: SLF001

    return {"item_id": row["item_id"], "moved": moved, "folder": old_name}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scope", default="not-generated",
                        choices=("not-posted", "not-generated", "all"))
    parser.add_argument("--apply", action="store_true",
                        help="ทำจริง (ไม่ใส่ = ดูอย่างเดียว)")
    parser.add_argument("--root", default=str(shared.DATA_DIR))
    parser.add_argument("--limit", type=int, default=0,
                        help="ทำแค่กี่ใบ (0 = ทั้งหมด) ใช้ตอนลองกับไม่กี่ใบก่อน")
    args = parser.parse_args()

    root = Path(args.root)
    rows = candidates(root, args.scope)
    if args.limit:
        rows = rows[:args.limit]

    images = sum(len(r["images"]) for r in rows)
    print(f"ขอบเขต: {args.scope} · เจอใบที่มีสตอรีบอร์ดเก่า {len(rows)} ใบ "
          f"· ไฟล์ภาพรวม {images} ไฟล์")
    if not rows:
        print("ไม่มีอะไรต้องเก็บ")
        return 0
    for row in rows[:8]:
        print(f"   {row['item_id']:<14} ภาพ {len(row['images'])} ใบ  {row['name']}")
    if len(rows) > 8:
        print(f"   … อีก {len(rows) - 8} ใบ")

    if not args.apply:
        print("\nนี่คือโหมดดูอย่างเดียว ยังไม่ได้แก้อะไร")
        print("ทำจริงให้ใส่ --apply")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = backup_zip(root, rows, stamp)
    print(f"\nสำรองไว้ที่ {zip_path} ({zip_path.stat().st_size/1048576:.1f} MB)")

    done, failed = [], []
    for row in rows:
        try:
            done.append(archive_one(root, row, stamp))
        except Exception as error:                            # noqa: BLE001
            failed.append((row["item_id"], f"{type(error).__name__}: {error}"))
            break            # **หยุดทันทีที่ใบแรกพลาด** อย่าทำต่อจนพังทั้งกอง

    print(f"\nย้ายของเก่าแล้ว {len(done)} ใบ · ล้มเหลว {len(failed)} ใบ")
    for item_id, why in failed:
        print(f"   ✕ {item_id}: {why}")

    # ---- ตรวจซ้ำหลังทำ: ทุกใบที่ทำไปต้องมีของเก่าอยู่จริง -------------------
    bad = []
    for entry in done:
        row = next(r for r in rows if r["item_id"] == entry["item_id"])
        old_dir = row["folder"] / entry["folder"]
        run = clip_store._read_json(row["run_file"])          # noqa: SLF001
        if not old_dir.is_dir():
            bad.append((entry["item_id"], "ไม่เจอโฟลเดอร์ของเก่า"))
        elif not run.get("storyboard_history"):
            bad.append((entry["item_id"], "ไม่ได้จดประวัติลงใบงาน"))
        elif run.get("storyboard"):
            bad.append((entry["item_id"], "ช่องสตอรีบอร์ดยังไม่ว่าง"))
    print(f"ตรวจซ้ำ: ผ่าน {len(done) - len(bad)}/{len(done)} ใบ")
    for item_id, why in bad:
        print(f"   ✕ {item_id}: {why}")

    if failed or bad:
        print("\n⛔ มีใบที่ไม่ผ่าน — **อย่าเพิ่งสั่งทำสตอรีบอร์ดใหม่**")
        print(f"   ของเดิมทั้งกองอยู่ใน {zip_path}")
        return 1
    print("\n✅ ของเก่าเก็บครบทุกใบแล้ว สั่งทำสตอรีบอร์ดใหม่ต่อได้")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
