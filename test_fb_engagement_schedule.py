from __future__ import annotations

from datetime import datetime
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TEST_ROOT = Path(tempfile.mkdtemp(prefix="bot8-schedule-app-"))
os.environ["STUDIO_DATA_DIR"] = str(TEST_ROOT / "data")

import app
import fb_engagement_schedule as schedule


class EngagementScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bot8-schedule-")
        self.file = Path(self.temp.name) / "schedule.json"
        self.patch = mock.patch.object(schedule, "STATE_FILE", self.file)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def test_once_fires_at_selected_time_then_disables(self) -> None:
        before = datetime(2026, 9, 23, 9, 0, 0)
        saved = schedule.set_schedule("Khao", "10:30", "once", now=before)
        self.assertTrue(saved["enabled"])
        self.assertEqual(saved["next_at"], "2026-09-23T10:30:00")
        self.assertFalse(schedule.due(datetime(2026, 9, 23, 10, 29, 59)))
        self.assertEqual(schedule.due(datetime(2026, 9, 23, 10, 30, 0))[0]["account"],
                         "Khao")
        consumed = schedule.mark_started("Khao", datetime(2026, 9, 23, 10, 30, 5))
        self.assertFalse(consumed["enabled"])
        self.assertFalse(schedule.due(datetime(2026, 9, 24, 10, 30, 0)))

    def test_daily_advances_to_next_day_without_duplicate_due_slot(self) -> None:
        schedule.set_schedule(
            "Preaw", "07:15", "daily", now=datetime(2026, 9, 23, 7, 0, 0))
        advanced = schedule.mark_started(
            "Preaw", now=datetime(2026, 9, 23, 7, 15, 2))
        self.assertTrue(advanced["enabled"])
        self.assertEqual(advanced["next_at"], "2026-09-24T07:15:00")
        self.assertFalse(schedule.due(datetime(2026, 9, 23, 7, 16, 0)))
        self.assertEqual(schedule.due(datetime(2026, 9, 24, 7, 15, 0))[0]["account"],
                         "Preaw")

    def test_time_that_already_passed_schedules_tomorrow(self) -> None:
        saved = schedule.set_schedule(
            "Khao", "08:00", "once", now=datetime(2026, 9, 23, 9, 0, 0))
        self.assertEqual(saved["next_at"], "2026-09-24T08:00:00")

    def test_clear_only_removes_requested_account(self) -> None:
        now = datetime(2026, 9, 23, 9, 0, 0)
        schedule.set_schedule("Khao", "10:00", "daily", now=now)
        schedule.set_schedule("Preaw", "11:00", "once", now=now)
        schedule.clear_schedule("Khao", now=now)
        self.assertFalse(schedule.status("Khao", now=now)["enabled"])
        self.assertTrue(schedule.status("Preaw", now=now)["enabled"])

    def test_invalid_mode_and_clock_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "1 ครั้ง"):
            schedule.set_schedule("Khao", "10:00", "weekly")
        with self.assertRaisesRegex(ValueError, "เวลา"):
            schedule.set_schedule("Khao", "25:00", "once")


class StopKeeper(BaseException):
    pass


class EngagementScheduleAppTests(unittest.TestCase):
    def test_due_schedule_queues_one_manual_run_then_consumes_slot(self) -> None:
        sleeps: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise StopKeeper()

        due = {"account": "Khao", "time": "10:30", "mode": "once"}
        with mock.patch.object(app, "_engagement_schedule_sleep", side_effect=fake_sleep), \
             mock.patch.object(schedule, "due", return_value=[due]), \
             mock.patch.object(app, "_engagement_active_posts",
                               return_value=[{"post_url": "https://facebook.test/p/1"}]), \
             mock.patch.object(app, "_start_engagement_manual",
                               return_value={"status": "queued"}) as start, \
             mock.patch.object(schedule, "mark_started") as marked, \
             mock.patch.object(app, "append_log"):
            with self.assertRaises(StopKeeper):
                app._engagement_schedule_keeper()

        start.assert_called_once()
        marked.assert_called_once_with("Khao")
        self.assertEqual(sleeps, [5, 15])

    def test_busy_manual_does_not_consume_due_slot(self) -> None:
        sleeps: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise StopKeeper()

        with mock.patch.object(app, "_engagement_schedule_sleep", side_effect=fake_sleep), \
             mock.patch.object(schedule, "due", return_value=[{
                 "account": "Preaw", "time": "09:00", "mode": "daily",
             }]), \
             mock.patch.object(app, "_engagement_active_posts", return_value=[{}]), \
             mock.patch.object(app, "_start_engagement_manual",
                               return_value={"busy": True}), \
             mock.patch.object(schedule, "mark_started") as marked:
            with self.assertRaises(StopKeeper):
                app._engagement_schedule_keeper()

        marked.assert_not_called()

    def test_schedule_api_uses_selected_account_and_mode(self) -> None:
        class Request:
            async def body(self):
                return b"payload"

            async def json(self):
                return {"account": "khao", "time": "08:45", "mode": "daily"}

        saved = {"account": "Khao", "time": "08:45", "mode": "daily",
                 "enabled": True}
        with mock.patch("fb_engagement.watched_accounts", return_value=["Khao"]), \
             mock.patch.object(schedule, "set_schedule", return_value=saved) as setter, \
             mock.patch.object(app, "append_log"):
            result = asyncio.run(app.fb_engage_schedule(Request()))

        self.assertTrue(result["ok"])
        setter.assert_called_once_with("Khao", "08:45", "daily")
        self.assertIn("ทุกวัน", result["message"])

    def test_web_has_time_and_mutually_exclusive_once_daily_choices(self) -> None:
        html = Path("web/index.html").read_text(encoding="utf-8")
        script = Path("web/engage.js").read_text(encoding="utf-8")
        self.assertIn('id="egScheduleTime" type="time"', html)
        self.assertIn('name="egScheduleMode" value="once"', html)
        self.assertIn('name="egScheduleMode" value="daily"', html)
        self.assertIn('api("/api/fb/engage/schedule"', script)
        self.assertIn("data.collector_schedule = out.collector_schedule", script)


if __name__ == "__main__":
    unittest.main()
