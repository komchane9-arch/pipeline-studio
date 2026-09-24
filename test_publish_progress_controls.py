"""ทดสอบ Resume/Reset จากสถานะจำลอง ไม่แตะมือถือและไม่โพสต์จริง."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import app


def row(target: str, lines: list[dict], status: str = "failed") -> dict:
    return {"status": status, "target": target, "step": len(lines), "lines": lines}


class PublishProgressControlTests(unittest.TestCase):
    def test_generic_resume_retries_failed_step(self):
        controls = app._progress_controls(row("shopee_video", [
            {"no": 16, "id": "link_paste", "name": "วางลิงก์", "ok": True},
            {"no": 17, "id": "import", "name": "กดนำเข้า", "ok": False},
        ]))
        self.assertTrue(controls["can_resume"])
        self.assertTrue(controls["can_reset"])
        self.assertEqual(17, controls["resume_step"])

    def test_running_and_done_cannot_be_reposted(self):
        for status in ("running", "done"):
            controls = app._progress_controls(row("facebook_reels", [], status))
            self.assertFalse(controls["can_resume"])
            self.assertFalse(controls["can_reset"])

    def test_unknown_post_result_disables_resume_but_reset_only_clears_status(self):
        controls = app._progress_controls(row("facebook_reels", [
            {"no": 23, "id": "share", "name": "กดแชร์เลย", "ok": False},
        ]))
        self.assertFalse(controls["can_resume"])
        self.assertTrue(controls["can_reset"])
        self.assertIn("ล้างเฉพาะสถานะ", controls["reason"])

    def test_tiktok_human_check_uses_current_product_resume(self):
        controls = app._progress_controls(row("tiktok", [
            {"no": 1, "id": "wake", "name": "ปลุกจอ", "ok": True},
            {"no": 2, "id": "human_verification", "name": "รอยืนยัน", "ok": False},
        ]))
        self.assertTrue(controls["can_resume"])
        self.assertEqual("current_product", controls["resume_mode"])

    def test_tiktok_showcase_failure_resumes_exact_failed_step(self):
        sample = row("tiktok", [
            {"no": 1, "id": "wake", "name": "ปลุกจอ", "ok": True},
            {"no": 2, "id": "send_clip", "name": "ส่งคลิป", "ok": False},
        ])
        sample["total"] = 14
        controls = app._progress_controls(sample)
        self.assertTrue(controls["can_resume"])
        self.assertEqual(2, controls["resume_step"])
        self.assertEqual("send_clip", controls["resume_step_id"])
        self.assertEqual("exact_step", controls["resume_mode"])

    def test_resume_progress_keeps_completed_lines_before_failed_step(self):
        original = dict(app._progress)
        try:
            app._progress.clear()
            app._progress["job"] = {
                "item_id": "job", "target": "tiktok", "serial": "phone",
                "lines": [
                    {"no": 1, "id": "wake", "ok": True},
                    {"no": 2, "id": "send_clip", "ok": False},
                ],
            }
            with (
                mock.patch.object(app, "_progress_save_locked"),
                mock.patch.object(app.clip_store, "load_run", return_value={"name": "สินค้า"}),
                mock.patch.object(app.device_book, "label", return_value="มือถือ"),
            ):
                app._progress_start("job", "tiktok", "phone", 14, 1,
                                    preserve_completed=True)
            self.assertEqual(1, app._progress["job"]["step"])
            self.assertEqual(["wake"], [line["id"] for line in app._progress["job"]["lines"]])
        finally:
            app._progress.clear()
            app._progress.update(original)

    def test_tiktok_profile_resume_requires_showcase_success(self):
        before_showcase = app._progress_controls(row("tiktok", [
            {"no": 1, "id": "profile", "name": "โปรไฟล์", "ok": False},
        ]))
        self.assertFalse(before_showcase["can_resume"])
        self.assertTrue(before_showcase["can_reset"])

        after_showcase = app._progress_controls(row("tiktok", [
            {"no": 1, "id": "showcase", "name": "เพิ่มโชว์เคส", "ok": True},
            {"no": 2, "id": "profile", "name": "โปรไฟล์", "ok": False},
        ]))
        self.assertTrue(after_showcase["can_resume"])
        self.assertEqual("profile_ready", after_showcase["resume_mode"])

    def test_tiktok_after_post_click_never_retries(self):
        controls = app._progress_controls(row("tiktok", [
            {"no": 12, "id": "post", "name": "แตะโพสต์หนึ่งครั้ง", "ok": True},
            {"no": 13, "id": "confirm_post", "name": "ยืนยันผลโพสต์", "ok": False},
        ]))
        self.assertFalse(controls["can_resume"])
        self.assertTrue(controls["can_reset"])

    def test_reset_clears_only_selected_target_without_starting_work(self):
        original = dict(app._progress)
        try:
            app._progress.clear()
            app._progress.update({
                "shopee": {"item_id": "shopee", "target": "shopee_video",
                            "status": "failed", "started_at": "2026-01-01T01:00:00"},
                "facebook": {"item_id": "facebook", "target": "facebook_reels",
                              "status": "failed", "started_at": "2026-01-01T02:00:00"},
                "tiktok": {"item_id": "tiktok", "target": "tiktok",
                            "status": "stopped", "started_at": "2026-01-01T03:00:00"},
            })
            with (
                mock.patch.object(app, "_progress_save_locked"),
                mock.patch.object(app, "append_log"),
            ):
                result = app._publish_progress_reset_result(
                    "facebook_reels", "facebook",
                )
            self.assertTrue(result["idle"])
            self.assertEqual(result["cleared"], 1)
            self.assertEqual(set(app._progress), {"shopee", "tiktok"})
        finally:
            app._progress.clear()
            app._progress.update(original)

    def test_reset_refuses_to_hide_running_work(self):
        original = dict(app._progress)
        try:
            app._progress.clear()
            app._progress["live"] = {
                "item_id": "live", "target": "tiktok", "status": "running",
            }
            with mock.patch.object(app, "_progress_save_locked"):
                with self.assertRaisesRegex(RuntimeError, "กำลังทำ"):
                    app._publish_progress_reset_result("tiktok", "live")
        finally:
            app._progress.clear()
            app._progress.update(original)

    def test_reset_supports_all_three_publish_targets(self):
        original = dict(app._progress)
        try:
            for target in ("shopee_video", "facebook_reels", "tiktok"):
                with self.subTest(target=target):
                    app._progress.clear()
                    app._progress[target] = {
                        "item_id": target, "target": target, "status": "failed",
                        "started_at": "2026-01-01T01:00:00",
                    }
                    with (
                        mock.patch.object(app, "_progress_save_locked"),
                        mock.patch.object(app, "append_log"),
                    ):
                        result = app._publish_progress_reset_result(target, target)
                    self.assertTrue(result["idle"])
                    self.assertEqual({}, app._progress)
        finally:
            app._progress.clear()
            app._progress.update(original)

    def test_web_reset_calls_status_endpoint_not_flow_runner(self):
        source = (Path(__file__).parent / "web" / "video.js").read_text(encoding="utf-8")
        self.assertIn('api("/api/publish/progress/reset"', source)
        self.assertIn('resetPublishStatus(clip, target, buttons)', source)
        self.assertNotIn('runPublishControl(clip, "reset"', source)


if __name__ == "__main__":
    unittest.main()
