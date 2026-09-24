from __future__ import annotations

import subprocess
import unittest
from unittest import mock

import fb_account_guard as guard


def _xml(*nodes: str) -> str:
    return (
        '<hierarchy><node bounds="[0,0][720,1600]" clickable="false">'
        + "".join(nodes) + "</node></hierarchy>"
    )


def _node(x1: int, y1: int, x2: int, y2: int, desc: str = "") -> str:
    return (f'<node bounds="[{x1},{y1}][{x2},{y2}]" clickable="true" '
            f'content-desc="{desc}" text="" />')


class FacebookAccountGuardTests(unittest.TestCase):
    def test_preaw_with_english_statistics(self):
        xml = '<hierarchy><node text="Preaw Buchakorn"/><node text="1,234 friends"/><node text="20 posts"/><node text="Edit profile"/></hierarchy>'
        self.assertEqual(guard._name_near_marker(xml), 'Preaw Buchakorn')

    def test_statistics_without_identity_fail_closed(self):
        xml = '<hierarchy><node text="14 posts"/><node text="followers"/><node text="Edit profile"/></hierarchy>'
        self.assertEqual(guard._name_near_marker(xml), '')

    def test_mixed_language_profile_statistics_are_not_account_name(self):
        xml = '<hierarchy><node text="Khao Fang Nichapa"/><node text="125"/><node text="เพื่อน"/><node text="14"/><node text="posts"/><node text="แก้ไขโปรไฟล์"/></hierarchy>'
        self.assertEqual(guard._name_near_marker(xml), 'Khao Fang Nichapa')

    def test_comment_identity_chip_is_not_bottom_navigation(self) -> None:
        chip = _node(24, 1477, 152, 1557, "Khao Fang Nichapa")
        self.assertEqual(guard._bottom_tabs(_xml(chip, chip)), [])

    def test_full_width_six_slot_navigation_is_accepted(self) -> None:
        nodes = [
            _node(i * 120, 1456, (i + 1) * 120, 1568,
                  "โปรไฟล์, แท็บ 6 จาก 6" if i == 5 else f"แท็บ {i + 1}")
            for i in range(6)
        ]
        tabs = guard._bottom_tabs(_xml(*nodes))
        self.assertEqual(len(tabs), 6)
        self.assertEqual(tabs[-1][0:2], (600, 720))

    def test_fresh_start_force_stops_then_opens_feed_and_reads_account(self) -> None:
        nav = _xml(*[
            _node(i * 120, 1456, (i + 1) * 120, 1568,
                  "โปรไฟล์, แท็บ 6 จาก 6" if i == 5 else f"แท็บ {i + 1}")
            for i in range(6)
        ])
        profile = (
            '<hierarchy><node bounds="[0,0][720,1600]" clickable="false">'
            '<node text="Khao Fang Nichapa" content-desc="" '
            'bounds="[100,300][500,360]" clickable="false" />'
            '<node text="แก้ไขโปรไฟล์" content-desc="แก้ไขโปรไฟล์" '
            'bounds="[380,680][690,750]" clickable="true" />'
            '</node></hierarchy>'
        )
        calls: list[tuple[str, ...]] = []

        def fake_sh(adb, serial, *args, **kwargs):
            calls.append(tuple(args))
            return subprocess.CompletedProcess([], 0, b"", b"")

        with mock.patch.object(guard, "_wake", return_value=True), \
             mock.patch.object(guard, "_sh", side_effect=fake_sh), \
             mock.patch.object(guard, "_dump", side_effect=[nav, profile]), \
             mock.patch.object(guard.time, "sleep"):
            found = guard.read_account(
                "adb", "serial", wait=0, fresh_start=True)

        self.assertEqual(found, "Khao Fang Nichapa")
        force = calls.index(("shell", "am", "force-stop", guard.APP))
        feed = next(i for i, call in enumerate(calls) if "fb://feed" in call)
        tap = next(i for i, call in enumerate(calls) if call[:3] ==
                   ("shell", "input", "tap"))
        self.assertLess(force, feed)
        self.assertLess(feed, tap)


if __name__ == "__main__":
    unittest.main()
