import os
import tempfile
import unittest
from unittest.mock import MagicMock

from sheng_wen.downloader.bilibili_yt_dlp import (
    apply_bilibili_ydl_auth,
    bilibili_ydl_auth_context,
    sanitize_sessdata,
    write_bilibili_cookiefile,
)
from sheng_wen.downloader.video_downloader_worker import VideoDownloaderWorker


class TestBilibiliYtDlpAuth(unittest.TestCase):
    def test_sanitize_sessdata(self):
        self.assertEqual(sanitize_sessdata(" abc\n"), "abc")
        self.assertEqual(sanitize_sessdata(None), "")

    def test_apply_headers_without_cookie_header(self):
        opts = apply_bilibili_ydl_auth({}, "cookie_value")
        headers = opts["http_headers"]
        self.assertEqual(headers["Referer"], "https://www.bilibili.com/")
        self.assertEqual(headers["Origin"], "https://www.bilibili.com")
        self.assertNotIn("Cookie", headers)
        self.assertNotIn("cookiefile", opts)

    def test_cookiefile_context(self):
        opts: dict = {}
        with bilibili_ydl_auth_context(opts, "cookie_value") as authed:
            self.assertIn("cookiefile", authed)
            cookie_path = authed["cookiefile"]
            self.assertTrue(os.path.exists(cookie_path))
            with open(cookie_path, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("SESSDATA\tcookie_value", content)
        self.assertFalse(os.path.exists(cookie_path))
        self.assertNotIn("cookiefile", opts)

    def test_write_bilibili_cookiefile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_bilibili_cookiefile("abc123", directory=tmp)
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as handle:
                self.assertIn("SESSDATA\tabc123", handle.read())
            os.unlink(path)


class TestPlaylistDownloadPathResolution(unittest.TestCase):
    def test_playlist_items_from_payload(self):
        items = VideoDownloaderWorker._playlist_items_from_payload(
            {"bilibili_parts": {"mode": "merge", "indices": [0, 2, 1]}}
        )
        self.assertEqual(items, "1,2,3")

    def test_collect_playlist_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = os.path.join(tmp, "BV_p1.mp4")
            p2 = os.path.join(tmp, "BV_p2.mp4")
            open(p1, "wb").close()
            open(p2, "wb").close()

            ydl = MagicMock()
            ydl.prepare_filename.side_effect = [
                os.path.join(tmp, "BV_p1.NA"),
                os.path.join(tmp, "BV_p2.NA"),
            ]
            info = {
                "_type": "playlist",
                "entries": [
                    {"id": "BV_p1"},
                    {"id": "BV_p2"},
                ],
            }
            paths = VideoDownloaderWorker._collect_downloaded_video_paths(ydl, info)
            self.assertEqual(paths, [p1, p2])

    def test_playlist_root_na_is_rejected(self):
        ydl = MagicMock()
        ydl.prepare_filename.return_value = "temp/BV1wd2gBUEeM.NA"
        info = {"_type": "playlist", "id": "BV1wd2gBUEeM", "entries": []}
        paths = VideoDownloaderWorker._collect_downloaded_video_paths(ydl, info)
        self.assertEqual(paths, [])


if __name__ == "__main__":
    unittest.main()
