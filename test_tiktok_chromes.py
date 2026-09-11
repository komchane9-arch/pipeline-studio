"""เทสตัวอ่านไอดี TikTok — ใช้ข้อมูลจริงที่เก็บจากหน้าเว็บ ไม่ต้องเปิดเบราว์เซอร์

ข้อมูลในไฟล์นี้เก็บจากของจริงเมื่อ 11 กันยายน 2569 (ตัดเอาเฉพาะส่วนที่ใช้
และลบค่าที่เป็นความลับออก) ไม่ได้แต่งขึ้นเอง
"""

import unittest

import tiktok_chromes as tc


# หน้าแรก tiktok.com ตอน **ยังไม่ล็อกอิน** — ไม่มีบัญชีเรา แต่มีชื่อคนอื่น
# ฝังอยู่ 3 ชื่อในรายการฟีด นี่คือกับดักที่ทำให้จดไอดีผิดช่องได้
HOME_LOGGED_OUT = {
    "__DEFAULT_SCOPE__": {
        "webapp.app-context": {
            "language": "en", "region": "TH", "appId": 1180,
            "appType": "t", "botType": "", "host": "https://www.tiktok.com",
        },
        "webapp.updated-items": [
            {"author": {"uniqueId": "armkiss"}},
            {"author": {"uniqueId": "_ply01"}},
            {"author": {"uniqueId": "wan.vogvax"}},
        ],
    }
}

# หน้า Studio ตอนยังไม่ล็อกอิน — TikTok ไล่ไปหน้าเข้าสู่ระบบเสมอ (วัดจริง)
STUDIO_LOGGED_OUT_URL = ("https://www.tiktok.com/login?redirect_url="
                         "https%3A%2F%2Fwww.tiktok.com%2Ftiktokstudio%2Fupload"
                         "&enter_method=redirect&enter_from=tiktokstudio")

STUDIO_URL = "https://www.tiktok.com/tiktokstudio/upload"


class HandleReaderTests(unittest.TestCase):
    def test_never_takes_a_strangers_handle_from_the_feed(self) -> None:
        """กับดักตัวจริง — ห้ามหยิบชื่อคนอื่นในฟีดมาเป็นไอดีของช่องเรา

        ข้อมูลชุดนี้มีคำว่า uniqueId อยู่ 3 ที่ ทั้งสามเป็นของคนแปลกหน้า
        ตัวอ่านรุ่นก่อนที่ไล่หาทั้งก้อนจะคืน armkiss ออกมาอย่างมั่นใจ
        แล้วคลิปของเราจะถูกจดว่าอยู่ช่องนั้น ซึ่งถอนไม่ได้
        """
        handle, why = tc.handle_from_blob(HOME_LOGGED_OUT, "https://www.tiktok.com/")
        self.assertIsNone(handle, f"ไปหยิบชื่อคนอื่นมา: {handle}")
        self.assertIn("ยังไม่ได้ล็อกอิน", why)
        for stranger in ("armkiss", "_ply01", "wan.vogvax"):
            self.assertNotIn(stranger, str(handle))

    def test_reads_own_handle_when_logged_in(self) -> None:
        blob = {"__DEFAULT_SCOPE__": {
            "webapp.app-context": {"region": "TH",
                                   "user": {"uniqueId": "somchai.shop"}},
            "webapp.updated-items": [{"author": {"uniqueId": "armkiss"}}],
        }}
        handle, why = tc.handle_from_blob(blob, STUDIO_URL)
        self.assertEqual(handle, "@somchai.shop")
        self.assertEqual(why, "")

    def test_redirect_to_login_means_not_logged_in(self) -> None:
        handle, why = tc.handle_from_blob(None, STUDIO_LOGGED_OUT_URL)
        self.assertIsNone(handle)
        self.assertIn("ยังไม่ได้ล็อกอิน", why)

    def test_on_studio_without_user_is_a_code_problem_not_a_login_problem(self) -> None:
        """อยู่หน้า Studio ได้ = ล็อกอินแล้ว แต่หาไอดีไม่เจอ = ต้องแก้โค้ด

        สองอย่างนี้แก้คนละทาง ห้ามรายงานเหมือนกัน (กติกา 2.3.1 ข้อ 4)
        """
        blob = {"__DEFAULT_SCOPE__": {"webapp.app-context": {"region": "TH"}}}
        handle, why = tc.handle_from_blob(blob, STUDIO_URL)
        self.assertIsNone(handle)
        self.assertIn("ล็อกอินแล้ว", why)
        self.assertNotIn("ยังไม่ได้ล็อกอิน", why)

    def test_rejects_junk_handle(self) -> None:
        for junk in ("", "  ", "a", "x" * 40, "ชื่อไทย"):
            blob = {"__DEFAULT_SCOPE__": {
                "webapp.app-context": {"user": {"uniqueId": junk}}}}
            handle, _why = tc.handle_from_blob(blob, STUDIO_URL)
            self.assertIsNone(handle, f"รับค่าที่ไม่ใช่ไอดีเข้ามา: {junk!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
