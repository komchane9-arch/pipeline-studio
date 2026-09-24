from __future__ import annotations

import unittest

import fb_mass_finder as mass


class MassProfileReservationTests(unittest.TestCase):
    def test_disabled_browser_keeps_mass_queue_off_chrome(self) -> None:
        with self.assertRaisesRegex(mass.MassFinderError, "ถูกปิดไว้"):
            mass.mass_browser_profile({
                "browser_enabled": False,
                "bot_profile": "Bot8",
            })

    def test_bot10_is_reserved_for_comment_collector(self) -> None:
        with self.assertRaisesRegex(mass.MassFinderError, "ห้ามใช้ Bot9"):
            mass.mass_browser_profile({
                "browser_enabled": True,
                "bot_profile": "Bot9",
            })

    def test_another_explicit_profile_can_be_enabled_later(self) -> None:
        self.assertEqual(
            mass.mass_browser_profile({
                "browser_enabled": True,
                "bot_profile": "Bot8",
            }),
            "Bot8",
        )


if __name__ == "__main__":
    unittest.main()
