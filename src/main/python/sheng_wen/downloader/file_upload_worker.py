import asyncio
import os
from typing import Any

from ..worker import Worker
from ..utils.logger import logger
from ..utils.media import (
    AUDIO_MEDIA_EXTENSIONS,
    SUBTITLE_TEXT_EXTENSIONS,
    SUPPORTED_MEDIA_EXTENSIONS,
    SUPPORTED_UPLOAD_EXTENSIONS,
    VIDEO_MEDIA_EXTENSIONS,
    build_transcriber_payload,
    is_subtitle_text_file,
)


class FileUploadWorker(Worker):
    """
    一个工作单元，用于处理用户上传的视频/音频/字幕/文稿文件。
    字幕与文稿文件会直接解析为转录文本并进入总结阶段，跳过语音识别。
    """

    # 支持的媒体文件扩展名
    VIDEO_EXTENSIONS = VIDEO_MEDIA_EXTENSIONS
    AUDIO_EXTENSIONS = AUDIO_MEDIA_EXTENSIONS
    SUBTITLE_EXTENSIONS = SUBTITLE_TEXT_EXTENSIONS
    SUPPORTED_EXTENSIONS = SUPPORTED_UPLOAD_EXTENSIONS

    # 文件大小限制 (500MB)
    MAX_FILE_SIZE = 500 * 1024 * 1024

    def __init__(self, name: str, next_worker: Worker = None, summary_worker: Worker = None):
        super().__init__(name)
        self.next_worker = next_worker
        # 字幕/文稿文件跳过转录，直接交给总结 Worker（LLM）。
        # next_worker 是转录 Worker，不能用于字幕直达总结。
        self.summary_worker = summary_worker
        self.output_dir = "temp"
        os.makedirs(self.output_dir, exist_ok=True)

    async def process_task(self, payload: Any):
        """
        处理上传的文件，将其保存到本地并传递给下一个工作单元。

        :param payload: 包含 'file_path' (已保存的临时文件路径), 'filename', 'task_id' 的字典。
        """
        file_path = payload.get("file_path")
        filename = payload.get("filename", "uploaded_file")
        task_id = payload.get("task_id")
        # 本地路径直读场景下文件属于用户，不应移动；仅解析复用。
        move_file = bool(payload.get("move_file", True))

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

            # 如果文件已经在 temp 目录且命名正确，无需移动；
            # 本地路径直读场景（move_file=False）不得移动用户原文件。
            if move_file and file_path != final_path:
                # 移动文件到最终位置
                import shutil
                shutil.move(file_path, final_path)
                logger.info(f"[{self.name}] 文件已移动到: {final_path}")
            else:
                final_path = file_path if not move_file else final_path
                logger.info(f"[{self.name}] 文件已在目标位置: {final_path}")

            # 获取文件标题（用于显示）
            title = os.path.splitext(filename)[0]

            # 字幕/文稿文件：直接解析为转录文本并进入总结阶段
            if file_ext in self.SUBTITLE_EXTENSIONS:
                await self._process_subtitle_file(
                    final_path=final_path,
                    task_id=task_id,
                    title=title,
                    payload=payload,
                )
                logger.info(f"[{self.name}] 字幕/文稿文件处理完成，已直接进入总结流程")
                return

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

    async def _process_subtitle_file(
        self,
        final_path: str,
        task_id: str,
        title: str,
        payload: dict[str, Any],
    ):
        """
        处理字幕/文稿文件：解析为转录文本（与 whisper 产物格式一致），
        写入中间文件并更新数据库，然后直接交给 LLM 总结，跳过语音识别。
        """
        from ..db import TaskStatus
        from ..task_updater import update_and_notify
        from ..utils.subtitle_parser import parse_subtitle_to_transcript

        transcript_text = parse_subtitle_to_transcript(final_path)
        if not transcript_text:
            await self._mark_task_failed(task_id, "字幕/文稿文件内容为空或无法解析，请检查文件编码（建议 UTF-8）")
            return

        # 与转录产物命名保持一致，方便下游复用
        output_base = os.path.join(self.output_dir, f"{task_id}_summary")
        intermediate_file_path = output_base + ".txt"
        try:
            with open(intermediate_file_path, "w", encoding="utf-8") as f:
                f.write(transcript_text)
        except OSError as exc:
            await self._mark_task_failed(task_id, f"写入转录中间文件失败: {exc}")
            return

        summary_mode = str(payload.get("summary_mode") or "").strip().lower()
        update_data = {
            "status": TaskStatus.SUMMARIZING,
            "progress": 0.0,
            "title": title,
            "transcript": transcript_text,
            "summary_chunk_total": None,
            "summary_chunk_done": None,
            "summary_meta": None,
        }
        if summary_mode in {"auto", "standard", "agent"}:
            update_data["summary_mode"] = summary_mode
        if task_id:
            await update_and_notify(task_id, update_data)

        # 字幕直达总结：目标必须是总结 Worker（LLM），next_worker 是转录 Worker 不能复用。
        summary_target = self.summary_worker or self.next_worker
        if summary_target:
            await summary_target.add_task({
                "task_id": task_id,
                "intermediate_file_path": intermediate_file_path,
                "output_file": output_base + ".md",
                "summary_mode": summary_mode,
            })
            logger.info(
                f"[{self.name}] 字幕/文稿解析完成，已进入总结阶段: task_id={task_id}, "
                f"summary_worker={getattr(summary_target, 'name', summary_target.__class__.__name__)}, "
                f"lines={len(transcript_text.splitlines())}"
            )
        else:
            await self._mark_task_failed(task_id, "未配置总结 Worker，无法处理字幕/文稿文件")

    async def _mark_task_failed(self, task_id: str, error_msg: str):
        """标记任务为失败状态并通知前端"""
        from ..db import TaskStatus
        from ..task_updater import update_and_notify
        await update_and_notify(task_id, {"status": TaskStatus.FAILED, "error_message": error_msg})
