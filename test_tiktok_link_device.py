"""ทดสอบการเลือก REDMI 15C สายวิดีโอสำหรับหาลิงก์โดยไม่แตะมือถือจริง."""

from __future__ import annotations

import json
import unittest
from unittest import mock

import clip_app as target


class _Response:
    def __init__(self, devices: list[dict]):
        self.payload = json.dumps({"ok": True, "devices": devices}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.payload


class TikTokLinkDeviceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.book = {
            "video": {"name": "REDMI 15C — วิดีโอ", "model": "25078RA3EA"},
            "spare": {"name": "REDMI 15C - สำรอง", "model": "25078RA3EA"},
        }
        self.devices = mock.Mock()
        self.devices.enabled_serials.return_value = ["video"]
        self.devices.get.side_effect = self.book.get
        self.devices.label.side_effect = lambda serial: self.book[serial]["name"]
        self.tiktok_bot = mock.Mock()
        self.tiktok_bot.supports.side_effect = lambda serial: serial == "video"

    def choose(self, live: list[dict]) -> tuple[str, str]:
        with (
            mock.patch.dict("sys.modules", {
                "devices": self.devices,
                "tiktok_publish_bot": self.tiktok_bot,
            }),
            mock.patch.object(target.urllib.request, "urlopen", return_value=_Response(live)),
        ):
            return target._auto_tiktok_link_device()

    def test_selects_connected_video_redmi(self) -> None:
        serial, why = self.choose([
            {"serial": "video", "state": "device", "ready": True},
            {"serial": "spare", "state": "offline", "ready": False},
        ])
        self.assertEqual(serial, "video")
        self.assertEqual(why, "")

    def test_ignores_connected_spare_redmi(self) -> None:
        serial, why = self.choose([
            {"serial": "video", "state": "device", "ready": True},
            {"serial": "spare", "state": "device", "ready": True},
        ])
        self.assertEqual(serial, "video")
        self.assertEqual(why, "")

    def test_reports_when_video_redmi_is_offline(self) -> None:
        serial, why = self.choose([
            {"serial": "video", "state": "offline", "ready": False},
            {"serial": "spare", "state": "offline", "ready": False},
        ])
        self.assertEqual(serial, "")
        self.assertIn("ยังไม่ได้เชื่อมต่อ", why)


if __name__ == "__main__":
    unittest.main()
