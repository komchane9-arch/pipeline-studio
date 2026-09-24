"""Regressions captured from the September 21 mobile reply audit."""
import unittest
from unittest.mock import MagicMock, patch

import facebook_group_post as fb
import fb_reply_safe as safe
import fb_engage


class AuditRegressions(unittest.TestCase):
    @staticmethod
    def _clipped_parent_xml(reply_top=260):
        return f'''<hierarchy>
        <node content-desc="รูปโปรไฟล์ของ Pirom Lobru" bounds="[24,162][104,242]" />
        <node text="ต่อเข้าเนตบ้านได้ไหม" bounds="[120,206][620,250]" />
        <node content-desc="ตอบกลับความคิดเห็นของ Pirom ปุ่ม"
          clickable="true" bounds="[104,{reply_top}][230,{reply_top + 64}]" />
        <node content-desc="รูปโปรไฟล์ของ Other" bounds="[24,500][104,580]" />
        </hierarchy>'''

    def test_reacquire_accepts_clipped_parent_when_reply_control_is_safe(self):
        phone = MagicMock()
        phone.dump.return_value = self._clipped_parent_xml(268)
        with patch.object(fb_engage, '_comment_zone', return_value=(260, 1000)):
            found, error = fb_engage._find_queued_comment(
                phone, dict(author='Pirom Lobru', body='ต่อเข้าเนตบ้านได้ไหม'),
                max_scrolls=0, in_comments=True)
        self.assertEqual(error, '')
        self.assertEqual(found['reply'], (167, 300))
        phone.vswipe.assert_not_called()

    def test_reacquire_never_uses_control_above_safe_boundary(self):
        phone = MagicMock()
        phone.dump.return_value = self._clipped_parent_xml(190)
        with patch.object(fb_engage, '_comment_zone', return_value=(260, 1000)), \
             patch.object(fb_engage.time, 'sleep'):
            found, error = fb_engage._find_queued_comment(
                phone, dict(author='Pirom Lobru', body='ต่อเข้าเนตบ้านได้ไหม'),
                max_scrolls=0, in_comments=True)
        self.assertIsNone(found)
        self.assertIn('ปุ่มตอบกลับ', error)

    def test_reload_unconfirmed_only_verifies_without_reply_button(self):
        item = dict(account='test', post_url='post', caption='caption')
        phone = MagicMock()
        with patch.object(fb, 'open_post_link', return_value=True) as opened, \
             patch.object(fb_engage, '_find_queued_comment', return_value=({'reply': None}, '')) as find, \
             patch.object(safe, 'verify_on_phone_result', return_value={'verified': True}) as verify, \
             patch.object(safe, 'send_reply') as send:
            result = fb_engage._recheck_delivery(phone, item, {'verified': False, 'reason': 'reply_not_in_thread'})
        self.assertTrue(result['verified'])
        opened.assert_called_once()
        find.assert_called_once_with(phone, item, require_reply=False)
        verify.assert_called_once_with(phone, item)
        send.assert_not_called()

    def test_confirmed_delivery_does_not_reload(self):
        with patch.object(fb, 'open_post_link') as opened:
            self.assertTrue(fb_engage._recheck_delivery(MagicMock(), {}, {'verified': True})['verified'])
        opened.assert_not_called()

    def test_reacquire_does_not_scroll_for_header_again(self):
        phone = MagicMock()
        phone.dump.return_value = '<hierarchy/>'
        row = dict(author='RubyOwl8377', text='question', top=500, reply=(100, 600))
        with patch.object(fb_engage, '_scroll_into_comments') as scroll, \
             patch.object(fb_engage, '_all_comments') as filters, \
             patch.object(fb, 'visible_comments', return_value=[row]):
            found, error = fb_engage._find_queued_comment(
                phone, dict(author='RubyOwl8377', body='question'), in_comments=True)
        self.assertEqual(found, row)
        self.assertEqual(error, '')
        scroll.assert_not_called()
        filters.assert_not_called()

    def test_anonymous_reply_accessibility_label(self):
        xml = '''<hierarchy>
        <node content-desc="รูปโปรไฟล์ของ RubyOwl8377" bounds="[24,296][104,376]" />
        <node text="ทำไงให้กินเเล้วไม่ตดเเตกครับ" bounds="[120,340][650,385]" />
        <node content-desc="ปุ่ม, ตอบกลับ แตะสองครั้งเพื่อตอบกลับความคิดเห็น"
          clickable="true" bounds="[104,386][230,451]" />
        <node content-desc="ดูการตอบกลับ 1 รายการที่ RubyOwl8377 ได้รับ..."
          clickable="true" bounds="[104,451][474,503]" />
        <node content-desc="รูปโปรไฟล์ของ Other" bounds="[24,527][104,607]" />
        </hierarchy>'''
        row = fb.visible_comments(xml)[0]
        self.assertEqual(row['reply'], (167, 418))
        self.assertFalse(fb._is_comment_reply_label('ดูข้อความตอบกลับ 1 รายการ'))

    def test_expand_before_accepting_next_parent_boundary(self):
        phone = MagicMock()
        phone.dump.return_value = '<hierarchy/>'
        closed = dict(verified=False, reason='reply_not_in_thread',
                      message='not visible', context={'thread_open': False})
        confirmed = dict(verified=True, reason='confirmed', context={})
        with patch.object(safe, 'verified_reply', side_effect=[closed, confirmed]), \
             patch.object(safe, 'target_reply_expander', return_value=(200, 300)), \
             patch.object(safe.time, 'sleep'):
            self.assertTrue(safe.verify_on_phone_result(phone, {})['verified'])
        phone.tap.assert_called_once_with((200, 300))
        phone.vswipe.assert_not_called()

    def test_select_all_comments_not_relevant(self):
        phone = MagicMock()
        phone.dump.side_effect = [
            '<hierarchy><node clickable="true" content-desc="กำลังแสดงความคิดเห็นเกี่ยวข้องมากที่สุด แตะเพื่อเปลี่ยนตัวกรองความคิดเห็น" bounds="[0,921][720,1017]" /></hierarchy>',
            '<hierarchy><node text="ความคิดเห็นทั้งหมด" bounds="[0,500][720,600]" /></hierarchy>',
            '<hierarchy><node clickable="true" content-desc="กำลังแสดงความคิดเห็นทั้งหมด แตะเพื่อเปลี่ยนตัวกรองความคิดเห็น" bounds="[0,921][720,1017]" /></hierarchy>',
        ]
        with patch.object(fb_engage.time, 'sleep'):
            self.assertTrue(fb_engage._all_comments(phone))
        self.assertEqual(phone.tap.call_count, 2)

    def test_filter_change_must_be_confirmed_not_assumed_after_tap(self):
        phone = MagicMock()
        relevant = '<hierarchy><node clickable="true" content-desc="เกี่ยวข้องมากที่สุด ตัวกรองความคิดเห็น" bounds="[0,900][720,1000]" /></hierarchy>'
        phone.dump.side_effect = [relevant,
            '<hierarchy><node text="ความคิดเห็นทั้งหมด" bounds="[0,500][720,600]" /></hierarchy>',
            relevant]
        with patch.object(fb_engage.time, 'sleep'):
            self.assertFalse(fb_engage._all_comments(phone))


if __name__ == '__main__':
    unittest.main()
