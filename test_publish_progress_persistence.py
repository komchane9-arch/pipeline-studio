"""Regression: กล่องสถานะโพสต์ต้องไม่ว่างหลังรีสตาร์ต และรองรับขั้น TikTok 1–7."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as studio_app                                      # noqa: E402


class PublishProgressPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_file = studio_app.PROGRESS_FILE
        self.original_progress = dict(studio_app._progress)
        self.temp = tempfile.TemporaryDirectory()
        studio_app.PROGRESS_FILE = Path(self.temp.name) / "publish_progress.json"
        studio_app._progress.clear()

    def tearDown(self) -> None:
        studio_app._progress.clear()
        studio_app._progress.update(self.original_progress)
        studio_app.PROGRESS_FILE = self.original_file
        self.temp.cleanup()

    def test_tiktok_link_step_is_saved_and_restored(self) -> None:
        studio_app._progress_start("item-1", "tiktok", "phone-1", 7)
        studio_app._progress_at(
            "item-1", 3, "results_1_2", "เก็บภาพผลค้นหาอันดับ 1–2",
            True, "results-1-2.png",
        )
        studio_app._progress_end("item-1", True, "เพิ่มสินค้าเข้าโชว์เคสครบ 7/7 แล้ว")

        payload = json.loads(studio_app.PROGRESS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(payload["clips"][0]["target"], "tiktok")
        self.assertEqual(payload["clips"][0]["step"], 3)
        self.assertEqual(payload["clips"][0]["status"], "done")
        self.assertEqual(
            payload["clips"][0]["now"], "เพิ่มสินค้าเข้าโชว์เคสครบ 7/7 แล้ว",
        )

        restored = studio_app._restore_progress()
        self.assertEqual(restored["item-1"]["lines"][0]["id"], "results_1_2")

    def test_running_row_becomes_failed_after_restart(self) -> None:
        studio_app._progress_start("item-2", "tiktok", "phone-1", 14)
        restored = studio_app._restore_progress()
        self.assertEqual(restored["item-2"]["status"], "failed")
        self.assertIn("รีสตาร์ต", restored["item-2"]["now"])

    def test_failed_summary_overrides_previous_successful_step(self) -> None:
        studio_app._progress_start("item-3", "tiktok", "phone-1", 7)
        studio_app._progress_at(
            "item-3", 6, "open_product", "เปิดสินค้า", True, "ตรง",
        )
        studio_app._progress_at(
            "item-3", 7, "showcase", "เพิ่มโชว์เคส", None, "",
        )
        studio_app._progress_end("item-3", False, "ไม่พบผลยืนยัน")
        self.assertEqual(studio_app._progress["item-3"]["status"], "failed")
        self.assertIs(studio_app._progress["item-3"]["ok"], False)

    def test_restore_repairs_old_failed_row_with_true_ok(self) -> None:
        studio_app.PROGRESS_FILE.write_text(json.dumps({"clips": [{
            "item_id": "legacy", "status": "failed", "ok": True,
            "lines": [], "now": "ล้มเหลว",
        }]}), encoding="utf-8")
        restored = studio_app._restore_progress()
        self.assertIs(restored["legacy"]["ok"], False)


if __name__ == "__main__":
    unittest.main()
