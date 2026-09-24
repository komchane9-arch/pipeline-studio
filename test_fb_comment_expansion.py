import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import fb_engagement as eg


class Node:
    def __init__(self, holder, label="View more comments"):
        self.holder, self.label = holder, label

    def is_visible(self):
        return True

    def inner_text(self):
        return self.label

    def get_attribute(self, name):
        return "Comment by Alice"

    def scroll_into_view_if_needed(self, **kwargs):
        pass

    def click(self, **kwargs):
        if self.holder.fail:
            raise RuntimeError("click failed")
        self.holder.pending = True


class Holder:
    def __init__(self, delay=6, pages=1, fail=False):
        self.delay, self.pages, self.fail = delay, pages, fail
        self.pending, self.ticks, self.loaded = False, 0, 0

    def query_selector_all(self, selector):
        if selector == 'div[role="article"]':
            return [Node(self, str(i)) for i in range(self.loaded + 1)]
        if 'progressbar' in selector:
            return [Node(self)] if self.pending else []
        return [Node(self)] if self.loaded < self.pages else []

    def evaluate(self, js):
        pass

    def wait_for_timeout(self, ms):
        if self.pending:
            self.ticks += 1
            if self.ticks >= self.delay:
                self.loaded += 1
                self.pending, self.ticks = False, 0


class ExpansionTests(unittest.TestCase):
    def test_reads_foreground_dialog_not_same_caption_in_background(self):
        page, dialog, background = MagicMock(), MagicMock(), MagicMock()
        page.url = 'https://facebook.test/groups/g/posts/p'
        dialog.is_visible.return_value = True
        dialog.inner_text.return_value = 'caption target'
        dialog.query_selector_all.return_value = []
        page.query_selector_all.side_effect = lambda selector: (
            [dialog] if selector == 'div[role="dialog"]' else [background])
        with patch.object(eg, 'expand_hidden', return_value={'complete': True}) as expand:
            result = eg.read_post(page, page.url, expect='caption target')
        self.assertTrue(result['comments_snapshot_complete'])
        self.assertIs(expand.call_args.args[0], dialog)
        background.inner_text.assert_not_called()

    def test_waits_for_delayed_response_and_more_than_old_click_limit(self):
        holder = Holder(pages=15)
        result = eg.expand_hidden(holder, holder, detailed=True)
        self.assertTrue(result['complete'])
        self.assertEqual(result['clicked'], 15)

    def test_advertised_count_exceeds_loaded_comments_is_incomplete(self):
        page, dialog, comment = MagicMock(), MagicMock(), MagicMock()
        page.url = 'https://facebook.test/groups/g/posts/p'
        dialog.is_visible.return_value = True
        dialog.inner_text.return_value = 'caption target\n6 comments'
        comment.get_attribute.return_value = 'Comment by Alice on 1 hour ago'
        comment.inner_text.return_value = 'Alice\nhello'
        dialog.query_selector_all.side_effect = lambda selector: (
            [comment] if selector == 'div[role="article"]' else [])
        page.query_selector_all.return_value = [dialog]
        with patch.object(eg, 'expand_hidden', return_value={'complete': True}):
            result = eg.read_post(page, page.url, expect='caption target')
        self.assertFalse(result['comments_snapshot_complete'])
        self.assertIn('เก็บยังไม่ครบ', result['note'])
        self.assertEqual(result['comments'], 6)

    def test_click_failure_is_not_complete(self):
        holder = Holder(fail=True)
        self.assertFalse(eg.expand_hidden(holder, holder, detailed=True)['complete'])

    def test_timeout_is_not_complete(self):
        holder = Holder(delay=100)
        self.assertFalse(eg.expand_hidden(holder, holder, detailed=True)['complete'])

    def test_partial_refresh_preserves_rows_and_metrics_then_complete_replaces(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(eg, 'DB_FILE', Path(temp)/'test.db'):
            conn = eg.open_db()
            post = dict(post_url='post', account='Owner', group_id='g', group_name='Group')
            comments = [dict(seq=i, author=f'Person{i}', body='hello', when_text='', reply_to='')
                        for i in range(4)]
            initial = dict(reachable=True, comments_snapshot_complete=True,
                           comments_list=comments, comments=4, reactions=10, shares=1)
            eg.save(conn, post, initial)
            before = [tuple(row) for row in conn.execute('SELECT * FROM my_comment')]
            partial = dict(initial, comments_snapshot_complete=False, comments_list=comments[:3], comments=3)
            eg.save(conn, post, partial)
            self.assertEqual(before, [tuple(row) for row in conn.execute('SELECT * FROM my_comment')])
            latest = conn.execute('SELECT comments,note FROM my_post ORDER BY id DESC LIMIT 1').fetchone()
            self.assertEqual(latest['comments'], 4)
            self.assertIn('เก็บยังไม่ครบ', latest['note'])
            eg.save(conn, post, dict(partial, comments_snapshot_complete=True))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM my_comment').fetchone()[0], 3)
            conn.close()


if __name__ == '__main__':
    unittest.main()
