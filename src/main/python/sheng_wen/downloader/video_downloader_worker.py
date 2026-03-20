import asyncio
import json
import os
import re
import uuid
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import Any, Dict, List, Tuple, Optional
import yt_dlp

from ..worker import Worker, TaskCancelledError
from ..utils.logger import logger
from ..utils.ffmpeg_helper import FFmpegHelper
from .bilibili_author_resolver import resolve_bilibili_author, BilibiliAuthorResolveError

class VideoDownloaderWorker(Worker):
    """
    一个工作单元，用于从给定的 URL 下载视频。
    """
    def __init__(
        self,
        name: str,
        next_worker: Worker = None,
        summary_worker: Worker = None,
        transcription_settings_manager: Any = None
    ):
        super().__init__(name)
        self.next_worker = next_worker
        self.summary_worker = summary_worker
        self.transcription_settings_manager = transcription_settings_manager
        self.output_dir = "temp"
        os.makedirs(self.output_dir, exist_ok=True)

    @staticmethod
    def _is_bilibili_url(video_url: str) -> bool:
        try:
            netloc = (urlparse(video_url).netloc or "").lower()
        except Exception:
            return False
        return "bilibili.com" in netloc or "b23.tv" in netloc

    @staticmethod
    def _is_youtube_url(video_url: str) -> bool:
        """判断是否为 YouTube 链接（含 youtu.be 短链）。"""
        try:
            netloc = (urlparse(video_url).netloc or "").lower()
        except Exception:
            return False
        return any(domain in netloc for domain in ("youtube.com", "youtu.be", "youtube-nocookie.com"))

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """将秒数格式化为 HHMMSS 字符串。"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        sec = int(seconds % 60)
        return f"{hours:02d}{minutes:02d}{sec:02d}"

    @staticmethod
    def _sanitize_cookie_value(value: str | None) -> str:
        return (value or "").strip().replace("\r", "").replace("\n", "")

    @staticmethod
    def _resolve_final_url(video_url: str) -> str:
        request = Request(video_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=15) as response:
            return response.geturl()

    @classmethod
    def _extract_bvid_from_url(cls, video_url: str) -> str:
        candidate = video_url
        if "b23.tv" in video_url:
            try:
                candidate = cls._resolve_final_url(video_url)
            except Exception:
                candidate = video_url

        match = re.search(r"/video/(BV[0-9A-Za-z]+)", candidate)
        if match:
            return match.group(1)

        fallback = re.search(r"(BV[0-9A-Za-z]+)", candidate)
        if fallback:
            return fallback.group(1)

        raise ValueError("无法从链接中提取 BV 号")

    @staticmethod
    def _normalize_subtitle_url(url: str) -> str:
        if not url:
            return ""
        if url.startswith("//"):
            return f"https:{url}"
        return url

    @staticmethod
    def _score_bilibili_subtitle_item(item: Dict[str, Any]) -> int:
        lan = str(item.get("lan") or item.get("lang") or "").strip().lower().replace("_", "-")
        url = str(item.get("subtitle_url") or item.get("url") or "")
        ext = os.path.splitext(url.split("?", 1)[0])[1].lstrip(".").lower()

        score = 0
        if lan == "ai-zh":
            score += 1000
        elif "zh" in lan and "ai" in lan:
            score += 900
        elif lan.startswith("zh"):
            score += 700
        elif "zh" in lan:
            score += 600
        elif lan:
            score += 100

        if ext == "json":
            score += 30
        elif ext:
            score += 10

        return score

    @classmethod
    def _select_bilibili_subtitle_item(cls, subtitle_items: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        best_item = None
        best_score = -1
        for item in subtitle_items:
            if not isinstance(item, dict):
                continue
            sub_url = cls._normalize_subtitle_url(str(item.get("subtitle_url") or item.get("url") or ""))
            if not sub_url:
                continue
            score = cls._score_bilibili_subtitle_item(item)
            if score > best_score:
                best_score = score
                best_item = item
        return best_item

    def _resolve_bilibili_sessdata(self, payload: Dict[str, Any]) -> Tuple[str, str]:
        task_override = self._sanitize_cookie_value(str(payload.get("bilibili_sessdata") or ""))
        manager = self.transcription_settings_manager
        if manager is not None and hasattr(manager, "resolve_bilibili_sessdata"):
            try:
                value, source = manager.resolve_bilibili_sessdata(task_override)
                return self._sanitize_cookie_value(value), str(source or "none")
            except Exception as e:
                logger.warning(f"[{self.name}] 读取 B 站 Cookie 设置失败，将回退环境变量: {e}")

        if task_override:
            return task_override, "task"

        env_cookie = self._sanitize_cookie_value(os.getenv("BILIBILI_SESSDATA") or os.getenv("SESSDATA"))
        if env_cookie:
            return env_cookie, "env"
        return "", "none"

    @staticmethod
    def _download_text(url: str, extra_headers: Dict[str, Any] | None = None) -> str:
        target = url
        if target.startswith("//"):
            target = f"https:{target}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
        }
        if isinstance(extra_headers, dict):
            for k, v in extra_headers.items():
                if isinstance(k, str) and isinstance(v, str):
                    headers[k] = v
        request = Request(target, headers=headers)
        with urlopen(request, timeout=15) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")

    def _build_transcript_from_subtitle_json(self, subtitle_json: Dict[str, Any]) -> str:
        lines: List[str] = []

        body = subtitle_json.get("body")
        if isinstance(body, list):
            for segment in body:
                if not isinstance(segment, dict):
                    continue
                content = str(segment.get("content") or segment.get("text") or "").strip()
                if not content:
                    continue
                start_raw = segment.get("from", segment.get("start", 0.0))
                try:
                    start = float(start_raw)
                except (TypeError, ValueError):
                    start = 0.0
                content = content.replace("\n", " ").strip()
                if content:
                    lines.append(f"{self._format_duration(start)}{content}\n")

            return "".join(lines)

        # 兼容 json3 类格式
        events = subtitle_json.get("events")
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue
                start_ms = event.get("tStartMs", event.get("t_start_ms", 0))
                try:
                    start = float(start_ms) / 1000.0
                except (TypeError, ValueError):
                    start = 0.0

                segments = event.get("segs")
                if isinstance(segments, list):
                    text_parts = []
                    for seg in segments:
                        if isinstance(seg, dict):
                            seg_text = str(seg.get("utf8") or "").strip()
                            if seg_text:
                                text_parts.append(seg_text)
                    content = "".join(text_parts).replace("\n", " ").strip()
                else:
                    content = str(event.get("content") or "").replace("\n", " ").strip()

                if content:
                    lines.append(f"{self._format_duration(start)}{content}\n")

            return "".join(lines)

        return ""

    async def _extract_bilibili_subtitle_via_api(
        self, video_url: str, sessdata: str, part_index: int = 0
    ) -> Dict[str, Any] | None:
        """
        提取 B 站视频字幕。

        Args:
            video_url: 视频链接
            sessdata: B 站 Cookie
            part_index: 分P索引（0-based），默认为0（第一个分P或单P视频）

        Returns:
            包含字幕信息的字典，或 None 如果获取失败
        """
        try:
            from bilibili_api import Credential, video
        except Exception as exc:
            raise RuntimeError("未安装 bilibili-api-python，无法进行 B 站字幕直取") from exc

        bvid = self._extract_bvid_from_url(video_url)
        credential = Credential(sessdata=sessdata or None) if sessdata else None

        video_obj = video.Video(bvid=bvid, credential=credential)
        info = await video_obj.get_info()
        cid = await video_obj.get_cid(part_index)
        player_info = await video_obj.get_player_info(cid=cid)

        subtitle_block = player_info.get("subtitle") if isinstance(player_info, dict) else None
        subtitle_items = subtitle_block.get("subtitles") if isinstance(subtitle_block, dict) else []
        if not isinstance(subtitle_items, list) or not subtitle_items:
            return None

        selected = self._select_bilibili_subtitle_item(subtitle_items)
        if not selected:
            return None

        subtitle_url = self._normalize_subtitle_url(str(selected.get("subtitle_url") or selected.get("url") or ""))
        if not subtitle_url:
            return None

        raw_subtitle = self._download_text(subtitle_url)
        subtitle_json = json.loads(raw_subtitle)
        transcript = self._build_transcript_from_subtitle_json(subtitle_json)
        if not transcript.strip():
            return None

        language = str(selected.get("lan") or selected.get("lang") or "")

        # 获取该分P的具体信息
        part_title = None
        part_duration = None
        pages = info.get("pages")
        if isinstance(pages, list) and len(pages) > part_index:
            page_info = pages[part_index]
            if isinstance(page_info, dict):
                part_title = page_info.get("part")
                part_duration = page_info.get("duration")

        return {
            "title": info.get("title"),
            "duration": part_duration or info.get("duration"),
            "transcript": transcript,
            "language": language,
            "is_auto": "ai" in language.lower(),
            "subtitle_url": subtitle_url,
            "part_index": part_index,
            "part_title": part_title,
        }

    async def _extract_bilibili_multi_part_subtitles(
        self, video_url: str, sessdata: str, part_indices: List[int]
    ) -> List[Dict[str, Any]]:
        """
        提取多个分P的字幕。

        Args:
            video_url: 视频链接
            sessdata: B 站 Cookie
            part_indices: 要提取的分P索引列表（0-based）

        Returns:
            成功提取的字幕信息列表
        """
        results = []
        for idx in part_indices:
            try:
                result = await self._extract_bilibili_subtitle_via_api(video_url, sessdata, idx)
                if result:
                    results.append(result)
                    logger.info(
                        f"[{self.name}] 成功提取分P {idx + 1} 字幕: "
                        f"{result.get('part_title') or f'第{idx + 1}P'}"
                    )
                else:
                    logger.warning(f"[{self.name}] 分P {idx + 1} 未找到字幕")
            except Exception as e:
                logger.warning(f"[{self.name}] 提取分P {idx + 1} 字幕失败: {e}")
        return results

    def _merge_transcripts_with_offset(
        self, subtitle_results: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Tuple[str, int]:
        """
        合并多个分P的字幕，计算时间偏移。

        Args:
            subtitle_results: 多个分P的字幕结果列表
            video_info: 视频信息，包含分P时长

        Returns:
            (合并后的转录文本, 总时长)
        """
        if not subtitle_results:
            return "", 0

        # 按分P索引排序
        sorted_results = sorted(subtitle_results, key=lambda x: x.get("part_index", 0))

        # 获取每个分P的时长用于计算偏移
        pages = video_info.get("pages", [])
        duration_map = {}
        for page in pages:
            if isinstance(page, dict):
                page_idx = page.get("page", 1) - 1  # page 是 1-based
                duration_map[page_idx] = page.get("duration", 0)

        merged_lines = []
        total_duration = 0
        time_offset = 0.0

        for result in sorted_results:
            part_idx = result.get("part_index", 0)
            transcript = result.get("transcript", "")

            # 获取该分P时长
            part_duration = duration_map.get(part_idx, result.get("duration", 0))
            total_duration += part_duration

            if time_offset > 0 and transcript:
                # 需要调整时间戳
                for line in transcript.split("\n"):
                    if not line.strip():
                        continue
                    # 解析 HHMMSS 格式的时间戳
                    match = re.match(r"^(\d{2})(\d{2})(\d{2})(.+)$", line)
                    if match:
                        h, m, s, text = int(match.group(1)), int(match.group(2)), int(match.group(3)), match.group(4)
                        original_seconds = h * 3600 + m * 60 + s
                        new_seconds = original_seconds + time_offset

                        new_h = int(new_seconds // 3600)
                        new_m = int((new_seconds % 3600) // 60)
                        new_s = int(new_seconds % 60)
                        merged_lines.append(f"{new_h:02d}{new_m:02d}{new_s:02d}{text}\n")
                    else:
                        merged_lines.append(line + "\n")
            else:
                merged_lines.append(transcript)
                if not transcript.endswith("\n"):
                    merged_lines.append("\n")

            # 更新时间偏移
            time_offset += part_duration

        return "".join(merged_lines), total_duration

    def _try_extract_bilibili_subtitle(self, video_url: str, sessdata: str) -> Dict[str, Any] | None:
        return asyncio.run(self._extract_bilibili_subtitle_via_api(video_url, sessdata, 0))

    def _try_process_with_bilibili_subtitle(self, payload: Dict[str, Any]) -> bool:
        video_url = str(payload.get("video_url") or "")
        task_id = payload.get("task_id")

        if not video_url or not task_id:
            return False
        if self.is_task_cancelled(task_id):
            raise TaskCancelledError(f"任务已取消，跳过字幕直取: {task_id}")
        if not self._is_bilibili_url(video_url):
            return False
        if self.summary_worker is None:
            return False

        if self.transcription_settings_manager is not None:
            try:
                settings = self.transcription_settings_manager.get_settings()
                if not bool(settings.get("enable_bilibili_subtitle_fetch", True)):
                    return False
            except Exception as e:
                logger.warning(f"[{self.name}] 读取转录设置失败，继续回退 ASR: {e}")
                return False

        sessdata, cookie_source = self._resolve_bilibili_sessdata(payload)

        # 检查是否有分P配置
        bilibili_parts = payload.get("bilibili_parts")
        if bilibili_parts and isinstance(bilibili_parts, dict):
            mode = bilibili_parts.get("mode")
            indices = bilibili_parts.get("indices")

            if mode == "merge" and isinstance(indices, list) and len(indices) > 0:
                # 合并模式：提取多个分P的字幕并合并
                return self._try_process_bilibili_multi_part_merge(
                    video_url, sessdata, task_id, indices, payload
                )
            # separate 模式由 API 层处理，这里不应该到达
            # 如果到达这里，说明配置有问题，回退到普通处理
            logger.warning(f"[{self.name}] 未知的分P处理模式或无效配置: {bilibili_parts}")

        logger.info(
            f"[{self.name}] 检测到 B 站 URL，尝试使用 bilibili-api 直取字幕: {video_url}"
            f" (cookie_source={cookie_source}, has_cookie={bool(sessdata)})"
        )

        try:
            subtitle_result = self._try_extract_bilibili_subtitle(video_url, sessdata)
            if not subtitle_result:
                logger.info(f"[{self.name}] 未获取到可用字幕，回退到下载+ASR流程。")
                return False

            transcript = subtitle_result["transcript"]
            intermediate_file_path = os.path.join(self.output_dir, f"{task_id}_subtitle.txt")
            output_file = os.path.join(self.output_dir, f"{task_id}_summary.md")

            with open(intermediate_file_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(transcript)

            from ..db import TaskStatus
            from ..task_updater import update_and_notify
            self._submit_coro(update_and_notify(task_id, {"status": TaskStatus.TRANSCRIBING}))

            if self.is_task_cancelled(task_id):
                raise TaskCancelledError(f"任务已取消，停止字幕分支: {task_id}")

            update_data = {
                "title": subtitle_result.get("title"),
                "status": TaskStatus.SUMMARIZING,
                "progress": 0.0,
                "transcript": transcript,
                "transcription_time": 0.0,
                "audio_duration": subtitle_result.get("duration"),
                "summary_chunk_total": None,
                "summary_chunk_done": None,
                "summary_meta": None,
            }
            summary_mode = str(payload.get("summary_mode") or "").strip().lower()
            if summary_mode in {"auto", "standard", "agent"}:
                update_data["summary_mode"] = summary_mode
            self._submit_coro(update_and_notify(task_id, update_data))

            next_payload = payload.copy()
            next_payload.update({
                "intermediate_file_path": intermediate_file_path,
                "output_file": output_file,
            })
            if self.is_task_cancelled(task_id):
                raise TaskCancelledError(f"任务已取消，停止派发总结: {task_id}")
            self._submit_coro(self.summary_worker.add_task(next_payload))

            logger.info(
                f"[{self.name}] 已使用B站字幕（{subtitle_result.get('language')}），跳过音频转录。"
            )
            return True
        except Exception as e:
            logger.warning(f"[{self.name}] B 站字幕直取失败，将回退 ASR: {e}")
            return False

    def _try_process_bilibili_multi_part_merge(
        self, video_url: str, sessdata: str, task_id: str, part_indices: List[int], payload: Dict[str, Any]
    ) -> bool:
        """
        处理多P视频合并模式：提取所有选中分P的字幕并合并为一个转录。
        """
        logger.info(
            f"[{self.name}] 处理多P视频合并模式: {video_url}, 分P: {[i + 1 for i in part_indices]}"
        )

        try:
            # 获取视频信息和所有分P字幕
            subtitle_results = asyncio.run(
                self._extract_bilibili_multi_part_subtitles(video_url, sessdata, part_indices)
            )

            if not subtitle_results:
                logger.warning(f"[{self.name}] 未能获取任何分P字幕，回退到下载+ASR流程")
                return False

            # 获取视频信息用于时长计算
            from bilibili_api import Credential, video
            bvid = self._extract_bvid_from_url(video_url)
            credential = Credential(sessdata=sessdata or None) if sessdata else None
            video_obj = video.Video(bvid=bvid, credential=credential)
            video_info = asyncio.run(video_obj.get_info())

            # 合并字幕
            merged_transcript, total_duration = self._merge_transcripts_with_offset(
                subtitle_results, video_info
            )

            if not merged_transcript.strip():
                logger.warning(f"[{self.name}] 合并后的字幕为空，回退到下载+ASR流程")
                return False

            # 构建标题（包含分P信息）
            title = video_info.get("title", "")
            if len(subtitle_results) < len(part_indices):
                title_suffix = f" (已合并 {len(subtitle_results)}/{len(part_indices)} 个分P)"
            else:
                title_suffix = f" (已合并 {len(part_indices)} 个分P)"

            intermediate_file_path = os.path.join(self.output_dir, f"{task_id}_subtitle.txt")
            output_file = os.path.join(self.output_dir, f"{task_id}_summary.md")

            with open(intermediate_file_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(merged_transcript)

            from ..db import TaskStatus
            from ..task_updater import update_and_notify
            self._submit_coro(update_and_notify(task_id, {"status": TaskStatus.TRANSCRIBING}))

            if self.is_task_cancelled(task_id):
                raise TaskCancelledError(f"任务已取消，停止字幕分支: {task_id}")

            update_data = {
                "title": title + title_suffix,
                "status": TaskStatus.SUMMARIZING,
                "progress": 0.0,
                "transcript": merged_transcript,
                "transcription_time": 0.0,
                "audio_duration": total_duration,
                "summary_chunk_total": None,
                "summary_chunk_done": None,
                "summary_meta": None,
            }
            summary_mode = str(payload.get("summary_mode") or "").strip().lower()
            if summary_mode in {"auto", "standard", "agent"}:
                update_data["summary_mode"] = summary_mode
            self._submit_coro(update_and_notify(task_id, update_data))

            next_payload = payload.copy()
            next_payload.update({
                "intermediate_file_path": intermediate_file_path,
                "output_file": output_file,
            })
            if self.is_task_cancelled(task_id):
                raise TaskCancelledError(f"任务已取消，停止派发总结: {task_id}")
            self._submit_coro(self.summary_worker.add_task(next_payload))

            logger.info(
                f"[{self.name}] 已合并 {len(subtitle_results)} 个分P的字幕，"
                f"总时长 {total_duration} 秒，跳过音频转录。"
            )
            return True

        except Exception as e:
            logger.error(f"[{self.name}] 处理多P视频合并失败: {e}", exc_info=True)
            return False

    async def _resolve_and_save_bilibili_author(self, task_id: str, video_url: str):
        if not task_id or not self._is_bilibili_url(video_url):
            return

        try:
            author_info = await resolve_bilibili_author(video_url)
            from ..task_updater import update_and_notify

            await update_and_notify(
                task_id,
                {
                    "author_name": author_info.get("author_name"),
                    "author_url": author_info.get("author_url"),
                },
            )
            logger.info(
                f"[{self.name}] 已解析 B 站作者信息: "
                f"{author_info.get('author_name')} ({author_info.get('author_url')})"
            )
        except BilibiliAuthorResolveError as e:
            logger.info(f"[{self.name}] B 站作者信息解析失败（仅提示，不影响流程）: {e}")
        except Exception as e:
            logger.info(f"[{self.name}] B 站作者信息写入失败（仅提示，不影响流程）: {e}")

    def process_task(self, payload: Any):
        """
        下载视频并将其传递给下一个工作单元。
        
        :param payload: 包含 'video_url' 的字典。
        """
        video_url = payload.get("video_url")
        quality = payload.get("quality", "best")
        task_id = payload.get("task_id") # 用于更新进度

        if not video_url:
            error_msg = "任务负载中缺少 'video_url'"
            logger.error(f"[{self.name}] 错误: {error_msg}")
            if task_id:
                from ..db import TaskStatus
                from ..task_updater import update_and_notify
                self._submit_coro(update_and_notify(task_id, {"status": TaskStatus.FAILED, "error_message": error_msg}))
            return

        try:
            if task_id and self.is_task_cancelled(task_id):
                raise TaskCancelledError(f"任务已取消，跳过下载: {task_id}")

            if self._try_process_with_bilibili_subtitle(payload):
                return
        except TaskCancelledError as e:
            logger.info(f"[{self.name}] {e}")
            return

        logger.info(f"[{self.name}] 开始下载视频: {video_url} (质量: {quality})")

        if task_id:
            from ..db import TaskStatus
            from ..task_updater import update_and_notify
            self._submit_coro(update_and_notify(task_id, {"status": TaskStatus.DOWNLOADING}))

        def progress_hook(d):
            if task_id and self.is_task_cancelled(task_id):
                raise TaskCancelledError(f"任务已取消，停止下载: {task_id}")

            if d['status'] == 'error':
                error_msg = f"yt-dlp 下载时报告错误: {d.get('error', '未知错误')}"
                logger.error(f"[{self.name}] {error_msg}")
                raise yt_dlp.utils.DownloadError(error_msg)

            if d['status'] == 'downloading':
                raw_p = d.get('_percent_str', '0%')
                # 首先清理 ANSI 颜色代码，然后移除百分号和空格
                clean_p = re.sub(r'\x1B(?:[@-Z\-_]|\[[0-?]*[ -/]*[@-~])', '', raw_p)
                p = clean_p.replace('%','').strip()
                try:
                    progress = float(p)
                    if task_id:
                        from ..api import notify_progress_update
                        # 直接广播进度，不再写入数据库
                        self._submit_coro(notify_progress_update(task_id, progress))
                except ValueError:
                    logger.warning(f"[{self.name}] 无法从 yt-dlp 解析进度: '{p}' (原始值: '{raw_p}')")

        try:
            # 重置缓存，确保重新检测 ffmpeg 路径（避免缓存无效的相对路径）
            FFmpegHelper.reset_cache()
            # 配置 ffmpeg 路径（使用 FFmpegHelper）
            ffmpeg_location = FFmpegHelper.get_yt_dlp_ffmpeg_location()

            # 根据 quality 参数构建 yt-dlp format 字符串
            # 设计决策：
            # - lowest（默认）：最低画质视频 + 最佳音频，适合转录场景，省内存省带宽
            # - medium：720p 以下中等画质 + 最佳音频
            # - highest：最高画质 + 最佳音频（注意：高分辨率视频合并时内存占用大）
            # - audio_only：与 lowest 格式相同（yt-dlp 不支持纯音频流时仍需最低画质视频）
            format_map = {
                'lowest': 'worstvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/worst[ext=mp4]/best',
                'medium': (
                    'bestvideo[height<=720][vcodec^=avc]+bestaudio[acodec^=mp4a]'
                    '/bestvideo[height<=720]+bestaudio'
                    '/best[height<=720]'
                    '/worst[ext=mp4]/best'
                ),
                'highest': (
                    'bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]'
                    '/bestvideo+bestaudio'
                    '/best'
                ),
                'audio_only': 'worstvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/worst[ext=mp4]/best',
            }
            # 兜底：未知 quality 值使用 lowest 策略
            chosen_format = format_map.get(quality, format_map['lowest'])

            if quality == "audio_only":
                ydl_opts = {
                    'outtmpl': os.path.join(self.output_dir, '%(id)s.%(ext)s'),
                    'format': chosen_format,
                    'progress_hooks': [progress_hook],
                    'writethumbnail': False,
                    'writesubtitles': False,
                }
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(self.output_dir, '%(id)s.%(ext)s'),
                    'format': chosen_format,
                    'merge_output_format': 'mp4',
                    'progress_hooks': [progress_hook],
                }
            
            # 如果有 ffmpeg 路径，添加到配置中
            if ffmpeg_location:
                ydl_opts['ffmpeg_location'] = ffmpeg_location

            # YouTube 反爬机制要求登录态，自动从浏览器读取 cookies 绕过验证。
            # yt-dlp 会按浏览器名称查找本地 cookie 存储，不需要浏览器正在运行。
            if self._is_youtube_url(video_url):
                ydl_opts['cookiesfrombrowser'] = ('chrome',)
                # 指定 Node.js 作为 JS 运行时，用于解决 YouTube 的 n parameter challenge。
                # 不解决此挑战会导致大部分 HTTPS 直连格式不可用，只剩 HLS (m3u8) 格式。
                # 需要系统已安装 Node.js，并且 pip install "yt-dlp[default]" 安装了 yt-dlp-ejs。
                import shutil
                if shutil.which('node'):
                    ydl_opts['js_runtimes'] = {'node': {}}
                    logger.info(f"[{self.name}] 检测到 Node.js，将使用 node 作为 JS 运行时解决 YouTube 挑战")
                # YouTube 的 HLS (m3u8) 分片模式在代理/网络不稳定时容易出现
                # "fragment not found" 错误。覆盖通用 format，加入 protocol!=m3u8 排除 HLS 流。
                yt_format_map = {
                    'lowest': (
                        'worstvideo[vcodec^=avc][protocol!*=m3u8]+bestaudio[acodec^=mp4a][protocol!*=m3u8]'
                        '/worstvideo[protocol!*=m3u8]+bestaudio[protocol!*=m3u8]'
                        '/worst[protocol!*=m3u8]'
                        '/worstvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]'
                        '/worst[ext=mp4]/best'
                    ),
                    'medium': (
                        'bestvideo[height<=720][vcodec^=avc][protocol!*=m3u8]+bestaudio[acodec^=mp4a][protocol!*=m3u8]'
                        '/bestvideo[height<=720][protocol!*=m3u8]+bestaudio[protocol!*=m3u8]'
                        '/best[height<=720][protocol!*=m3u8]'
                        '/bestvideo[height<=720][vcodec^=avc]+bestaudio[acodec^=mp4a]'
                        '/best[height<=720]/best'
                    ),
                    'highest': (
                        'bestvideo[vcodec^=avc][protocol!*=m3u8]+bestaudio[acodec^=mp4a][protocol!*=m3u8]'
                        '/bestvideo[protocol!*=m3u8]+bestaudio[protocol!*=m3u8]'
                        '/best[protocol!*=m3u8]'
                        '/bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]'
                        '/best'
                    ),
                    'audio_only': (
                        'worstvideo[vcodec^=avc][protocol!*=m3u8]+bestaudio[acodec^=mp4a][protocol!*=m3u8]'
                        '/worstvideo[protocol!*=m3u8]+bestaudio[protocol!*=m3u8]'
                        '/worst[protocol!*=m3u8]'
                        '/worstvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]'
                        '/worst[ext=mp4]/best'
                    ),
                }
                ydl_opts['format'] = yt_format_map.get(quality, yt_format_map['lowest'])
                # HLS 分片下载的容错和重试配置（兜底时 HLS 仍可能被选中）
                ydl_opts['fragment_retries'] = 10
                ydl_opts['retries'] = 5
                ydl_opts['skip_unavailable_fragments'] = False
                logger.info(f"[{self.name}] 检测到 YouTube 链接，将从 Chrome 读取 cookies 并优先使用 HTTPS 直连格式下载")

            # B 站反爬机制：HTTP 412 Precondition Failed
            # B 站对未携带有效 Cookie 的请求会返回 412，需要注入 SESSDATA 来绕过。
            # 通过 yt-dlp 的 http_headers 注入 Cookie（比 cookiejar 文件更简洁）。
            if self._is_bilibili_url(video_url):
                sessdata, cookie_source = self._resolve_bilibili_sessdata(payload)
                if sessdata:
                    # 将 SESSDATA 注入到 HTTP 请求头的 Cookie 字段
                    existing_headers = ydl_opts.get('http_headers', {})
                    existing_headers['Cookie'] = f'SESSDATA={sessdata}'
                    existing_headers['Referer'] = 'https://www.bilibili.com/'
                    ydl_opts['http_headers'] = existing_headers
                    logger.info(
                        f"[{self.name}] 检测到 B 站链接，已注入 SESSDATA Cookie "
                        f"(来源: {cookie_source})"
                    )
                else:
                    # 没有 SESSDATA 时，尝试从浏览器读取 Cookie 作为兜底
                    # 注意：macOS 上可能需要 Keychain 授权弹窗
                    ydl_opts['cookiesfrombrowser'] = ('chrome',)
                    logger.warning(
                        f"[{self.name}] 检测到 B 站链接但未配置 SESSDATA，"
                        f"将尝试从 Chrome 读取 cookies（可能触发系统授权弹窗）"
                    )

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=True)
                video_path = ydl.prepare_filename(info_dict)

            logger.info(f"[{self.name}] 视频下载成功: {video_path}")

            if task_id and self.is_task_cancelled(task_id):
                raise TaskCancelledError(f"任务已取消，停止后续处理: {task_id}")

            if task_id and self._is_bilibili_url(str(video_url)):
                self._submit_coro(self._resolve_and_save_bilibili_author(task_id, str(video_url)))

            if task_id:
                logger.info(
                    f"[VideoDownloader] Download completed: task_id={task_id}, "
                    f"status: DOWNLOADING→TRANSCRIBING, video={video_path}"
                )

                from ..db import TaskStatus
                from ..task_updater import update_and_notify
                self._submit_coro(update_and_notify(task_id, {"status": TaskStatus.TRANSCRIBING}))

            if self.next_worker:
                next_payload = payload.copy()
                next_payload['video_file'] = video_path
                base_name = os.path.splitext(os.path.basename(video_path))[0]
                next_payload['audio_file'] = os.path.join(self.output_dir, f"{base_name}.mp3")
                next_payload['output_file'] = os.path.join(self.output_dir, f"{base_name}_summary.md")
                
                self._submit_coro(self.next_worker.add_task(next_payload))

        except TaskCancelledError as e:
            logger.info(f"[{self.name}] {e}")
        except Exception as e:
            logger.error(f"[{self.name}] 下载视频时出错: {e}", exc_info=True)
            if task_id:
                from ..db import TaskStatus
                from ..task_updater import update_and_notify
                # 清理错误信息中的 ANSI 转义序列
                clean_error = re.sub(r'\x1B(?:[@-Z\-_]|\[[0-?]*[ -/]*[@-~])', '', str(e))
                self._submit_coro(update_and_notify(task_id, {"status": TaskStatus.FAILED, "error_message": clean_error}))
