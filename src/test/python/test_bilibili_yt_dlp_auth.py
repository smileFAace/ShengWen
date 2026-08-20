import unittest

from sheng_wen.downloader.bilibili_yt_dlp import apply_bilibili_ydl_auth, sanitize_sessdata


class TestBilibiliYtDlpAuth(unittest.TestCase):
    def test_sanitize_sessdata(self):
        self.assertEqual(sanitize_sessdata("  abc\n"), "abc")
        self.assertEqual(sanitize_sessdata(None), "")

    def test_apply_headers_without_cookie(self):
        opts = apply_bilibili_ydl_auth({})
        headers = opts["http_headers"]
        self.assertEqual(headers["Referer"], "https://www.bilibili.com/")
        self.assertEqual(headers["Origin"], "https://www.bilibili.com")
        self.assertNotIn("Cookie", headers)

    def test_apply_sessdata_cookie(self):
        opts = apply_bilibili_ydl_auth({}, "cookie_value")
        self.assertEqual(opts["http_headers"]["Cookie"], "SESSDATA=cookie_value")

    def test_preserve_existing_cookie_and_headers(self):
        opts = apply_bilibili_ydl_auth(
            {
                "http_headers": {
                    "Referer": "https://example.com/",
                    "Cookie": "foo=bar",
                }
            },
            "cookie_value",
        )
        headers = opts["http_headers"]
        self.assertEqual(headers["Referer"], "https://example.com/")
        self.assertEqual(headers["Origin"], "https://www.bilibili.com")
        self.assertEqual(headers["Cookie"], "foo=bar; SESSDATA=cookie_value")

    def test_do_not_duplicate_sessdata(self):
        opts = apply_bilibili_ydl_auth(
            {"http_headers": {"Cookie": "SESSDATA=already"}},
            "new_value",
        )
        self.assertEqual(opts["http_headers"]["Cookie"], "SESSDATA=already")


if __name__ == "__main__":
    unittest.main()
