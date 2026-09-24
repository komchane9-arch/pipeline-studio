from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


TEST_ROOT = Path(tempfile.mkdtemp(prefix="pipeline-fb-engage-watch-"))
os.environ["STUDIO_DATA_DIR"] = str(TEST_ROOT / "data")

import app  # noqa: E402
import fb_engagement  # noqa: E402


class StopKeeper(BaseException):
    """ออกจากลูปตัวเฝ้าใน test โดยไม่ถูกด่านจับข้อผิดพลาดของ production กลืน."""


class EngagementWatchAppTests(unittest.TestCase):
    def test_keeper_finishes_one_cycle_then_waits_for_next_six_hour_cycle(self) -> None:
        sleeps: list[float] = []
        test_thread = threading.get_ident()
        real_sleep = time.sleep

        def fake_sleep(seconds: float) -> None:
            if threading.get_ident() != test_thread:
                real_sleep(seconds)
                return
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise StopKeeper("stop-test-loop")

        with mock.patch.object(app, "_engagement_keeper_sleep",
                               side_effect=fake_sleep), \
             mock.patch.object(app, "bots_paused", return_value=""), \
             mock.patch.object(fb_engagement, "collect_cycle_status",
                               return_value={"active": False}), \
             mock.patch.object(app, "_run_engagement_once",
                               return_value={"posts": 0}):
            with self.assertRaisesRegex(StopKeeper, "stop-test-loop"):
                app._engagement_keeper()

        self.assertEqual(sleeps[0], 120)
        self.assertGreaterEqual(sleeps[1],
                                fb_engagement.CHECK_EVERY_SECONDS - 5)

    def test_legacy_mobile_pause_flag_does_not_preempt_desktop_cycle(self) -> None:
        sleeps: list[float] = []
        test_thread = threading.get_ident()
        real_sleep = time.sleep

        def fake_sleep(seconds: float) -> None:
            if threading.get_ident() != test_thread:
                real_sleep(seconds)
                return
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise StopKeeper("stop-test-loop")

        with mock.patch.object(app, "_engagement_keeper_sleep",
                               side_effect=fake_sleep), \
             mock.patch.object(app, "bots_paused", return_value=""), \
             mock.patch.object(app, "append_log"), \
             mock.patch.object(fb_engagement, "collect_cycle_status",
                               return_value={"active": False}), \
             mock.patch.object(app, "_run_engagement_once", return_value={
                 "paused_for_post": True,
                 "wait_seconds": 0,
                 "note": "งานโพสต์มาก่อน",
             }):
            with self.assertRaisesRegex(StopKeeper, "stop-test-loop"):
                app._engagement_keeper()

        self.assertEqual(sleeps[0], 120)
        self.assertGreaterEqual(sleeps[1],
                                fb_engagement.CHECK_EVERY_SECONDS - 5)

    def test_checkpoint_cycle_rechecks_instead_of_waiting_six_hours(self) -> None:
        sleeps: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise StopKeeper("stop-test-loop")

        with mock.patch.object(app, "_engagement_keeper_sleep",
                               side_effect=fake_sleep), \
             mock.patch.object(app, "bots_paused", return_value=""), \
             mock.patch.object(app, "append_log"), \
             mock.patch.object(fb_engagement, "collect_cycle_status",
                               return_value={"active": False}), \
             mock.patch.object(app, "_run_engagement_once", return_value={
                 "incomplete": True,
                 "remaining": 17,
                 "cycle_total": 185,
             }):
            with self.assertRaisesRegex(StopKeeper, "stop-test-loop"):
                app._engagement_keeper()

        self.assertEqual(sleeps, [120, 300])

    def test_busy_manual_with_checkpoint_retries_instead_of_waiting_six_hours(self) -> None:
        sleeps: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise StopKeeper("stop-test-loop")

        cycle = {"active": True, "remaining": 12, "total": 185}
        manual = {"status": "running", "active": True}
        with mock.patch.object(app, "_engagement_keeper_sleep",
                               side_effect=fake_sleep), \
             mock.patch.object(app, "bots_paused", return_value=""), \
             mock.patch.object(app, "append_log"), \
             mock.patch.object(fb_engagement, "collect_cycle_status",
                               return_value=cycle), \
             mock.patch.object(app, "_engagement_manual_status",
                               return_value=manual), \
             mock.patch.object(app, "_run_engagement_once", return_value={
                 "busy": True, "note": "Bot9 กำลังทำ Manual",
             }):
            with self.assertRaisesRegex(StopKeeper, "stop-test-loop"):
                app._engagement_keeper()

        self.assertEqual(sleeps, [15, 120])

    def test_keeper_resumes_checkpoint_quickly_after_restart(self) -> None:
        sleeps: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            raise StopKeeper("stop-before-browser")

        with mock.patch.object(app, "_engagement_keeper_sleep",
                               side_effect=fake_sleep), \
             mock.patch.object(app, "append_log"), \
             mock.patch.object(fb_engagement, "collect_cycle_status",
                               return_value={
                                   "active": True, "remaining": 17, "total": 185,
                               }):
            with self.assertRaisesRegex(StopKeeper, "stop-before-browser"):
                app._engagement_keeper()

        self.assertEqual(sleeps, [15])

    def test_suggestion_message_has_stop_and_keep_buttons(self) -> None:
        done = {
            "rows": [],
            "suggestions": [{
                "group": "กลุ่มทดสอบ",
                "url": "https://facebook.test/post/1",
                "watch_key": "abcdef1234567890",
                "suggest_stop": True,
                "notify_suggestion": True,
                "suggest_reason": "24 ชม. เพิ่มรวม 0",
            }],
        }
        message = app._engagement_message(done)
        keyboard = app._engagement_keyboard(done)

        self.assertIn("แนะนำให้พิจารณาเลิกเก็บ", message)
        buttons = keyboard["inline_keyboard"][0]
        self.assertEqual(buttons[0]["callback_data"],
                         "fb:ew:stop:abcdef1234567890")
        self.assertEqual(buttons[1]["callback_data"],
                         "fb:ew:keep:abcdef1234567890")

    def test_telegram_button_changes_only_requested_watch_key(self) -> None:
        with mock.patch.object(app, "_engagement_channel",
                               return_value=("token", "owner-chat")), \
             mock.patch.object(
                 fb_engagement, "set_post_watch",
                 return_value={"post_url": "https://facebook.test/post/1"}) as change:
            note = app._engagement_watch_callback(
                "owner-chat", "ew:stop:abcdef1234567890", {})

        self.assertIn("เลิกเก็บโพสต์นี้แล้ว", note)
        change.assert_called_once_with(
            watch_key="abcdef1234567890", active=False, actor="telegram")

    def test_telegram_button_rejects_other_chat(self) -> None:
        with mock.patch.object(app, "_engagement_channel",
                               return_value=("token", "owner-chat")), \
             mock.patch.object(fb_engagement, "set_post_watch") as change:
            note = app._engagement_watch_callback(
                "stranger", "ew:keep:abcdef1234567890", {})

        self.assertIn("ไม่มีสิทธิ์", note)
        change.assert_not_called()


if __name__ == "__main__":
    unittest.main()
