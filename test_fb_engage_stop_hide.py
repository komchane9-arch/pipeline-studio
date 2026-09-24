from pathlib import Path
import unittest


class EngageStopHideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = Path("web/engage.js").read_text(encoding="utf-8")

    def test_stop_removes_post_card_immediately(self) -> None:
        self.assertIn('if (action === "stop" && !nowActive)', self.source)
        self.assertIn("removeStoppedPost(post, panel)", self.source)
        self.assertIn('querySelectorAll(".eg-post, .eg-tracked-row")', self.source)
        self.assertIn('if (row.dataset.postUrl === post.post_url) row.remove()', self.source)

    def test_reload_filters_stopped_posts_but_keeps_server_history(self) -> None:
        self.assertIn("data.posts = (data.posts || []).filter(isPostActive)", self.source)
        self.assertIn("API เก็บโพสต์ที่หยุดไว้เป็นประวัติ", self.source)


if __name__ == "__main__":
    unittest.main()
