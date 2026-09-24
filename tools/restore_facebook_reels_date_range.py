"""คืนใบที่เคยจดว่าโพสต์ Facebook Reels ในช่วงวันที่กลับเข้าคิว.

ค่าเริ่มต้นเป็น dry-run; ต้องส่ง ``--apply`` จึงจะแก้ไฟล์จริง. ก่อนแก้จะสร้าง
ZIP ของ run.json ทุกสำเนาที่ได้รับผล พร้อม manifest สำหรับตรวจย้อนหลัง/กู้คืน.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import clip_store  # noqa: E402


TARGET = "facebook_reels"


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"วันที่ไม่ถูกต้อง: {value}") from error


def candidates(root: Path, start: date, end: date) -> list[dict]:
    rows: list[dict] = []
    for bucket in clip_store.ALL_DIRS:
        base = root / bucket
        if not base.is_dir():
            continue
        for folder in sorted(base.iterdir(), key=lambda path: path.name):
            run_file = folder / clip_store.RUN_FILE
            if not folder.is_dir() or not run_file.is_file():
                continue
            run = clip_store._read_json(run_file)  # noqa: SLF001 - migration tool
            state = ((run.get("publish") or {}).get(TARGET) or {})
            posted_at = str(state.get("posted_at") or "")
            try:
                posted_day = date.fromisoformat(posted_at[:10])
            except ValueError:
                continue
            if state.get("status") != "posted" or not start <= posted_day <= end:
                continue
            rows.append({
                "item_id": str(run.get("item_id") or folder.name),
                "name": str(run.get("name") or ""),
                "posted_at": posted_at,
                "folder": folder,
                "run_file": run_file,
                "run": run,
                "old_state": dict(state),
            })
    return sorted(rows, key=lambda row: (row["posted_at"], row["item_id"]))


def backup(root: Path, rows: list[dict], start: date, end: date) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = root / "backup" / f"facebook-reels-{start}-{end}-{stamp}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, row in enumerate(rows, 1):
            relative = row["run_file"].relative_to(root).as_posix()
            archive.write(row["run_file"], f"runs/{index:03d}/{relative}")
            manifest.append({
                "item_id": row["item_id"],
                "name": row["name"],
                "posted_at": row["posted_at"],
                "source": relative,
                "old_state": row["old_state"],
            })
        archive.writestr(
            "manifest.json",
            json.dumps({
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "target": TARGET,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "count": len(rows),
                "items": manifest,
            }, ensure_ascii=False, indent=2),
        )
    return target


def restore(root: Path, rows: list[dict], reason: str) -> list[dict]:
    changed = []
    restored_at = datetime.now().isoformat(timespec="seconds")
    for row in rows:
        folder: Path = row["folder"]
        run = clip_store._read_json(folder / clip_store.RUN_FILE)  # noqa: SLF001
        publish = run.get("publish") or {}
        current = dict((publish.get(TARGET) or {}))
        # ป้องกัน race: ถ้าสถานะเปลี่ยนหลัง dry-run ห้ามทับข้อมูลใหม่.
        if (current.get("status") != "posted"
                or str(current.get("posted_at") or "") != row["posted_at"]):
            raise RuntimeError(
                f"สถานะ {row['item_id']} เปลี่ยนระหว่างทำ; ยกเลิกก่อนทับข้อมูลใหม่"
            )
        publish[TARGET] = {
            "status": "pending",
            "posted_at": "",
            "url": "",
            "error": "",
            "unposted_at": restored_at,
            "restored_from_posted_at": row["posted_at"],
            "restored_from_url": str(current.get("url") or ""),
            "restore_reason": reason,
        }
        run["publish"] = publish
        clip_store._write_json(folder / clip_store.RUN_FILE, run)  # noqa: SLF001
        moved = clip_store.refile_folder(root, folder)
        changed.append({
            "item_id": row["item_id"],
            "posted_at": row["posted_at"],
            "from": str(folder.relative_to(root)),
            "to": str(moved.relative_to(root)),
        })
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("start", type=parse_date)
    parser.add_argument("end", type=parse_date)
    parser.add_argument("--root", type=Path, default=BASE_DIR / "data")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("วันที่เริ่มต้องไม่เกินวันที่จบ")

    root = args.root.resolve()
    rows = candidates(root, args.start, args.end)
    days = Counter(row["posted_at"][:10] for row in rows)
    ids = Counter(row["item_id"] for row in rows)
    print(json.dumps({
        "mode": "apply" if args.apply else "dry-run",
        "target": TARGET,
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "records": len(rows),
        "unique_item_ids": len(ids),
        "by_day": dict(sorted(days.items())),
        "duplicate_item_ids": {key: count for key, count in ids.items() if count > 1},
    }, ensure_ascii=False, indent=2))
    if not args.apply or not rows:
        return 0

    saved = backup(root, rows, args.start, args.end)
    changed = restore(
        root, rows,
        f"ผู้ใช้สั่งคืนใบ Facebook Reels วันที่ {args.start} ถึง {args.end}",
    )
    print(json.dumps({
        "backup": str(saved),
        "changed": len(changed),
        "moves": changed,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
