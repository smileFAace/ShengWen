import asyncio
import os
from typing import Any

from ..worker import Worker
from ..utils.logger import logger
from ..utils.media import (
    AUDIO_MEDIA_EXTENSIONS,
    VIDEO_MEDIA_EXTENSIONS,
    SUPPORTED_MEDIA_EXTENSIONS,
    build_transcriber_payload,
)


class FileUploadWorker(Worker):
    """
    一个工作单元，用于处理用户上传的视频/音频文件。
    """

    # 支持的媒体文件扩展名
    VIDEO_EXTENSIONS = VIDEO_MEDIA_EXTENSIONS
    AUDIO_EXTENSIONS = AUDIO_MEDIA_EXTENSIONS
    SUPPORTED_EXTENSIONS = SUPPORTED_MEDIA_EXTENSIONS

    # 文件大小限制 (500MB)
    MAX_FILE_SIZE = 500 * 1024 * 1024

    def __init__(self, name: str, next_worker: Worker = None):
        super().__init__(name)
        self.next_worker = next_worker
        # 从配置读取输出目录（转录文件目录）
        self.output_dir = self._get_output_dir("transcript_dir", "temp")
        os.makedirs(self.output_dir, exist_ok=True)

    @staticmethod
    def _get_output_dir(config_key: str, default: str = "temp") -> str:
        """
        从配置获取输出目录，如果未配置则使用默认值。

        Args:
            config_key: 配置键名 (transcript_dir 或 summary_dir)
            default: 默认目录

        Returns:
            输出目录路径
        """
        from ..config.settings import config
        output_dir = getattr(config.output, config_key, None) if hasattr(config, "output") else None
        if not output_dir:
            output_dir = default
        # 确保目录存在
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

    async def process_task(self, payload: Any):
        """
        处理上传的文件，将其保存到本地并传递给下一个工作单元。

        :param payload: 包含 'file_path' (已保存的临时文件路径), 'filename', 'task_id' 的字典。
        """
        file_path = payload.get("file_path")
        filename = payload.get("filename", "uploaded_file")
        task_id = payload.get("task_id")

        if not file_path or not os.path.exists(file_path):
            error_msg = "文件路径无效或文件不存在"
            logger.error(f"[{self.name}] 错误: {error_msg}")
            if task_id:
                await self._mark_task_failed(task_id, error_msg)
            return

        logger.info(f"[{self.name}] 开始处理上传文件: {filename} (任务ID: {task_id})")

        if task_id:
            from ..db import TaskStatus
            from ..task_updater import update_and_notify
            await update_and_notify(task_id, {"status": TaskStatus.UPLOADING, "progress": 0.0})

        try:
            # 获取文件大小
            file_size = os.path.getsize(file_path)

            # 检查文件大小限制
            if file_size > self.MAX_FILE_SIZE:
                error_msg = f"文件过大 ({file_size / 1024 / 1024:.1f}MB)，最大支持 {self.MAX_FILE_SIZE / 1024 / 1024:.0f}MB"
                logger.error(f"[{self.name}] {error_msg}")
                if task_id:
                    await self._mark_task_failed(task_id, error_msg)
                return

            # 检查文件扩展名
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext not in self.SUPPORTED_EXTENSIONS:
                error_msg = f"不支持的文件格式: {file_ext}。支持的格式: {', '.join(sorted(self.SUPPORTED_EXTENSIONS))}"
                logger.error(f"[{self.name}] {error_msg}")
                if task_id:
                    await self._mark_task_failed(task_id, error_msg)
                return

            # 模拟上传进度 (从 0% 到 100%)
            # 在实际场景中，文件已经被 FastAPI 保存，这里只是模拟进度反馈
            upload_steps = 10
            for i in range(1, upload_steps + 1):
                progress = (i / upload_steps) * 100
                if task_id:
                    from ..api import notify_progress_update
                    await notify_progress_update(task_id, progress)
                await asyncio.sleep(0.05)  # 轻微延迟，让前端能看到进度

            # 确定最终文件路径
            final_path = os.path.join(self.output_dir, f"{task_id}{file_ext}")

            # 如果文件已经在 temp 目录且命名正确，无需移动
            if file_path != final_path:
                # 移动文件到最终位置
                import shutil
                shutil.move(file_path, final_path)
                logger.info(f"[{self.name}] 文件已移动到: {final_path}")
            else:
                logger.info(f"[{self.name}] 文件已在目标位置: {final_path}")

            # 获取文件标题（用于显示）
            title = os.path.splitext(filename)[0]
            if task_id:
                from ..db import TaskStatus
                from ..task_updater import update_and_notify
                await update_and_notify(task_id, {"title": title, "status": TaskStatus.TRANSCRIBING})

            # 传递给下一个 Worker
            if self.next_worker:
                next_payload = build_transcriber_payload(
                    task_id=task_id,
                    media_path=final_path,
                    output_dir=self.output_dir,
                    summary_mode=str(payload.get("summary_mode") or ""),
                )
                await self.next_worker.add_task(next_payload)

            logger.info(f"[{self.name}] 文件处理完成，已传递给下一个 Worker")

        except Exception as e:
            logger.error(f"[{self.name}] 处理上传文件时出错: {e}", exc_info=True)
            if task_id:
                await self._mark_task_failed(task_id, str(e))

    async def _mark_task_failed(self, task_id: str, error_msg: str):
        """标记任务为失败状态并通知前端"""
        from ..db import TaskStatus
        from ..task_updater import update_and_notify
        await update_and_notify(task_id, {"status": TaskStatus.FAILED, "error_message": error_msg})
