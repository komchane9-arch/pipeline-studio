"""Regression: ธงพักใน run.json ต้องชนะใบคิวเก่าสถานะ done."""

from __future__ import annotations

import tempfile
from pathlib import Path

import clip_board


with tempfile.TemporaryDirectory() as tmp:
    folder = Path(tmp) / "9154852607"
    video = folder / "video" / "clip.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    run = {
        "item_id": "9154852607",
        "name": "สินค้าทดสอบ",
        "folder": str(folder),
        "videos": ["video/clip.mp4"],
        "parked": {"from": "shopee_video", "why": "พักไว้"},
        "publish": {
            "shopee_video": {"status": "posted"},
            "facebook_reels": {"status": "pending"},
            "tiktok": {"status": "pending"},
        },
    }
    jobs = [{
        "id": "old-queue-row",
        "item_id": "9154852607",
        "name": "สินค้าทดสอบ",
        "stage": "done",
    }]

    board = clip_board.build(jobs, lambda _item: run, [run])
    buckets = {bucket["key"]: bucket for bucket in board["buckets"]}

    assert buckets["facebook_reels"]["count"] == 0
    assert buckets["shopee_video"]["parked_count"] == 1
    assert buckets["shopee_video"]["parked"][0]["item_id"] == "9154852607"

print("OK: parked run.json overrides an unparked legacy queue row")
