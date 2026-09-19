from __future__ import annotations

import io
import unittest
import tempfile
from pathlib import Path
from unittest import mock

from PIL import Image

import tiktok_product_link as target


class SearchQueryTests(unittest.TestCase):
    def test_tcl_query_prefers_model_over_4k(self) -> None:
        name = "NEW 2026 TCL ทีวี 85 นิ้ว 4K SQD Mini QLED Google TV รุ่น 85Q7D PRO/P7L"
        query = target.build_search_query(name)
        self.assertIn("85Q7D PRO", query)
        self.assertIn("85 นิ้ว", query)
        self.assertNotEqual(query.split()[1], "4K")

    def test_tcl_query_prefers_size_specific_model(self) -> None:
        name = "NEW 2025 TCL TV รุ่น V6C ขนาด 65 นิ้ว 4K UHD Google TV รุ่น 65V6C"
        self.assertEqual(target.build_search_query(name), "TCL 65V6C ทีวี 65 นิ้ว")

    def test_tcl_air_is_not_labelled_as_tv(self) -> None:
        name = "TCL แอร์ Full DC Inverter ขนาด 9200 BTU รุ่น TAC-XAL09CH2"
        self.assertEqual(
            target.build_search_query(name),
            "TCL TAC-XAL09CH2 แอร์ 9200 BTU",
        )


class ConfidenceGateTests(unittest.TestCase):
    def test_redmi_analysis_does_not_pad_offscreen_crop_with_black(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            paths = [folder / name for name in ("target.jpg", "first.png", "second.png")]
            for path in paths:
                Image.new("RGB", (720, 1600), "white").save(path)
            response = mock.Mock()
            response.json.return_value = {"response": '{"match":0,"confidence":"low"}'}
            with mock.patch.object(target.httpx, "post", return_value=response) as post:
                target.analyze_four(*paths, "สินค้า", folder, "full")
            with Image.open(folder / "tiktok-link-four-results.jpg") as collage:
                self.assertGreater(collage.convert("L").crop((570, 45, 1660, 1100)).getextrema()[0], 240)
                # Text labels can be dark, but the former padded crop areas must be white.
                self.assertGreater(collage.convert("L").getpixel((1050, 350)), 240)
                self.assertGreater(collage.convert("L").getpixel((1600, 450)), 240)
            self.assertIn("SAME results grid", post.call_args.kwargs["json"]["prompt"])

    def test_analysis_transport_failure_is_marked_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            paths = [folder / name for name in ("target.jpg", "first.png", "second.png")]
            for path in paths:
                Image.new("RGB", (1080, 2400), "white").save(path)
            with mock.patch.object(target.httpx, "post",
                                   side_effect=RuntimeError("temporary failure")):
                result = target.analyze_four(
                    paths[0], paths[1], paths[2], "สินค้า", folder, "full")
        self.assertTrue(result.get("analysis_error"))
        self.assertIn("ตรวจสี่อันดับไม่ได้", result.get("reason", ""))

    def test_รับทั้งสองชั้นตามเกณฑ์ที่เจ้าของสั่ง(self) -> None:
        """เจ้าของสั่ง 13 ก.ย. 2569 ให้ตัดสินสองชั้น

        ชั้นที่ 1  รหัสรุ่นตรง            -> โมเดลตอบ high   -> เลือกเลย
        ชั้นที่ 2  ยี่ห้อ ชนิด ขนาด ตัวเลือก  -> โมเดลตอบ medium -> เลือกได้

        **คำสั่งกับตัวกรองต้องตรงกัน** ของเดิมรับเฉพาะ high ถ้าไม่แก้ตรงนี้
        ชั้นที่ 2 จะไม่มีวันถูกเลือกเลยแม้คำสั่งจะบอกให้เลือก = แก้แล้วเหมือนไม่ได้แก้
        """
        self.assertEqual(
            target.confident_rank({"match": 3, "confidence": "high"}, {})[0], 3,
            "ชั้นที่ 1 รหัสรุ่นตรง ต้องเลือกเลย")
        self.assertEqual(
            target.confident_rank({"match": 2, "confidence": "medium"}, {})[0], 2,
            "ชั้นที่ 2 ตรงครบสี่อย่าง ต้องเลือกได้")

    def test_rejects_low_confidence_and_uncertain_reference(self) -> None:
        self.assertEqual(
            target.confident_rank({"match": 1, "confidence": "low"}, {})[0], 0)
        self.assertEqual(
            target.confident_rank(
                {"match": 1, "confidence": "high"},
                {"reference_review": True})[0], 0)
        # รูปตั้งต้นน่าสงสัย = ห้ามเลือกแม้ชั้นที่ 2 จะผ่าน
        self.assertEqual(
            target.confident_rank(
                {"match": 1, "confidence": "medium"},
                {"reference_review": True})[0], 0)
        # **ทุกครั้งที่ไม่รับ ต้องบอกเหตุผลด้วย** ไม่ใช่คืนเลข 0 เงียบ ๆ
        # แล้วปล่อยให้ใบงานเก็บแต่เหตุผลของ AI ซึ่งตอนตัดสินผิดจะฟังดูดีเสมอ
        self.assertTrue(
            target.confident_rank({"match": 1, "confidence": "low"}, {})[1])


class ShowcaseStepTests(unittest.TestCase):
    def test_item_flow_does_not_retry_same_item_after_showcase_failure(self) -> None:
        class FakePhone:
            searches = 0

            def __init__(self, *_args, **_kwargs):
                pass

            def clear_and_push(self, _reference, _item_id):
                return "/sdcard/product.jpg"

            def open_search_with_text(self, _query):
                type(self).searches += 1
                return "full"

            def capture(self, path):
                Path(path).touch()

            def swipe(self, *_args):
                pass

            def open_rank(self, *_args, **_kwargs):
                pass

            def copy_current_product_name(self, _fallback):
                # ชื่อจริงที่อ่านได้จากหน้า TikTok ของใบ 29708536674
                # (คัดลอกมาทั้งดุ้นรวมจุดไข่ปลาที่หน้าจอตัดไว้จริง)
                return ("UGREEN 100W สายชาร์จ USB-C to USB-C PD3.0 "
                        "ชาร์จเร็ว 5A มีจอ LE ...")

            def add_current_product_to_showcase(self, *_args, **_kwargs):
                raise target.TikTokLinkError("หน้าจอไม่ยืนยันผลสำเร็จ")

        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            reference = folder / "reference.jpg"
            reference.touch()
            with (
                mock.patch.object(target, "choose_reference", return_value=(
                    reference, {"index": 1, "ok": True},
                )),
                mock.patch.object(target.clip_store, "target_dir", return_value=folder),
                mock.patch.object(target, "PhoneFlow", FakePhone),
                mock.patch.object(target, "analyze_four", return_value={
                    "confidence": "high", "reason": "ตรง", "titles": ["UGREEN"],
                }),
                mock.patch.object(target, "confident_rank", return_value=(1, "")),
            ):
                with self.assertRaisesRegex(target.TikTokLinkError,
                                            "หน้าจอไม่ยืนยันผลสำเร็จ"):
                    target.find_product_link(
                        # ชื่อจริงจากใบงาน 29708536674 — ต้องมีคำบอกชนิดสินค้า
                        # ("สายชาร์จ") ไม่งั้นด่านคำค้นจะหยุดตั้งแต่ก่อนเปิดแอป
                        "phone", "item",
                        {"name": "UGREEN Uno 100W Type C สายชาร์จเร็ว E-Marker "
                                 "สําหรับ iPhone 17 Pro Max"}, folder,
                        log=lambda _message: None,
                    )

        self.assertEqual(1, FakePhone.searches)

    def test_detects_wide_promo_button_from_real_screen_geometry(self) -> None:
        image = Image.new("RGB", (720, 1600), "white")
        for y in range(1440, 1537):
            for x in range(32, 689):
                image.putpixel((x, y), (254, 44, 85))
        self.assertEqual(
            (32, 1440, 690, 1538),
            target.promo_add_button_bounds(image),
        )

    def test_does_not_treat_small_red_card_as_promo_button(self) -> None:
        image = Image.new("RGB", (720, 1600), "white")
        for y in range(1300, 1400):
            for x in range(40, 240):
                image.putpixel((x, y), (254, 44, 85))
        self.assertIsNone(target.promo_add_button_bounds(image))

    def test_ocr_nodes_fallback_exposes_text_and_bounds(self) -> None:
        raw = io.BytesIO()
        Image.new("RGB", (720, 1600), "white").save(raw, format="PNG")
        flow = object.__new__(target.PhoneFlow)
        flow.log = mock.Mock()
        flow.adb_run = mock.Mock(return_value=raw.getvalue())
        engine = mock.Mock(return_value=([
            ([[100, 200], [300, 200], [300, 240], [100, 240]],
             "ข้อมูลโปรโมชั่น", .95),
        ], None))
        with mock.patch("publish_flow.get_ocr_engine", return_value=engine):
            rows = flow.ocr_nodes()
        self.assertEqual("ข้อมูลโปรโมชั่น", rows[0]["text"])
        self.assertEqual((100, 200, 300, 240), rows[0]["bounds"])

    def test_promotion_chevron_base_coordinate_scales_to_redmi_button(self) -> None:
        flow = object.__new__(target.PhoneFlow)
        flow.width, flow.height = 720, 1600
        self.assertEqual((360, 1297), flow.point(540, 1945))

    def test_search_wraps_scrcpy_failure_for_same_job_retry(self) -> None:
        flow = object.__new__(target.PhoneFlow)
        flow.serial = "phone"
        flow.adb = "adb"
        flow.log = mock.Mock()
        flow.swipe = mock.Mock()
        flow.launch_tiktok = mock.Mock()
        flow.tap = mock.Mock()
        flow.adb_run = mock.Mock(return_value=b"")
        with (
            mock.patch.object(target.scrcpy_control, "set_clipboard",
                              side_effect=RuntimeError("server stopped")),
            mock.patch.object(target.time, "sleep"),
        ):
            with self.assertRaisesRegex(target.TikTokLinkError,
                                        "วางคำค้นผ่าน scrcpy ไม่สำเร็จ"):
                flow.open_search_with_text("สินค้า")

    def test_product_title_comes_from_detail_area_not_search_box(self) -> None:
        nodes = [
            {"text": "สายชาร์จ ugreen", "desc": "", "bounds": (192, 100, 408, 136)},
            {"text": "UGREEN สายชาร์จ USB-C to Lightning MFi Certified PD 20W",
             "desc": "", "bounds": (32, 1086, 648, 1205)},
            {"text": "ขายแล้ว 105.7K ชิ้นทางออนไลน์", "desc": "",
             "bounds": (255, 1245, 608, 1279)},
        ]
        found = target.product_title_from_nodes(
            nodes, "Ugreen สายชาร์จ Fast Charging 20W", 1600)
        self.assertIsNotNone(found)
        self.assertIn("USB-C to Lightning", found[0])

    def test_copies_expanded_product_title_without_pasting(self) -> None:
        flow = object.__new__(target.PhoneFlow)
        flow.serial = "phone"
        flow.adb = "adb"
        flow.height = 1600
        flow.log = mock.Mock()
        flow.nodes = mock.Mock(side_effect=[
            [{"text": "UGREEN สายชาร์จ USB-C to Lightning ...", "desc": "",
              "bounds": (32, 1086, 648, 1205)}],
            [{"text": "UGREEN สายชาร์จ USB-C to Lightning MFi Certified PD 20W",
              "desc": "", "bounds": (32, 1086, 648, 1281)}],
        ])
        flow.adb_run = mock.Mock(return_value=b"")
        with (
            mock.patch.object(target.scrcpy_control, "set_clipboard") as copy,
            mock.patch.object(target.time, "sleep"),
        ):
            title = flow.copy_current_product_name("Ugreen สายชาร์จ 20W")
        self.assertIn("MFi Certified", title)
        copy.assert_called_once_with("adb", "phone", title, paste=False)

    def test_title_read_closes_coupon_popup_then_retries_same_step(self) -> None:
        flow = object.__new__(target.PhoneFlow)
        flow.serial = "phone"
        flow.adb = "adb"
        flow.height = 1600
        flow.log = mock.Mock()
        title_nodes = [{
            "text": "UGREEN สายชาร์จ USB-C to Lightning MFi Certified PD 20W",
            "desc": "", "bounds": (32, 1086, 648, 1205),
        }]
        flow.nodes = mock.Mock(side_effect=[[], title_nodes])
        flow.dismiss_blocking_popup = mock.Mock(return_value=True)
        flow.adb_run = mock.Mock(return_value=b"")

        with (
            mock.patch.object(target.scrcpy_control, "set_clipboard") as copy,
            mock.patch.object(target.time, "sleep"),
        ):
            title = flow.copy_current_product_name("Ugreen สายชาร์จ 20W")

        self.assertIn("MFi Certified", title)
        flow.dismiss_blocking_popup.assert_called_once_with()
        copy.assert_called_once_with("adb", "phone", title, paste=False)

    def test_title_read_retries_only_once_after_popup(self) -> None:
        flow = object.__new__(target.PhoneFlow)
        flow.height = 1600
        flow.log = mock.Mock()
        flow.nodes = mock.Mock(return_value=[])
        flow.dismiss_blocking_popup = mock.Mock(return_value=True)

        with mock.patch.object(target.time, "sleep"):
            with self.assertRaisesRegex(target.TikTokLinkError, "อ่านชื่อสินค้า"):
                flow.copy_current_product_name("Ugreen สายชาร์จ 20W")

        self.assertEqual(2, flow.nodes.call_count)
        flow.dismiss_blocking_popup.assert_called_once_with()

    def test_coupon_popup_taps_collect_only_with_coupon_context(self) -> None:
        flow = object.__new__(target.PhoneFlow)
        flow.log = mock.Mock()
        flow.nodes = mock.Mock(return_value=[
            {"text": "รับคูปองส่วนลด", "desc": "", "bounds": (40, 300, 680, 380)},
            {"text": "เก็บ", "desc": "", "bounds": (80, 1000, 640, 1120)},
        ])
        flow.ocr_nodes = mock.Mock(return_value=[])
        flow.tap_actual_bounds = mock.Mock()

        with mock.patch.object(target.time, "sleep"):
            self.assertTrue(flow.dismiss_blocking_popup())

        flow.tap_actual_bounds.assert_called_once_with((80, 1000, 640, 1120))

    def test_search_retries_shop_tab_after_dismissing_popup(self) -> None:
        flow = object.__new__(target.PhoneFlow)
        flow.serial = "phone"
        flow.adb = "adb"
        flow.log = mock.Mock()
        flow.swipe = mock.Mock()
        flow.launch_tiktok = mock.Mock()
        flow.tap = mock.Mock()
        flow.foreground_package = mock.Mock(return_value=target.TIKTOK_PACKAGE)
        flow.tap_text = mock.Mock(side_effect=[False, True])
        flow.dismiss_blocking_popup = mock.Mock(return_value=True)
        flow.dismiss_shop_popup = mock.Mock(return_value=False)
        flow.adb_run = mock.Mock(return_value=b"")

        with (
            mock.patch.object(target.scrcpy_control, "set_clipboard"),
            mock.patch.object(target.time, "sleep"),
        ):
            self.assertEqual("full", flow.open_search_with_text("UGREEN สายชาร์จ"))

        self.assertEqual(2, flow.tap_text.call_count)
        flow.dismiss_blocking_popup.assert_called_once_with()
        # ไม่ใช้พิกัด fallback ของแท็บ เพราะอ่านเจอหลังปิด popup แล้ว.
        flow.tap.assert_called_once_with(1000, 160)

    def test_adds_product_and_waits_for_success_state(self) -> None:
        flow = object.__new__(target.PhoneFlow)
        flow.serial = "phone"
        flow.adb = "adb"
        flow.log = mock.Mock()
        flow.foreground_package = mock.Mock(return_value=target.TIKTOK_PACKAGE)
        flow.tap_text = mock.Mock(return_value=True)
        flow.tap = mock.Mock()
        flow.nodes = mock.Mock(side_effect=[
            [{"text": "ข้อมูลโปรโมชั่น เพิ่มในโชว์เคส", "desc": ""}],
            [{"text": "ข้อมูลโปรโมชั่น สำรวจสินค้าสำหรับคุณ", "desc": ""}],
        ])

        with mock.patch.object(target.time, "sleep"):
            flow.add_current_product_to_showcase()

        flow.tap_text.assert_called_once_with("เพิ่มในโชว์เคส")
        flow.tap.assert_not_called()  # แผงเปิดอยู่แล้ว จึงไม่แตะพิกัดลูกศรซ้ำ

    def test_accepts_closed_panel_after_text_tap_with_visual_proof(self) -> None:
        flow = object.__new__(target.PhoneFlow)
        flow.serial = "phone"
        flow.adb = "adb"
        flow.log = mock.Mock()
        flow.foreground_package = mock.Mock(return_value=target.TIKTOK_PACKAGE)
        flow.tap_text = mock.Mock(return_value=True)
        flow.tap = mock.Mock()
        flow.nodes = mock.Mock(return_value=[
            {"text": "ข้อมูลโปรโมชั่น เพิ่มในโชว์เคส", "desc": ""},
        ])
        flow.promo_button_from_screen = mock.Mock(side_effect=[
            (32, 1440, 688, 1536), None,
        ])

        with mock.patch.object(target.time, "sleep"):
            flow.add_current_product_to_showcase()

        flow.tap_text.assert_called_once_with("เพิ่มในโชว์เคส")

    def test_already_added_create_now_state_is_success_without_tapping(self) -> None:
        flow = object.__new__(target.PhoneFlow)
        flow.serial = "phone"
        flow.adb = "adb"
        flow.log = mock.Mock()
        flow.foreground_package = mock.Mock(return_value=target.TIKTOK_PACKAGE)
        flow.tap_text = mock.Mock()
        flow.tap = mock.Mock()
        flow.nodes = mock.Mock(return_value=[
            {"text": "", "desc": "สร้างตอนนี้เลย"},
        ])

        flow.add_current_product_to_showcase()

        flow.tap_text.assert_not_called()
        flow.tap.assert_not_called()

    def test_canvas_showcase_success_is_read_before_any_second_tap(self) -> None:
        flow = object.__new__(target.PhoneFlow)
        flow.foreground_package = mock.Mock(return_value=target.TIKTOK_PACKAGE)
        flow.nodes = mock.Mock(return_value=[{"text": "ข้อมูลโปรโมชั่น", "desc": ""}])
        flow.ocr_nodes = mock.Mock(return_value=[{"text": "สำรวจสินค้าสำหรับคุณ"}])
        flow.tap_text = mock.Mock()
        flow.tap = mock.Mock()
        flow.add_current_product_to_showcase()
        flow.tap.assert_not_called()
        flow.tap_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
