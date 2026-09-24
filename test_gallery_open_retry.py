"""Gallery opening needs positive grid evidence before selecting a photo."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class FakePhone:
    def __init__(self, *, successful_tap=1, grid_after_dumps=1, screen="composer"):
        self.successful_tap = successful_tap
        self.grid_after_dumps = grid_after_dumps
        self.screen = screen
        self.taps = []
        self.dumps_after_tap = 0
        self.logs = []

    def tap(self, point):
        self.taps.append(point)
        self.dumps_after_tap = 0

    def dump(self):
        self.dumps_after_tap += 1
        if (len(self.taps) >= self.successful_tap
                and self.dumps_after_tap >= self.grid_after_dumps):
            self.screen = "grid"
        return self.screen

    def find(self, xml, hints):
        return (100, 1200) if xml == "composer" and hints == ["gallery"] else (
            (200, 400) if xml == "composer" and hints == ["caption"] else None)

    def log(self, line):
        self.logs.append(line)


def make_open_picker():
    tree = ast.parse(Path(__file__).with_name("facebook_group_post.py").read_bytes())
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "open_photo_picker")
    captured = []
    namespace = {
        "Phone": FakePhone,
        "time": SimpleNamespace(sleep=lambda _seconds: None),
        "photo_cell": lambda xml, number: (30, 30) if xml == "grid" else None,
        "CAPTION_FIELD_HINTS": ["caption"],
        "PHOTO_HINTS": ["gallery"],
        "keep_failure_screen": lambda *_args: captured.append(True),
        "PostError": RuntimeError,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]),
                 "facebook_group_post.py", "exec"), namespace)
    return namespace["open_photo_picker"], captured


class GalleryOpenTests(unittest.TestCase):
    def test_successful_first_tap_does_not_tap_twice(self):
        open_picker, evidence = make_open_picker()
        phone = FakePhone(grid_after_dumps=3)
        open_picker(phone, (100, 1200))
        self.assertEqual(1, len(phone.taps))
        self.assertEqual([], evidence)

    def test_ignored_first_tap_retries_only_on_same_composer(self):
        open_picker, evidence = make_open_picker()
        phone = FakePhone(successful_tap=2)
        open_picker(phone, (100, 1200))
        self.assertEqual(2, len(phone.taps))
        self.assertTrue(any("อีกครั้ง" in line for line in phone.logs))
        self.assertEqual([], evidence)

    def test_other_screen_stops_without_blind_second_tap(self):
        open_picker, evidence = make_open_picker()
        phone = FakePhone(successful_tap=99, screen="permission")
        with self.assertRaisesRegex(RuntimeError, "ไม่เปิดหน้าเลือกรูป"):
            open_picker(phone, (100, 1200))
        self.assertEqual(1, len(phone.taps))
        self.assertEqual([True], evidence)


if __name__ == "__main__":
    unittest.main()
