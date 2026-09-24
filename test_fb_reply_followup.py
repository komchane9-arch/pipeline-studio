from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from playwright.sync_api import expect, sync_playwright


_root = tempfile.TemporaryDirectory(prefix="reply-followup-test-")
os.environ["STUDIO_DATA_DIR"] = _root.name
os.environ["STUDIO_POST_STATE_DIR"] = _root.name + "/post-state"

import app
import fb_engagement as store
import fb_engage


class ReplyFollowupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = mock.patch.object(
            store, "DB_FILE", Path(self.temp.name) / "engage.sqlite3")
        self.db_patch.start()
        conn = store.open_db()
        conn.execute(
            """INSERT INTO my_comment
                 (comment_key, post_url, account, author, body,
                  first_seen, last_seen)
               VALUES ('parent', 'post', 'Profile A', 'Pawee Naa',
                       'น่าสนใจ', 'now', 'now')""")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_followup_requires_first_comment_to_be_queued(self):
        with self.assertRaisesRegex(ValueError, "comment แรก"):
            store.queue_followup("parent", "comment 2", now=1000, delay_seconds=60)

    def test_countdown_starts_after_first_comment_is_confirmed(self):
        base = 1_790_000_000
        store.queue_reply("parent", "comment 1")
        queued = store.queue_followup(
            "parent", "comment 2", now=base, delay_seconds=60)
        self.assertEqual(queued["followup_due_at"], 0)
        with mock.patch.object(store.time, "time", return_value=base + 59):
            self.assertEqual(
                [row["queue_kind"] for row in store.queued_replies(account="Profile A")],
                ["first"],
            )

        store.mark_reply_submitted("parent", "comment 1")
        store.mark_reply_result("parent", True, now=base + 100)
        with mock.patch.object(store.time, "time", return_value=base + 159):
            self.assertEqual(store.queued_replies(account="Profile A"), [])
        with mock.patch.object(store.time, "time", return_value=base + 160):
            rows = store.queued_replies(account="Profile A")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["queue_kind"], "followup")
        self.assertEqual(rows[0]["comment_key"], "parent::followup-2")
        self.assertEqual(rows[0]["reply_draft"], "comment 2")

    def test_repeated_queue_does_not_reset_persisted_random_delay(self):
        base = 1_790_000_000
        store.queue_reply("parent", "comment 1")
        first = store.queue_followup(
            "parent", "comment 2", now=base, delay_seconds=180)
        repeated = store.queue_followup(
            "parent", "comment 2", now=base + 30, delay_seconds=300)
        self.assertEqual(repeated["followup_queued_at"], first["followup_queued_at"])
        self.assertEqual(repeated["followup_delay_seconds"], 180)
        with self.assertRaisesRegex(ValueError, "ห้ามเปลี่ยนข้อความ"):
            store.queue_followup(
                "parent", "different text", now=base + 30, delay_seconds=300)

    def test_followup_has_separate_receipt_and_daily_count(self):
        base = 1_790_000_000
        store.queue_reply("parent", "comment 1")
        store.queue_followup("parent", "comment 2", now=base, delay_seconds=300)
        store.mark_reply_submitted("parent", "comment 1")
        store.mark_reply_result("parent", True, now=base + 100)
        key = store.followup_key("parent")
        store.mark_reply_submitted(key, "comment 2")
        result = store.mark_reply_result(key, True, now=base + 400)
        state = store.reply_states(["parent", key])

        self.assertEqual(result["queue_kind"], "followup")
        self.assertEqual(store.reply_daily_status("Profile A", now=base + 401)["used"], 2)
        self.assertTrue(state[0]["reply_sent_at"])
        self.assertTrue(state[0]["followup_sent_at"])
        self.assertEqual(state[1]["reply_sent_at"], state[0]["followup_sent_at"])

        # Reconfirming the same receipt must not consume quota twice.
        store.mark_reply_result(key, True, now=base + 500)
        self.assertEqual(store.reply_daily_status("Profile A", now=base + 501)["used"], 2)

    def test_retry_failed_followup_requeues_only_second_comment(self):
        base = 1_790_000_000
        store.queue_reply("parent", "comment 1")
        store.queue_followup("parent", "comment 2", now=base, delay_seconds=60)
        store.mark_reply_submitted("parent", "comment 1")
        store.mark_reply_result("parent", True, now=base + 10)
        first_sent_at = store.reply_states(["parent"])[0]["reply_sent_at"]
        key = store.followup_key("parent")
        store.mark_reply_result(key, False, "หาแถวต้นทางไม่เจอ", now=base + 80)

        out = store.retry_saved_reply(key, "Profile A")
        queued = store.queued_replies(account="Profile A")

        self.assertEqual(out["queue_kind"], "followup")
        self.assertFalse(out["verification_only"])
        self.assertEqual([row["comment_key"] for row in queued], [key])
        self.assertEqual(store.reply_states(["parent"])[0]["reply_sent_at"], first_sent_at)
        self.assertEqual(store.reply_states([key])[0]["reply_error"], "")

    def test_retry_submitted_followup_is_verification_only(self):
        base = 1_790_000_000
        store.queue_reply("parent", "comment 1")
        store.queue_followup("parent", "comment 2", now=base, delay_seconds=60)
        store.mark_reply_submitted("parent", "comment 1")
        store.mark_reply_result("parent", True, now=base + 10)
        key = store.followup_key("parent")
        store.mark_reply_submitted(key, "comment 2")
        store.mark_reply_result(key, False, "ตรวจยังไม่ชัด", now=base + 80)

        out = store.retry_saved_reply(key, "Profile A")

        self.assertTrue(out["verification_only"])
        self.assertTrue(out["reply_submitted_at"])
        self.assertEqual(store.queued_replies(account="Profile A")[0]["comment_key"], key)

    def test_retry_confirms_unique_collector_child_without_resending(self):
        store.queue_reply("parent", "comment 1")
        conn = store.open_db()
        conn.execute("UPDATE my_comment SET answered=1, reply_error='old failure' "
                     "WHERE comment_key='parent'")
        conn.execute(
            """INSERT INTO my_comment
                 (comment_key, post_url, account, author, body, reply_to,
                  is_ours, first_seen, last_seen)
               VALUES ('child', 'post', 'Profile A', 'Profile A',
                       'Pawee Naa comment 1', 'Pawee Naa', 1,
                       '2999-01-01T00:00:00', '2999-01-01T00:00:00')"""
        )
        conn.commit()
        conn.close()

        out = store.retry_saved_reply("parent", "Profile A")

        self.assertTrue(out["collector_confirmed"])
        self.assertTrue(out["verification_only"])
        self.assertEqual(out["reply_sent_at"], "2999-01-01T00:00:00")
        self.assertEqual(store.reply_states(["parent"])[0]["reply_error"], "")

    def test_collector_confirmation_refuses_duplicate_parent_collision(self):
        store.queue_reply("parent", "comment 1")
        conn = store.open_db()
        conn.execute("UPDATE my_comment SET answered=1 WHERE comment_key='parent'")
        conn.execute(
            """INSERT INTO my_comment
                 (comment_key, post_url, account, author, body, is_ours,
                  first_seen, last_seen)
               VALUES ('duplicate-parent', 'post', 'Profile A', 'Pawee Naa',
                       'another question', 0, 'now', 'now')"""
        )
        conn.execute(
            """INSERT INTO my_comment
                 (comment_key, post_url, account, author, body, reply_to,
                  is_ours, first_seen, last_seen)
               VALUES ('child', 'post', 'Profile A', 'Profile A',
                       'Pawee Naa comment 1', 'Pawee Naa', 1,
                       '2999-01-01T00:00:00', '2999-01-01T00:00:00')"""
        )
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(ValueError, "มีคำตอบแล้ว"):
            store.retry_saved_reply("parent", "Profile A")
        self.assertEqual(store.reply_states(["parent"])[0]["reply_sent_at"], "")

    def test_followup_bypasses_normal_10_to_15_minute_gap(self):
        item = {
            "comment_key": "parent::followup-2", "parent_comment_key": "parent",
            "queue_kind": "followup", "account": "Profile A",
            "author": "Pawee Naa", "post_url": "post", "reply_draft": "comment 2",
        }
        with mock.patch.object(app, "_fb_comment_priority_status", return_value={"blocked": False}), \
             mock.patch("fb_engagement.queued_replies", return_value=[item]), \
             mock.patch.object(app, "_fb_reply_schedule_status", return_value={"waiting": True}), \
             mock.patch("fb_engagement.reply_daily_status", return_value={"waiting": False}), \
             mock.patch.object(fb_engage, "run_queued_reply",
                               return_value={"sent": False, "error": "test"}) as run, \
             mock.patch("fb_engagement.mark_reply_result", return_value={}):
            app._run_one_fb_reply(send=True)
        run.assert_called_once()

    def test_ui_exposes_add_comment_and_followup_api(self):
        js = Path("web/engage.js").read_text(encoding="utf-8")
        css = Path("web/styles.css").read_text(encoding="utf-8")
        self.assertIn("+ เพิ่ม comment", js)
        self.assertIn("/api/fb/engage/followup", js)
        self.assertIn("eg-followup-editor", css)

    def test_ui_creates_second_editor_only_after_click_and_queues_it(self):
        requests = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page()

            def route(request):
                path = request.request.url.split("studio.test", 1)[1].split("?", 1)[0]
                if path == "/":
                    ids = ["egNote", "egTimer", "egList", "egDaily", "egCollector",
                           "egManualFeedback", "egStamp"]
                    request.fulfill(content_type="text/html",
                                    body="".join(f'<div id="{item}"></div>' for item in ids))
                elif path == "/api/fb/engage/threads":
                    request.fulfill(json={
                        "account": "Profile A",
                        "posts": [{
                            "post_url": "https://facebook.com/share/p/test/",
                            "account": "Profile A", "group_id": "g", "group_name": "group",
                            "active": True, "comments_list": [{
                                "comment_key": "parent", "author": "Pawee Naa",
                                "body": "น่าสนใจ", "is_ours": False, "answered": 0,
                                "reply_draft": "comment 1", "reply_queued_at": "queued",
                            }, {
                                "comment_key": "done", "author": "Already Done",
                                "body": "ตอบไปแล้ว", "is_ours": False, "answered": 1,
                                "reply_sent_at": "2026-09-22T10:00:00",
                            }],
                        }],
                    })
                elif path == "/api/fb/engage/followup":
                    requests.append(request.request.post_data_json)
                    request.fulfill(json={
                        "followup_draft": "comment 2", "followup_queued_at": "queued",
                        "followup_due_at": 0, "followup_delay_seconds": 180,
                        "message": "comment 2 เข้าคิวแล้ว · รอ comment แรกยืนยัน",
                    })
                elif path == "/core.js":
                    request.fulfill(content_type="text/javascript", body=(
                        "export const api=async(u,o={})=>{const r=await fetch(u,o);"
                        "const j=await r.json();if(!r.ok)throw new Error(j.detail);return j};"))
                elif path == "/gfaccount.js":
                    request.fulfill(content_type="text/javascript", body=(
                        "export const gfQuery=p=>p;export const gfAccount=()=>\"Profile A\";"))
                elif path == "/engage.js":
                    request.fulfill(path=str(Path("web/engage.js").resolve()))
                else:
                    request.fulfill(json={})

            page.route("**/*", route)
            page.goto("http://studio.test/")
            page.evaluate("async()=>{window.eg=await import('/engage.js');await eg.loadEngage()}")
            row = page.locator('.eg-comment[data-comment-key="parent"]')
            done = page.locator('.eg-comment[data-comment-key="done"]')
            expect(done).to_contain_text("ตอบแล้ว")
            expect(done.get_by_role("button", name="+ เพิ่ม comment", exact=True)).to_have_count(0)
            expect(done.locator("textarea")).to_have_count(0)
            expect(row.locator("textarea")).to_have_count(1)
            row.get_by_role("button", name="+ เพิ่ม comment", exact=True).click()
            expect(row.locator("textarea")).to_have_count(2)
            row.get_by_placeholder("comment 2 ต่อจากคำตอบของ Pawee Naa…").fill("comment 2")
            row.get_by_role("button", name="↩ เข้าคิว comment 2", exact=True).click()
            expect(row.locator(".eg-followup .eg-note")).to_contain_text("รอ comment แรกยืนยัน")
            expect(row.get_by_role("button", name="✓ comment 2 เข้าคิวแล้ว", exact=True)).to_be_disabled()
            self.assertEqual(requests, [{"comment_key": "parent", "text": "comment 2"}])
            browser.close()


if __name__ == "__main__":
    unittest.main()
