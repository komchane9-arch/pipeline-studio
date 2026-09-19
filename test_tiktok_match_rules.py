"""ด่านกันผูกสินค้าผิดตัว — ทดสอบด้วย **ข้อความจริงจากใบงานจริง** เท่านั้น

ทุกสายอักขระในไฟล์นี้คัดลอกมาทั้งดุ้นจาก ``data/**/run.json`` ของจริง
รวมทั้งที่สะกดผิดและวรรณยุกต์ที่ตัวอ่านภาพทำตก **ห้ามแต่งข้อความสวย ๆ
มาทดสอบเอง** — เคยพลาดมาแล้ว: ทดสอบการจับคำไทยด้วยข้อความที่สะกดถูก
ทั้งที่ของจริงมาจากการอ่านจอซึ่งวรรณยุกต์หายไป ตัวแก้จึงไม่เคยทำงานเลย

ที่มาของแต่ละชุดข้อมูลเขียนกำกับไว้เป็นรหัสใบงาน เปิดไปดูของจริงได้
"""

from __future__ import annotations

import unittest

import tiktok_match_rules as rules


# ---- ใบ 52807075353 — ใบที่ TikTok ตีธง 14 ก.ย. 2569 ----------------------
FLAGGED_NAME = ("[972]buy①get⑤🎁 สำหรับ Vivo X300 X300 pro X200 ultra X300fe "
                "X200 pro mini  X100 X100 pro X90 X80 X70 X200fe  V23 V25pro "
                "V27 V40 V70 เคสdiandu")
FLAGGED_QUERY = ("สำหรับ Vivo X300 X300 pro X200 ultra X300fe X200 pro mini "
                 "X100 X100 pro X90 X80 X70 X200fe V23 V25pro V27 V40 V70 "
                 "เคสdiandu")
FLAGGED_TITLE = "x300 ultra x3oo pro x300 x3oo"
FLAGGED_REASON = ("The target product is a decorative phone case with a "
                  "glittery finish and a Hello Kitty design. The first listing "
                  "shows a decorative phone case with a similar glittery finish "
                  "and Hello Kitty design, matching the target product.")
FLAGGED_LISTING = "Lereach Anti-Spy HD Glass สำหรับ Vivo X300..."


class TitleCheckTests(unittest.TestCase):
    """ข้อ 1 — อ่านชื่อจากหน้า TikTok แล้วไม่ใช่ชื่อสินค้า = ห้ามผูก"""

    def test_flagged_title_is_rejected_with_every_reason(self) -> None:
        verdict = rules.title_check(FLAGGED_TITLE, FLAGGED_NAME)
        self.assertIs(verdict.ok, False)
        # ผิดพร้อมกันทุกข้อที่เจ้าของระบุ: สั้น · มีแต่รหัสรุ่น · ไม่มีชนิดสินค้า
        # · คำซ้ำ · อ่านเพี้ยน (x3oo คือ x300)
        for problem in ("too_short", "no_type_word", "codes_only",
                        "repeated", "garbled"):
            self.assertIn(problem, verdict.problems)

    def test_ocr_misread_brand_is_rejected(self) -> None:
        """ใบ 41707120950 · 23645899829 — ตัวอ่านภาพสะกดยี่ห้อผิดหนึ่งตัว"""
        for title in ("ugreem nexode 65w/ universal travel",
                      "mall] ฮับ usb, ugreem,"):
            verdict = rules.title_check(
                title, "UGREEN Nexode 65W Universal Travel Adapter ปลั๊กสลับได้")
            self.assertIs(verdict.ok, False, title)
            self.assertIn("garbled", verdict.problems, title)

    def test_real_product_titles_still_pass(self) -> None:
        """ชื่อจริงที่อ่านได้ครบต้องผ่าน ไม่งั้นด่านนี้จะปฏิเสธทุกใบ"""
        good = [
            # ใบ 28829283590
            ("NEW 2026 TCL แอร์ ขนาด 9,200 BTU SaveIN Series ระบบ Full DC "
             "Inverter รุ่น TAC-XAL09CH2",
             "TCL แอร์ Full DC Inverter ขนาด 9200 BTU รุ่น TAC-XAL09CH2"),
            # ใบ 29708428217 — วรรณยุกต์ต่างจากใบงานเพราะอ่านมาจากภาพ
            ("ugreen เคส iphone สำหรับ 16 pro max เคส",
             "Ugreen เคส iPhone สําหรับ iPhone 16 Pro Max เคสกันกระแทกแบบใส"),
            # ใบ 42653351351
            ("PATARA โซฟาขนแกะ รุ่น INNER โซฟา โซฟาปรับนอน โซฟาปรับระดับ นุ่ม",
             "PATARA โซฟาขนแกะ รุ่น INNER โซฟา โซฟาปรับนอน โซฟาปรับระดับ นุ่ม"),
            # ใบ 58105793156
            ("รุ่นใหม่ pocket wifi6 ใส่ซิม wireless",
             "Pocket WiFi6 ใส่ซิม Wireless 3000mAh 4G Router SIM AIS True NT"),
        ]
        for title, name in good:
            self.assertIs(rules.title_check(title, name).ok, True, title)

    def test_unread_title_is_not_a_failed_title(self) -> None:
        """กติกา 2.3.1 — "ยังไม่ได้ตรวจ" ต้องไม่หน้าตาเหมือน "ตรวจแล้วไม่ผ่าน" """
        self.assertIsNone(rules.title_check("", FLAGGED_NAME).ok)
        # ใบ 41625762598 — ชื่อถูกตัดท้ายจนคำว่า Charger หายไป ไม่ใช่ชื่อปลอม
        cut = rules.title_check(
            "【Qi2.2】UGREEN รูปทรงจรวด UNO MPP 2-in-1 MagFlow Wireless 25W Cha ...",
            "UGREEN รูปทรงจรวด UNO MPP 2-in-1 MagFlow Wireless 25W Charger")
        self.assertIsNone(cut.ok)
        self.assertIn("title_truncated", cut.problems)


class SearchQueryTests(unittest.TestCase):
    """ข้อ 2 — คำค้นต้องมีคำบอกชนิดสินค้า ไม่ใช่รหัสรุ่นล้วน"""

    def test_compat_list_query_is_compressed_to_say_what_it_is(self) -> None:
        fixed, note = rules.improve_query(FLAGGED_QUERY, FLAGGED_NAME)
        self.assertTrue(note)
        self.assertEqual("เคส vivo X300", fixed)
        self.assertIs(rules.query_check(fixed).ok, True)

    def test_query_without_any_type_word_fails(self) -> None:
        # ใบ 28721190301 — ชื่อไม่เคยบอกเลยว่ามันคือสาย
        verdict = rules.query_check("Ugreen USB C ถึง USB Type C สําหรับ Samsung S24")
        self.assertIs(verdict.ok, False)
        self.assertIn("no_type_word", verdict.problems)

    def test_descriptive_query_is_left_alone(self) -> None:
        """ชื่อที่บรรยายสินค้าจริงห้ามถูกย่อ — ย่อแล้วเสียของ (ใบ 23645899829)"""
        real = ("Ugreen ฮับ USB C 10Gbps 4K60Hz 9 in 1 Type C เป็น HDMI RJ45 "
                "Ethernet PD100W สําหรับ MacBook iPad Huawei Sumsang PC")
        fixed, note = rules.improve_query(real, real)
        self.assertEqual(real, fixed)
        self.assertEqual("", note)


class EvidenceTests(unittest.TestCase):
    """ข้อ 3 — ห้ามตัดสินว่าตรงจากหน้าตาอย่างเดียว"""

    def test_lookalike_reason_is_refused(self) -> None:
        verdict = rules.evidence_check(
            {"match": 1, "confidence": "high", "reason": FLAGGED_REASON,
             "titles": [FLAGGED_LISTING, "", "", ""]},
            FLAGGED_NAME)
        self.assertIs(verdict.ok, False)
        self.assertIn("looks_only_reason", verdict.problems)
        # ประกาศที่เลือกเป็น "ฟิล์ม" ทั้งที่ใบงานเป็น "เคส"
        self.assertIn("type_mismatch", verdict.problems)

    def test_model_stating_image_only_is_refused(self) -> None:
        verdict = rules.evidence_check(
            {"match": 1, "evidence": "image_only", "reason": "รูปเหมือนกัน",
             "titles": ["เคสมือถือ Vivo X300", "", "", ""]}, FLAGGED_NAME)
        self.assertIs(verdict.ok, False)
        self.assertIn("image_only", verdict.problems)

    def test_unreadable_listing_is_unknown_not_failed(self) -> None:
        """อ่านชื่อประกาศไม่ได้ = ยังพิสูจน์ไม่ได้ ไปพิสูจน์ต่อที่หน้าสินค้า"""
        verdict = rules.evidence_check(
            {"match": 1, "reason": "The listing shows the same model code",
             "titles": []},
            "TCL ทีวี 55 นิ้ว รุ่น 55Q7D PRO 4K SQD Mini QLED Google TV")
        self.assertIsNone(verdict.ok)
        self.assertIn("no_listing_title", verdict.problems)

    def test_same_family_different_word_is_not_a_clash(self) -> None:
        """ใบ 9983149742 · 47350858748 — เรียกคนละชื่อแต่ของกลุ่มเดียวกัน"""
        self.assertIsNone(rules.type_clash(
            "Ugreen อะแดปเตอร์ฮับ USB 4K 60Hz USB C เป็น HDMI 2.0 RJ45",
            "UGREEN, 4K 60Hz, 10-in-1 Docking Station"))
        self.assertIsNone(rules.type_clash(
            "UGREEN Magflow Magnetic Wireless 10000mAh สายเคเบิลในตัว "
            "Fast Charging Power Bank",
            "【CCC Certified】UGREEN Magnetic Power Bank Qi2 25W 10000mAh"))


class NameAgreementTests(unittest.TestCase):
    def test_flagged_page_title_shares_nothing_but_model_codes(self) -> None:
        verdict = rules.name_agreement(FLAGGED_TITLE, FLAGGED_NAME)
        self.assertIs(verdict.ok, False)
        self.assertIn("no_shared_word", verdict.problems)

    def test_real_matching_pair_passes(self) -> None:
        # ใบ 29708536674 — จุดไข่ปลาท้ายชื่อมีอยู่จริงบนหน้าจอ
        self.assertIs(rules.name_agreement(
            "UGREEN 100W สายชาร์จ USB-C to USB-C PD3.0 ชาร์จเร็ว 5A มีจอ LE ...",
            "UGREEN Uno 100W Type C สายชาร์จเร็ว E-Marker สําหรับ iPhone 17 Pro Max",
        ).ok, True)


class GenericLookalikeTests(unittest.TestCase):
    """ข้อ 4 — ของทั่วไปที่หน้าตาซ้ำทั้งตลาด ต้องให้เจ้าของยืนยันเสมอ"""

    def test_no_brand_phone_case_needs_owner(self) -> None:
        verdict = rules.generic_lookalike(FLAGGED_NAME)
        self.assertIs(verdict.ok, True)
        self.assertIn("generic_lookalike", verdict.problems)

    def test_branded_case_does_not_need_the_extra_gate(self) -> None:
        # ใบ 29708428217 — เคสเหมือนกัน แต่มียี่ห้อ UGREEN กำกับ
        self.assertIs(rules.generic_lookalike(
            "Ugreen เคส iPhone สําหรับ iPhone 16 Pro Max เคสกันกระแทกแบบใส",
        ).ok, False)

    def test_tv_is_not_a_lookalike_commodity(self) -> None:
        self.assertIs(rules.generic_lookalike(
            "TCL ทีวี 55 นิ้ว รุ่น 55Q7D PRO 4K SQD Mini QLED Google TV").ok,
            False)


class ProductTypeReadingTests(unittest.TestCase):
    """ชนิดสินค้าต้องอ่านจากชื่อจริงให้ถูก ไม่งั้นด่านข้างบนตัดสินผิดหมด"""

    def test_type_word_must_not_come_from_inside_another_word(self) -> None:
        cases = [
            # ใบ 44416841132 — "iWatch" ไม่ได้แปลว่าสินค้าคือนาฬิกา
            ("ที่ชาร์จ", "UGREEN MagFlow Qi 2 25W 3-IN-1 เครื่องชาร์จไร้สาย"
                         "สําหรับ iPhone 17 Pro Max AirPods iWatch"),
            # ใบ 43009371400 — "ไร้สายชาร์จ" ไม่ได้แปลว่าเป็นสายชาร์จ
            ("พาวเวอร์แบงค์", "UGREEN Qi2 15W PD20W 10000mAh แม่เหล็กไร้สาย"
                              "ชาร์จเร็ว 2-in-1 Power Bank"),
            # ใบ 2374652255 — "อุปกรณ์หูฟัง" คือของที่ใส่ในกล่อง ไม่ใช่ตัวสินค้า
            ("กล่องเก็บของ", "UGREEN กล่องเก็บอุปกรณ์หูฟัง เมมโมรี่การ์ด "
                             "ขนาด 8x8x4 ซม. ไซซ์ S"),
            # ใบ 24834702222 — เคสที่มีขาตั้ง ยังเป็นเคส
            ("เคสมือถือ", "Ugreen เคสโทรศัพท์ MagSafe สําหรับ iPhone 16 Series "
                          "ขาตั้งกล้องแม่เหล็กป้องกัน"),
            # ใบ 27389325800 — "แผ่นฟิล์ม" ต้องอ่านออกว่าเป็นฟิล์ม
            ("ฟิล์มกันจอ", "【for iPhone 17 Series】UGREEN แผ่นฟิล์มกระจก"
                           "ปกป้องหน้าจอ 2 ชิ้น ทนทาน"),
        ]
        for want, name in cases:
            self.assertEqual(want, rules.main_type(name), name[:40])


if __name__ == "__main__":                                      # pragma: no cover
    unittest.main()
