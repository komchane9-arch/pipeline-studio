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

import shutil
import tempfile
import unittest
from pathlib import Path

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


class RecordingTests(unittest.TestCase):
    """อ่านไอดีออกแล้วต้องจดลงแฟ้มได้ด้วย — อ่านออกแต่จดไม่ลงก็เท่ากับไม่ได้ทำ

    ใช้แฟ้มชั่วคราว ไม่แตะข้อมูลจริง (กติกา 7.4)
    """

    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="tiktok-test-"))
        self.real = tc.STATE_FILE
        tc.STATE_FILE = self.temp / "tiktok_chromes.json"

    def tearDown(self) -> None:
        tc.STATE_FILE = self.real
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_saved_handle_comes_back_ready(self) -> None:
        tc.save("tiktok1", REAL, note="ล็อกอินแล้ว")
        row = tc.load()["tiktok1"]
        self.assertEqual(row["handle"], REAL)
        self.assertFalse(row["stale"])
        self.assertTrue(row["checked_at"])
        self.assertTrue(row["last_ok_at"])

    def test_unreadable_round_keeps_the_old_handle(self) -> None:
        """เน็ตสะดุดรอบเดียว ห้ามทำให้ช่องที่ล็อกอินไว้กลายเป็นว่างเปล่า

        ถ้าลบไอดีทิ้งทุกครั้งที่อ่านไม่ได้ ช่องที่ล็อกอินอยู่จะขึ้นว่า
        "ยังไม่ได้ล็อกอิน" แล้วคนจะไปล็อกอินซ้ำโดยไม่จำเป็น
        """
        tc.save("tiktok1", REAL, note="ล็อกอินแล้ว")
        tc.save("tiktok1", None, note="อ่านไม่ได้รอบนี้")
        row = tc.load()["tiktok1"]
        self.assertEqual(row["handle"], REAL, "ไอดีเดิมหายไป")
        self.assertTrue(row["stale"], "ไม่ได้ติดธงว่าไอดีอาจเก่าแล้ว")
        self.assertEqual(row["note"], "อ่านไม่ได้รอบนี้")

    def test_never_read_is_not_the_same_as_read_and_failed(self) -> None:
        """ยังไม่เคยตรวจ กับ ตรวจแล้วไม่ผ่าน ต้องแยกออก (กติกา 2.3.1 ข้อ 4)"""
        never = tc.load().get("tiktok5")
        self.assertIsNone(never)
        tc.save("tiktok5", None, note="ยังไม่ได้ล็อกอิน")
        failed = tc.load()["tiktok5"]
        self.assertIsNone(failed["handle"])
        self.assertTrue(failed["stale"])
        self.assertTrue(failed["checked_at"])

    def test_board_shows_the_saved_handle(self) -> None:
        """สิ่งที่จดไว้ต้องไปโผล่ในรายการที่หน้าเว็บดึงไปแสดง"""
        tc.save("tiktok3", REAL, note="ล็อกอินแล้ว")
        row = next(r for r in tc.rows() if r["profile"] == "tiktok3")
        self.assertEqual(row["handle"], REAL)
        self.assertTrue(row["ready"])
        self.assertFalse(row["stale"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
