import os
import tempfile
import unittest

from sheng_wen.downloader.video_downloader_worker import VideoDownloaderWorker
from sheng_wen.utils.task_temp_files import cleanup_task_temp_files


class TestTaskTempCleanup(unittest.TestCase):
    def test_cleanup_only_task_scoped_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_id = "681f9ee5-c491-4e31-a231-6f831b883d24"
            task_files = [
                os.path.join(tmp, f"{task_id}_merged.mp4"),
                os.path.join(tmp, f"{task_id}_audio.mp3"),
                os.path.join(tmp, f"{task_id}_summary.md"),
                os.path.join(tmp, f"{task_id}.mp4"),
            ]
            shared = os.path.join(tmp, "BV1wd2gBUEeM_p1.mp4")
            for path in task_files + [shared]:
                with open(path, "wb") as handle:
                    handle.write(b"x")

            deleted = cleanup_task_temp_files(task_id, temp_dir=tmp)
            self.assertEqual(len(deleted), 4)
            for path in task_files:
                self.assertFalse(os.path.exists(path))
            self.assertTrue(os.path.exists(shared))


class TestBilibiliDownloadCache(unittest.TestCase):
    def test_cache_hit_for_selected_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = VideoDownloaderWorker("t")
            worker.output_dir = tmp
            for i in (1, 2, 3):
                with open(os.path.join(tmp, f"BV1wd2gBUEeM_p{i}.mp4"), "wb") as handle:
                    handle.write(b"data")

            paths = worker._try_resolve_bilibili_cache_paths(
                "https://www.bilibili.com/video/BV1wd2gBUEeM/",
                "1,2,3",
            )
            self.assertIsNotNone(paths)
            assert paths is not None
            self.assertEqual(len(paths), 3)

    def test_cache_miss_when_part_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = VideoDownloaderWorker("t")
            worker.output_dir = tmp
            with open(os.path.join(tmp, "BV1wd2gBUEeM_p1.mp4"), "wb") as handle:
                handle.write(b"data")

            paths = worker._try_resolve_bilibili_cache_paths(
                "https://www.bilibili.com/video/BV1wd2gBUEeM/",
                "1,2",
            )
            self.assertIsNone(paths)

    def test_single_video_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = VideoDownloaderWorker("t")
            worker.output_dir = tmp
            with open(os.path.join(tmp, "BV1YR5E6EE9o.mp4"), "wb") as handle:
                handle.write(b"data")

            paths = worker._try_resolve_bilibili_cache_paths(
                "https://www.bilibili.com/video/BV1YR5E6EE9o/",
                None,
            )
            self.assertEqual(paths, [os.path.join(tmp, "BV1YR5E6EE9o.mp4")])


if __name__ == "__main__":
    unittest.main()
