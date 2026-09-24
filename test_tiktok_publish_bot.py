from __future__ import annotations

import io
import random
import unittest
from pathlib import Path

from PIL import Image

import publish_flow
import tiktok_publish_bot as bot


ROOT = Path(__file__).resolve().parent


class _ScreenContext:
    def __init__(self, png: bytes):
        self.png = png

    def run_adb(self, *args):
        return self.png


class TikTokPublishBotTests(unittest.TestCase):
    def test_exact_resume_retries_failed_step_without_reporting_step_one_again(self):
        reports = []

        class Context:
            serial = bot.SUPPORTED_SERIAL
            hashtags = ["ทดสอบ"]
            tag_results = []
            wake_screen = staticmethod(lambda: "จอพร้อม")
            send_clip = staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("ส่งไม่สำเร็จ")))
            report = staticmethod(lambda step, ok, message: reports.append((step.id, ok)))
            log = staticmethod(lambda message: None)

        run = {
            "tiktok_product_link": {
                "status": "showcase_added", "showcase_added": True,
                "confidence": "human_confirmed",
            },
        }
        result = bot.run(Context(), run, resume_step_id="send_clip", resume_step_no=2)
        self.assertFalse(result["ok"])
        self.assertEqual(1, result["done"])
        self.assertEqual([("send_clip", False)], reports)

    def test_foreground_accepts_tiktok_package_activity_pair(self):
        self.assertTrue(bot.is_tiktok_foreground(
            "com.ss.android.ugc.trill/com.ss.android.ugc.aweme.splash.SplashActivity"))
        self.assertFalse(bot.is_tiktok_foreground(
            "com.android.chrome/com.google.android.apps.chrome.Main"))

    def test_shop_results_accepts_large_canvas_product_cover_without_price(self):
        xml = ('<node text="ร้านค้า" selected="true" bounds="[239,178][368,258]" />'
               '<node resource-id="com.ss.android.ugc.trill:id/cover" '
               'class="android.widget.ImageView" bounds="[12,516][354,972]" />')
        self.assertTrue(bot.shop_results_visible(xml))
        self.assertFalse(bot.shop_results_visible(
            '<node text="ร้านค้า" bounds="[239,178][368,258]" />'))

    def test_shop_results_accepts_two_loaded_canvas_card_frames(self):
        xml = ('<node text="ร้านค้า" selected="true" bounds="[239,178][368,258]" />'
               '<node class="android.view.ViewGroup" bounds="[12,516][354,858]" />'
               '<node class="android.view.ViewGroup" bounds="[366,516][708,858]" />')
        self.assertTrue(bot.shop_results_visible(xml))

    def test_product_card_page_is_not_detail_until_buy_now_bar_exists(self):
        card = ('<node text="ร้านค้า" />'
                '<node text="NEW 2026 TCL TAC-XAL09CH2" />'
                '<node text="ซื้อ" />')
        detail = card + '<node text="แชท" /><node text="ซื้อเลย" />'
        self.assertFalse(bot.product_detail_visible(card))
        self.assertTrue(bot.product_detail_visible(detail))

    def test_finds_only_truncated_product_title_expand_area(self):
        run = {"name": "TCL แอร์ รุ่น TAC-XAL09CH2"}
        xml = ('<node text="TCL TAC-XAL09CH2" bounds="[100,90][624,162]" />'
               '<node text="NEW 2026 TCL แอร์ ขนา ..." bounds="[32,1424][630,1462]" />')
        self.assertEqual((558, 1424, 630, 1462),
                         bot.truncated_product_title_bounds(run, xml))

    def test_contacts_prompt_denial_is_a_clickable_target(self):
        xml = ('<node text="อนุญาตให้เข้าถึงรายชื่อติดต่อของคุณ" '
               'clickable="false" bounds="[120,684][592,869]" />'
               '<node text="ไม่อนุญาต" clickable="true" '
               'bounds="[80,910][359,1005]" />')
        self.assertEqual((80, 910, 359, 1005),
                         bot.find_bounds(xml, ("ไม่อนุญาต",)))

    def test_coupon_popup_is_closed_only_when_coupon_heading_is_present(self):
        instance = bot.Bot.__new__(bot.Bot)
        xml = ('<node text="รับคูปองส่วนลด" />'
               '<node text="เก็บ" clickable="true" bounds="[110,1134][610,1248]" />')
        tapped = []
        instance.xml = lambda: xml
        instance.tap = lambda target, settle=0: tapped.append(target.label)
        instance.c = type("Context", (), {})()
        message = instance.dismiss_soft_prompts()
        self.assertEqual("ปิดป๊อปอัปรับคูปองแล้ว", message)
        self.assertEqual(["ปิดป๊อปอัปรับคูปอง"], tapped)

    def test_promotion_step_retries_after_closing_popup(self):
        instance = bot.Bot.__new__(bot.Bot)
        events = []
        instance.c = type("Context", (), {"log": events.append})()
        instance.tap = lambda target, settle=0: events.append(target.label)
        instance.wait_text = lambda *args, **kwargs: '<node text="รับคูปองส่วนลด" />'
        instance.dismiss_soft_prompts = lambda: "ปิดป๊อปอัปรับคูปองแล้ว"
        instance.xml = lambda: '<node text="ข้อมูลโปรโมชั่น" />'
        instance.promotion_panel_visible = lambda: False
        xml, ok = instance.open_promotion_panel('<node text="ซื้อเลย" />')
        self.assertTrue(ok)
        self.assertIn("ข้อมูลโปรโมชั่น", xml)
        self.assertEqual(1, events.count("ลูกศรขึ้นสองขีด"))

    def test_detects_canvas_promotion_chooser_from_trained_screen(self):
        image = Image.open(
            ROOT / "data/evidence/train-tiktok-promotion-chooser.png")
        self.assertTrue(bot.promotion_chooser_visible(image))
        self.assertFalse(bot.promotion_chooser_visible(
            Image.new("RGB", (720, 1600), "white")))

    def test_jitter_never_leaves_button(self):
        random.seed(2569)
        bounds = (100, 200, 121, 221)
        for _ in range(3000):
            x, y = publish_flow.humanize_point_in_bounds(bounds, 720, 1600, 6, 4)
            self.assertLessEqual(104, x)
            self.assertLessEqual(x, 116)
            self.assertLessEqual(204, y)
            self.assertLessEqual(y, 216)

    def test_finds_real_showcase_button_bounds(self):
        xml = (ROOT / "data/evidence/train-tiktok-double-chevron.xml").read_text("utf-8")
        self.assertEqual((32, 1440, 688, 1528),
                         bot.find_bounds(xml, ("เพิ่มในโชว์เคส",)))

    def test_exact_labels_win_over_similar_rows(self):
        profile = (ROOT / "data/evidence/train-tiktok-profile.xml").read_text("utf-8")
        editor = (ROOT / "data/evidence/train-tiktok-next2.xml").read_text("utf-8")
        self.assertEqual((576, 1470, 720, 1568), bot.find_bounds(profile, ("โปรไฟล์",)))
        self.assertEqual((288, 1470, 432, 1568), bot.find_bounds(profile, ("สร้าง",)))
        self.assertEqual((368, 1456, 696, 1544), bot.find_bounds(editor, ("โพสต์",)))

    def test_clickable_hashtag_suggestion_wins_over_caption_text(self):
        xml = ('<node text="#ตัดไฟเอง" clickable="false" bounds="[32,294][186,333]" />'
               '<node text="#ตัดไฟเอง" clickable="true" bounds="[16,620][704,710]" />')
        self.assertEqual((16, 620, 704, 710),
                         bot.find_clickable_bounds(xml, ("#ตัดไฟเอง",)))

    def test_hashtag_text_uses_nearest_clickable_parent_row(self):
        xml = ('<hierarchy><node clickable="true" bounds="[0,612][720,714]">'
               '<node clickable="false" bounds="[32,644][176,682]" '
               'text="#ล้างตัวเอง" /></node></hierarchy>')
        self.assertEqual((0, 612, 720, 714),
                         bot.find_clickable_bounds(xml, ("#ล้างตัวเอง",)))

    def test_extracts_real_model_but_ignores_network_spec(self):
        self.assertEqual(["TCL", "27P2A"],
                         bot._model_terms("TCL Monitor 27 นิ้ว รุ่น 27P2A Gaming Mini LED"))
        self.assertEqual(["UGREEN"],
                         bot._model_terms("UGREEN เมาส์ไร้สาย 4000 DPI 2.4G"))

    def test_resume_after_human_check_requires_matched_high_and_screen_identity(self):
        instance = bot.Bot.__new__(bot.Bot)
        instance.run = {
            "name": "NEW 2025 TCL ทีวี 65 นิ้ว รุ่น 65T6C/T6D",
            "tiktok_product_link": {"status": "matched", "confidence": "high"},
        }
        xml = '<node text="TCL ทีวี 65 นิ้ว 4K QLED" bounds="[0,0][10,10]" />'
        self.assertTrue(instance.verify_current_after_human_check(xml))
        instance.run["tiktok_product_link"]["confidence"] = "low"
        self.assertFalse(instance.verify_current_after_human_check(xml))

    def test_recognizes_trained_success_banner(self):
        png = bot.SUCCESS_REFERENCE.read_bytes()
        instance = bot.Bot.__new__(bot.Bot)
        instance.c = _ScreenContext(png)
        self.assertTrue(instance.success_banner_visible())

        blank = Image.new("RGB", (720, 1600), "black")
        raw = io.BytesIO()
        blank.save(raw, format="PNG")
        instance.c = _ScreenContext(raw.getvalue())
        self.assertFalse(instance.success_banner_visible())

    def test_accepts_lynx_anchor_length_when_input_hides_text(self):
        hidden = ('<node text="ชื่อสินค้า19/30" />'
                  '<node class="com.bytedance.ies.xelement.input.LynxInputView" text="" />')
        self.assertTrue(bot.Bot.anchor_name_entered(hidden))
        self.assertFalse(bot.Bot.anchor_name_entered(hidden.replace("19/30", "30/30")))

    def test_rename_page_can_be_identified_by_anchor_input_desc(self):
        xml = ('<node text="NEW 2026 TCL" content-desc="edit_anchor_name_input" />'
               '<node content-desc="edit_anchor_add_button" />')
        self.assertIn("edit_anchor_name_input", xml)

    def test_showcase_state_replaces_product_url_preflight(self):
        run = {
            "tiktok_product_link": {
                "status": "showcase_added",
                "showcase_added": True,
                "confidence": "human_confirmed",
            },
        }
        self.assertTrue(bot.showcase_prepared(run))
        run["tiktok_product_link"]["showcase_added"] = False
        self.assertFalse(bot.showcase_prepared(run))

    def test_new_anchor_name_is_the_trained_short_label(self):
        self.assertEqual("กดซื้อเลย", bot.ANCHOR_NAME)
        hidden = ('<node text="ชื่อสินค้า9/30" />'
                  '<node class="com.bytedance.ies.xelement.input.LynxInputView" text="" />')
        self.assertTrue(bot.Bot.anchor_name_entered(hidden))

    def test_saved_product_must_match_name_not_only_saved_rank(self):
        run = {"name": "สินค้า Shopee",
               "tiktok_product_link": {
                   "tiktok_product_name":
                       "UGREEN สายชาร์จ USB-C to Lightning MFi Certified PD 20W",
                   "selected_rank": 1,
               }}
        correct = '<node text="UGREEN สายชาร์จ USB-C to Lightning PD 20W" />'
        wrong = '<node text="UGREEN เคสโทรศัพท์ MagSafe iPhone 16 Pro Max" />'
        self.assertTrue(bot.saved_product_matches(run, correct))
        self.assertFalse(bot.saved_product_matches(run, wrong))

    def test_fresh_feed_requires_all_hashtags_and_seconds_timestamp(self):
        run = {"hashtags": ["Ugreen", "สายชาร์จไอโฟน", "ตัดไฟเอง"]}
        good = ("อาไท รีวิว · 1 วินาทีก่อน "
                "#Ugreen #สายชาร์จไอโฟน #ตัดไฟเอง")
        self.assertTrue(bot.fresh_post_visible(run, good))
        self.assertFalse(bot.fresh_post_visible(run, good.replace("#ตัดไฟเอง", "")))
        self.assertFalse(bot.fresh_post_visible(run, good.replace("1 วินาทีก่อน", "1 วันก่อน")))


if __name__ == "__main__":
    unittest.main()
