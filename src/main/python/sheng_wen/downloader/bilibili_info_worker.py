import asyncio
import os
from typing import Any, Dict
import yt_dlp

from ..worker import Worker
from ..utils.logger import logger
from .bilibili_yt_dlp import bilibili_ydl_auth_context, sanitize_sessdata


class BilibiliInfoWorker(Worker):
    """
    一个工作单元，用于获取B站视频的元信息（封面、时长、标题等）。
    不下载视频，只提取信息。
    """

    def __init__(self, name: str, next_worker: Worker = None):
        super().__init__(name)
        self.next_worker = next_worker

    async def process_task(self, payload: Any):
        """
        获取B站视频信息并将其传递给下一个工作单元。

        :param payload: 包含 'video_url' 的字典。
        """
        video_url = payload.get("video_url")
        task_id = payload.get("task_id")

        if not video_url:
            error_msg = "任务负载中缺少 'video_url'"
            logger.error(f"[{self.name}] 错误: {error_msg}")
            if task_id:
                from ..db import TaskStatus
                from ..task_updater import update_and_notify
                asyncio.create_task(update_and_notify(task_id, {"status": TaskStatus.FAILED, "error_message": error_msg}))
            return

        logger.info(f"[{self.name}] 开始获取视频信息: {video_url}")

        try:
            sessdata = sanitize_sessdata(str(payload.get("bilibili_sessdata") or ""))
            if not sessdata:
                sessdata = sanitize_sessdata(os.getenv("BILIBILI_SESSDATA") or os.getenv("SESSDATA"))
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
            }

            with bilibili_ydl_auth_context(ydl_opts, sessdata):
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(video_url, download=False)

            video_info = {
                "title": info_dict.get("title", "未知标题"),
                "duration": info_dict.get("duration", 0),
                "duration_string": self._format_duration(info_dict.get("duration", 0)),
                "thumbnail": info_dict.get("thumbnail", ""),
                "description": info_dict.get("description", ""),
                "uploader": info_dict.get("uploader", "未知UP主"),
                "upload_date": info_dict.get("upload_date", ""),
                "view_count": info_dict.get("view_count", 0),
                "like_count": info_dict.get("like_count", 0),
                "video_id": info_dict.get("id", ""),
                "webpage_url": info_dict.get("webpage_url", video_url),
                "formats_count": len(info_dict.get("formats", [])),
            }

            logger.info(f"[{self.name}] 视频信息获取成功:")
            logger.info(f"  标题: {video_info['title']}")
            logger.info(f"  时长: {video_info['duration_string']} ({video_info['duration']}秒)")
            logger.info(f"  UP主: {video_info['uploader']}")
            logger.info(f"  播放量: {video_info['view_count']}")
            logger.info(f"  点赞数: {video_info['like_count']}")
            logger.info(f"  封面URL: {video_info['thumbnail']}")
            logger.info(f"  可用格式数: {video_info['formats_count']}")

            if self.next_worker:
                next_payload = payload.copy()
                next_payload["video_info"] = video_info
                await self.next_worker.add_task(next_payload)

        except Exception as e:
            logger.error(f"[{self.name}] 获取视频信息时出错: {e}", exc_info=True)
            if task_id:
                from ..db import TaskStatus
                from ..task_updater import update_and_notify
                asyncio.create_task(update_and_notify(task_id, {"status": TaskStatus.FAILED, "error_message": str(e)}))

    def _format_duration(self, seconds: float) -> str:
        if seconds <= 0:
            return "00:00"

        seconds = int(seconds)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"
