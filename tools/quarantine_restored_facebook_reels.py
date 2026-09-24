"""พักใบ Facebook Reels ที่ถูกคืนจาก posted มาเป็น pending เพื่อกัน Auto หยิบ.

ค่าเริ่มต้นเป็น dry-run; ต้องส่ง ``--apply`` จึงแก้ข้อมูลจริง และจะสร้าง ZIP
ของ run.json ทุกสำเนาที่ได้รับผลก่อนเขียนเสมอ.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import clip_store  # noqa: E402
import publish_media  # noqa: E402


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
            run = clip_store._read_json(run_file)  # noqa: SLF001 - maintenance tool
            state = ((run.get("publish") or {}).get(TARGET) or {})
            restored_from = str(state.get("restored_from_posted_at") or "")
            try:
                restored_day = date.fromisoformat(restored_from[:10])
            except ValueError:
                continue
            if state.get("status") != "pending" or not start <= restored_day <= end:
                continue
            rows.append({
                "item_id": str(run.get("item_id") or folder.name).strip(),
                "name": str(run.get("name") or ""),
                "restored_from": restored_from,
                "folder": folder,
                "run_file": run_file,
                "already_parked": bool(run.get("parked")),
            })
    return sorted(rows, key=lambda row: (row["restored_from"], row["item_id"]))


def backup(root: Path, rows: list[dict], start: date, end: date) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = root / "backup" / f"facebook-reels-hold-{start}-{end}-{stamp}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, row in enumerate(rows, 1):
            relative = row["run_file"].relative_to(root).as_posix()
            archive.write(row["run_file"], f"runs/{index:03d}/{relative}")
            manifest.append({
                "item_id": row["item_id"],
                "name": row["name"],
                "restored_from": row["restored_from"],
                "source": relative,
            })
        queue = root / "clip_queue.json"
        if queue.is_file():
            archive.write(queue, "clip_queue.json")
        archive.writestr("manifest.json", json.dumps({
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "target": TARGET,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "record_count": len(rows),
            "unique_item_ids": len({row["item_id"] for row in rows}),
            "items": manifest,
        }, ensure_ascii=False, indent=2))
    return target


def quarantine(root: Path, rows: list[dict], reason: str) -> list[dict]:
    changed: list[dict] = []
    parked_at = datetime.now().isoformat(timespec="seconds")
    for row in rows:
        folder: Path = row["folder"]
        run_file = folder / clip_store.RUN_FILE
        run = clip_store._read_json(run_file)  # noqa: SLF001
        state = ((run.get("publish") or {}).get(TARGET) or {})
        if (state.get("status") != "pending"
                or str(state.get("restored_from_posted_at") or "")
                != row["restored_from"]):
            raise RuntimeError(
                f"สถานะ {row['item_id']} เปลี่ยนระหว่างทำ; ยกเลิกก่อนทับข้อมูลใหม่"
            )
        run["parked"] = {
            "at": parked_at,
            "from": TARGET,
            "why": reason,
        }
        state["auto_hold"] = True
        state["auto_hold_at"] = parked_at
        state["auto_hold_reason"] = reason
        run.setdefault("publish", {})[TARGET] = state
        clip_store._write_json(run_file, run)  # noqa: SLF001
        moved = clip_store.refile_folder(root, folder)
        changed.append({
            "item_id": row["item_id"],
            "from": str(folder.relative_to(root)),
            "to": str(moved.relative_to(root)),
        })
    return changed


def release(root: Path, rows: list[dict]) -> list[dict]:
    """ปลดพักชุดที่เครื่องมือนี้พักไว้ พร้อมล้างธง auto_hold คู่กัน.

    ทำกับทุกสำเนาที่ตรงช่วงวันที่ ไม่ใช้ ``target_dir`` แบบเลือกสำเนาเดียว
    เพราะสำเนาเก่าที่ค้างธงพักจะทำให้หน้ากระดานกับตัวเลือก Auto นับไม่ตรงกัน.
    """
    changed: list[dict] = []
    for row in rows:
        folder: Path = row["folder"]
        run_file = folder / clip_store.RUN_FILE
        run = clip_store._read_json(run_file)  # noqa: SLF001
        park = run.get("parked") or {}
        state = ((run.get("publish") or {}).get(TARGET) or {})
        if str(park.get("from") or "") != TARGET:
            raise RuntimeError(
                f"ใบ {row['item_id']} ไม่ได้พักจาก Facebook Reels; ห้ามปลดผิดกอง"
            )
        if state.get("status") != "pending":
            raise RuntimeError(
                f"สถานะ {row['item_id']} ไม่ใช่ pending; ห้ามปลดไปโพสต์ซ้ำ"
            )
        run.pop("parked", None)
        for key in ("auto_hold", "auto_hold_at", "auto_hold_reason"):
            state.pop(key, None)
        run.setdefault("publish", {})[TARGET] = state
        clip_store._write_json(run_file, run)  # noqa: SLF001
        moved = clip_store.refile_folder(root, folder)
        changed.append({
            "item_id": row["item_id"],
            "from": str(folder.relative_to(root)),
            "to": str(moved.relative_to(root)),
        })
    return changed


def preflight_release(rows: list[dict]) -> dict:
    """ตรวจคลิปทุกสำเนาให้ครบก่อนปลดแม้แต่ใบเดียว."""
    hashes_by_item: dict[str, set[str]] = {}
    for row in rows:
        run = clip_store._read_json(row["run_file"])  # noqa: SLF001
        item_id = str(row["item_id"] or "").strip()
        videos = list(run.get("videos") or [])
        if not videos:
            raise RuntimeError(f"ใบ {item_id} ไม่มีชื่อคลิป — ยังปลดพักไม่ได้")
        # ตัวเดียวกับด่านส่งมือถือ: รหัสใน run.json ต้องตรงกับใบงานก่อน
        # และชื่อบนมือถือจะมี item_id นำหน้าเสมอ.
        publish_media.expected_phone_video_name(
            item_id, str(run.get("item_id") or ""), str(videos[0]),
        )
        local = row["folder"] / str(videos[0])
        if not local.is_file() or local.stat().st_size <= 0:
            raise RuntimeError(f"ใบ {item_id} ไม่มีไฟล์คลิปจริง: {local}")
        digest = hashlib.sha256(local.read_bytes()).hexdigest()
        hashes_by_item.setdefault(item_id, set()).add(digest)

    ambiguous = {item: len(values) for item, values in hashes_by_item.items()
                 if len(values) > 1}
    if ambiguous:
        raise RuntimeError(
            "พบ item_id ซ้ำแต่คลิปคนละไฟล์ — ห้ามเดาว่าจะโพสต์ตัวไหน: "
            + ", ".join(sorted(ambiguous))
        )
    return {
        "records": len(rows),
        "unique_item_ids": len(hashes_by_item),
        "video_identity_ok": len(rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("start", type=parse_date)
    parser.add_argument("end", type=parse_date)
    parser.add_argument("--root", type=Path, default=BASE_DIR / "data")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--release", action="store_true")
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("วันที่เริ่มต้องไม่เกินวันที่จบ")

    root = args.root.resolve()
    rows = candidates(root, args.start, args.end)
    ids = Counter(row["item_id"] for row in rows)
    summary = {
        "mode": "release" if args.release else ("apply" if args.apply else "dry-run"),
        "target": TARGET,
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "records": len(rows),
        "unique_item_ids": len(ids),
        "already_parked_records": sum(row["already_parked"] for row in rows),
        "duplicate_item_ids": {key: count for key, count in ids.items() if count > 1},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not (args.apply or args.release) or not rows:
        return 0

    if args.release:
        print(json.dumps({"release_preflight": preflight_release(rows)},
                         ensure_ascii=False, indent=2))
    saved = backup(root, rows, args.start, args.end)
    if args.release:
        changed = release(root, rows)
    else:
        changed = quarantine(
            root, rows,
            "พักตรวจโพสต์เดิม Facebook Reels วันที่ 6–8 ก.ย. 2026; "
            "ห้าม Auto หยิบจนกว่าจะยืนยันว่าลบโพสต์เดิมแล้ว",
        )
    print(json.dumps({
        "backup": str(saved),
        "changed_records": len(changed),
        "changed_unique_item_ids": len({row["item_id"] for row in changed}),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
