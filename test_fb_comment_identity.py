import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fb_engagement as store
import fb_engage
import facebook_group_post as fb


class CommentIdentityTests(unittest.TestCase):
    def test_manual_label_requires_single_post_header_and_owner(self):
        xml = '<hierarchy><node text="Khao Fang Nichapa" bounds="[0,100][100,200]"/><node content-desc="โพสต์ของ Khao Fang Nichapa" bounds="[0,0][100,50]"/></hierarchy>'
        self.assertTrue(fb._post_identity_visible(xml, 'Khao Fang Nichapa', 'ลิงก์ที่สั่งเก็บ 2'))
        self.assertFalse(fb._post_identity_visible(xml.replace('โพสต์ของ Khao Fang Nichapa', 'ฟีด'), 'Khao Fang Nichapa', 'ลิงก์ที่สั่งเก็บ 2'))
        self.assertFalse(fb._post_identity_visible(xml, 'Different Owner', 'ลิงก์ที่สั่งเก็บ 2'))
        self.assertFalse(fb._post_identity_visible(xml, 'Khao Fang Nichapa', 'Real Group'))

    def test_english_relative_time_is_not_name(self):
        for label in ('Comment by สมบูรณ์ วรรณใส 12 hours ago',
                      'ความคิดเห็นจาก สมบูรณ์ วรรณใส 12 hours ago'):
            self.assertEqual(store.parse_comment_label(label), dict(
                author='สมบูรณ์ วรรณใส', reply_to='', when_text='12 hours ago'))
        self.assertEqual(store.parse_comment_label('Comment by Alice on Monday')['when_text'], 'Monday')
        self.assertEqual(store.parse_comment_label('Comment by Khun Rose a day ago'), dict(
            author='Khun Rose', reply_to='', when_text='a day ago'))
        self.assertEqual(store.split_comment_author('Studio 54'), ('Studio 54', ''))
        self.assertEqual(store.split_comment_author('Alice 12 hours'), ('Alice 12 hours', ''))

    def test_indefinite_english_age_is_removed_from_legacy_identity(self):
        old = dict(author='Khun Rose a day ago', body='Khun Rose\nใช้ดีมาก',
                   when_text='')
        clean = store.normalize_comment_identity(old)
        self.assertEqual(clean['author'], 'Khun Rose')
        self.assertEqual(clean['body'], 'ใช้ดีมาก')
        self.assertEqual(clean['when_text'], 'a day ago')
        self.assertEqual(store.comment_age_hours(clean['when_text']), 24)

    def test_reply_label_and_legacy_body(self):
        self.assertEqual(store.parse_comment_label("Reply by Owner to Alice's comment 2 hours ago"),
                         dict(author='Owner', reply_to='Alice', when_text='2 hours ago'))
        old = dict(author='Alice 12 hours ago', body='Alice\nสนใจ', comment_key='unchanged',
                   reply_draft='answer', reply_submitted_at='receipt')
        clean = store.normalize_comment_identity(old)
        self.assertEqual(clean['author'], 'Alice')
        self.assertEqual(clean['body'], 'สนใจ')
        self.assertEqual(clean['comment_key'], old['comment_key'])
        self.assertEqual(clean['reply_submitted_at'], 'receipt')
        self.assertTrue(fb_engage.queued_comment_matches(dict(author='Alice', text='สนใจ'), clean['author'], clean['body']))

    def test_refresh_keeps_original_key_and_draft(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DB_FILE', Path(temp)/'db.sqlite3'):
            conn = store.open_db()
            conn.execute("INSERT INTO my_comment (comment_key,post_url,account,author,body,first_seen,last_seen,reply_draft,reply_queued_at,is_ours,answered) VALUES ('old','post','Owner','Alice 12 hours ago','Alice\nสนใจ','old','old','answer','old',0,0)")
            conn.commit()
            store.save(conn, dict(post_url='post',account='Owner',group_id='g',group_name='G'),
                       dict(reachable=True, comments_snapshot_complete=True, comments_list=[
                           dict(author='Alice 13 hours ago',body='Alice\nสนใจ',seq=1)]))
            rows = conn.execute('SELECT * FROM my_comment').fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['comment_key'], 'old')
            self.assertEqual(rows[0]['author'], 'Alice')
            self.assertEqual(rows[0]['reply_draft'], 'answer')
            conn.close()

    def test_duplicate_new_comment_in_one_snapshot_has_complete_state(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
                store, 'DB_FILE', Path(temp) / 'db.sqlite3'):
            conn = store.open_db()
            item = dict(author='Alice', body='สนใจ', seq=1)
            fresh, total = store.save(
                conn,
                dict(post_url='post', account='Owner', group_id='g', group_name='G'),
                dict(reachable=True, comments_snapshot_complete=True,
                     comments_list=[dict(item), dict(item)]),
            )
            rows = conn.execute('SELECT * FROM my_comment').fetchall()
            self.assertEqual((fresh, total), (1, 2))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['followup_sent_at'], '')
            conn.close()

    def test_save_failure_rolls_back_writer_lock(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
                store, 'DB_FILE', Path(temp) / 'db.sqlite3'):
            conn = store.open_db()

            def fail_after_write(connection, *_args, **_kwargs):
                connection.execute(
                    "INSERT INTO my_post "
                    "(post_url,group_id,group_name,account,reachable,checked_at) "
                    "VALUES ('locked','g','G','Owner',1,'now')")
                raise KeyError('followup_sent_at')

            with patch.object(store, '_save_unprotected', side_effect=fail_after_write):
                with self.assertRaises(KeyError):
                    store.save(conn, {}, {})
            other = store.open_db()
            other.execute('BEGIN IMMEDIATE')
            other.rollback()
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM my_post WHERE post_url='locked'").fetchone()[0],
                0,
            )
            other.close()
            conn.close()

    def test_repeated_open_is_read_only_while_another_writer_is_active(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
                store, 'DB_FILE', Path(temp) / 'db.sqlite3'):
            first = store.open_db()
            first.close()
            blocker = store.sqlite3.connect(store.DB_FILE)
            blocker.execute('PRAGMA journal_mode=WAL')
            blocker.execute('BEGIN IMMEDIATE')
            original_connect = store.sqlite3.connect

            def quick_connect(database, **kwargs):
                return original_connect(database, timeout=0.05)

            with patch.object(store.sqlite3, 'connect', side_effect=quick_connect):
                reader = store.open_db()
                self.assertEqual(reader.execute('SELECT COUNT(*) FROM my_post').fetchone()[0], 0)
                reader.close()
            blocker.rollback()
            blocker.close()


if __name__ == '__main__':
    unittest.main()
