"""เริ่มชุด TikTok ใหม่และบันทึกฐานสำหรับหยุดเมื่อโพสต์ครบตามเป้า.

ค่าเริ่มต้นเป็น dry-run; ใช้ ``--apply`` จึงเปลี่ยน snapshot ชุดค้นหาและสร้าง
``data/tiktok_monitor_session.json``. เลือกเฉพาะใบที่อยู่กอง TikTok, คลิปผ่าน
การตรวจแล้ว, ยังไม่เคยค้นสินค้าในชุดใหม่ และไม่ใช้สมาชิก snapshot เดิมซ้ำ.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import clip_store  # noqa: E402
import studio_shared as shared  # noqa: E402


BATCH_FILE = shared.DATA_DIR / "tiktok_link_batch.json"
SESSION_FILE = shared.DATA_DIR / "tiktok_monitor_session.json"


def board_jobs(url: str) -> list[dict]:
    with urllib.request.urlopen(url, timeout=30) as response:
        board = json.loads(response.read().decode("utf-8"))
    bucket = next((row for row in board.get("buckets") or []
                   if row.get("key") == "tiktok"), {})
    return list(bucket.get("jobs") or [])


def posted_ids(root: Path) -> list[str]:
    found = set()
    for run in clip_store.list_runs(root) + clip_store.list_done(root):
        state = ((run.get("publish") or {}).get("tiktok") or {})
        item_id = str(run.get("item_id") or "").strip()
        if item_id and state.get("status") == "posted":
            found.add(item_id)
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=10,
                        help="จำนวนโพสต์ TikTok สำเร็จใหม่ที่ต้องการ")
    parser.add_argument("--candidates", type=int, default=55,
                        help="จำนวนใบค้นหาสินค้าสูงสุดใน snapshot ใหม่")
    parser.add_argument("--board-url", default="http://127.0.0.1:8877/api/board")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.target < 1 or args.candidates < args.target:
        parser.error("candidates ต้องไม่น้อยกว่า target และ target ต้องอย่างน้อย 1")

    old = shared.read_json(BATCH_FILE, {})
    old_ids = {str(value) for value in (old.get("item_ids") or []) if str(value)}
    eligible = []
    for row in board_jobs(args.board_url):
        item_id = str(row.get("item_id") or "").strip()
        if (not item_id or item_id in old_ids or row.get("parked")
                or row.get("tiktok_link_status")
                or row.get("video_ok") is not True):
            continue
        eligible.append(row)
    picked = eligible[:args.candidates]
    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "target_posts": args.target,
        "eligible_new": len(eligible),
        "picked": len(picked),
        "first_ids": [row["item_id"] for row in picked[:10]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.apply:
        return 0
    if len(picked) < args.target:
        raise RuntimeError(
            f"มีใบใหม่ที่คลิปผ่านเพียง {len(picked)} ใบ น้อยกว่าเป้า {args.target}"
        )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = shared.DATA_DIR / "backup" / f"tiktok-link-batch-{stamp}.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if BATCH_FILE.is_file():
        shutil.copy2(BATCH_FILE, backup)

    now = datetime.now().isoformat(timespec="seconds")
    ids = [str(row["item_id"]) for row in picked]
    shared.write_json_atomic(BATCH_FILE, {
        "limit": len(ids),
        "item_ids": ids,
        "created_at": now,
        "note": (f"ชุด monitor TikTok เป้าโพสต์สำเร็จ {args.target} ใบ; "
                 "เลือกเฉพาะคลิปผ่านและยังไม่เคยค้นใน snapshot ก่อนหน้า"),
    })
    shared.write_json_atomic(SESSION_FILE, {
        "status": "active",
        "started_at": now,
        "target_successes": args.target,
        "baseline_posted_ids": posted_ids(shared.DATA_DIR),
        "batch_ids": ids,
        "batch_backup": str(backup) if backup.is_file() else "",
    })
    print(json.dumps({
        "batch_file": str(BATCH_FILE),
        "session_file": str(SESSION_FILE),
        "backup": str(backup) if backup.is_file() else "",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
