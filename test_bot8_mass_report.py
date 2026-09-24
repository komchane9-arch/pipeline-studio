"""Offline regressions for Bot8's popular-post queue and report rules."""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import bot8_mass_report as jobs
from tools.bot8_mass_report import qualifying_posts
import tools.bot8_mass_report as scanner
from tools.bot8_today_report import save_report


class MassReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        state = Path(self.temp.name) / "bot8_mass_report.json"
        claim = patch.object(jobs, "STATE_FILE", state)
        claim.start()
        self.addCleanup(claim.stop)
        self.now = datetime(2026, 9, 24, 9, 0)

    def test_once_clock_queues_only_once_and_does_not_duplicate_active_job(self):
        jobs.set_schedule("09:01", "once", self.now)
        due = self.now + timedelta(minutes=1)
        accepted, first = jobs.enqueue("scheduled", due)
        self.assertTrue(accepted)
        self.assertEqual("queued", first["status"])
        self.assertFalse(jobs.schedule_status(due)["enabled"])
        accepted, second = jobs.enqueue("scheduled", due)
        self.assertFalse(accepted)
        self.assertEqual(first["id"], second["id"])
        accepted, _ = jobs.enqueue("manual", due)
        self.assertFalse(accepted)

    def test_daily_clock_moves_forward_and_keeps_last_report(self):
        jobs.set_schedule("09:01", "daily", self.now)
        due = self.now + timedelta(minutes=1)
        accepted, first = jobs.enqueue("scheduled", due)
        self.assertTrue(accepted)
        self.assertEqual("2026-09-25T09:01:00", jobs.schedule_status(due)["next_at"])
        jobs.update_job(first["id"], status="running", now=due)
        jobs.update_job(first["id"], status="complete", report_id=
                        "bot8-mass-sales-20260924-090100-" + first["id"], now=due)
        accepted, second = jobs.enqueue("manual", due)
        self.assertTrue(accepted)
        self.assertNotEqual(first["id"], second["id"])
        self.assertIn(first["id"], jobs.status()["latest_report_url"])

    def test_running_job_expires_without_automatic_duplicate(self):
        accepted, job = jobs.enqueue(now=self.now)
        self.assertTrue(accepted)
        jobs.update_job(job["id"], status="running", now=self.now)
        self.assertEqual("running", jobs.expire_stale(self.now + timedelta(minutes=4))["status"])
        self.assertEqual("error", jobs.expire_stale(self.now + timedelta(minutes=6))["status"])
        self.assertEqual(job["id"], jobs.job_status()["id"])

    def test_popular_cutoff_sort_and_group_guard(self):
        prefix = "https://www.facebook.com/groups/123/posts/"
        posts = [
            {"id": "a", "url": prefix + "a/", "caption": "พร้อมส่ง", "likes": 100, "comments": 0, "shares": 0},
            {"id": "b", "url": prefix + "b/", "caption": "สั่งซื้อได้", "likes": 80, "comments": 21, "shares": 0},
            {"id": "c", "url": prefix + "c/", "caption": "พร้อมส่ง", "likes": 110, "comments": 5, "shares": 2},
            {"id": "c", "url": prefix + "c/", "caption": "พร้อมส่ง", "likes": 110, "comments": 5, "shares": 2},
            {"id": "x", "url": "https://www.facebook.com/groups/456/posts/x/",
             "caption": "พร้อมส่ง", "likes": 999, "comments": 0, "shares": 0},
            {"id": "d", "url": prefix + "d/", "caption": "แค่รีวิวของดี",
             "likes": 999, "comments": 0, "shares": 0},
        ]
        result = qualifying_posts(posts, "123")
        self.assertEqual(["c", "b"], [post["id"] for post in result])
        self.assertEqual([117, 101], [post["total_engagement"] for post in result])

    def test_popular_report_shows_proof_and_escapes_caption(self):
        folder = Path(self.temp.name) / "report"
        post = {"url": "https://www.facebook.com/groups/123/posts/456/",
                "caption": "พร้อมส่ง <script>alert(1)</script>", "likes": 80,
                "comments": 20, "shares": 1, "image": "123-456.png"}
        save_report(folder, {"date": "2026-09-24", "mode": "sales",
                             "status": "done", "groups": [{"name": "sample", "accounts": ["A"],
                             "selected": [post], "eligible_count": 1, "scanned": 10}]})
        html = (folder / "report.html").read_text(encoding="utf-8")
        self.assertIn("ยอดรวม 101", html)
        self.assertIn("123-456.png", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_offline_scan_keeps_five_limit_images_and_group_pacing(self):
        accepted, job = jobs.enqueue(now=self.now)
        self.assertTrue(accepted)
        jobs.update_job(job["id"], status="running", now=self.now)
        groups = [{"id": "123", "name": "A", "accounts": ["Khao Fang Nichapa"]},
                  {"id": "456", "name": "B", "accounts": ["Preaw Buchakorn"]}]
        page = MagicMock()
        page.url = ""
        page.goto.side_effect = lambda url, **_kw: setattr(page, "url", url)
        context = MagicMock()
        context.pages = [page]
        launcher = MagicMock()
        launcher.__enter__.return_value = MagicMock()
        launcher.__exit__.return_value = False

        def fake_scan(_page, url, _scrolls, _log):
            gid = url.rstrip("/").split("/")[-1]
            posts = [{"id": str(i + int(gid) * 100),
                      "url": f"https://www.facebook.com/groups/{gid}/posts/{i + int(gid) * 100}/",
                      "caption": "พร้อมส่ง สั่งซื้อได้", "likes": 101 + i,
                      "comments": 1, "shares": 0} for i in range(7)]
            return {"posts": posts, "error": ""}

        def fake_capture(*_args, **_kwargs):
            base = Path(self.temp.name) / "capture"
            base.with_suffix(".png").write_bytes(b"png-test")
            return base

        with patch.object(scanner, "linked_groups", return_value=groups), \
             patch("studio_shared.DATA_DIR", Path(self.temp.name)), \
             patch("bot_profiles.ProfileFarm"), \
             patch("fb_mass_finder.find_bot", return_value={"name": "Bot8"}), \
             patch("fb_mass_finder.launch_bot_browser", return_value=context), \
             patch("fb_mass_finder.ensure_logged_in"), \
             patch("fb_mass_finder.scan_group", side_effect=fake_scan), \
             patch("playwright.sync_api.sync_playwright", return_value=launcher), \
             patch("evidence.capture", side_effect=fake_capture), \
             patch.object(scanner.time, "sleep") as sleeper:
            folder = scanner.run(job["id"], 2)

        self.assertEqual(6, sleeper.call_count)
        sleeper.assert_any_call(10)
        report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(2, len(report["groups"]))
        self.assertEqual([5, 5], [len(g["selected"]) for g in report["groups"]])
        self.assertEqual(10, jobs.job_status()["found"])
        self.assertEqual("complete", jobs.job_status()["status"])
        for group in report["groups"]:
            for post in group["selected"]:
                self.assertGreater(post["total_engagement"], 100)
                self.assertTrue((folder / post["image"]).is_file())

    def test_start_endpoint_only_queues_and_never_opens_chrome(self):
        import app

        groups = [{"id": "123", "name": "A", "accounts": ["Khao Fang Nichapa"]}]
        with patch.object(scanner, "linked_groups", return_value=groups), \
             patch.object(app, "append_log"):
            first = asyncio.run(app.fb_mass_report_start())
            second = asyncio.run(app.fb_mass_report_start())
        self.assertTrue(first["accepted"])
        self.assertFalse(second["accepted"])
        self.assertEqual(first["job"]["id"], second["job"]["id"])
        self.assertEqual("queued", jobs.job_status()["status"])


if __name__ == "__main__":
    unittest.main()
