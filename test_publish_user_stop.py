"""ทดสอบปุ่ม Stop โดยไม่แตะมือถือ ไม่เปิด auto และไม่โพสต์จริง."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

import app
import publish_flow
import publish_stop
import tiktok_product_link


class FakeStore:
    def sequence(self, _target: str):
        return [publish_flow.Step(id="open", name="เปิดแอป", kind="tap")]


class PublishUserStopTests(unittest.TestCase):
    def test_stopped_flow_never_taps(self):
        stop = threading.Event()
        stop.set()
        tapped: list[tuple[int, int]] = []
        context = publish_flow.RunContext(
            serial="test", store=FakeStore(), target="shopee_video",
            screen=(720, 1600), tap=lambda x, y: tapped.append((x, y)),
            type_text=lambda _text: None, run_adb=lambda *_args: b"",
            stop=stop.is_set,
        )
        result = publish_flow.run_flow(context)
        self.assertTrue(result["stopped"])
        self.assertFalse(result["ok"])
        self.assertEqual([], tapped)

    def test_stop_wins_before_irreversible_gate(self):
        state = {"stop": threading.Event(), "irreversible": False}
        state["stop"].set()
        self.assertFalse(app._publish_begin_irreversible(state))
        self.assertFalse(state["irreversible"])

    def test_post_gate_wins_then_stop_must_not_cancel(self):
        state = {"stop": threading.Event(), "irreversible": False}
        self.assertTrue(app._publish_begin_irreversible(state))
        self.assertTrue(state["irreversible"])

    def test_stopped_item_is_persisted_at_front(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            publish_stop.pin(root, "facebook_reels", "b")
            rows = [{"item_id": "a"}, {"item_id": "b"}, {"item_id": "c"}]
            self.assertEqual(["b", "a", "c"], [r["item_id"] for r in
                                                  publish_stop.first(root, "facebook_reels", rows)])
            publish_stop.clear(root, "facebook_reels", "b")
            self.assertEqual(["a", "b", "c"], [r["item_id"] for r in
                                                  publish_stop.first(root, "facebook_reels", rows)])

    def test_stopped_progress_can_reset_but_not_resume(self):
        controls = app._progress_controls({
            "status": "stopped", "target": "tiktok", "step": 4, "lines": [],
        })
        self.assertFalse(controls["can_resume"])
        self.assertTrue(controls["can_reset"])

    def test_tiktok_product_phone_stops_before_next_adb_command(self):
        phone = tiktok_product_link.PhoneFlow.__new__(tiktok_product_link.PhoneFlow)
        phone.stop = lambda: True
        with self.assertRaises(tiktok_product_link.TikTokLinkStopped):
            phone.adb_run("shell", "input", "tap", "1", "1")

    def test_tiktok_stop_turns_off_search_and_publish(self):
        stored: list[dict] = []
        original = app.studio_shared.update_json

        def fake_update(_path, change, default=None, **_kwargs):
            data = {"clip_auto_approve": {
                "tiktok_link": True, "tiktok_publish": True,
                "shopee_post": True,
            }}
            result = change(data)
            stored.append(result if result is not None else data)
            return stored[-1]

        try:
            app.studio_shared.update_json = fake_update
            app._disable_publish_auto("tiktok")
        finally:
            app.studio_shared.update_json = original
        flags = stored[-1]["clip_auto_approve"]
        self.assertFalse(flags["tiktok_link"])
        self.assertFalse(flags["tiktok_publish"])
        self.assertTrue(flags["shopee_post"])

    def test_ui_stop_is_always_enabled_for_all_three_boxes(self):
        source = (Path(__file__).parent / "web" / "video.js").read_text(encoding="utf-8")
        self.assertIn('textContent: "■ Stop", disabled: false', source)
        self.assertIn('appendPublishControls(box, null, bucket.key)', source)
        self.assertIn('body: JSON.stringify({ target })', source)


if __name__ == "__main__":
    unittest.main()
