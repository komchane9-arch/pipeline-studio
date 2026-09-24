import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import facebook_group_post as fb
import fb_engage


ITEM = {
    "author": "Aekbodin Prasitsuwan",
    "body": "กี่บาทครับราคาเท่าไหร่",
}


def comment_xml(*, liked=False, include_like=True, next_row=True):
    like_label = ("ได้มีการกดปุ่ม ถูกใจ ไปแล้ว แตะสองครั้งเพื่อเปลี่ยนความรู้สึก"
                  if liked else "ถูกใจปุ่มแสดงความคิดเห็นของ Aekbodin Prasitsuwan")
    like_node = (f'<node content-desc="{like_label}" clickable="true" '
                 'bounds="[100,600][220,660]" />') if include_like else ""
    following = ('<node content-desc="รูปโปรไฟล์ของ Other Person" '
                 'bounds="[20,900][90,970]" />') if next_row else ""
    return f'''<hierarchy>
      <node content-desc="รูปโปรไฟล์ของ Aekbodin Prasitsuwan"
            bounds="[20,400][90,470]" />
      <node text="กี่บาทครับราคาเท่าไหร่" bounds="[110,480][600,540]" />
      {like_node}
      <node content-desc="ตอบกลับความคิดเห็นของ Aekbodin ปุ่ม"
            clickable="true" bounds="[230,600][380,660]" />
      {following}
    </hierarchy>'''


class ReplyLikeBeforeSendTests(unittest.TestCase):
    def test_visible_comment_binds_like_and_reply_to_same_row(self):
        rows = fb.visible_comments(comment_xml())
        self.assertEqual(rows[0]["like"], (160, 630))
        self.assertFalse(rows[0]["liked"])
        self.assertEqual(rows[0]["reply"], (305, 630))

    def test_already_liked_row_has_no_unlike_point(self):
        row = fb.visible_comments(comment_xml(liked=True))[0]
        self.assertTrue(row["liked"])
        self.assertIsNone(row["like"])

    def test_like_is_confirmed_before_fresh_reply_geometry_is_returned(self):
        phone = MagicMock()
        phone.dump.return_value = comment_xml(liked=True)
        initial = fb.visible_comments(comment_xml())[0]
        with patch.object(fb_engage.time, "sleep"):
            fresh, error = fb_engage._like_queued_comment(phone, ITEM, initial)
        self.assertEqual(error, "")
        self.assertTrue(fresh["liked"])
        self.assertEqual(fresh["reply"], (305, 630))
        phone.tap.assert_called_once_with((160, 630))

    def test_unconfirmed_like_stops_before_reply(self):
        phone = MagicMock()
        phone.dump.return_value = comment_xml(liked=False)
        initial = fb.visible_comments(comment_xml())[0]
        with patch.object(fb_engage.time, "sleep"):
            fresh, error = fb_engage._like_queued_comment(phone, ITEM, initial)
        self.assertIsNone(fresh)
        self.assertIn("หยุดก่อนตอบ", error)
        phone.tap.assert_called_once_with((160, 630))

    def test_already_liked_does_not_toggle_off(self):
        phone = MagicMock()
        initial = fb.visible_comments(comment_xml(liked=True))[0]
        fresh, error = fb_engage._like_queued_comment(phone, ITEM, initial)
        self.assertIs(fresh, initial)
        self.assertEqual(error, "")
        phone.tap.assert_not_called()

    def test_send_flow_likes_before_tapping_reply(self):
        import fb_account_guard
        import fb_reply_safe

        item = dict(ITEM, account="Khao Fang Nichapa", reply_draft="ดูในลิงก์เลยค่ะ",
                    comment_key="comment-key", post_url="https://example.test/post")
        phone = MagicMock()
        events = []
        phone.tap.side_effect = lambda point: events.append(("tap", point))
        initial = {"author": ITEM["author"], "text": ITEM["body"],
                   "reply": (20, 20), "like": (10, 10), "liked": False}
        fresh = dict(initial, reply=(30, 30), like=None, liked=True)

        with ExitStack() as stack:
            stack.enter_context(patch.object(fb_engage.devices, "device_for_account",
                                             return_value="phone"))
            stack.enter_context(patch.object(fb_engage.devices, "account",
                                             return_value=item["account"]))
            stack.enter_context(patch.object(fb_engage.fb_auto_post, "use_account"))
            stack.enter_context(patch.object(fb_engage.studio_shared, "phone_lock"))
            stack.enter_context(patch.object(fb_engage.fb_screen,
                                             "keep_awake_while_working"))
            stack.enter_context(patch.object(fb_engage.fb, "Phone", return_value=phone))
            stack.enter_context(patch.object(fb_engage.fb, "require_network"))
            stack.enter_context(patch.object(fb_account_guard, "require"))
            stack.enter_context(patch.object(fb_engage.fb, "open_post_link",
                                             return_value=True))
            finder = stack.enter_context(patch.object(
                fb_engage, "_find_queued_comment", return_value=(initial, "")))
            stack.enter_context(patch.object(fb_reply_safe, "verified_reply",
                                             return_value=False))
            stack.enter_context(patch.object(fb_reply_safe, "target_reply_expander",
                                             return_value=None))
            stack.enter_context(patch.object(fb_engage, "_new_reply_target",
                                             return_value="ตอบกลับ Aekbodin Prasitsuwan"))
            stack.enter_context(patch.object(fb_engage, "reply_quota_status",
                                             return_value={"waiting": False}))
            stack.enter_context(patch.object(fb_engage.fb.fb_comment_guard,
                                             "hold_reason", return_value=""))
            stack.enter_context(patch.object(fb_engage.fb, "_note_comment_sent"))
            stack.enter_context(patch.object(fb_engage.fb.fb_comment_guard,
                                             "note_success"))
            stack.enter_context(patch.object(fb_reply_safe, "send_reply",
                                             return_value={"verified": True,
                                                           "reason": "confirmed"}))
            stack.enter_context(patch.object(fb_engage, "_recheck_delivery",
                                             side_effect=lambda _p, _i, delivery, _r: delivery))
            stack.enter_context(patch.object(fb_engage.time, "sleep"))

            def like_first(_phone, _item, _comment):
                events.append(("like-confirmed", _comment["like"]))
                return fresh, ""

            stack.enter_context(patch.object(fb_engage, "_like_queued_comment",
                                             side_effect=like_first))
            result = fb_engage.run_queued_reply(item, send=True)

        self.assertTrue(result["sent"])
        self.assertEqual(events[:2], [("like-confirmed", (10, 10)),
                                      ("tap", (30, 30))])
        finder.assert_called_once_with(phone, item, require_like=True)


if __name__ == "__main__":
    unittest.main()
