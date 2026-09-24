import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch
from xml.sax.saxutils import escape

import fb_reply_safe as safe
import fb_engage
import fb_engagement as store


ITEM = dict(author='Anurak Wongsawad', account='Preaw Buchakorn',
            body='คุ้มเลยย', reply_draft='ตามมาเลยยยยย', comment_key='key')


def field(text):
    return '<hierarchy><node text="กำลังตอบกลับ Anurak Wongsawad" bounds="[0,0][100,100]" /><node class="android.widget.EditText" focused="true" text="' + escape(text) + '" /></hierarchy>'


class ReplySafeTests(unittest.TestCase):
    def test_scroll_before_expansion_does_not_exhaust_child_visibility(self):
        phone = MagicMock()
        phone.dump.return_value = '<hierarchy/>'
        with patch.object(safe, 'verified_reply', side_effect=[False, False, False, True]), \
             patch.object(safe, 'target_reply_expander', side_effect=[None, (100, 200)]), \
             patch.object(safe.time, 'sleep'):
            self.assertTrue(safe.verify_on_phone(phone, ITEM))
        self.assertEqual(phone.vswipe.call_count, 2)
        phone.tap.assert_called_once_with((100, 200))

    def test_platform_restriction_stops_verification_and_records_hold(self):
        xml = '<hierarchy><node text="คุณไม่สามารถใช้ฟีเจอร์นี้ได้ในขณะนี้" /></hierarchy>'
        phone = MagicMock()
        phone.dump.return_value = xml
        with patch.object(safe.fb.fb_comment_guard, 'note_failure') as failure, \
             patch.object(safe, 'verified_reply') as verified:
            with self.assertRaises(safe.FacebookRestricted):
                safe.verify_on_phone(phone, ITEM)
        failure.assert_called_once_with(xml)
        verified.assert_not_called()
        phone.tap.assert_not_called()
        phone.vswipe.assert_not_called()

    def test_platform_restriction_before_composer_never_types_or_submits(self):
        phone = MagicMock()
        phone.dump.return_value = '<hierarchy><node text="คุณไม่สามารถใช้ฟีเจอร์นี้ได้ในขณะนี้" /></hierarchy>'
        dispatch = MagicMock()
        with patch.object(safe.fb.fb_comment_guard, 'note_failure'), self.assertRaises(safe.FacebookRestricted):
            safe.send_reply(phone, ITEM, dispatch)
        dispatch.assert_not_called()
        phone.type_text.assert_not_called()
        phone.tap.assert_not_called()

    def test_verification_expands_only_target_child_thread(self):
        rows = [dict(author=ITEM['author'], text=ITEM['body'], top=100),
                dict(author='Other', text='hello', top=500)]
        widgets = [([f"ดูการตอบกลับ 1 รายการที่ {ITEM['author']} ได้รับ..."], (50,300,200,340), True),
                   (["ดูการตอบกลับ 1 รายการที่ Other ได้รับ..."], (50,600,200,640), True)]
        with patch.object(safe.fb, 'visible_comments', return_value=rows), \
             patch.object(safe.fb, 'iter_widgets', return_value=widgets):
            self.assertEqual(safe.target_reply_expander('<hierarchy/>', ITEM), (125,320))
            rows[0]['text'] = 'different parent'
            self.assertIsNone(safe.target_reply_expander('<hierarchy/>', ITEM))

    def test_verification_scrolls_toward_new_reply_after_send(self):
        phone = MagicMock()
        phone.dump.return_value = '<hierarchy/>'
        with patch.object(safe, 'verified_reply', side_effect=[False, True]), \
             patch.object(safe, 'target_reply_expander', return_value=None), \
             patch.object(safe.time, 'sleep'):
            self.assertTrue(safe.verify_on_phone(phone, ITEM))
        # Reacquire the parent above the just-posted child before walking down
        # its thread; this preserves the parent/child boundary across screens.
        phone.vswipe.assert_called_once_with('850', '1250', '500')

    def test_inline_mention_does_not_replace_full_comment_text(self):
        rows = [(100, ['จุ๊บ แจง']), (100, ['จุ๊บ แจง  คุ้มมากค่าาาา'])]
        self.assertEqual(safe.fb._comment_text_near(rows, 50, 'Preaw Buchakorn', min_length=1, max_length=None),
                         'จุ๊บ แจง คุ้มมากค่าาาา')
        long_text = 'คำตอบยาว ' * 20
        self.assertEqual(safe.fb._comment_text_near([(100, [long_text])], 50, 'Preaw', min_length=1, max_length=None),
                         long_text.strip())

    def test_facebook_autocomplete_mention_preserves_name_and_answer(self):
        xml = '<hierarchy><node class="android.widget.AutoCompleteTextView" focused="true" text="กล่าวถึง, จุ๊บ แจง, นอกเหนือการกล่าวถึง" /></hierarchy>'
        self.assertEqual(safe.editor(xml), 'จุ๊บ แจง')
        self.assertEqual(safe.composer_plan(safe.editor(xml), 'จุ๊บ แจง', 'คุ้มมากค่าาาา'),
                         (' คุ้มมากค่าาาา', 'จุ๊บ แจง คุ้มมากค่าาาา'))
        typed = xml.replace('นอกเหนือการกล่าวถึง', 'นอกเหนือการกล่าวถึง คุ้มมากค่าาาา')
        self.assertEqual(safe.editor(typed), 'จุ๊บ แจง คุ้มมากค่าาาา')
        actual = xml.replace('นอกเหนือการกล่าวถึง', 'นอกเหนือการกล่าวถึง,  คุ้มมากค่าาาา')
        self.assertEqual(safe.editor(actual), 'จุ๊บ แจง คุ้มมากค่าาาา')
        broken = xml.replace('นอกเหนือการกล่าวถึง', 'นอกเหนือการกล่าวถึง, คุ้มมากค่าาาา')
        self.assertEqual(safe.editor(broken), 'จุ๊บ แจงคุ้มมากค่าาาา')
        with self.assertRaises(ValueError):
            safe.editor(xml.replace('</hierarchy>', '<node class="android.widget.EditText" focused="true" /></hierarchy>'))

    def test_autocomplete_contents_are_not_delivery_evidence(self):
        xml = '<hierarchy><node class="android.widget.AutoCompleteTextView" text="คุ้มมากค่าาาา" content-desc="pending reply" /></hierarchy>'
        with patch.object(safe.fb, 'visible_comments', return_value=[]) as rows:
            self.assertFalse(safe.verified_reply(xml, ITEM))
        self.assertNotIn('คุ้มมากค่าาาา', rows.call_args.args[0])
        self.assertNotIn('pending reply', rows.call_args.args[0])

    def test_queued_reply_starts_from_feed_and_existing_reply_never_types(self):
        import fb_account_guard
        phone = MagicMock()
        phone.dump.return_value = '<hierarchy/>'
        with ExitStack() as stack:
            stack.enter_context(patch.object(fb_engage.devices, 'device_for_account', return_value='phone'))
            stack.enter_context(patch.object(fb_engage.devices, 'account', return_value=ITEM['account']))
            stack.enter_context(patch.object(fb_engage.fb_auto_post, 'use_account'))
            stack.enter_context(patch.object(fb_engage.studio_shared, 'phone_lock'))
            stack.enter_context(patch.object(fb_engage.fb_screen, 'keep_awake_while_working'))
            stack.enter_context(patch.object(fb_engage.fb, 'Phone', return_value=phone))
            stack.enter_context(patch.object(fb_engage.fb, 'require_network'))
            require = stack.enter_context(patch.object(fb_account_guard, 'require'))
            stack.enter_context(patch.object(fb_engage.fb, 'open_post_link', return_value=True))
            stack.enter_context(patch.object(fb_engage, '_find_queued_comment', return_value=({'reply': (20,20)}, '')))
            stack.enter_context(patch.object(safe, 'verified_reply', return_value=True))
            result = fb_engage.run_queued_reply(ITEM, send=False)
        self.assertTrue(result['already_present'])
        self.assertTrue(result['verification_only'])
        self.assertTrue(require.call_args.kwargs['fresh_start'])
        phone.tap.assert_not_called()
        phone.type_text.assert_not_called()

    def test_submitted_reply_verifies_without_requiring_parent_reply_button(self):
        import fb_account_guard
        item = dict(ITEM, reply_submitted_at='2026-09-21T20:42:18')
        phone = MagicMock()
        phone.dump.return_value = '<hierarchy/>'
        with ExitStack() as stack:
            stack.enter_context(patch.object(fb_engage.devices, 'device_for_account', return_value='phone'))
            stack.enter_context(patch.object(fb_engage.devices, 'account', return_value=ITEM['account']))
            stack.enter_context(patch.object(fb_engage.fb_auto_post, 'use_account'))
            stack.enter_context(patch.object(fb_engage.studio_shared, 'phone_lock'))
            stack.enter_context(patch.object(fb_engage.fb_screen, 'keep_awake_while_working'))
            stack.enter_context(patch.object(fb_engage.fb, 'Phone', return_value=phone))
            stack.enter_context(patch.object(fb_engage.fb, 'require_network'))
            stack.enter_context(patch.object(fb_account_guard, 'require'))
            stack.enter_context(patch.object(fb_engage.fb, 'open_post_link', return_value=True))
            finder = stack.enter_context(patch.object(
                fb_engage, '_find_queued_comment', return_value=({'reply': None}, '')))
            stack.enter_context(patch.object(
                safe, 'verify_on_phone_result',
                return_value={'verified': True, 'reason': 'confirmed', 'message': 'ok'}))
            result = fb_engage.run_queued_reply(item, send=True)
        self.assertTrue(result['sent'])
        self.assertTrue(result['verification_only'])
        finder.assert_called_once_with(phone, item, require_reply=False)

    def test_prefix_preserved_and_separated(self):
        self.assertEqual(safe.composer_plan(ITEM['author'], ITEM['author'], ITEM['reply_draft']),
                         (' '+ITEM['reply_draft'], ITEM['author']+' '+ITEM['reply_draft']))
        with self.assertRaises(ValueError):
            safe.composer_plan('Anurak '+ITEM['reply_draft']+' Wongsawad', ITEM['author'], ITEM['reply_draft'])

    def test_wrong_full_text_never_sends(self):
        phone = MagicMock()
        phone.find.return_value = (10, 10)
        phone.dump.side_effect = ['<hierarchy/>', field(ITEM['author']), field('Anurak wrong Wongsawad')]
        dispatch = MagicMock()
        with patch.object(safe.time, 'sleep'), self.assertRaises(ValueError):
            safe.send_reply(phone, ITEM, dispatch)
        dispatch.assert_not_called()
        self.assertEqual(phone.tap.call_count, 1)
        phone.shell.assert_called_once_with('input keyevent 123')

    def test_intent_saved_before_tap_and_timeout_not_retried(self):
        phone = MagicMock()
        phone.find.return_value = (10, 10)
        phone.dump.side_effect = ['<hierarchy/>', field(ITEM['author']),
                                  field(ITEM['author']+' '+ITEM['reply_draft'])]
        events = []
        def tap(point):
            events.append('tap')
            if len(events) > 1:
                raise TimeoutError('unknown delivery')
        phone.tap.side_effect = tap
        with patch.object(safe.time, 'sleep'):
            self.assertFalse(safe.send_reply(phone, ITEM, lambda: events.append('persist')))
        self.assertEqual(events, ['tap', 'persist', 'tap'])

    def test_verification_requires_owner_parent_full_body_and_indentation(self):
        rows = [dict(author=ITEM['author'], text=ITEM['body'], top=100),
                dict(author=ITEM['account'], text=ITEM['author']+' '+ITEM['reply_draft'], top=200, reply=None)]
        widgets = [([safe.fb.AVATAR_PREFIX+ITEM['author']], (10,100,50,150), True),
                   ([safe.fb.AVATAR_PREFIX+ITEM['account']], (60,200,100,250), True)]
        with patch.object(safe.fb, 'visible_comments', return_value=rows), \
             patch.object(safe.fb, 'iter_widgets', return_value=widgets):
            self.assertTrue(safe.verified_reply('<hierarchy/>', ITEM))
            rows[1]['text'] += ' bad'
            self.assertFalse(safe.verified_reply('<hierarchy/>', ITEM))
            rows[1]['text'] = ITEM['reply_draft']
            rows[1]['author'] = 'Someone else'
            self.assertFalse(safe.verified_reply('<hierarchy/>', ITEM))
            rows[1]['author'] = ITEM['account']
            widgets[1] = (widgets[1][0], (10,200,50,250), True)
            self.assertFalse(safe.verified_reply('<hierarchy/>', ITEM))

    def test_verification_carries_parent_boundary_across_viewports(self):
        parent_rows = [dict(author=ITEM['author'], text=ITEM['body'], top=100)]
        child_rows = [dict(author=ITEM['account'], text=ITEM['reply_draft'],
                           top=100, reply=None)]
        parent_widgets = [([safe.fb.AVATAR_PREFIX + ITEM['author']],
                           (10, 100, 50, 150), True)]
        child_widgets = [([safe.fb.AVATAR_PREFIX + ITEM['account']],
                          (60, 100, 100, 150), True)]
        with patch.object(safe.fb, 'visible_comments', side_effect=[parent_rows, child_rows]), \
             patch.object(safe.fb, 'iter_widgets', side_effect=[parent_widgets, child_widgets]):
            first = safe.verified_reply('<hierarchy/>', ITEM, return_detail=True)
            self.assertFalse(first['verified'])
            second = safe.verified_reply(
                '<hierarchy/>', ITEM, context=first['context'], return_detail=True)
        self.assertTrue(second['verified'])
        self.assertEqual(second['reason'], 'confirmed')

    def test_verification_never_accepts_matching_text_under_next_parent(self):
        parent_rows = [dict(author=ITEM['author'], text=ITEM['body'], top=100)]
        next_rows = [dict(author='Next Person', text='next', top=100),
                     dict(author=ITEM['account'], text=ITEM['reply_draft'], top=200)]
        parent_widgets = [([safe.fb.AVATAR_PREFIX + ITEM['author']],
                           (10, 100, 50, 150), True)]
        next_widgets = [([safe.fb.AVATAR_PREFIX + 'Next Person'],
                         (10, 100, 50, 150), True),
                        ([safe.fb.AVATAR_PREFIX + ITEM['account']],
                         (60, 200, 100, 250), True)]
        with patch.object(safe.fb, 'visible_comments', side_effect=[parent_rows, next_rows]), \
             patch.object(safe.fb, 'iter_widgets', side_effect=[parent_widgets, next_widgets]):
            first = safe.verified_reply('<hierarchy/>', ITEM, return_detail=True)
            second = safe.verified_reply(
                '<hierarchy/>', ITEM, context=first['context'], return_detail=True)
        self.assertFalse(second['verified'])
        self.assertEqual(second['reason'], 'reply_not_in_thread')

    def test_verification_requires_urls_in_same_reply_row(self):
        item = dict(ITEM, reply_draft='รายละเอียดครบ\nhttps://example.com/item')
        rows = [dict(author=ITEM['author'], text=ITEM['body'], top=100),
                dict(author=ITEM['account'],
                     text=ITEM['author'] + ' รายละเอียดครบ', top=200,
                     reply=(100, 300))]
        widgets = [([safe.fb.AVATAR_PREFIX + ITEM['author']],
                    (10, 100, 50, 150), True),
                   ([safe.fb.AVATAR_PREFIX + ITEM['account']],
                    (60, 200, 100, 250), True)]
        with patch.object(safe.fb, 'visible_comments', return_value=rows), \
             patch.object(safe.fb, 'iter_widgets', return_value=widgets):
            self.assertFalse(safe.verified_reply('<hierarchy/>', item))
            widgets.append((['https://example.com/item'], (60, 250, 300, 280), True))
            self.assertTrue(safe.verified_reply('<hierarchy/>', item))
            widgets[-1] = (['https://example.com/wrong'], (60, 250, 300, 280), True)
            self.assertFalse(safe.verified_reply('<hierarchy/>', item))
            # A URL in the parent cannot prove the child contains that URL.
            widgets[-1] = (['https://example.com/item'], (10, 150, 300, 180), True)
            self.assertFalse(safe.verified_reply('<hierarchy/>', item))

    def test_marker_requires_full_exact_name(self):
        xml = '<hierarchy><node text="กำลังตอบกลับ Anurak Wongsawad" bounds="[0,0][100,100]" /></hierarchy>'
        self.assertTrue(fb_engage._new_reply_target('<hierarchy/>', xml, ITEM['author']))
        self.assertFalse(fb_engage._new_reply_target('<hierarchy/>', xml, 'Anurak'))

    def test_dispatch_survives_restart_refresh_and_manual_retry_is_verify_only(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'DB_FILE', Path(temp)/'db.sqlite3'):
            conn = store.open_db()
            conn.execute("INSERT INTO my_comment (comment_key,post_url,account,author,body,first_seen,last_seen,reply_draft,is_ours,answered) VALUES ('key','post',?,?,?,'now','now',?,0,0)",
                         (ITEM['account'], ITEM['author'], ITEM['body'], ITEM['reply_draft']))
            conn.commit()
            conn.close()
            store.mark_reply_submitted('key')
            with self.assertRaises(ValueError):
                store.mark_reply_submitted('key')
            with self.assertRaises(ValueError):
                store.save_reply('key', 'different')
            conn = store.open_db()
            store.save(conn, dict(post_url='post',account=ITEM['account'],group_id='g',group_name='g'),
                       dict(reachable=True,comments_snapshot_complete=True,comments_list=[]))
            row = conn.execute("SELECT * FROM my_comment WHERE comment_key='key'").fetchone()
            self.assertTrue(row['reply_submitted_at'])
            conn.close()
            store.queue_reply('key', ITEM['reply_draft'])
            with patch.object(store, '_post_meta_by_link', return_value={}):
                pending = store.queued_replies()
            self.assertEqual(len(pending), 1)
            self.assertTrue(pending[0]['reply_submitted_at'])
            self.assertEqual(store.reply_daily_status(ITEM['account'])['used'], 0)


if __name__ == '__main__':
    unittest.main()
