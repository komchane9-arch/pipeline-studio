import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

# Isolate imports, logs and state from the running studio.
_root = tempfile.TemporaryDirectory(prefix="reply-quota-test-")
os.environ["STUDIO_DATA_DIR"] = _root.name
os.environ["STUDIO_POST_STATE_DIR"] = _root.name + "/post-state"

import app
import fb_engage
import phone_queue
import facebook_group_post as fb


class ReplyQuotaWaitTests(unittest.TestCase):
    def test_unconfirmed_submission_still_starts_send_gap(self):
        item = {"comment_key": "key", "account": "test", "author": "person", "post_url": "test"}
        with mock.patch.object(app, '_fb_comment_priority_status', return_value={'blocked': False}), \
             mock.patch('fb_engagement.queued_replies', return_value=[item]), \
             mock.patch.object(app, '_fb_reply_schedule_status', return_value={'waiting': False}), \
             mock.patch('fb_engagement.reply_daily_status', return_value={'waiting': False}), \
             mock.patch.object(fb_engage, 'run_queued_reply', return_value={'sent': False, 'error': 'unconfirmed'}), \
             mock.patch('fb_engagement.mark_reply_result', return_value={}), \
             mock.patch('fb_engagement.reply_states', return_value=[{'reply_submitted_at': 'receipt'}]), \
             mock.patch('fb_engagement.schedule_next_reply', return_value={'wait_seconds': 700, 'next_at_text': 'later'}) as schedule:
            result = app._run_one_fb_reply(send=True)
        self.assertFalse(result['sent'])
        schedule.assert_called_once_with('key', 'test')
        self.assertEqual(result['wait_seconds'], 700)

    def test_live_phone_ticket_waits_without_failed_delivery_or_quota(self):
        item = {"comment_key": "key", "account": "test", "author": "person", "post_url": "test"}
        with mock.patch.object(app, '_fb_comment_priority_status', return_value={'blocked': False}), \
             mock.patch('fb_engagement.queued_replies', return_value=[item]), \
             mock.patch.object(app, '_fb_reply_schedule_status', return_value={'waiting': False}), \
             mock.patch('fb_engagement.reply_daily_status', return_value={'waiting': False}), \
             mock.patch.object(fb_engage, 'run_queued_reply', side_effect=phone_queue.QueueBusy('ticket 3320 running')), \
             mock.patch('fb_engagement.mark_reply_result') as mark, \
             mock.patch('fb_engagement.schedule_next_reply') as schedule:
            result = app._run_one_fb_reply(send=True)
        self.assertTrue(result['waiting'])
        self.assertFalse(result['sent'])
        self.assertEqual(result['reason'], 'phone_busy')
        mark.assert_not_called()
        schedule.assert_not_called()

    def test_other_queue_errors_are_not_silently_retried(self):
        item = {"comment_key": "key", "account": "test", "author": "person", "post_url": "test"}
        with mock.patch.object(app, '_fb_comment_priority_status', return_value={'blocked': False}), \
             mock.patch('fb_engagement.queued_replies', return_value=[item]), \
             mock.patch.object(app, '_fb_reply_schedule_status', return_value={'waiting': False}), \
             mock.patch('fb_engagement.reply_daily_status', return_value={'waiting': False}), \
             mock.patch.object(fb_engage, 'run_queued_reply', side_effect=phone_queue.QueueError('invalid queue')), \
             mock.patch('fb_engagement.mark_reply_result', return_value={}) as mark:
            result = app._run_one_fb_reply(send=True)
        self.assertFalse(result.get('waiting', False))
        self.assertIn('invalid queue', result['error'])
        mark.assert_called_once()

    def test_submitted_verification_can_run_during_sending_hold(self):
        item = {"comment_key": "test-key", "account": "test", "author": "person", "post_url": "test", "reply_submitted_at": "receipt"}
        with mock.patch.object(app, '_fb_comment_priority_status', return_value={'blocked':False}), \
             mock.patch('fb_engagement.queued_replies', return_value=[item]), \
             mock.patch.object(app, '_fb_reply_schedule_status', return_value={'waiting':True, 'wait_seconds':3600}), \
             mock.patch('fb_engagement.reply_daily_status', return_value={'waiting':True, 'wait_seconds':3600}), \
             mock.patch.object(fb_engage, 'run_queued_reply', return_value={'sent':False, 'verification_only':True}) as run, \
             mock.patch('fb_engagement.mark_reply_result', return_value={}):
            result = app._run_one_fb_reply(send=True)
        self.assertTrue(result['verification_only'])
        self.assertTrue(run.call_args.args[0]['reply_submitted_at'])

    def test_successful_verification_does_not_create_new_send_cooldown(self):
        item = {"comment_key": "test-key", "account": "test", "author": "person",
                "post_url": "test", "reply_submitted_at": "receipt"}
        with mock.patch.object(app, '_fb_comment_priority_status', return_value={'blocked':False}), \
             mock.patch('fb_engagement.queued_replies', return_value=[item]), \
             mock.patch.object(app, '_fb_reply_schedule_status', return_value={'waiting':False}), \
             mock.patch('fb_engagement.reply_daily_status', return_value={'waiting':False}), \
             mock.patch.object(fb_engage, 'run_queued_reply',
                               return_value={'sent':True, 'verification_only':True}), \
             mock.patch('fb_engagement.mark_reply_result', return_value={}), \
             mock.patch('fb_engagement.schedule_next_reply') as schedule:
            result = app._run_one_fb_reply(send=True)
        self.assertTrue(result['sent'])
        schedule.assert_not_called()

    def test_platform_hold_cannot_be_bypassed_by_manual_hourly_override(self):
        with mock.patch.object(fb_engage.devices, 'device_for_account', return_value='serial'), \
             mock.patch.object(fb_engage.fb_auto_post, 'use_account'), \
             mock.patch.object(fb.fb_comment_guard, 'load', return_value={}), \
             mock.patch.object(fb.fb_comment_guard, '_held_until', return_value=datetime.now()+timedelta(hours=12)), \
             mock.patch.object(fb.fb_comment_guard, 'hold_reason', return_value='Facebook restriction'), \
             mock.patch.object(fb, 'comment_quota_left', return_value=99) as quota:
            result = fb_engage.reply_quota_status('test')
        self.assertTrue(result['waiting'])
        self.assertEqual(result['reason'], 'safety_hold')
        quota.assert_not_called()

    def test_other_lane_waits_until_last_post_expires(self):
        with mock.patch.object(fb, "comment_quota_left", return_value=0), \
             mock.patch.object(fb, "lane_owning_hour", return_value="post"), \
             mock.patch.object(fb, "_comment_times", side_effect=lambda lane: [500, 900] if lane == "post" else []), \
             mock.patch.object(fb, "_all_comment_times", return_value=[500, 900]), \
             mock.patch.object(fb, "comment_limit_per_hour", return_value=12), \
             mock.patch.object(fb.time, "time", return_value=1000):
            self.assertEqual(fb.comment_quota_resets_in("reply", "device"), 3500)

    def test_quota_wait_does_not_mark_reply_failed(self):
        item = {"comment_key": "test-key", "account": "test", "author": "person", "post_url": "test"}
        with mock.patch.object(app, "_fb_comment_priority_status", return_value={"blocked": False}), \
             mock.patch("fb_engagement.queued_replies", return_value=[item]), \
             mock.patch.object(app, "_fb_reply_schedule_status", return_value={"waiting": False}), \
             mock.patch("fb_engagement.reply_daily_status", return_value={"waiting": False}), \
             mock.patch.object(fb_engage, "run_queued_reply", return_value={"waiting": True, "sent": False, "wait_seconds": 60}), \
             mock.patch("fb_engagement.mark_reply_result") as mark:
            result = app._run_one_fb_reply(send=True)
        self.assertTrue(result["waiting"])
        mark.assert_not_called()

    def test_preflight_quota_wait_never_opens_phone(self):
        item = {"account": "test", "author": "person", "reply_draft": "answer"}
        with mock.patch.object(fb_engage.devices, "device_for_account", return_value="serial"), \
             mock.patch.object(fb_engage.devices, "account", return_value="test"), \
             mock.patch.object(fb_engage, "reply_quota_status", return_value={"waiting": True, "wait_seconds": 60}), \
             mock.patch.object(fb, "Phone") as phone:
            self.assertTrue(fb_engage.run_queued_reply(item, send=True)["waiting"])
        phone.assert_not_called()


if __name__ == "__main__":
    unittest.main()
