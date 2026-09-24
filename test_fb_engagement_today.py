from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fb_engagement as engage
import fb_engage


class EngagementTodayTests(unittest.TestCase):
    def test_failed_attempts_do_not_start_window_or_consume_quota(self):
        base = 1_790_000_000
        with tempfile.TemporaryDirectory() as raw, \
             mock.patch.object(engage, "DB_FILE", Path(raw) / "engage.sqlite3"):
            conn = engage.open_db()
            conn.execute("""INSERT INTO my_comment
                (comment_key, post_url, account, author, body, first_seen, last_seen)
                VALUES ('reply', 'post', 'Preaw', 'Alice', 'hello', 'now', 'now')""")
            conn.commit()
            conn.close()
            for n in range(4):
                engage.mark_reply_result("reply", False, "หาเป้าหมายไม่เจอ", now=base+1000+n)
            status = engage.reply_daily_status("Preaw", now=base+1010)
            self.assertEqual(status["used"], 0)
            self.assertEqual(status["window_started_at"], 0)
            engage.mark_reply_result("reply", True, now=base+1020)
            # Simulate refresh losing mutable delivery flags; receipt survives.
            conn = engage.open_db()
            conn.execute("UPDATE my_comment SET reply_sent_at='', answered=0 WHERE comment_key='reply'")
            conn.commit()
            conn.close()
            engage.mark_reply_result("reply", True, now=base+1030)
            engage.mark_reply_result("reply", False, "stale failure", now=base+1040)
            status = engage.reply_daily_status("Preaw", now=base+1050)
            self.assertEqual(status["used"], 1)
            self.assertEqual(status["window_started_at"], base+1020)
            conn = engage.open_db()
            row = conn.execute("SELECT reply_error, reply_sent_at FROM my_comment").fetchone()
            self.assertEqual(row["reply_error"], "")
            self.assertTrue(row["reply_sent_at"])
            conn.close()

    @staticmethod
    def _snapshot(conn, url: str, when: str, reactions: int,
                  comments: int, shares: int) -> None:
        conn.execute(
            """INSERT INTO my_post
                   (post_url, group_id, group_name, account, reactions,
                    comments, shares, reachable, note, checked_at)
               VALUES (?, 'g1', 'กลุ่มทดสอบ', 'Profile Owner', ?, ?, ?, 1, '', ?)""",
            (url, reactions, comments, shares, when))
        conn.commit()

    def test_quiet_24_hours_only_suggests_and_never_stops_by_itself(self) -> None:
        with tempfile.TemporaryDirectory() as raw, \
             mock.patch.object(engage, "DB_FILE", Path(raw) / "engage.sqlite3"):
            conn = engage.open_db()
            try:
                self._snapshot(conn, "https://facebook.test/quiet",
                               "2026-09-17T10:00:00", 10, 2, 1)
                self._snapshot(conn, "https://facebook.test/quiet",
                               "2026-09-18T10:05:00", 11, 2, 1)
                status = engage.watch_status(
                    conn, "https://facebook.test/quiet",
                    now=engage.datetime.fromisoformat("2026-09-18T10:05:00"))
                keep, _ = engage.still_worth_watching(
                    conn, "https://facebook.test/quiet")
            finally:
                conn.close()

        self.assertTrue(status["suggest_stop"])
        self.assertTrue(status["notify_suggestion"])
        self.assertEqual(status["delta_reactions"], 1)
        self.assertTrue(keep, "ยอดนิ่งต้องเสนอเท่านั้น ห้ามหยุดเอง")

    def test_manual_stop_and_keep_are_reversible_without_deleting_history(self) -> None:
        with tempfile.TemporaryDirectory() as raw, \
             mock.patch.object(engage, "DB_FILE", Path(raw) / "engage.sqlite3"):
            conn = engage.open_db()
            try:
                self._snapshot(conn, "https://facebook.test/control",
                               "2026-09-17T10:00:00", 5, 0, 0)
            finally:
                conn.close()

            stopped = engage.set_post_watch(
                post_url="https://facebook.test/control", active=False, actor="test")
            conn = engage.open_db()
            try:
                keep, _ = engage.still_worth_watching(
                    conn, "https://facebook.test/control")
                history = conn.execute(
                    "SELECT COUNT(*) FROM my_post WHERE post_url=?",
                    ("https://facebook.test/control",)).fetchone()[0]
            finally:
                conn.close()
            resumed = engage.set_post_watch(
                watch_key=stopped["watch_key"], active=True, actor="test")

        self.assertFalse(keep)
        self.assertEqual(history, 1)
        self.assertTrue(resumed["active"])
        self.assertTrue(resumed["keep_until"])
        self.assertFalse(resumed["suggest_stop"])

    def test_pending_comment_blocks_quiet_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as raw, \
             mock.patch.object(engage, "DB_FILE", Path(raw) / "engage.sqlite3"):
            conn = engage.open_db()
            try:
                url = "https://facebook.test/owed"
                self._snapshot(conn, url, "2026-09-17T10:00:00", 5, 1, 0)
                self._snapshot(conn, url, "2026-09-18T10:05:00", 5, 1, 0)
                conn.execute(
                    """INSERT INTO my_comment
                           (comment_key, post_url, seq, author, body, when_text,
                            reply_to, is_ours, answered, first_seen, last_seen)
                       VALUES ('owed', ?, 1, 'Alice', 'สนใจ', '', '', 0, 0,
                               '2026-09-18', '2026-09-18')""", (url,))
                conn.commit()
                status = engage.watch_status(
                    conn, url,
                    now=engage.datetime.fromisoformat("2026-09-18T10:05:00"))
            finally:
                conn.close()

        self.assertFalse(status["suggest_stop"])
        self.assertIn("รอตอบ 1", status["suggest_reason"])

    def test_all_history_and_new_jobs_are_discovered_without_date_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            account_dir = Path(raw)
            (account_dir / "fb_groups.json").write_text(json.dumps([
                {"group_id": "g1", "name": "กลุ่มหนึ่ง"},
            ]), encoding="utf-8")
            (account_dir / "fb_jobs.json").write_text(json.dumps([
                {"id": "old", "created_at": "2026-01-01T09:00:00",
                 "caption": "เก่า", "results": [
                     {"group_id": "g1", "link": "https://facebook.test/old"}]},
                {"id": "new", "created_at": "2026-09-18T09:00:00",
                 "caption": "ใหม่", "results": [
                     {"group_id": "g1", "link": "https://facebook.test/new"}]},
            ]), encoding="utf-8")
            with mock.patch.object(engage.shared, "known_accounts",
                                   return_value=["Profile Owner"]), \
                 mock.patch.object(engage.shared, "account_dir",
                                   return_value=account_dir), \
                 mock.patch.object(engage, "watched_accounts",
                                   return_value=["Profile Owner"]), \
                 mock.patch.object(engage, "WATCH_SINCE", ""):
                rows = engage.our_posts()

        self.assertEqual([row["post_url"] for row in rows], [
            "https://facebook.test/old", "https://facebook.test/new"])

    def test_reply_states_returns_only_requested_latest_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw, \
             mock.patch.object(engage, "DB_FILE", Path(raw) / "engage.sqlite3"):
            conn = engage.open_db()
            try:
                conn.executemany(
                    """INSERT INTO my_comment
                           (comment_key, post_url, account, seq, author, body, when_text,
                            reply_to, is_ours, answered, first_seen, last_seen)
                         VALUES (?, ?, 'Profile Owner', ?, ?, ?, '', '', 0, 0, ?, ?)""",
                    [
                        ("done", "https://facebook.test/1", 1, "Alice", "หนึ่ง", "now", "now"),
                        ("waiting", "https://facebook.test/1", 2, "Bob", "สอง", "now", "now"),
                        ("other", "https://facebook.test/1", 3, "Cara", "สาม", "now", "now"),
                    ],
                )
                conn.commit()
            finally:
                conn.close()
            engage.mark_reply_result("done", sent=True)
            states = engage.reply_states(["waiting", "done", "missing", "done"])

        self.assertEqual([row["comment_key"] for row in states], ["waiting", "done"])
        self.assertFalse(states[0]["reply_sent_at"])
        self.assertTrue(states[1]["reply_sent_at"])
        self.assertEqual(states[1]["answered"], 1)

    def test_comment_age_parser_supports_thai_and_english_relative_time(self) -> None:
        self.assertEqual(engage.comment_age_hours("เมื่อสักครู่"), 0)
        self.assertEqual(engage.comment_age_hours("23 ชั่วโมงที่แล้ว"), 23)
        self.assertEqual(engage.comment_age_hours("1 วัน"), 24)
        self.assertEqual(engage.comment_age_hours("2 days ago"), 48)
        self.assertIsNone(engage.comment_age_hours("17 ก.ย. เวลา 08:00"))

    def test_reply_queue_uses_injected_random_choice(self) -> None:
        rows = [{"comment_key": "first"}, {"comment_key": "second"}]
        picked = engage.pick_random_reply(rows, chooser=lambda items: items[-1])
        self.assertEqual(picked["comment_key"], "second")

    def test_reply_cooldown_persists_separately_per_profile(self) -> None:
        with tempfile.TemporaryDirectory() as raw, \
             mock.patch.object(engage, "REPLY_SCHEDULE_FILE",
                               Path(raw) / "reply-schedule.json"):
            scheduled = engage.schedule_next_reply(
                "comment-1", "Profile A", now=1_000, delay_seconds=731)
            profile_a = engage.reply_schedule_status("Profile A", now=1_100)
            profile_b = engage.reply_schedule_status("Profile B", now=1_100)
            ready_a = engage.reply_schedule_status("Profile A", now=1_731)

        self.assertEqual(scheduled["delay_seconds"], 731)
        self.assertEqual(profile_a["wait_seconds"], 631)
        self.assertTrue(profile_a["waiting"])
        self.assertFalse(profile_b["waiting"])
        self.assertFalse(ready_a["waiting"])

    def test_reply_cooldown_rejects_delay_outside_policy(self) -> None:
        with self.assertRaises(ValueError):
            engage.schedule_next_reply(
                "comment-1", "Profile A", now=1_000, delay_seconds=599)

    def test_reply_daily_limit_is_fixed_24_hours_and_separate_per_profile(self) -> None:
        with tempfile.TemporaryDirectory() as raw, \
             mock.patch.object(engage, "DB_FILE", Path(raw) / "engage.sqlite3"):
            conn = engage.open_db()
            try:
                rows = []
                for index in range(1, 52):
                    rows.append((f"a-{index}", "Profile A", index))
                rows.append(("b-1", "Profile B", 100))
                conn.executemany(
                    """INSERT INTO my_comment
                           (comment_key, post_url, account, seq, author, body,
                            when_text, reply_to, is_ours, answered,
                            reply_queued_at, first_seen, last_seen)
                       VALUES (?, 'https://facebook.test/quota', ?, ?, 'Alice',
                               'สนใจ', '', '', 0, 0, 'queued', 'now', 'now')""",
                    rows,
                )
                conn.commit()
            finally:
                conn.close()

            start = 2_000_000_000.0
            for index in range(1, 51):
                engage.mark_reply_result(f"a-{index}", sent=True, now=start + index)
            # เรียกซ้ำคีย์เดิมต้องไม่กินโควตาเป็นครั้งที่ 51
            engage.mark_reply_result("a-50", sent=True, now=start + 100)
            full = engage.reply_daily_status("Profile A", now=start + 100)
            other = engage.reply_daily_status("Profile B", now=start + 100)
            queued = engage.queued_replies(account="Profile A", limit=100)

            self.assertEqual(full["used"], 50)
            self.assertEqual(full["remaining"], 0)
            self.assertTrue(full["waiting"])
            self.assertEqual(other["used"], 0)
            self.assertFalse(other["waiting"])
            self.assertEqual([row["comment_key"] for row in queued], ["a-51"])

            first_sent = start + 1
            before_reset = engage.reply_daily_status(
                "Profile A", now=first_sent + engage.REPLY_DAILY_WINDOW_SECONDS - 1)
            reset = engage.reply_daily_status(
                "Profile A", now=first_sent + engage.REPLY_DAILY_WINDOW_SECONDS)
            self.assertEqual(before_reset["wait_seconds"], 1)
            self.assertEqual(reset["used"], 0)
            self.assertFalse(reset["waiting"])

            next_start = first_sent + engage.REPLY_DAILY_WINDOW_SECONDS
            engage.mark_reply_result("a-51", sent=True, now=next_start)
            restarted = engage.reply_daily_status("Profile A", now=next_start)
            self.assertEqual(restarted["used"], 1)
            self.assertEqual(restarted["window_started_at"], next_start)

            engage.mark_reply_result("b-1", sent=True, now=start + 500)
            self.assertEqual(
                engage.reply_daily_status("Profile B", now=start + 500)["used"], 1)

    def test_mobile_reply_match_requires_full_name_and_same_text(self) -> None:
        row = {"author": "Mamee Sirikarn", "text": "คุ้มมากค่ะ"}
        self.assertTrue(fb_engage.queued_comment_matches(
            row, "Mamee Sirikarn", "คุ้มมากค่ะ"))
        self.assertFalse(fb_engage.queued_comment_matches(
            row, "Mamee", "คุ้มมากค่ะ"))
        self.assertFalse(fb_engage.queued_comment_matches(
            row, "Mamee Sirikarn", "ข้อความอื่น"))

    def test_mobile_parser_keeps_short_comment_for_exact_reply(self) -> None:
        xml = (
            '<hierarchy><node text="" content-desc="รูปโปรไฟล์ของ Mamee Sirikarn" '
            'clickable="true" bounds="[33,1209][143,1319]" />'
            '<node text="คุ้มมากค่ะ" content-desc="คุ้มมากค่ะ" clickable="false" '
            'bounds="[165,1267][343,1327]" />'
            '<node text="" content-desc="ตอบกลับความคิดเห็นของ Mamee, ปุ่ม" '
            'clickable="true" bounds="[143,1333][317,1422]" /></hierarchy>')
        rows = fb_engage.fb.visible_comments(xml)
        self.assertEqual(rows[0]["author"], "Mamee Sirikarn")
        self.assertEqual(rows[0]["text"], "คุ้มมากค่ะ")
        self.assertIsNotNone(rows[0]["reply"])

    def test_mobile_parser_accepts_short_and_english_reply_labels(self) -> None:
        for label in ("ตอบกลับ", "Reply", "Reply to Mamee Sirikarn"):
            xml = (
                '<hierarchy><node text="" content-desc="รูปโปรไฟล์ของ Mamee Sirikarn" '
                'clickable="true" bounds="[33,300][143,410]" />'
                '<node text="สน" content-desc="สน" clickable="false" '
                'bounds="[165,400][500,450]" />'
                f'<node text="" content-desc="{label}" clickable="true" '
                'bounds="[143,455][400,510]" /></hierarchy>')
            self.assertIsNotNone(fb_engage.fb.visible_comments(xml)[0]["reply"])

    def test_mobile_parser_ignores_changing_time_before_comment(self) -> None:
        xml = (
            '<hierarchy><node text="" content-desc="รูปโปรไฟล์ของ Sandy Sand" '
            'clickable="true" bounds="[33,300][143,410]" />'
            '<node text="Sandy Sand" content-desc="Sandy Sand" clickable="false" '
            'bounds="[165,315][500,350]" />'
            '<node text="6 ชม." content-desc="6 ชม." clickable="false" '
            'bounds="[165,355][300,390]" />'
            '<node text="คุ้มมากๆค่ะ" content-desc="คุ้มมากๆค่ะ" clickable="false" '
            'bounds="[165,400][500,450]" />'
            '<node text="" content-desc="ตอบกลับความคิดเห็นของ Sandy, ปุ่ม" '
            'clickable="true" bounds="[143,455][400,510]" /></hierarchy>')
        rows = fb_engage.fb.visible_comments(xml)
        self.assertEqual(rows[0]["author"], "Sandy Sand")
        self.assertEqual(rows[0]["text"], "คุ้มมากๆค่ะ")

    def test_reply_match_uses_only_name_and_real_comment_text(self) -> None:
        row = {"author": "Oon Sudarat", "text": "น่าสนมากค่ะ"}
        self.assertTrue(fb_engage.queued_comment_matches(
            row, "Oon Sudarat", "ติดตาม\nน่าสนมากค่ะ\n1"))

    def test_mobile_parser_removes_avatar_story_status(self) -> None:
        xml = (
            '<hierarchy><node text="" '
            'content-desc="รูปโปรไฟล์ของ Supaporn Kajorn, สตอรี่ที่ยังไม่เห็น" '
            'clickable="true" bounds="[33,300][143,410]" />'
            '<node text="5 ชม." content-desc="5 ชม." clickable="false" '
            'bounds="[165,355][300,390]" />'
            '<node text="น่าสนใจค่ะ" content-desc="น่าสนใจค่ะ" clickable="false" '
            'bounds="[165,400][500,450]" />'
            '<node text="" content-desc="ตอบกลับความคิดเห็นของ Supaporn, ปุ่ม" '
            'clickable="true" bounds="[143,455][400,510]" /></hierarchy>')
        rows = fb_engage.fb.visible_comments(xml)
        self.assertEqual(rows[0]["author"], "Supaporn Kajorn")
        self.assertEqual(rows[0]["text"], "น่าสนใจค่ะ")

    def test_reply_target_marker_must_be_new_and_contain_full_name(self) -> None:
        before = ('<hierarchy><node text="ตอบกลับความคิดเห็นของ Mamee" '
                  'bounds="[0,100][500,200]" /></hierarchy>')
        after = ('<hierarchy><node text="ตอบกลับความคิดเห็นของ Mamee" '
                 'bounds="[0,100][500,200]" />'
                 '<node text="กำลังตอบกลับ Mamee Sirikarn" '
                 'bounds="[0,1800][800,1900]" /></hierarchy>')
        self.assertEqual(
            fb_engage._new_reply_target(before, after, "Mamee Sirikarn"),
            "กำลังตอบกลับ Mamee Sirikarn")
        self.assertEqual(fb_engage._new_reply_target(before, before,
                                                     "Mamee Sirikarn"), "")

    def test_reply_comment_scroll_uses_screen_scaled_phone_helper(self) -> None:
        """สายตอบต้องผ่าน Phone.vswipe; ห้ามใช้ y=1800 กับ ADB โดยตรง."""
        class Phone:
            def __init__(self) -> None:
                self.dumps = 0
                self.swipes = []

            def dump(self) -> str:
                self.dumps += 1
                if self.dumps == 1:
                    return '<hierarchy />'
                return ('<hierarchy><node text="เกี่ยวข้องมากที่สุด" '
                        'bounds="[0,900][700,980]" /></hierarchy>')

            def vswipe(self, *args) -> None:
                self.swipes.append(args)

            def run(self, *_args, **_kwargs):
                raise AssertionError("ห้าม bypass Phone.vswipe ด้วย input swipe ตรง")

        phone = Phone()
        with mock.patch.object(fb_engage.time, "sleep"):
            entered = fb_engage._scroll_into_comments(phone)

        self.assertTrue(entered)
        self.assertEqual(phone.swipes, [
            ("1800", str(1800 - fb_engage.fb.SCROLL_STEP),
             str(fb_engage.fb.SCROLL_DURATION_MS)),
        ])

    def test_reply_target_search_also_uses_screen_scaled_scroll(self) -> None:
        class Phone:
            def __init__(self) -> None:
                self.swipes = []

            def dump(self) -> str:
                return '<hierarchy />'

            def vswipe(self, *args) -> None:
                self.swipes.append(args)

            def run(self, *_args, **_kwargs):
                raise AssertionError("ห้าม bypass Phone.vswipe ด้วย input swipe ตรง")

        phone = Phone()
        with mock.patch.object(fb_engage, "_scroll_into_comments", return_value=True), \
             mock.patch.object(fb_engage.time, "sleep"):
            found, why = fb_engage._find_queued_comment(
                phone, {"author": "Alice", "body": "สนใจ"})

        self.assertIsNone(found)
        self.assertIn("หาแถวของ Alice", why)
        self.assertEqual(phone.swipes, [
            ("1800", str(1800 - fb_engage.fb.SCROLL_STEP),
             str(fb_engage.fb.SCROLL_DURATION_MS)),
        ])

    def test_found_target_is_repositioned_until_its_reply_button_is_visible(self) -> None:
        class Phone:
            def __init__(self) -> None:
                self.swipes = []

            def dump(self) -> str:
                return '<hierarchy />'

            def to_ref_y(self, y) -> float:
                return float(y)

            def vswipe(self, *args) -> None:
                self.swipes.append(args)

        phone = Phone()
        rows = [
            [dict(author='Ruby', text='hello', top=1200, reply=None)],
            [dict(author='Ruby', text='hello', top=850, reply=None)],
            [dict(author='Ruby', text='hello', top=700, reply=(300, 900))],
        ]
        with mock.patch.object(fb_engage, '_scroll_into_comments', return_value=True), \
             mock.patch.object(fb_engage.fb, 'visible_comments', side_effect=rows), \
             mock.patch.object(fb_engage.time, 'sleep'):
            found, why = fb_engage._find_queued_comment(
                phone, {'author': 'Ruby', 'body': 'hello'})
        self.assertEqual(why, '')
        self.assertEqual(found['reply'], (300, 900))
        self.assertEqual(len(phone.swipes), 2)

    def test_found_target_reports_button_not_visible_instead_of_comment_missing(self) -> None:
        class Phone:
            def __init__(self) -> None:
                self.swipes = []

            def dump(self) -> str:
                return '<hierarchy />'

            def to_ref_y(self, y) -> float:
                return float(y)

            def vswipe(self, *args) -> None:
                self.swipes.append(args)

        phone = Phone()
        row = [dict(author='Ruby', text='hello', top=700, reply=None)]
        with mock.patch.object(fb_engage, '_scroll_into_comments', return_value=True), \
             mock.patch.object(fb_engage.fb, 'visible_comments', return_value=row), \
             mock.patch.object(fb_engage.time, 'sleep'):
            found, why = fb_engage._find_queued_comment(
                phone, {'author': 'Ruby', 'body': 'hello'})
        self.assertIsNone(found)
        self.assertIn('พบคอมเมนต์เป้าหมายแล้ว', why)
        self.assertIn('ยังไม่ได้ส่ง', why)
        self.assertEqual(len(phone.swipes), 5)

    def test_same_author_two_comments_marks_only_replied_thread(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(engage.SCHEMA)
        post = {
            "post_url": "https://facebook.test/post/1",
            "group_id": "g1",
            "group_name": "กลุ่มทดสอบ",
            "account": "Profile Owner",
        }
        result = {
            "reachable": True,
            "reactions": 1,
            "comments": 3,
            "shares": 0,
            "comments_list": [
                {"seq": 1, "author": "Alice", "body": "ข้อความแรก",
                 "when_text": "1 ชั่วโมง", "reply_to": ""},
                {"seq": 2, "author": "Profile Owner", "body": "ตอบแล้ว",
                 "when_text": "50 นาที", "reply_to": "Alice"},
                {"seq": 3, "author": "Alice", "body": "ข้อความที่สอง",
                 "when_text": "10 นาที", "reply_to": ""},
            ],
        }

        fresh, _ = engage.save(conn, post, result)
        rows = conn.execute(
            "SELECT body, account, answered FROM my_comment "
            "WHERE is_ours=0 ORDER BY seq").fetchall()

        self.assertEqual(fresh, 1)
        self.assertEqual([(r["body"], r["account"], r["answered"]) for r in rows], [
            ("ข้อความแรก", "Profile Owner", 1),
            ("ข้อความที่สอง", "Profile Owner", 0),
        ])

    def test_save_with_24_hour_scope_excludes_old_and_unknown_comments(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(engage.SCHEMA)
        post = {
            "post_url": "https://facebook.test/post/fresh-only",
            "group_id": "g1",
            "group_name": "กลุ่มทดสอบ",
            "account": "Profile Owner",
        }
        result = {
            "reachable": True,
            "reactions": 1,
            "comments": 3,
            "shares": 0,
            "comments_list": [
                {"seq": 1, "author": "Fresh", "body": "ใหม่",
                 "when_text": "23 ชั่วโมง", "reply_to": ""},
                {"seq": 2, "author": "Boundary", "body": "ครบหนึ่งวัน",
                 "when_text": "1 วัน", "reply_to": ""},
                {"seq": 3, "author": "Old", "body": "เก่า",
                 "when_text": "2 วัน", "reply_to": ""},
                {"seq": 4, "author": "Unknown", "body": "อ่านเวลาไม่ได้",
                 "when_text": "17 ก.ย. เวลา 08:00", "reply_to": ""},
            ],
        }

        fresh, total = engage.save(
            conn, post, result, max_comment_age_hours=24)
        bodies = [row[0] for row in conn.execute(
            "SELECT body FROM my_comment ORDER BY seq").fetchall()]

        self.assertEqual(fresh, 2)
        self.assertEqual(total, 2)
        self.assertEqual(bodies, ["ใหม่", "ครบหนึ่งวัน"])

    def test_six_hour_rescan_refreshes_metadata_and_merges_legacy_duplicates(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(engage.SCHEMA)
        url = "https://facebook.test/post/refresh"
        conn.executemany(
            """INSERT INTO my_comment
                   (comment_key, post_url, account, seq, author, body, when_text,
                    reply_to, is_ours, answered, reply_draft, reply_saved_at,
                    reply_sent_at, reply_queued_at, reply_attempted_at,
                    reply_error, ignored, ignored_at, first_seen, last_seen)
               VALUES (?, ?, 'Profile Owner', ?, 'Alice', ?, ?, '', 0, ?, ?,
                       ?, ?, ?, '', '', 0, '', '2026-09-16', '2026-09-16')""",
            [
                ("clean", url, 1, "น่าสนใจค่ะ", "7 นาที", 0,
                 "", "", "", ""),
                ("dirty", url, 9, "ติดตาม\nน่าสนใจค่ะ\n1", "47 นาที", 1,
                 "ตอบแล้ว", "2026-09-16 10:00:00",
                 "2026-09-16 10:01:00", "2026-09-16 09:59:00"),
            ],
        )
        conn.commit()
        post = {
            "post_url": url, "group_id": "g1", "group_name": "กลุ่มทดสอบ",
            "account": "Profile Owner",
        }
        result = {
            "reachable": True, "reactions": 5, "comments": 1, "shares": 0,
            "comments_list": [{
                "seq": 3, "author": "Alice", "body": "ติดตาม\nน่าสนใจค่ะ\n2",
                "when_text": "2 วัน", "reply_to": "",
            }],
        }

        fresh, total = engage.save(conn, post, result)
        rows = conn.execute(
            "SELECT * FROM my_comment WHERE post_url=?", (url,)).fetchall()

        self.assertEqual((fresh, total), (0, 1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["body"], "น่าสนใจค่ะ")
        self.assertEqual(rows[0]["when_text"], "2 วัน")
        self.assertEqual(rows[0]["seq"], 3)
        self.assertEqual(rows[0]["answered"], 1)
        self.assertEqual(rows[0]["reply_draft"], "ตอบแล้ว")
        self.assertEqual(rows[0]["reply_sent_at"], "2026-09-16 10:01:00")
        self.assertTrue(result["comments_list"][0]["_answered"])

    def test_successful_refresh_replaces_old_comment_snapshot(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(engage.SCHEMA)
        url = "https://facebook.test/post/snapshot"
        conn.executemany(
            """INSERT INTO my_comment
                   (comment_key, post_url, account, seq, author, body, when_text,
                    reply_to, is_ours, answered, first_seen, last_seen)
               VALUES (?, ?, 'Profile Owner', ?, ?, ?, '', '', 0, 0,
                       '2026-09-19', '2026-09-19')""",
            [
                ("old-10h", url, 1, "Alice 10 hours ago", "Alice\nสนใจค่ะ"),
                ("old-12h", url, 2, "Alice 12 hours ago", "Alice\nสนใจค่ะ"),
                ("current", url, 3, "Alice", "สนใจค่ะ"),
            ],
        )
        conn.commit()
        post = {
            "post_url": url, "group_id": "g1", "group_name": "กลุ่มทดสอบ",
            "account": "Profile Owner",
        }
        result = {
            "reachable": True, "reactions": 1, "comments": 1, "shares": 0,
            "comments_snapshot_complete": True,
            "comments_list": [{
                "seq": 1, "author": "Alice", "body": "สนใจค่ะ",
                "when_text": "12 ชั่วโมง", "reply_to": "",
            }],
        }

        engage.save(conn, post, result)
        rows = conn.execute(
            "SELECT comment_key, author, body, when_text FROM my_comment "
            "WHERE post_url=?", (url,)).fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["comment_key"], "current")
        self.assertEqual(rows[0]["author"], "Alice")
        self.assertEqual(rows[0]["body"], "สนใจค่ะ")
        self.assertEqual(rows[0]["when_text"], "12 ชั่วโมง")

    def test_failed_comment_read_keeps_previous_snapshot(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(engage.SCHEMA)
        url = "https://facebook.test/post/incomplete"
        conn.execute(
            """INSERT INTO my_comment
                   (comment_key, post_url, account, seq, author, body, when_text,
                    reply_to, is_ours, answered, first_seen, last_seen)
               VALUES ('kept', ?, 'Profile Owner', 1, 'Alice', 'ยังอยู่', '', '',
                       0, 0, '2026-09-19', '2026-09-19')""", (url,))
        conn.commit()
        post = {
            "post_url": url, "group_id": "g1", "group_name": "กลุ่มทดสอบ",
            "account": "Profile Owner",
        }
        result = {
            "reachable": True, "reactions": 1, "comments": 1, "shares": 0,
            "comments_snapshot_complete": False, "comments_list": [],
        }

        engage.save(conn, post, result)

        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM my_comment WHERE post_url=?", (url,)
        ).fetchone()[0], 1)

    def test_reply_from_other_profile_does_not_hide_comment(self) -> None:
        items = [
            {"author": "Alice", "reply_to": ""},
            {"author": "Different Profile", "reply_to": "Alice"},
        ]
        self.assertEqual(engage._answered_comment_indexes(items, "Profile Owner"), set())

    def test_threads_group_count_includes_only_active_watches(self) -> None:
        with tempfile.TemporaryDirectory() as raw, \
             mock.patch.object(engage, "DB_FILE", Path(raw) / "engage.sqlite3"), \
             mock.patch.object(engage, "_post_meta_by_link", return_value={}):
            conn = engage.open_db()
            try:
                for index in (1, 2):
                    conn.execute(
                        """INSERT INTO my_post
                               (post_url, group_id, group_name, account, reactions,
                                comments, shares, reachable, note, checked_at)
                           VALUES (?, 'same-group', 'กลุ่มเดียวกัน', 'Profile Owner',
                                   1, 0, 0, 1, '', ?)""",
                        (f"https://facebook.test/group/post-{index}",
                         f"2026-09-18T10:0{index}:00"),
                    )
                conn.execute(
                    """INSERT INTO post_watch
                           (post_url, active, stopped_at, stopped_by)
                       VALUES ('https://facebook.test/group/post-2', 0,
                               '2026-09-18T11:00:00', 'test')"""
                )
                conn.commit()
            finally:
                conn.close()

            rows = engage.threads(limit=20, only_pending=False,
                                  account="Profile Owner")

        self.assertEqual(len(rows), 2)
        self.assertEqual({row["group_id"] for row in rows}, {"same-group"})
        self.assertEqual({row["group_total_posts"] for row in rows}, {2})
        self.assertEqual({row["group_active_posts"] for row in rows}, {1})

    def test_date_scope_excludes_older_jobs_and_last_link_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            account_dir = Path(raw)
            (account_dir / "fb_groups.json").write_text(json.dumps([
                {"group_id": "g1", "name": "กลุ่มหนึ่ง",
                 "last_link": "https://facebook.test/old-last"},
            ]), encoding="utf-8")
            (account_dir / "fb_jobs.json").write_text(json.dumps([
                {"id": "old", "created_at": "2026-09-15T09:00:00",
                 "caption": "เก่า", "results": [
                     {"group_id": "g1", "link": "https://facebook.test/old"}]},
                {"id": "today", "created_at": "2026-09-16T09:00:00",
                 "caption": "วันนี้", "results": [
                     {"group_id": "g1", "link": "https://facebook.test/today"}]},
            ]), encoding="utf-8")
            with mock.patch.object(engage.shared, "known_accounts",
                                   return_value=["Profile Owner"]), \
                 mock.patch.object(engage.shared, "account_dir",
                                   return_value=account_dir), \
                 mock.patch.object(engage, "watched_accounts",
                                   return_value=["Profile Owner"]):
                rows = engage.our_posts(on_date="2026-09-16")

        self.assertEqual([r["post_url"] for r in rows],
                         ["https://facebook.test/today"])
        self.assertEqual(rows[0]["account"], "Profile Owner")


if __name__ == "__main__":
    unittest.main()
