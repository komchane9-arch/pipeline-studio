import json
import tempfile
import unittest
from pathlib import Path

from tools.migrate_fb_post_state import migrate


class PostStateMigrationTests(unittest.TestCase):
    def test_copy_all_accounts_and_recover_missing_preaw_groups(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "drive-state"
            destination = root / "local-state"
            backup = root / "backups"
            (source / "accounts" / "preaw-buchakorn").mkdir(parents=True)
            (source / "accounts" / "khao-fang-nichapa").mkdir(parents=True)
            (source / "accounts" / "_index.json").write_text(
                json.dumps({"preaw-buchakorn": "Preaw Buchakorn"}),
                encoding="utf-8")
            (source / "accounts" / "preaw-buchakorn" / "fb_jobs.json").write_text(
                "[]", encoding="utf-8")
            (source / "accounts" / "khao-fang-nichapa" / "fb_groups.json").write_text(
                '[{"group_id":"1"}]', encoding="utf-8")
            snapshot = root / "preaw.json"
            snapshot.write_text(json.dumps([
                {"group_id": "778495273564899", "name": "บ้าน"},
                {"group_id": "apparelmakers", "name": "บิวตี้"},
            ]), encoding="utf-8")

            result = migrate(
                source, destination, backup_root=backup,
                group_snapshot=snapshot)

            self.assertEqual(result["copied"], 3)
            self.assertEqual(result["groups"], 2)
            self.assertTrue((destination / "accounts" / "khao-fang-nichapa" /
                             "fb_groups.json").is_file())
            groups = json.loads((destination / "accounts" / "preaw-buchakorn" /
                                 "fb_groups.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [row["group_id"] for row in groups],
                ["778495273564899", "569042730582923"],
            )

    def test_invalid_source_json_does_not_copy_partial_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            (source / "good.json").write_text("[]", encoding="utf-8")
            (source / "bad.json").write_text("{", encoding="utf-8")

            with self.assertRaises(json.JSONDecodeError):
                migrate(source, destination, backup_root=root / "backups")
            self.assertFalse((destination / "good.json").exists())


if __name__ == "__main__":
    unittest.main()
