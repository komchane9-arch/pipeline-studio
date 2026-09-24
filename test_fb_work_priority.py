from __future__ import annotations

import asyncio
import json
import unittest
from unittest import mock

import app
from fastapi import HTTPException


class FacebookWorkPriorityTests(unittest.TestCase):
    def test_start_now_clears_post_cooldown_for_selected_account_only(self):
        with app._fb_priority_lock:
            app._fb_priority_by_account.update({
                "Khao": {"resume_at": 2_000.0, "was_active": False},
                "Preaw": {"resume_at": 3_000.0, "was_active": False},
            })

        app._clear_fb_post_reply_cooldown("Khao")

        self.assertEqual(app._fb_priority_by_account["Khao"]["resume_at"], 0.0)
        self.assertEqual(app._fb_priority_by_account["Preaw"]["resume_at"], 3_000.0)

    def test_start_now_endpoint_clears_both_wait_layers_and_reports_ready(self):
        class Request:
            async def body(self):
                return json.dumps({"account": "Khao"}).encode()

            async def json(self):
                return {"account": "Khao"}

        with app._fb_priority_lock:
            app._fb_priority_by_account["Khao"] = {
                "resume_at": 2_000.0, "was_active": False,
            }
        cleared = {"account": "Khao", "waiting": False,
                   "wait_seconds": 0, "next_at": 0}
        with mock.patch.object(app, "_fb_post_work_active", return_value=False), \
             mock.patch("fb_engagement.clear_reply_gap", return_value=cleared) as clear, \
             mock.patch.object(app, "append_log"):
            out = asyncio.run(app.fb_engage_start_now(Request()))

        clear.assert_called_once_with("Khao")
        self.assertFalse(out["work_priority"]["blocked"])
        self.assertFalse(out["reply_schedule"]["waiting"])
        self.assertEqual(app._fb_priority_by_account["Khao"]["resume_at"], 0.0)

    def test_start_now_cannot_clear_guard_while_post_is_active(self):
        class Request:
            async def body(self):
                return json.dumps({"account": "Khao"}).encode()

            async def json(self):
                return {"account": "Khao"}

        with app._fb_priority_lock:
            app._fb_priority_by_account["Khao"] = {
                "resume_at": 2_000.0, "was_active": True,
            }
        with mock.patch.object(app, "_fb_post_work_active", return_value=True), \
             mock.patch("fb_engagement.clear_reply_gap") as clear:
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(app.fb_engage_start_now(Request()))

        self.assertEqual(caught.exception.status_code, 409)
        clear.assert_not_called()
        self.assertEqual(app._fb_priority_by_account["Khao"]["resume_at"], 2_000.0)

    def test_resume_after_restriction_releases_selected_account_and_wait_layers(self):
        class Request:
            async def body(self):
                return json.dumps({"account": "Khao"}).encode()

            async def json(self):
                return {"account": "Khao"}

        ready = {"account": "Khao", "waiting": False,
                 "wait_seconds": 0, "next_at": 0}
        release_context = mock.MagicMock()
        with mock.patch.object(app, "_fb_comment_priority_status",
                               return_value={"account": "Khao", "blocked": False}), \
             mock.patch("fb_engage.reply_quota_status", return_value={
                 "account": "Khao", "waiting": True, "reason": "safety_hold",
                 "wait_seconds": 1_000,
             }), \
             mock.patch.object(app.fb_auto_post, "use_account",
                               return_value=release_context) as use_account, \
             mock.patch.object(app.fb_comment_guard, "release",
                               return_value="ปลดพักคอมเมนต์แล้ว") as release, \
             mock.patch.object(app, "_clear_fb_post_reply_cooldown") as clear_post, \
             mock.patch("fb_engagement.clear_reply_gap", return_value=ready) as clear_gap, \
             mock.patch.object(app, "_fb_reply_schedule_status", return_value=ready), \
             mock.patch.object(app, "append_log"):
            out = asyncio.run(app.fb_engage_resume_after_restriction(Request()))

        use_account.assert_called_once_with("Khao")
        release.assert_called_once_with()
        clear_post.assert_called_once_with("Khao")
        clear_gap.assert_called_once_with("Khao")
        self.assertFalse(out["reply_schedule"]["waiting"])

    def test_resume_after_restriction_never_releases_while_post_is_active(self):
        class Request:
            async def body(self):
                return json.dumps({"account": "Khao"}).encode()

            async def json(self):
                return {"account": "Khao"}

        with mock.patch.object(app, "_fb_comment_priority_status", return_value={
                "account": "Khao", "blocked": True, "reason": "post"}), \
             mock.patch("fb_engage.reply_quota_status") as hold, \
             mock.patch.object(app.fb_comment_guard, "release") as release:
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(app.fb_engage_resume_after_restriction(Request()))

        self.assertEqual(caught.exception.status_code, 409)
        hold.assert_not_called()
        release.assert_not_called()

    def test_resume_after_restriction_rejects_stale_banner(self):
        class Request:
            async def body(self):
                return json.dumps({"account": "Khao"}).encode()

            async def json(self):
                return {"account": "Khao"}

        with mock.patch.object(app, "_fb_comment_priority_status",
                               return_value={"account": "Khao", "blocked": False}), \
             mock.patch("fb_engage.reply_quota_status", return_value={
                 "account": "Khao", "waiting": False, "wait_seconds": 0,
             }), \
             mock.patch.object(app.fb_comment_guard, "release") as release:
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(app.fb_engage_resume_after_restriction(Request()))

        self.assertEqual(caught.exception.status_code, 409)
        release.assert_not_called()

    def test_post_and_cooldown_are_separate_per_account(self):
        app._fb_request_post_priority("khao-job", now=1000, account="Khao")
        self.assertTrue(app._fb_comment_priority_status(
            now=1001, active=True, account="Khao")["blocked"])
        self.assertFalse(app._fb_comment_priority_status(
            now=1001, active=False, account="Preaw")["blocked"])
        self.assertEqual(app._fb_comment_priority_status(
            now=1100, active=False, account="Khao", delay_seconds=600)["wait_seconds"], 600)
        self.assertFalse(app._fb_comment_priority_status(
            now=1101, active=False, account="Preaw")["blocked"])

    def test_other_device_post_does_not_block_idle_profile(self):
        with mock.patch("devices.device_for_account", return_value="preaw-phone"), \
             mock.patch.object(app.fb_runner, "running", return_value={"khao-phone": "khao-job"}), \
             mock.patch.object(app.fb_jobs, "listing", return_value=[]), \
             mock.patch.object(app.fb_auto_post, "use_account", return_value=mock.MagicMock()):
            self.assertFalse(app._fb_post_work_active("Preaw"))

    def test_worker_skips_blocked_account_and_runs_preaw(self):
        rows = [{"account": a, "comment_key": a, "author": "person", "post_url": "url"}
                for a in ["Khao", "Preaw"]]
        def priority(**kw):
            return {"blocked": kw.get("account") == "Khao", "reason": "post", "note": "post"}
        with mock.patch.object(app, "_fb_comment_priority_status", side_effect=priority), \
             mock.patch("fb_engagement.queued_replies", return_value=rows), \
             mock.patch("fb_engage.run_queued_reply", return_value={"verified": True, "sent": False}) as run:
            app._run_one_fb_reply(send=False)
        self.assertEqual(run.call_args.args[0]["account"], "Preaw")

    def test_reply_worker_is_visible_to_restart_guard_until_phone_work_finishes(self):
        item = {"account": "Preaw", "comment_key": "c-live", "author": "Alice",
                "post_url": "https://facebook.com/p/live", "job_id": "P-LIVE",
                "group_name": "กลุ่มสด"}

        def running(_item, **_kwargs):
            activity = app._fb_reply_activity_status("Preaw")
            self.assertTrue(activity["active"])
            self.assertEqual(activity["job_id"], "P-LIVE")
            self.assertTrue(any(row["key"].startswith("fb-reply:")
                                for row in app._busy_rows()))
            return {"verified": True, "sent": False}

        with mock.patch.object(app, "_fb_comment_priority_status",
                               return_value={"blocked": False}), \
             mock.patch("fb_engagement.queued_replies", return_value=[item]), \
             mock.patch("fb_engage.run_queued_reply", side_effect=running):
            app._run_one_fb_reply(send=False)

        self.assertFalse(app._fb_reply_activity_status("Preaw")["active"])
        self.assertFalse(any(row["key"].startswith("fb-reply:")
                             for row in app._busy_rows()))

    def setUp(self) -> None:
        with app._fb_priority_lock:
            app._fb_post_requested_at = 0.0
            app._fb_post_requested_job = ""
            app._fb_post_was_active = False
            app._fb_comments_resume_at = 0.0
            app._fb_priority_by_account.clear()
        app._engagement_manual_requested.clear()
        with app._engagement_manual_lock:
            app._engagement_manual_state.clear()
            app._engagement_manual_state.update({
                "status": "idle", "active": False, "scope": "", "label": "",
                "total": 0, "completed": 0, "remaining": 0,
            })

    def test_post_preempts_comments_then_starts_fixed_cooldown_once(self) -> None:
        app._fb_request_post_priority("p-test", now=1_000)
        starting = app._fb_comment_priority_status(now=1_001, active=False)
        running = app._fb_comment_priority_status(now=1_010, active=True)
        cooling = app._fb_comment_priority_status(
            now=1_100, active=False, delay_seconds=600)
        same_cooling = app._fb_comment_priority_status(
            now=1_200, active=False, delay_seconds=900)
        ready = app._fb_comment_priority_status(now=1_700, active=False)

        self.assertEqual(starting["reason"], "post")
        self.assertEqual(running["reason"], "post")
        self.assertEqual(cooling["reason"], "cooldown")
        self.assertEqual(cooling["wait_seconds"], 600)
        self.assertEqual(same_cooling["wait_seconds"], 500)
        self.assertFalse(ready["blocked"])

    def test_failed_post_request_does_not_create_comment_cooldown(self) -> None:
        app._fb_request_post_priority("p-bad", now=2_000)
        status = app._fb_comment_priority_status(
            now=2_000 + app.FB_POST_REQUEST_GRACE_SECONDS + 1,
            active=False, delay_seconds=600)
        self.assertFalse(status["blocked"])
        self.assertEqual(app._fb_comments_resume_at, 0.0)

    def test_reply_worker_does_not_pick_queue_during_post_priority(self) -> None:
        blocked = {
            "blocked": True, "reason": "post", "wait_seconds": 0,
            "note": "พักงานคอมเมนต์ — ให้งานโพสต์จบใบงานก่อน",
        }
        with mock.patch.object(app, "_fb_comment_priority_status",
                               return_value=blocked), \
             mock.patch("fb_engagement.queued_replies", return_value=[{"account": "Preaw"}]) as queued:
            result = app._run_one_fb_reply(send=True)

        queued.assert_called_once()
        self.assertTrue(result["waiting"])
        self.assertEqual(result["priority"], "post")

    def test_desktop_collector_ignores_mobile_post_priority(self) -> None:
        blocked = {
            "blocked": True, "reason": "post", "wait_seconds": 0,
            "note": "พักคิวตอบคอมเมนต์บนมือถือ",
        }
        collected = {"posts": 1, "ok": 1, "blocked": 0}
        with mock.patch.object(app, "_fb_comment_priority_status",
                               return_value=blocked), \
             mock.patch.object(app, "_wait_chrome_free", return_value=True), \
             mock.patch("fb_engagement.check_once", return_value=collected) as check:
            result = app._run_engagement_once()

        self.assertEqual(result, collected)
        check.assert_called_once()
        # ไม่สนธงงานโพสต์มือถือ แต่ยอมคืนคิวให้คำสั่ง Manual ของ Bot9
        # ที่ใช้ Chrome โปรไฟล์เดียวกัน ณ ขอบโพสต์ที่ปลอดภัย.
        self.assertTrue(callable(check.call_args.kwargs["stop"]))
        self.assertIs(check.call_args.kwargs["stop"].__self__,
                      app._engagement_manual_requested)

    def test_post_wait_does_not_wait_for_desktop_collector(self) -> None:
        app._engagement_run_lock.acquire()
        try:
            self.assertTrue(app._wait_comment_work_yield(timeout=0))
        finally:
            app._engagement_run_lock.release()

    def test_manual_worker_exposes_live_scope_and_finishes(self) -> None:
        posts = [{
            "post_url": "https://www.facebook.com/share/p/test/",
            "caption": "โพสต์ทดสอบ", "group_id": "123",
            "group_name": "กลุ่มทดสอบ", "account": "Khao Fang Nichapa",
        }]

        def fake_run(**kwargs):
            kwargs["progress"]({
                "phase": "comments", "action": "กำลังอ่านคอมเมนต์",
                "completed": 0, "total": 1, **posts[0],
            })
            kwargs["progress"]({
                "phase": "resting", "action": "บันทึกผลแล้ว",
                "completed": 1, "total": 1, **posts[0],
            })
            return {"ok": 1, "blocked": 0, "new_comments": 2}

        with mock.patch.object(app, "_run_engagement_locked",
                               side_effect=fake_run), \
             mock.patch.object(app, "append_log"):
            app._engagement_manual_worker(posts, "post", "โพสต์ทดสอบ")

        state = app._engagement_manual_status()
        self.assertEqual(state["status"], "complete")
        self.assertFalse(state["active"])
        self.assertEqual(state["completed"], 1)
        self.assertEqual(state["remaining"], 0)
        self.assertEqual(state["current_group"], "กลุ่มทดสอบ")
        self.assertEqual(state["result"]["new_comments"], 2)

    def test_manual_start_rejects_second_overlapping_request(self) -> None:
        posts = [{"post_url": "https://www.facebook.com/share/p/test/"}]
        thread = mock.MagicMock()
        with mock.patch.object(app.threading, "Thread", return_value=thread):
            first = app._start_engagement_manual(posts, "all", "ทุกโพสต์")
            second = app._start_engagement_manual(posts, "all", "ทุกโพสต์")

        self.assertEqual(first["status"], "queued")
        self.assertTrue(second["busy"])
        thread.start.assert_called_once()
        app._engagement_manual_requested.clear()

    def test_completed_legacy_finishing_label_does_not_block_comments(self) -> None:
        job = {"status": app.fb_auto_post.STATUS_FINISHING, "results": [{}]}
        with mock.patch.object(app.fb_runner, "running", return_value={}), \
             mock.patch.object(app, "_bound_post_accounts", return_value=["บัญชีทดสอบ"]), \
             mock.patch.object(app.fb_auto_post, "use_account", return_value=mock.MagicMock()), \
             mock.patch.object(app.fb_jobs, "listing", return_value=[job]), \
             mock.patch.object(app, "_fb_pending_followup_groups", return_value=[]):
            self.assertFalse(app._fb_post_work_active())

    def test_finishing_with_mandatory_steps_left_keeps_post_priority(self) -> None:
        job = {"status": app.fb_auto_post.STATUS_FINISHING, "results": [{}]}
        with mock.patch.object(app.fb_runner, "running", return_value={}), \
             mock.patch.object(app, "_bound_post_accounts", return_value=["บัญชีทดสอบ"]), \
             mock.patch.object(app.fb_auto_post, "use_account", return_value=mock.MagicMock()), \
            mock.patch.object(app.fb_jobs, "listing", return_value=[job]), \
             mock.patch.object(app, "_fb_pending_followup_groups", return_value=["group-1"]):
            self.assertTrue(app._fb_post_work_active())

    def test_jobs_api_survives_unavailable_drive_image(self) -> None:
        job = {
            "id": "p-drive", "status": app.fb_auto_post.STATUS_READY,
            "image": r"G:\My Drive\pipeline studio\Post\images\missing.jpg",
            "groups": [], "results": [], "log": [],
        }
        with mock.patch.object(app.fb_jobs, "listing", return_value=[job]), \
             mock.patch.object(app.fb_runner, "running", return_value={}), \
             mock.patch.object(app.Path, "is_file", side_effect=PermissionError(5)):
            body = app._fb_list_jobs_body()

        self.assertTrue(body["ok"])
        self.assertFalse(body["control_job"]["has_image"])


if __name__ == "__main__":
    unittest.main()
