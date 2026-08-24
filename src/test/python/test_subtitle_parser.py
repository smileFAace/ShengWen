import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sheng_wen.downloader.file_upload_worker import FileUploadWorker
from sheng_wen.utils.subtitle_parser import parse_subtitle_to_transcript


def _write_tmp(content: str, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


class TestSrtParser(unittest.TestCase):
    def test_basic_srt(self):
        content = """1
00:00:01,000 --> 00:00:04,000
你好，世界

2
00:00:05,500 --> 00:00:08,000
第二句话
"""
        path = _write_tmp(content, ".srt")
        try:
            result = parse_subtitle_to_transcript(path)
        finally:
            os.unlink(path)
        self.assertIn("000001你好，世界", result)
        self.assertIn("000005第二句话", result)

    def test_srt_multi_line_merged(self):
        content = """1
00:00:01,000 --> 00:00:04,000
第一行
第二行
"""
        path = _write_tmp(content, ".srt")
        try:
            result = parse_subtitle_to_transcript(path)
        finally:
            os.unlink(path)
        self.assertIn("000001第一行 第二行", result)


class TestVttParser(unittest.TestCase):
    def test_basic_vtt(self):
        content = """WEBVTT

00:00:01.000 --> 00:00:04.000
Hello world

00:00:05.500 --> 00:00:08.000
Second line
"""
        path = _write_tmp(content, ".vtt")
        try:
            result = parse_subtitle_to_transcript(path)
        finally:
            os.unlink(path)
        self.assertIn("000001Hello world", result)
        self.assertIn("000005Second line", result)

    def test_vtt_minutes_only_timestamp(self):
        content = """WEBVTT

00:01.500 --> 00:04.000
Short timestamp
"""
        path = _write_tmp(content, ".vtt")
        try:
            result = parse_subtitle_to_transcript(path)
        finally:
            os.unlink(path)
        self.assertIn("000001Short timestamp", result)


class TestAssParser(unittest.TestCase):
    def test_basic_ass(self):
        content = """[Script Info]
Title: Test

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,你好，字幕
Dialogue: 0,0:00:05.50,0:00:08.00,Default,,0,0,0,,第二句
"""
        path = _write_tmp(content, ".ass")
        try:
            result = parse_subtitle_to_transcript(path)
        finally:
            os.unlink(path)
        self.assertIn("000001你好，字幕", result)
        self.assertIn("000005第二句", result)

    def test_ass_newline_escapes(self):
        content = """[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,第一行\\N第二行
"""
        path = _write_tmp(content, ".ass")
        try:
            result = parse_subtitle_to_transcript(path)
        finally:
            os.unlink(path)
        self.assertIn("000001第一行 第二行", result)


class TestTxtParser(unittest.TestCase):
    def test_plain_text_preserved(self):
        content = """第一段文字。

第二段文字。
"""
        path = _write_tmp(content, ".txt")
        try:
            result = parse_subtitle_to_transcript(path)
        finally:
            os.unlink(path)
        self.assertEqual(result, "第一段文字。\n第二段文字。")

    def test_empty_file(self):
        path = _write_tmp("", ".txt")
        try:
            result = parse_subtitle_to_transcript(path)
        finally:
            os.unlink(path)
        self.assertEqual(result, "")


class TestFileUploadWorkerSubtitle(unittest.IsolatedAsyncioTestCase):
    async def test_subtitle_goes_directly_to_summary(self):
        content = """1
00:00:01,000 --> 00:00:04,000
你好，世界
"""
        path = _write_tmp(content, ".srt")
        temp_dir = tempfile.mkdtemp()
        task_id = "test-subtitle-task"

        # 模拟真实拓扑：next_worker=转录 Worker，summary_worker=总结 Worker
        next_worker = AsyncMock()
        summary_worker = AsyncMock()
        worker = FileUploadWorker(name="FileUploadWorker", next_worker=next_worker, summary_worker=summary_worker)
        worker.output_dir = temp_dir

        try:
            with patch("sheng_wen.task_updater.update_and_notify", new=AsyncMock()) as updater:
                await worker.process_task({
                    "task_id": task_id,
                    "file_path": path,
                    "filename": "示例字幕.srt",
                    "summary_mode": "agent",
                })
            # 应直接进入总结，不再经过转录
            update_kwargs = updater.call_args.args[1]
            self.assertEqual(update_kwargs["status"].value, "SUMMARIZING")
            self.assertIn("000001你好，世界", update_kwargs["transcript"])

            # 字幕 payload 必须发给总结 Worker，绝不能发给转录 Worker
            next_payload = summary_worker.add_task.call_args.args[0]
            self.assertEqual(next_payload["task_id"], task_id)
            self.assertTrue(next_payload["intermediate_file_path"].endswith(f"{task_id}_summary.txt"))
            self.assertTrue(next_payload["output_file"].endswith(f"{task_id}_summary.md"))
            self.assertEqual(next_payload["summary_mode"], "agent")
            next_worker.add_task.assert_not_awaited()
        finally:
            for f in os.listdir(temp_dir):
                os.unlink(os.path.join(temp_dir, f))
            os.rmdir(temp_dir)
            if os.path.exists(path):
                os.unlink(path)

    async def test_media_file_still_goes_to_transcriber(self):
        """普通音视频文件仍走转录流程。"""
        path = _write_tmp("dummy", ".mp3")
        temp_dir = tempfile.mkdtemp()
        task_id = "test-media-task"

        next_worker = AsyncMock()
        worker = FileUploadWorker(name="FileUploadWorker", next_worker=next_worker)
        worker.output_dir = temp_dir

        try:
            with patch("sheng_wen.downloader.file_upload_worker.build_transcriber_payload", return_value={"task_id": task_id}) as builder:
                with patch("sheng_wen.task_updater.update_and_notify", new=AsyncMock()):
                    await worker.process_task({
                        "task_id": task_id,
                        "file_path": path,
                        "filename": "sample.mp3",
                        "summary_mode": "standard",
                    })
            builder.assert_called_once()
        finally:
            for f in os.listdir(temp_dir):
                os.unlink(os.path.join(temp_dir, f))
            os.rmdir(temp_dir)
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    unittest.main()
