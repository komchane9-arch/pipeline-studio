"""Regression tests for Facebook vanity group links and verified numeric IDs."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import fb_auto_post


class GroupAliasTests(unittest.TestCase):
    def test_verified_apparelmakers_alias_uses_numeric_id(self) -> None:
        self.assertEqual(
            fb_auto_post.resolve_group_id(
                "https://www.facebook.com/groups/apparelmakers/"),
            "569042730582923",
        )

    def test_numeric_group_id_is_unchanged(self) -> None:
        self.assertEqual(
            fb_auto_post.resolve_group_id(
                "https://www.facebook.com/groups/569042730582923/"),
            "569042730582923",
        )

    @patch.object(
        fb_auto_post, "resolve_share_link",
        side_effect=fb_auto_post.AutoPostError("resolve failed"),
    )
    def test_unknown_unresolved_slug_is_rejected(self, _resolve) -> None:
        with self.assertRaisesRegex(
                fb_auto_post.AutoPostError, "ป้องกันเปิดหรือโพสต์ผิดกลุ่ม"):
            fb_auto_post.resolve_group_id(
                "https://www.facebook.com/groups/not-verified-slug/")


if __name__ == "__main__":
    unittest.main()
