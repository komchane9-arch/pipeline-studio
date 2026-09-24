"""Regression tests for Facebook captions rendered below post media."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import facebook_group_post as fb


def _screen(*rows: str) -> str:
    nodes = []
    for index, text in enumerate(rows):
        y1 = 120 + index * 120
        y2 = y1 + 90
        nodes.append(
            f'<node text="{text}" content-desc="" bounds="[0,{y1}][1080,{y2}]" />'
        )
    return "<hierarchy>" + "".join(nodes) + "</hierarchy>"


class FakePhone:
    def __init__(self, screens: list[str]):
        self.screens = screens
        self.index = 0
        self.swipes = 0

    def dump(self) -> str:
        return self.screens[self.index]

    def vswipe(self, *_args) -> None:
        self.swipes += 1
        if self.index + 1 < len(self.screens):
            self.index += 1


class CaptionBelowImageTests(unittest.TestCase):
    def test_preaw_public_and_approval_caption_fields(self):
        phone = object.__new__(fb.Phone)
        for label in ("สร้างโพสต์สาธารณะ...", "ส่งโพสต์สาธารณะให้ผู้ดูแลอนุมัติ...",
                      "บอกอะไรสักหน่อยเกี่ยวกับรูปภาพเหล่านี้..."):
            xml = ('<hierarchy><node content-desc="โพสต์" bounds="[800,2100][1040,2240]" />'
                   '<node class="android.widget.AutoCompleteTextView" '
                   f'content-desc="{label}" bounds="[0,580][1080,674]" /></hierarchy>')
            self.assertEqual(phone.find(xml, fb.CAPTION_FIELD_HINTS), (540, 627))
        self.assertIsNone(phone.find(_screen("โพสต์", "รูปภาพ"), fb.CAPTION_FIELD_HINTS))

    @patch.object(fb.time, "sleep", return_value=None)
    def test_known_caption_below_image_is_revealed(self, _sleep) -> None:
        caption = "จ่ายเน็ต 800 เหลือแค่ 200 ต่อเดือน"
        phone = FakePhone([
            _screen("Preaw Buchakorn•21 ชม.•แชร์กับ: กลุ่มสาธารณะ", "[รูปภาพ]"),
            _screen(caption, "เขียนความคิดเห็นสาธารณะ..."),
        ])

        self.assertEqual(fb._confirm_linked_post(phone, caption, tries=3), caption)
        self.assertEqual(phone.swipes, 1)

    @patch.object(fb.time, "sleep", return_value=None)
    def test_legacy_caption_above_image_does_not_scroll(self, _sleep) -> None:
        caption = "แคปชันโครงเดิมอยู่เหนือรูป"
        phone = FakePhone([_screen(caption, "[รูปภาพ]")])

        self.assertEqual(fb._confirm_linked_post(phone, caption, tries=3), caption)
        self.assertEqual(phone.swipes, 0)

    @patch.object(fb.time, "sleep", return_value=None)
    def test_missing_saved_caption_uses_verified_identity(self, _sleep) -> None:
        observed = "จ่ายเน็ต 800 เหลือแค่ 200 ต่อเดือน ใช้ได้ยาว ๆ"
        phone = FakePhone([
            _screen(
                "สกินแคร์กู้หน้า ของใช้กู้บ้าน",
                "Preaw Buchakorn•21 ชม.•แชร์กับ: กลุ่มสาธารณะ",
                "[รูปภาพ]",
            ),
            _screen(observed, "เขียนความคิดเห็นสาธารณะ..."),
        ])

        self.assertEqual(
            fb._confirm_linked_post(
                phone, "", account="Preaw Buchakorn",
                group_name="สกินแคร์กู้หน้าของใช้กู้บ้าน", tries=3,
            ),
            observed,
        )
        self.assertEqual(phone.swipes, 1)

    @patch.object(fb.time, "sleep", return_value=None)
    def test_missing_saved_caption_without_identity_is_rejected(self, _sleep) -> None:
        phone = FakePhone([
            _screen("โพสต์คนอื่น", "[รูปภาพ]"),
            _screen(
                "ข้อความยาวของโพสต์คนอื่นที่ไม่ควรถูกเลือก",
                "เขียนความคิดเห็นสาธารณะ...",
            ),
        ])

        self.assertEqual(
            fb._confirm_linked_post(
                phone, "", account="Preaw Buchakorn",
                group_name="สกินแคร์กู้หน้าของใช้กู้บ้าน", tries=1,
            ),
            "",
        )


if __name__ == "__main__":
    unittest.main()
