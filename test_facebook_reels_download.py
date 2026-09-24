import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from facebook_reels_download import create_router, download_reel, open_download_folder, validate_url


class ReelTests(unittest.TestCase):
    def test_url_allowlist(self):
        for url in ["http://facebook.com/reel/123", "https://facebook.com.evil.test/reel/123",
                    "https://localhost/reel/123", "https://facebook.com/", "https://a@facebook.com/reel/123",
                    "https://facebook.com:88/reel/123"]:
            with self.assertRaises(ValueError):
                validate_url(url)
        self.assertEqual(validate_url(" https://www.facebook.com/share/r/19RuFEFSSX/ "),
                         "https://www.facebook.com/share/r/19RuFEFSSX/")

    def test_download_and_file_routes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = FastAPI()
            app.include_router(create_router(root))
            client = TestClient(app)
            def run(command, **kwargs):
                target = Path(command[command.index("-o") + 1].replace("%(ext)s", "mp4"))
                target.write_bytes(b"fake video" * 200)
                return SimpleNamespace(returncode=0, stdout=json.dumps({"id": "123", "title": "ทดสอบ"}))
            with patch("facebook_reels_download.subprocess.run", side_effect=run):
                response = client.post("/api/facebook-reels/download", json={"url": "https://facebook.com/reel/123"})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(client.get(data["video_url"]).status_code, 200)
            self.assertIn("attachment", client.get(data["download_url"]).headers["content-disposition"])
            self.assertEqual(client.get("/api/facebook-reels/files/not-a-token").status_code, 404)
            self.assertEqual(client.post("/api/facebook-reels/download", json={"url":"https://evil.test"}).status_code, 400)

    def test_timeout_and_missing_video(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("facebook_reels_download.subprocess.run", side_effect=subprocess.TimeoutExpired("test", 180)):
                with self.assertRaisesRegex(RuntimeError, "3 นาที"):
                    download_reel("https://facebook.com/reel/123", Path(temp))
            with patch("facebook_reels_download.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="{}")):
                with self.assertRaisesRegex(RuntimeError, "MP4"):
                    download_reel("https://facebook.com/reel/123", Path(temp))

    def test_open_folder_uses_only_configured_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "facebook_reels_downloads"
            with patch("facebook_reels_download.os.startfile") as startfile:
                opened = open_download_folder(root)
            self.assertTrue(root.is_dir())
            startfile.assert_called_once_with(str(root.resolve()))
            self.assertEqual(opened, str(root.resolve()))

            app = FastAPI()
            app.include_router(create_router(root))
            client = TestClient(app)
            with patch("facebook_reels_download.os.startfile") as startfile:
                response = client.post("/api/facebook-reels/open-folder")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["path"], str(root.resolve()))
            startfile.assert_called_once_with(str(root.resolve()))


if __name__ == "__main__":
    unittest.main()
