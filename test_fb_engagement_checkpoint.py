from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import fb_engagement


def post(number: int) -> dict:
    return {
        "post_url": f"https://facebook.test/posts/{number}",
        "group_id": str(number),
        "group_name": f"กลุ่ม {number}",
        "account": "Khao Fang Nichapa",
    }


class EngagementCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="fb-cycle-")
        root = Path(self.temp.name)
        self.checkpoint = root / "cycle.json"
        self.log = root / "engagement.log"
        self.db = root / "engagement.db"
        self.patches = [
            mock.patch.object(fb_engagement, "COLLECT_CYCLE_FILE", self.checkpoint),
            mock.patch.object(fb_engagement, "LOG_FILE", self.log),
            mock.patch.object(fb_engagement, "DB_FILE", self.db),
            mock.patch("fb_collect_gate.STATE_FILE", root / "gate.json"),
            mock.patch("fb_collect_gate.require_login"),
            mock.patch("fb_collect_gate.wait_for_turn", return_value=True),
            mock.patch("fb_collect_gate.reserve_gap", return_value=0),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temp.cleanup()

    def test_restart_returns_only_posts_not_finished(self) -> None:
        posts = [post(1), post(2), post(3)]
        pending, state, resumed = fb_engagement._prepare_collect_cycle(posts)
        self.assertFalse(resumed)
        self.assertEqual([item["post_url"] for item in pending],
                         [item["post_url"] for item in posts])

        fb_engagement._mark_collect_cycle_done(state, posts[0])
        pending, restored, resumed = fb_engagement._prepare_collect_cycle(posts)

        self.assertTrue(resumed)
        self.assertEqual([item["post_url"] for item in pending],
                         [posts[1]["post_url"], posts[2]["post_url"]])
        self.assertEqual(restored["completed"], 1)
        self.assertEqual(restored["remaining"], 2)

    def test_collector_finishes_khao_before_preaw(self) -> None:
        mixed = [
            {**post(1), "account": "Preaw Buchakorn"},
            {**post(2), "account": "Khao Fang Nichapa"},
            {**post(3), "account": "Preaw Buchakorn"},
            {**post(4), "account": "Khao Fang Nichapa"},
        ]

        ordered = fb_engagement._prioritize_collect_posts(mixed)

        self.assertEqual([item["account"] for item in ordered], [
            "Khao Fang Nichapa", "Khao Fang Nichapa",
            "Preaw Buchakorn", "Preaw Buchakorn",
        ])
        # ภายในบัญชีเดียวกันยังรักษาลำดับเดิม ไม่ทำให้ checkpoint สับสน.
        self.assertEqual([item["post_url"] for item in ordered], [
            post(2)["post_url"], post(4)["post_url"],
            post(1)["post_url"], post(3)["post_url"],
        ])

    def test_newest_job_from_both_accounts_runs_before_old_backlog(self) -> None:
        mixed = [
            {**post(1), "account": "Khao Fang Nichapa", "job_id": "k-old",
             "job_created_at": "2026-09-20T10:00:00"},
            {**post(2), "account": "Preaw Buchakorn", "job_id": "p-old",
             "job_created_at": "2026-09-20T11:00:00"},
            {**post(3), "account": "Khao Fang Nichapa", "job_id": "k-new",
             "job_created_at": "2026-09-22T12:00:00"},
            {**post(4), "account": "Khao Fang Nichapa", "job_id": "k-new",
             "job_created_at": "2026-09-22T12:00:00"},
            {**post(5), "account": "Preaw Buchakorn", "job_id": "p-new",
             "job_created_at": "2026-09-22T13:00:00"},
        ]

        ordered = fb_engagement._prioritize_collect_posts(mixed)

        self.assertEqual([item["job_id"] for item in ordered], [
            "k-new", "k-new", "p-new", "k-old", "p-old",
        ])
        # Two posts in the same work order remain adjacent; no pacing gap is
        # introduced between its Facebook groups.
        self.assertTrue(fb_engagement._collect_job_ends(ordered, 1))
        self.assertFalse(fb_engagement._collect_job_ends(ordered, 0))

    def test_running_checkpoint_promotes_new_jobs_without_forgetting_done(self) -> None:
        original = [
            {**post(1), "job_id": "k-old",
             "job_created_at": "2026-09-20T10:00:00"},
            {**post(2), "job_id": "k-old",
             "job_created_at": "2026-09-20T10:00:00"},
        ]
        _, state, _ = fb_engagement._prepare_collect_cycle(original)
        fb_engagement._mark_collect_cycle_done(state, original[0])
        refreshed = fb_engagement._prioritize_collect_posts([
            *original,
            {**post(3), "job_id": "k-new",
             "job_created_at": "2026-09-22T12:00:00"},
            {**post(4), "account": "Preaw Buchakorn", "job_id": "p-new",
             "job_created_at": "2026-09-22T13:00:00"},
        ])

        pending, restored, resumed = fb_engagement._prepare_collect_cycle(refreshed)

        self.assertTrue(resumed)
        self.assertEqual([item["job_id"] for item in pending], [
            "k-new", "p-new", "k-old",
        ])
        self.assertNotIn(original[0]["post_url"], [
            item["post_url"] for item in pending
        ])
        self.assertEqual(restored["completed"], 1)
        self.assertEqual(restored["remaining"], 3)

    def test_new_post_is_added_to_running_cycle(self) -> None:
        original = [post(1), post(2)]
        _, state, _ = fb_engagement._prepare_collect_cycle(original)
        fb_engagement._mark_collect_cycle_done(state, original[0])

        pending, restored, resumed = fb_engagement._prepare_collect_cycle(
            [*original, post(3)])

        self.assertTrue(resumed)
        self.assertEqual([item["post_url"] for item in pending],
                         [original[1]["post_url"], post(3)["post_url"]])
        self.assertEqual(restored["total"], 3)

    def test_live_status_names_current_group_post_and_action(self) -> None:
        posts = [post(1), post(2)]
        _, state, _ = fb_engagement._prepare_collect_cycle(posts)
        current = {
            **posts[0],
            "caption": "ตัวอย่างแคปชันที่ Bot9 กำลังอ่าน",
        }

        fb_engagement._set_collect_cycle_current(
            state, current, "comments", "กำลังอ่านข้อความและชื่อผู้คอมเมนต์")
        status = fb_engagement.collect_cycle_status()

        self.assertTrue(status["active"])
        self.assertTrue(status["working"])
        self.assertEqual(status["current_phase"], "comments")
        self.assertEqual(status["current_action"],
                         "กำลังอ่านข้อความและชื่อผู้คอมเมนต์")
        self.assertEqual(status["current_group"], "กลุ่ม 1")
        self.assertEqual(status["current_account"], "Khao Fang Nichapa")
        self.assertEqual(status["current_post_url"], posts[0]["post_url"])
        self.assertIn("ตัวอย่างแคปชัน", status["current_caption"])

    def test_finish_removes_checkpoint(self) -> None:
        posts = [post(1)]
        _, state, _ = fb_engagement._prepare_collect_cycle(posts)
        fb_engagement._mark_collect_cycle_done(state, posts[0])
        fb_engagement._finish_collect_cycle(state)
        self.assertFalse(self.checkpoint.exists())

    def test_transient_network_error_keeps_current_post_for_retry(self) -> None:
        posts = [post(1), post(2)]
        browser = mock.MagicMock()
        browser.new_page.return_value = mock.MagicMock()
        playwright_context = mock.MagicMock()
        playwright_context.__enter__.return_value = mock.MagicMock()

        with mock.patch.object(fb_engagement, "our_posts", return_value=posts), \
             mock.patch("fb_mass_finder.find_bot", return_value={"id": "bot10"}), \
             mock.patch("fb_mass_finder.launch_bot_browser",
                        return_value=browser), \
             mock.patch("playwright.sync_api.sync_playwright",
                        return_value=playwright_context), \
             mock.patch.object(fb_engagement, "read_post", side_effect=Exception(
                 "Page.goto: net::ERR_QUIC_PROTOCOL_ERROR")):
            result = fb_engagement.check_once()

        self.assertTrue(result["incomplete"])
        self.assertEqual(result["remaining"], 2)
        self.assertTrue(self.checkpoint.exists())

    def test_manual_preemption_finishes_current_post_then_resumes_next(self) -> None:
        posts = [post(1), post(2), post(3)]
        browser = mock.MagicMock()
        browser.new_page.return_value = mock.MagicMock()
        playwright_context = mock.MagicMock()
        playwright_context.__enter__.return_value = mock.MagicMock()
        manual_requested = False

        def read_current(*_args, **_kwargs):
            nonlocal manual_requested
            manual_requested = True
            return {
                "reachable": True, "note": "", "reactions": 1,
                "comments": 0, "shares": 0, "comments_list": [],
                "comments_snapshot_complete": True,
            }

        with mock.patch.object(fb_engagement, "our_posts", return_value=posts), \
             mock.patch("fb_mass_finder.find_bot", return_value={"id": "bot9"}), \
             mock.patch("fb_mass_finder.launch_bot_browser",
                        return_value=browser), \
             mock.patch("playwright.sync_api.sync_playwright",
                        return_value=playwright_context), \
             mock.patch.object(fb_engagement, "read_post",
                               side_effect=read_current) as read:
            result = fb_engagement.check_once(stop=lambda: manual_requested)

        self.assertEqual(read.call_count, 1)
        self.assertTrue(result["preempted"])
        self.assertTrue(result["incomplete"])
        self.assertEqual(result["remaining"], 2)

        pending, _state, resumed = fb_engagement._prepare_collect_cycle(posts)
        self.assertTrue(resumed)
        self.assertEqual([item["post_url"] for item in pending], [
            posts[1]["post_url"], posts[2]["post_url"],
        ])

    def test_first_deploy_recovers_old_unfinished_round_from_log_and_db(self) -> None:
        posts = [post(1), post(2)]
        started = datetime.now() - timedelta(minutes=1)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.log.write_text(
            f"{started:%d/%m %H:%M:%S} เริ่มรอบเช็ค ตามช่วงเฝ้าปกติ\n",
            encoding="utf-8",
        )
        conn = fb_engagement.open_db()
        conn.execute(
            """INSERT INTO my_post
               (post_url, group_id, group_name, account, reactions, comments,
                shares, reachable, note, checked_at)
               VALUES (?, '', '', '', 0, 0, 0, 1, '', ?)""",
            (posts[0]["post_url"], datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        conn.close()

        pending, state, resumed = fb_engagement._prepare_collect_cycle(posts)

        self.assertTrue(resumed)
        self.assertEqual([item["post_url"] for item in pending],
                         [posts[1]["post_url"]])
        self.assertEqual(state["completed"], 1)


if __name__ == "__main__":
    unittest.main()
