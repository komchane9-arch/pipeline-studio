from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

import facebook_group_post as post


class ImagePushRetryTests(unittest.TestCase):
    @staticmethod
    def phone() -> post.Phone:
        phone = post.Phone.__new__(post.Phone)
        phone.adb = "adb"
        phone.serial = "phone-1"
        phone._push_seq = 0
        phone._pushed = {}
        return phone

    def test_timeout_waits_for_same_device_then_retries_once(self) -> None:
        phone = self.phone()
        calls: list[tuple[str, ...]] = []
        logs: list[str] = []

        def run(*args: str, timeout: float = 30) -> subprocess.CompletedProcess:
            calls.append(args)
            pushes = sum(1 for call in calls if call[0] == "push")
            if args[0] == "push" and pushes == 1:
                raise subprocess.TimeoutExpired(args, timeout)
            return subprocess.CompletedProcess(args, 0, b"", b"")

        phone.run = run
        phone.shell = mock.Mock(return_value="pipeline-ready")
        phone.log = logs.append
        with mock.patch.object(post.time, "sleep"):
            remote = phone.push_image(Path("p800715611-1.jpg"))

        push_calls = [call for call in calls if call[0] == "push"]
        self.assertEqual(len(push_calls), 2)
        self.assertEqual(push_calls[0][2], push_calls[1][2])
        self.assertIn(("wait-for-device",), calls)
        self.assertIn("p800715611-1", remote)
        self.assertTrue(any("ลองอีกครั้ง" in line for line in logs))

    def test_second_timeout_returns_clear_post_error(self) -> None:
        phone = self.phone()
        phone.run = mock.Mock(side_effect=subprocess.TimeoutExpired("push", 180))
        phone.shell = mock.Mock(return_value="")
        phone.log = mock.Mock()
        with mock.patch.object(post.time, "sleep"), self.assertRaisesRegex(
                post.PostError, "หลังลอง 2 ครั้ง"):
            phone.push_image(Path("image.jpg"))


if __name__ == "__main__":
    unittest.main()
