from __future__ import annotations

import unittest
from unittest import mock

import facebook_group_post as fb


def screen(label: str, *, field: bool = False) -> str:
    klass = "android.widget.EditText" if field else "android.widget.Button"
    hint = label if field else ""
    return (
        "<hierarchy>"
        f'<node text="{label}" content-desc="{label}" class="{klass}" '
        f'clickable="true" bounds="[700,80][1040,180]" hint="{hint}" />'
        "</hierarchy>"
    )


class SearchPhone:
    def __init__(self, caption: str, field_label: str = "ค้นหาในกลุ่มนี้"):
        self.caption = caption
        self.field_label = field_label
        self.stage = 0
        self.typed = ""
        self.swipes = 0
        self.restored = ""
        self.logs: list[str] = []

    def dump(self) -> str:
        if self.stage == 0:
            return screen("ค้นหา")
        if self.stage == 1:
            return screen(self.field_label, field=True)
        if self.stage == 2:
            return screen("ผลการค้นหา")
        return screen(self.caption)

    def find(self, xml: str, texts: list[str]):
        return fb.Phone.find(self, xml, texts)

    def tap(self, _point) -> None:
        if self.stage == 0:
            self.stage = 1

    def shell(self, command: str, timeout: float = 30) -> str:
        if "default_input_method" in command:
            return "com.android.inputmethod.latin/.LatinIME\n"
        return ""

    def use_adb_keyboard(self) -> str:
        return "com.android.inputmethod.latin/.LatinIME"

    def type_text(self, text: str) -> None:
        self.typed = text
        self.stage = 2

    def run(self, *_args, **_kwargs):
        return None

    def hide_keyboard(self) -> bool:
        return True

    def restore_keyboard(self, original: str) -> None:
        self.restored = original

    def vswipe(self, *_args) -> None:
        self.swipes += 1
        self.stage = 3

    def back(self) -> None:
        self.stage = 0

    def log(self, message: str) -> None:
        self.logs.append(message)


class GroupSearchTests(unittest.TestCase):
    @mock.patch.object(fb.time, "sleep", return_value=None)
    def test_searches_by_profile_then_scrolls_until_caption_matches(self, _sleep) -> None:
        caption = "โพสต์เป้าหมายที่ต้องหาให้ตรง"
        phone = SearchPhone(caption)

        result = fb.search_own_post_in_group(
            phone, "Preaw Buchakorn", caption, "440966771947927")

        self.assertTrue(result["used"])
        self.assertEqual(result["route"], "search")
        self.assertEqual(phone.typed, "Preaw Buchakorn")
        self.assertEqual(phone.swipes, 1)
        self.assertEqual(phone.restored,
                         "com.android.inputmethod.latin/.LatinIME")
        self.assertTrue(any("เจอโพสต์จากผลค้นหา" in line for line in phone.logs))

    @mock.patch.object(fb.time, "sleep", return_value=None)
    def test_accepts_dynamic_search_field_with_group_name(self, _sleep) -> None:
        """Facebook รุ่นจริงใส่ชื่อกลุ่มต่อท้ายแทนคำว่า 'กลุ่ม'."""
        caption = "โพสต์เป้าหมาย"
        phone = SearchPhone(caption, "ค้นหาใน แม่บ้านชอบรีวิว")

        result = fb.search_own_post_in_group(
            phone, "Preaw Buchakorn", caption, "440966771947927")

        self.assertTrue(result["used"])
        self.assertEqual(result["route"], "search")
        self.assertEqual(phone.typed, "Preaw Buchakorn")

    @mock.patch.object(fb, "search_own_post_in_group")
    @mock.patch.object(fb, "open_post_from_notification", return_value=False)
    @mock.patch.object(fb, "open_post_link", return_value=False)
    def test_open_own_post_uses_group_search_before_plain_feed(
        self, _link, _notification, search,
    ) -> None:
        search.return_value = {"used": True, "route": "search", "link": ""}

        class Phone:
            def __init__(self):
                self.opened = []

            def log(self, _message):
                pass

            def open_group(self, group_id):
                self.opened.append(group_id)

        phone = Phone()
        result = fb.open_own_post(
            phone, "440966771947927", "แม่บ้านชอบรีวิว", "แคปชันทดสอบ",
            account="Preaw Buchakorn")

        self.assertEqual(result["route"], "search")
        self.assertEqual(phone.opened, ["440966771947927"])
        search.assert_called_once_with(
            phone, "Preaw Buchakorn", "แคปชันทดสอบ", "440966771947927",
            clipboard=None)

    def test_missing_profile_name_keeps_legacy_feed_available(self) -> None:
        phone = SearchPhone("แคปชัน")
        result = fb.search_own_post_in_group(phone, "", "แคปชัน", "group")

        self.assertFalse(result["used"])
        self.assertEqual(phone.stage, 0)
        self.assertEqual(phone.typed, "")

    @mock.patch.object(fb.time, "sleep", return_value=None)
    @mock.patch.object(fb, "_copy_link_from_menu", return_value="https://facebook/link")
    def test_moves_post_menu_out_from_under_sticky_search_bar(
        self, copy_link, _sleep,
    ) -> None:
        caption = "แกร อาบน้ำเสร็จหอมแป๊บเดียว"
        hidden = (
            "<hierarchy>"
            '<node text="" content-desc="ตัวเลือกเพิ่มเติมสำหรับโพสต์ของ Preaw" '
            'bounds="[965,100][1080,215]" />'
            f'<node text="{caption}" content-desc="{caption}" '
            'bounds="[33,1836][1047,1973]" />'
            "</hierarchy>"
        )
        visible = (
            "<hierarchy>"
            '<node text="" content-desc="ตัวเลือกเพิ่มเติมสำหรับโพสต์ของ Preaw" '
            'bounds="[965,329][1080,444]" />'
            f'<node text="{caption}" content-desc="{caption}" '
            'bounds="[33,2065][1047,2202]" />'
            "</hierarchy>"
        )

        class Phone:
            def __init__(self):
                self.screen = hidden
                self.swipes = 0
                self.logs = []

            def dump(self):
                return self.screen

            def vswipe(self, *_args):
                self.swipes += 1
                self.screen = visible

            def log(self, message):
                self.logs.append(message)

        phone = Phone()
        result = fb.copy_post_link(phone, "440966771947927", caption, object())

        self.assertEqual(result, "https://facebook/link")
        self.assertEqual(phone.swipes, 1)
        copy_link.assert_called_once_with(phone, (1022, 386), mock.ANY)


if __name__ == "__main__":
    unittest.main()
