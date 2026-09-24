import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import fb_engagement as store


class RetrySavedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(store, 'DB_FILE', Path(self.temp.name)/'db.sqlite')
        self.patch.start()
        self.conn = store.open_db()
        self.conn.execute("INSERT INTO my_comment (comment_key,post_url,account,author,body,reply_draft,reply_error,first_seen,last_seen) VALUES ('key','https://www.facebook.com/share/p/test/','Preaw','Demi','hello','saved answer','timeout','now','now')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.patch.stop()
        self.temp.cleanup()

    def test_retry_keeps_saved_draft_and_repeated_click_is_idempotent(self):
        first = store.retry_saved_reply('key', 'Preaw')
        second = store.retry_saved_reply('key', 'Preaw')
        row = self.conn.execute('SELECT * FROM my_comment').fetchone()
        self.assertEqual(first['reply_queued_at'], second['reply_queued_at'])
        self.assertEqual(row['reply_draft'], 'saved answer')
        self.assertEqual(row['reply_error'], '')
        self.assertFalse(row['reply_sent_at'])
        self.assertEqual(store.reply_daily_status('Preaw')['used'], 0)

    def test_submitted_can_only_verify_and_success_never_requeues(self):
        store.mark_reply_submitted('key')
        result = store.retry_saved_reply('key', 'Preaw')
        self.assertTrue(result['verification_only'])
        self.assertTrue(result['reply_submitted_at'])
        store.mark_reply_result('key', True)
        result = store.retry_saved_reply('key', 'Preaw')
        self.assertTrue(result['reply_sent_at'])
        self.assertEqual(store.queued_replies(account='Preaw'), [])
        self.assertEqual(store.reply_daily_status('Preaw')['used'], 1)

    def test_wrong_account_and_missing_draft_fail_without_mutation(self):
        with self.assertRaises(ValueError):
            store.retry_saved_reply('key', 'Khao Fang')
        self.conn.execute("UPDATE my_comment SET reply_draft='' WHERE comment_key='key'")
        self.conn.commit()
        with self.assertRaises(ValueError):
            store.retry_saved_reply('key', 'Preaw')
        self.assertEqual(self.conn.execute('SELECT reply_error FROM my_comment').fetchone()[0], 'timeout')

    def test_restart_recovers_once_and_keeps_receipt(self):
        store.retry_saved_reply('key', 'Preaw')
        store.mark_reply_submitted('key')
        receipt = self.conn.execute('SELECT reply_submitted_at FROM my_comment').fetchone()[0]
        self.assertEqual(store.recover_interrupted_reply_checks(), 1)
        row = store.queued_replies(account='Preaw')[0]
        self.assertEqual(row['reply_submitted_at'], receipt)
        self.assertEqual(store.recover_interrupted_reply_checks(), 0)
        store.mark_reply_result('key', False, 'reply_not_in_thread')
        self.assertEqual(store.recover_interrupted_reply_checks(), 0)
        self.assertEqual(store.queued_replies(account='Preaw'), [])

    def test_failed_check_preserves_original_restriction(self):
        store.mark_reply_submitted('key')
        store.mark_reply_result('key', False, 'FacebookRestricted: limited')
        store.mark_reply_result('key', False, 'reply_not_in_thread')
        error = self.conn.execute('SELECT reply_error FROM my_comment').fetchone()[0]
        self.assertIn('FacebookRestricted: limited', error)
        self.assertIn('reply_not_in_thread', error)

    def test_delete_notice_keeps_history_but_removes_item_from_worker_queue(self):
        store.retry_saved_reply('key', 'Preaw')
        self.assertEqual(len(store.queued_replies(account='Preaw')), 1)
        store.ignore_comment('key', True)
        self.assertEqual(store.queued_replies(account='Preaw'), [])
        row = self.conn.execute(
            'SELECT ignored, reply_draft, reply_queued_at FROM my_comment WHERE comment_key=?',
            ('key',)).fetchone()
        self.assertEqual(row['ignored'], 1)
        self.assertEqual(row['reply_draft'], 'saved answer')
        self.assertTrue(row['reply_queued_at'])

if __name__ == '__main__':
    unittest.main()
