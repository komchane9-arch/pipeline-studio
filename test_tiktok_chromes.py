"""เทสตัวอ่านไอดี TikTok — ใช้ค่าที่วัดจากของจริง ไม่ต้องเปิดเบราว์เซอร์

ที่มาของตัวเลขและชื่อช่องทุกตัวในไฟล์นี้ (12 กันยายน 2569)

  หน้า Studio ตอนล็อกอินแล้ว   __Creator_Center_Context__
                               commonAppContext.user.uniqueId = taiwhatsale
                               (ก้อนนี้เข้ารหัสแบบ HTML · ทั้งหน้ามีคำว่า
                                uniqueId อยู่ที่เดียว ไม่มีชื่อคนอื่นปน)
  หน้าแรกตอนล็อกอินแล้ว        __UNIVERSAL_DATA_FOR_REHYDRATION__
                               __DEFAULT_SCOPE__["webapp.app-context"]
                                 .user.uniqueId = taiwhatsale
  หน้าแรกตอนยังไม่ล็อกอิน      ไม่มีก้อน user แต่มีชื่อคนอื่นในฟีด 3 ชื่อ
  หน้า Studio ตอนยังไม่ล็อกอิน  เด้งไปหน้าเข้าสู่ระบบเสมอ
"""

import unittest

import tiktok_chromes as tc

STUDIO_URL = "https://www.tiktok.com/tiktokstudio/upload"
HOME_URL = "https://www.tiktok.com/"
LOGIN_URL = ("https://www.tiktok.com/login?redirect_url="
             "https%3A%2F%2Fwww.tiktok.com%2Ftiktokstudio%2Fupload"
             "&enter_method=redirect&enter_from=tiktokstudio")

REAL = "@taiwhatsale"


class HandleReaderTests(unittest.TestCase):
    def test_reads_handle_from_studio_page(self) -> None:
        """ค่าที่วัดได้จริงจากหน้า Studio ของบัญชีที่ล็อกอินอยู่"""
        handle, why = tc.pick_handle(
            {"studio": "taiwhatsale", "www": None}, STUDIO_URL)
        self.assertEqual(handle, REAL)
        self.assertEqual(why, "")

    def test_reads_handle_from_home_page(self) -> None:
        handle, _why = tc.pick_handle(
            {"studio": None, "www": "taiwhatsale"}, HOME_URL)
        self.assertEqual(handle, REAL)

    def test_two_sources_that_disagree_are_refused(self) -> None:
        """สองแหล่งไม่ตรงกัน = ไม่เดา ไม่เลือกข้าง

        จดผิดช่องแล้วคลิปขึ้นผิดบัญชี ถอนไม่ได้ — ยอมอ่านไม่ออกดีกว่า
        """
        handle, why = tc.pick_handle(
            {"studio": "taiwhatsale", "www": "armkiss"}, STUDIO_URL)
        self.assertIsNone(handle)
        self.assertIn("ไม่ตรงกัน", why)

    def test_never_takes_a_strangers_handle(self) -> None:
        """ชื่อคนอื่นในฟีดต้องไม่มีทางกลายเป็นไอดีของช่องเรา

        ตัวอ่านรับเฉพาะที่อยู่ของบัญชีตัวเอง ชื่อที่โผล่ที่อื่นบนหน้า
        (updated-items[].author.uniqueId) จึงไม่มีทางถูกส่งเข้ามาที่นี่
        """
        handle, why = tc.pick_handle({"studio": None, "www": None}, HOME_URL)
        self.assertIsNone(handle)
        self.assertIn("ยังไม่ได้ล็อกอิน", why)

    def test_redirect_to_login_means_not_logged_in(self) -> None:
        handle, why = tc.pick_handle({"studio": None, "www": None}, LOGIN_URL)
        self.assertIsNone(handle)
        self.assertIn("ยังไม่ได้ล็อกอิน", why)

    def test_on_studio_without_handle_is_a_code_problem(self) -> None:
        """อยู่หน้า Studio ได้ = ล็อกอินแล้ว หาไอดีไม่เจอ = ต้องแก้โค้ด

        สองอย่างนี้แก้คนละทาง ห้ามรายงานเหมือนกัน (กติกา 2.3.1 ข้อ 4)
        เคสนี้เกิดจริงมาแล้ว — ตอนแรกอ่านแต่ก้อนของหน้าแรก ซึ่งหน้า Studio
        ไม่มีเลย
        """
        handle, why = tc.pick_handle({"studio": None, "www": None}, STUDIO_URL)
        self.assertIsNone(handle)
        self.assertIn("ล็อกอินแล้ว", why)
        self.assertNotIn("ยังไม่ได้ล็อกอิน", why)

    def test_rejects_values_that_are_not_handles(self) -> None:
        for junk in ("", "  ", "a", "x" * 40, "ชื่อไทย", "มี ช่องว่าง"):
            handle, _why = tc.pick_handle({"studio": junk, "www": None}, STUDIO_URL)
            self.assertIsNone(handle, f"รับค่าที่ไม่ใช่ไอดีเข้ามา: {junk!r}")

    def test_nothing_came_back_is_not_a_pass(self) -> None:
        handle, why = tc.pick_handle(None, STUDIO_URL)
        self.assertIsNone(handle)
        self.assertIn("อ่านหน้าไม่ได้", why)

    def test_the_reading_script_asks_for_both_places(self) -> None:
        """สคริปต์ที่ยิงเข้าหน้าต้องถามทั้งสองก้อน

        หน้า Studio กับหน้าแรกเก็บชื่อบัญชีคนละที่ ขาดก้อนไหนไปก็อ่าน
        หน้านั้นไม่ออก
        """
        for piece in ("__Creator_Center_Context__", "commonAppContext",
                      "__UNIVERSAL_DATA_FOR_REHYDRATION__", "webapp.app-context",
                      "uniqueId"):
            self.assertIn(piece, tc.READ_JS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
