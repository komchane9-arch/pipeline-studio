"""ทดสอบการจับคู่ Chrome profile โดยไม่แตะหน้าต่างจริง."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chrome_view


class ChromeViewTests(unittest.TestCase):
    def test_matches_equals_style_user_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(chrome_view._uses_profile(
                ["chrome.exe", f"--user-data-dir={folder}", "--profile-directory=Default"],
                Path(folder),
            ))

    def test_matches_split_user_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(chrome_view._uses_profile(
                ["chrome.exe", "--user-data-dir", folder], Path(folder),
            ))

    def test_rejects_other_profile(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            self.assertFalse(chrome_view._uses_profile(
                ["chrome.exe", f"--user-data-dir={first}"], Path(second),
            ))

    def test_ghost_window_is_not_counted(self) -> None:
        """หน้าต่างซ่อนของ Chrome ต้องไม่ถูกนับว่า "ยังเปิดอยู่"

        วัดจากของจริง 11 ก.ย. 2569: โปรไฟล์ tiktok1 มีหน้าต่าง 3 บาน
        บานเดียวที่คนเห็นคือ 'Log in | TikTok - Google Chrome'
        อีกสองบานเป็น Chrome_WidgetWin_0 ขนาด 0x0 ไม่มีชื่อ ซึ่งไม่ปิด
        ตามคำสั่งปิด ทำให้สั่งปิดแล้วระบบตอบว่าล้มทุกครั้ง
        """
        self.assertTrue(
            chrome_view._is_real_window(True, "Log in | TikTok - Google Chrome"))
        self.assertFalse(chrome_view._is_real_window(False, ""))
        self.assertFalse(chrome_view._is_real_window(False, "ซ่อนแต่มีชื่อ"))
        self.assertFalse(chrome_view._is_real_window(True, "   "))

    @patch.object(chrome_view, "_matching_windows", return_value=[])
    def test_profile_running_is_false_without_window(self, _matching) -> None:
        self.assertFalse(chrome_view.profile_running("missing-profile"))

    @patch.object(chrome_view, "_matching_windows", side_effect=[[(111, 222, "งาน")], []])
    def test_close_profile_waits_until_exact_window_is_gone(self, _matching) -> None:
        result = chrome_view.close_profile("target-profile", timeout=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["closed"], 1)


if __name__ == "__main__":
    unittest.main()
