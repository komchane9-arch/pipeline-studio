"""กองใหม่ "ไม่มีสินค้าใน TikTok" ต้องรับเฉพาะใบที่หาแล้วไม่เจอจริงๆ

เจ้าของสั่ง 13 ก.ย. 2569: *"เพิ่มช่องหน่อย อีกช่องว่าไม่มีสินค้าใน tiktok
แล้วใบงานไหนไม่มีให้ย้ายไปช่องนั้น"*

**หัวใจคือแยกสามสถานะที่หน้าตาคล้ายกันออกจากกัน** (กติกา 2.3.1)
  ยังไม่ได้หา        ไม่มี matched_rank     -> ยังอยู่กอง TikTok ตามเดิม
  หาแล้วไม่เจอ       matched_rank == 0      -> กองใหม่
  หาเจอและเพิ่มแล้ว   showcase_added == True -> ยังอยู่กอง TikTok ตามเดิม
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_board                                             # noqa: E402


def _run(tmp: Path, item: str, link: dict | None) -> dict:
    folder = tmp / item
    video = folder / "video" / "clip.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"video")
    run = {
        "item_id": item,
        "name": f"สินค้า {item}",
        "folder": str(folder),
        "videos": ["video/clip.mp4"],
        # ลง Shopee กับ Facebook ไปแล้ว คิวถัดไปคือ TikTok
        "publish": {
            "shopee_video": {"status": "posted", "posted_at": "2026-09-01T10:00:00"},
            "facebook_reels": {"status": "posted", "posted_at": "2026-09-02T10:00:00"},
        },
    }
    if link is not None:
        run["tiktok_product_link"] = link
    return run


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        ยังไม่ได้หา = _run(root, "1000000001", None)
        หาแล้วไม่เจอ = _run(root, "1000000002", {
            "status": "pending_review", "matched_rank": 0, "confidence": "low",
            "showcase_added": False,
            "search_query": "เคสมือถือลาย Hello Kitty",
            # เหตุผลดิบของตัวดูรูปเป็นภาษาอังกฤษ — ห้ามเอามาโชว์ตรงๆ
            "reason": "The TARGET product is a Hello Kitty case, while results are other designs",
        })
        หาเจอแล้ว = _run(root, "1000000003", {
            "status": "showcase_added", "matched_rank": 1, "confidence": "high",
            "showcase_added": True, "reason": "",
        })
        # เคยหาแล้วไม่เจอ แต่ภายหลังเพิ่มเข้าโชว์เคสได้ = ต้องกลับกอง TikTok
        เพิ่มได้ทีหลัง = _run(root, "1000000004", {
            "status": "showcase_added", "matched_rank": 0,
            "showcase_added": True, "reason": "เคยหาไม่เจอ",
        })

        got = {r["item_id"]: clip_board.bucket_of_run(r) for r in (
            ยังไม่ได้หา, หาแล้วไม่เจอ, หาเจอแล้ว, เพิ่มได้ทีหลัง)}

        assert got["1000000001"] == clip_board.TIKTOK, (
            f"ใบที่ยังไม่ได้หา ต้องอยู่กอง TikTok ตามเดิม ได้ {got['1000000001']}")
        assert got["1000000002"] == clip_board.NO_SHOP, (
            f"ใบที่หาแล้วไม่เจอ ต้องไปกองใหม่ ได้ {got['1000000002']}")
        assert got["1000000003"] == clip_board.TIKTOK, (
            f"ใบที่หาเจอแล้ว ต้องอยู่กอง TikTok ได้ {got['1000000003']}")
        assert got["1000000004"] == clip_board.TIKTOK, (
            f"ใบที่เพิ่มโชว์เคสได้แล้ว ต้องกลับกอง TikTok ได้ {got['1000000004']}")

        # เหตุผลต้องติดไปกับใบด้วย ไม่ใช่แค่ย้ายกองเฉยๆ
        key, why = clip_board.bucket_of({"stage": "done"}, หาแล้วไม่เจอ)
        assert key == clip_board.NO_SHOP, key
        # **ต้องเป็นภาษาไทยที่เจ้าของอ่านรู้เรื่อง** (กติกา 5.2)
        assert "ไม่เจอสินค้าตัวนี้ใน TikTok Shop" in why, f"เหตุผลไม่ใช่ภาษาคน: {why!r}"
        assert "TARGET product" not in why, (
            f"เหตุผลดิบของตัวดูรูปหลุดมาโชว์: {why!r}")
        # คำที่บอทใช้ค้นต้องติดมาด้วย — ใช้แยก "คำค้นแย่" ออกจาก "ร้านไม่มีของ"
        assert "Hello Kitty" in why, f"คำค้นหายไป: {why!r}"

        # กองใหม่ต้องไม่ไปย้ายไฟล์จริง — ใช้โฟลเดอร์เดียวกับ TikTok
        assert (clip_board.FOLDER_OF_BUCKET[clip_board.NO_SHOP]
                == clip_board.FOLDER_OF_BUCKET[clip_board.TIKTOK])

    print("ผ่านหมด — กอง 'ไม่มีสินค้าใน TikTok' แยกสามสถานะได้ถูกต้อง")


main()
