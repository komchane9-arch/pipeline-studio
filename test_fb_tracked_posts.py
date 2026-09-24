import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fb_engagement as engage


class TrackedPostsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(engage, "DB_FILE", Path(tmp.name) / "test.sqlite3")
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(engage, "_post_meta_by_link", return_value={})
        patch.start()
        self.addCleanup(patch.stop)

    def seed(self, url, account="Preaw", group="g1", name="Same name"):
        conn = engage.open_db()
        conn.execute("""INSERT INTO my_post
            (post_url, account, group_id, group_name, checked_at)
            VALUES (?, ?, ?, ?, '2026-09-20T10:00:00')""", (url, account, group, name))
        conn.commit()
        conn.close()

    def test_all_active_posts_without_comments_and_no_page_limit(self):
        for n in range(505):
            self.seed(f"https://www.facebook.com/groups/g1/posts/{n}")
        self.assertEqual(engage.threads(200, True, "Preaw"), [])
        rows = engage.tracked_posts("Preaw", "g1")
        self.assertEqual(len(rows), 505)
        self.assertTrue(all("comments_list" not in row for row in rows))

    def test_account_group_latest_snapshot_and_stop(self):
        url = "https://www.facebook.com/groups/g1/posts/1"
        self.seed(url)
        self.seed(url)  # Multiple snapshots produce only one entry.
        self.seed("other-account", account="Khao Fang")
        self.seed("other-group", group="g2")
        self.seed("no-id", group="", name="Legacy group")
        rows = engage.tracked_posts("Preaw", "g1")
        self.assertEqual([row["post_url"] for row in rows], [url])
        engage.set_post_watch(post_url=url, active=False, actor="test")
        self.assertEqual(engage.tracked_posts("Preaw", "g1"), [])
        self.assertEqual(len(engage.tracked_posts("Khao Fang", "g1")), 1)
        self.assertEqual(len(engage.tracked_posts("Preaw", "", "Legacy group")), 1)
        conn = engage.open_db()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM my_post WHERE post_url=?", (url,)).fetchone()[0], 2)
        conn.close()
        engage.set_post_watch(post_url=url, active=True, actor="test")
        self.assertEqual(len(engage.tracked_posts("Preaw", "g1")), 1)


if __name__ == "__main__":
    unittest.main()
