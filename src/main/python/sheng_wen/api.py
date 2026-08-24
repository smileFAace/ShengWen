import os
import sys
import asyncio
import json
import glob
import ipaddress
import subprocess
import yt_dlp
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Request
from fastapi import Form
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional
import uuid
from datetime import datetime
from urllib.parse import unquote, urlparse
from .db import db, TaskStatus
from .utils.logger import logger
from .config.settings import config, get_config_manager
from .version import APP_VERSION
from .llm.llm import LLMConfig
from .llm.provider_manager import LLMProviderManager
from .transcriber.settings_manager import TranscriptionSettingsManager
from .transcriber.transcriber import ModelLoadError
from .utils.media import (
    SUPPORTED_MEDIA_EXTENSIONS,
    SUPPORTED_UPLOAD_EXTENSIONS,
    build_transcriber_payload,
    is_subtitle_text_file,
)
from .downloader.bilibili_author_resolver import (
    resolve_bilibili_author,
    BilibiliAuthorResolveError,
)

app = FastAPI(title="ShengWen API", description="视频转录与 AI 总结服务", version=APP_VERSION)

VALID_SUMMARY_MODES = {"auto", "standard", "agent"}


def _build_model_load_error_detail(error: ModelLoadError) -> str:
    detail = str(error or "").strip()
    return detail or "转录模型加载失败，请检查模型配置、网络或代理设置后重试。"


async def _fail_task_with_model_error(task_id: str | None, error: ModelLoadError) -> None:
    detail = _build_model_load_error_detail(error)
    logger.warning(f"[Transcriber] 模型加载失败: task_id={task_id}, detail={detail}")
    if not task_id:
        return
    from .task_updater import update_and_notify
    await update_and_notify(
        task_id,
        {
            "status": TaskStatus.FAILED,
            "error_message": detail,
        },
    )


async def _resolve_worker_or_raise(worker_factory, task_id: str | None = None):
    try:
        return await worker_factory()
    except ModelLoadError as e:
        await _fail_task_with_model_error(task_id, e)
        raise HTTPException(status_code=503, detail=_build_model_load_error_detail(e)) from e


@app.exception_handler(ModelLoadError)
async def handle_model_load_error(_: Request, exc: ModelLoadError):
    return JSONResponse(
        status_code=503,
        content={"detail": _build_model_load_error_detail(exc)},
    )

# 允许跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件（前端打包后的文件）
# 使用绝对路径以确保在不同目录下启动都能找到文件
# api.py 位于 src/main/python/sheng_wen/api.py，需要向上跳 5 级到达项目根目录
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
dist_dir = os.path.join(base_dir, "frontend", "dist")

if os.path.exists(dist_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(dist_dir, "assets")), name="assets")
    
    @app.get("/")
    async def read_index():
        from fastapi.responses import FileResponse
        return FileResponse(os.path.join(dist_dir, "index.html"))

# --- 数据模型 ---

class TaskCreate(BaseModel):
    video_url: HttpUrl
    quality: Optional[str] = "best" # "best", "audio_only"
    summary_mode: Optional[str] = Field(
        default=None,
        description="总结模式: standard | agent | auto（前端建议仅 standard/agent）",
    )
    bilibili_sessdata: Optional[str] = Field(
        default=None,
        description="任务级 B 站 SESSDATA，可覆盖全局配置与环境变量",
    )

class LocalPathTaskCreate(BaseModel):
    file_path: str = Field(..., min_length=1, description="本机文件绝对路径")
    summary_mode: Optional[str] = Field(
        default=None,
        description="总结模式: standard | agent | auto（前端建议仅 standard/agent）",
    )

class TaskUpdate(BaseModel):
    topic: Optional[str] = None
    summary: Optional[str] = None

class Task(BaseModel):
    id: str
    video_url: str
    status: TaskStatus
    created_at: datetime
    latest_modified_at: Optional[datetime] = None
    progress: float = 0.0
    title: Optional[str] = None
    topic: Optional[str] = None
    transcript: Optional[str] = None
    summary: Optional[str] = None
    error_message: Optional[str] = None
    audio_duration: Optional[float] = None
    transcription_time: Optional[float] = None
    author_name: Optional[str] = None
    author_url: Optional[str] = None
    summary_mode: Optional[str] = None
    summary_chunk_total: Optional[int] = None
    summary_chunk_done: Optional[int] = None
    summary_meta: Optional[str] = None
    folder_id: Optional[str] = None


class FolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    parent_id: Optional[str] = Field(default=None, description="父文件夹ID，NULL为顶层")

class FolderUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    parent_id: Optional[str] = Field(default=None, description="移动到新父文件夹")
    sort_order: Optional[int] = None

class TaskFolderAssign(BaseModel):
    folder_id: Optional[str] = Field(default=None, description="分配到文件夹，NULL为取消分配")

class Folder(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
    folder_type: str = "manual"
    source_video_url: Optional[str] = None
    sort_order: int = 0
    created_at: Optional[datetime] = None


class ReSummarizeRequest(BaseModel):
    summary_mode: Optional[str] = Field(
        default=None,
        description="重新总结时指定模式: standard | agent | auto",
    )


class ReTranscribeRequest(BaseModel):
    summary_mode: Optional[str] = Field(
        default=None,
        description="重新转录后进入总结时指定模式: standard | agent | auto",
    )


class LLMProviderInfo(BaseModel):
    id: str
    label: str
    default_base_url: str
    default_model_id: str
    description: str


class LLMProfileInfo(BaseModel):
    id: str
    name: str
    provider: str
    base_url: str
    model_id: str
    temperature: float
    context_window_size: int
    has_api_key: bool
    api_key_hint: str


class LLMProfilesSettings(BaseModel):
    active_profile_id: str
    profiles: List[LLMProfileInfo]


class LLMProfileCreate(BaseModel):
    name: str = Field(..., description="Profile 名称")
    provider: str = Field(..., description="供应商类型")
    base_url: Optional[str] = None
    api_key: Optional[str] = Field(default=None, description="API Key（可选）")
    model_id: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)


class LLMProfileUpdate(BaseModel):
    profile_id: str = Field(..., description="要更新的 Profile ID")
    name: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = Field(default=None, description="不传则保持当前密钥")
    model_id: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    context_window_size: Optional[int] = Field(default=None, ge=1)


class LLMActiveProfileUpdate(BaseModel):
    profile_id: str


class TranscriptionSettings(BaseModel):
    device: str
    model_source: str
    model_size: str
    model_path: str
    compute_type_mode: str
    compute_type: str
    manual_compute_type: str
    available_compute_types: List[str]
    model_path_valid: bool
    model_path_message: str
    model_path_resolved: str
    required_model_files: List[str]
    cuda_available: bool
    available_devices: List[str]
    has_nvidia_gpu: bool
    torch_installed: bool
    torch_cuda_built: bool
    ctranslate2_installed: bool
    ctranslate2_cuda_device_count: int
    cuda_reason: str
    cuda_message: str
    enable_bilibili_subtitle_fetch: bool
    has_bilibili_sessdata: bool
    bilibili_cookie_source: str
    bilibili_sessdata_masked: str


class TranscriptionSettingsUpdate(BaseModel):
    device: Optional[str] = Field(default=None, description="cpu 或 cuda")
    model_source: Optional[str] = Field(default=None, description="auto_download 或 manual_path")
    model_size: Optional[str] = Field(default=None, description="tiny/base/small/medium/large")
    model_path: Optional[str] = Field(default=None, description="手动模型目录路径")
    compute_type_mode: Optional[str] = Field(default=None, description="auto 或 manual")
    compute_type: Optional[str] = Field(default=None, description="int8/float16/float32/bfloat16")
    enable_bilibili_subtitle_fetch: Optional[bool] = Field(
        default=None,
        description="是否优先尝试直取 B 站字幕（失败时回退 ASR）"
    )
    bilibili_sessdata: Optional[str] = Field(
        default=None,
        description="设置全局 B 站 SESSDATA（明文保存在本机 config/settings.json）",
    )
    clear_bilibili_sessdata: Optional[bool] = Field(
        default=None,
        description="是否清空当前保存的全局 B 站 SESSDATA",
    )


class BilibiliCookieFromBrowserResult(BaseModel):
    success: bool = Field(description="是否成功读取")
    sessdata: Optional[str] = Field(default=None, description="读取到的 SESSDATA（完整值）")
    sessdata_masked: Optional[str] = Field(default=None, description="脱敏后的 SESSDATA")
    source_browser: Optional[str] = Field(default=None, description="读取来源浏览器")
    error: Optional[str] = Field(default=None, description="错误信息")


class BilibiliVideoPartInfo(BaseModel):
    index: int = Field(description="分P索引（0-based）")
    cid: int = Field(description="分P的 cid")
    title: str = Field(description="分P标题")
    duration: int = Field(description="分P时长（秒）")


class BilibiliVideoInfoRequest(BaseModel):
    url: str = Field(..., description="B站视频链接")


class BilibiliVideoInfo(BaseModel):
    is_multi_part: bool = Field(description="是否为多P视频")
    title: str = Field(description="视频标题")
    bvid: str = Field(description="BV号")
    duration: int = Field(description="视频总时长（秒）")
    parts: Optional[List[BilibiliVideoPartInfo]] = Field(default=None, description="分P列表（仅多P视频）")


class BilibiliPartsConfig(BaseModel):
    mode: str = Field(description="处理模式: merge（合并）或 separate（拆分）")
    indices: List[int] = Field(description="要处理的分P索引列表")


class TaskCreate(BaseModel):
    video_url: HttpUrl
    quality: Optional[str] = "best" # "best", "audio_only"
    summary_mode: Optional[str] = Field(
        default=None,
        description="总结模式: standard | agent | auto（前端建议仅 standard/agent）",
    )
    bilibili_sessdata: Optional[str] = Field(
        default=None,
        description="任务级 B 站 SESSDATA，可覆盖全局配置与环境变量",
    )
    bilibili_parts: Optional[BilibiliPartsConfig] = Field(
        default=None,
        description="B站分P处理配置（仅多P视频需要）",
    )


class SummarizationSettings(BaseModel):
    mode: str
    auto_chunk_min_audio_duration_sec: int
    auto_chunk_min_transcript_lines: int
    chunk_target_duration_sec: int
    chunk_min_duration_sec: int
    chunk_max_duration_sec: int
    boundary_jump_sec: int
    prev_tail_timestamp_lines_m: int
    prev_summary_tail_chars_j: int
    llm_call_retry_max: int
    max_agent_value_chars: int
    fallback_to_standard_on_agent_error: bool


class SummarizationSettingsUpdate(BaseModel):
    mode: Optional[str] = Field(default=None, description="auto | standard | agent")
    auto_chunk_min_audio_duration_sec: Optional[int] = Field(default=None, ge=300)
    auto_chunk_min_transcript_lines: Optional[int] = Field(default=None, ge=100)
    chunk_target_duration_sec: Optional[int] = Field(default=None, ge=60)
    chunk_min_duration_sec: Optional[int] = Field(default=None, ge=30)
    chunk_max_duration_sec: Optional[int] = Field(default=None, ge=60)
    boundary_jump_sec: Optional[int] = Field(default=None, ge=1)
    prev_tail_timestamp_lines_m: Optional[int] = Field(default=None, ge=0)
    prev_summary_tail_chars_j: Optional[int] = Field(default=None, ge=0)
    llm_call_retry_max: Optional[int] = Field(default=None, ge=1)
    max_agent_value_chars: Optional[int] = Field(default=None, ge=100)
    fallback_to_standard_on_agent_error: Optional[bool] = None


class LLMTestResult(BaseModel):
    status: str  # "success", "warning", "error"
    message: str
    response: Optional[str] = None


class VersionInfo(BaseModel):
    version: str


# --- WebSocket 管理 ---

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()
_author_resolution_inflight_task_ids: set[str] = set()
_author_resolution_attempted_task_ids: set[str] = set()
_prewarm_ready = False


def set_prewarm_ready():
    """标记预热完成并广播给所有客户端"""
    global _prewarm_ready
    _prewarm_ready = True
    import asyncio
    asyncio.ensure_future(manager.broadcast(json.dumps({
        "type": "prewarm_status",
        "ready": True,
    })))
    logger.info("--- [Prewarm] 后台预热完成，已通知前端 ---")


async def notify_prewarm_status():
    """主动推送预热状态给客户端"""
    await manager.broadcast(json.dumps({
        "type": "prewarm_status",
        "ready": _prewarm_ready,
    }))

async def notify_task_update(task_id: str, task_data: dict = None):
    """
    通知所有客户端任务已更新

    Args:
        task_id: 任务ID
        task_data: 可选的任务数据，如果不提供则从数据库读取
                   传入此参数可避免重复读取数据库，确保广播的是最新数据
    """
    if task_data is None:
        task_data = db.get_task(task_id)

    if task_data:
        # Convert datetime to string for JSON broadcast
        if isinstance(task_data.get("created_at"), datetime):
            task_data["created_at"] = task_data["created_at"].isoformat()
        if isinstance(task_data.get("latest_modified_at"), datetime):
            task_data["latest_modified_at"] = task_data["latest_modified_at"].isoformat()

        message = json.dumps({
            "type": "task_update",
            "task": task_data
        })

        await manager.broadcast(message)
    else:
        # 添加日志：任务不存在
        logger.warning(f"[WebSocket] Task not found for broadcast: task_id={task_id}")

async def notify_progress_update(task_id: str, progress: float):
    """直接向客户端广播一个轻量级的进度更新事件。"""
    message = json.dumps({
        "type": "progress_update",
        "task_id": task_id,
        "progress": progress
    })
    logger.debug(f"{message}")
    await manager.broadcast(message)


async def notify_summary_delta(task_id: str, delta: str, chunk_done: int | None = None, chunk_total: int | None = None):
    """高频增量文本广播。不写DB，不防抖。前端用于实时流式渲染。"""
    message_dict: dict = {
        "type": "summary_delta",
        "task_id": task_id,
        "delta": delta,
    }
    if chunk_done is not None:
        message_dict["chunk_done"] = chunk_done
    if chunk_total is not None:
        message_dict["chunk_total"] = chunk_total
    await manager.broadcast(json.dumps(message_dict))

# --- 接口定义 ---

# 全局 Worker 引用（懒加载模式 - 由 Worker 基类管理初始化）
downloader_worker = None
file_upload_worker = None
llm_worker = None
transcriber_worker = None

config_manager = get_config_manager()


@app.get("/version", response_model=VersionInfo)
async def get_version():
    return {"version": APP_VERSION}


@app.get("/prewarm/status")
async def get_prewarm_status():
    return {"ready": _prewarm_ready}


llm_cfg = config.llm
initial_llm_config = LLMConfig(
    base_url=llm_cfg.base_url,
    api_key=llm_cfg.api_key,
    model_id=llm_cfg.model_id,
    temperature=llm_cfg.temperature,
    context_window_size=llm_cfg.context_window_size,
    provider=llm_cfg.provider,
)
initial_provider_id = llm_cfg.provider.strip() if llm_cfg.provider.strip() else None

llm_provider_manager = LLMProviderManager(
    initial_config=initial_llm_config,
    initial_provider_id=initial_provider_id,
)
# Load all profiles from settings.json into the manager
llm_profiles_config = config_manager.get_llm_profiles_config()
llm_provider_manager.load_profiles(
    [{"id": p.id, "name": p.name, "provider": p.provider, "base_url": p.base_url, "api_key": p.api_key, "model_id": p.model_id, "temperature": p.temperature, "context_window_size": p.context_window_size} for p in llm_profiles_config.profiles],
    llm_profiles_config.active_profile_id,
)

whisper_cfg = config.whisper
initial_transcription_device = str(whisper_cfg.device).lower()
if initial_transcription_device not in {"cpu", "cuda"}:
    initial_transcription_device = "cpu"
initial_enable_bilibili_subtitle_fetch = bool(whisper_cfg.enable_bilibili_subtitle_fetch)
initial_bilibili_sessdata = str(whisper_cfg.bilibili_sessdata or "")

transcription_settings_manager = TranscriptionSettingsManager(
    initial_device=initial_transcription_device,
    model_source=str(whisper_cfg.model_source),
    model_size=whisper_cfg.model_size,
    model_path=whisper_cfg.configured_model_path,
    initial_compute_type_mode=str(whisper_cfg.compute_type_mode),
    initial_compute_type=str(whisper_cfg.compute_type),
    initial_enable_bilibili_subtitle_fetch=initial_enable_bilibili_subtitle_fetch,
    initial_bilibili_sessdata=initial_bilibili_sessdata,
)


# --- 全局 Worker 工厂函数（懒初始化）---

async def get_llm_worker():
    """获取 LLM Worker（懒初始化）"""
    global llm_worker
    if llm_worker is not None:
        return llm_worker

    from .llm.llm import get_llm
    from .llm.llm_worker import LLMWorker

    llm_config = llm_provider_manager.get_runtime_config()
    llm_client = get_llm(llm_config)
    llm_worker = LLMWorker(name="LLMWorker", llm_client=llm_client)
    llm_worker.load_system_prompt(config.app.prompt_file)
    llm_provider_manager.bind_llm_worker(llm_worker)
    llm_worker.start()
    return llm_worker


async def get_transcriber_worker():
    """获取 Transcriber Worker（懒初始化）"""
    global transcriber_worker
    if transcriber_worker is not None:
        return transcriber_worker

    from .transcriber.transcriber import get_transcriber
    from .transcriber.transcriber_worker import TranscriberWorker

    runtime_transcription_state = transcription_settings_manager.get_runtime_state()
    transcriber_config = transcription_settings_manager.build_transcriber_kwargs()
    model_source = str(runtime_transcription_state.get("model_source") or "auto_download")

    if model_source == "manual_path":
        logger.info(f"[Transcriber] 使用本地模型路径: {transcriber_config.get('model_size_or_path')}")
    else:
        logger.info(f"[Transcriber] 使用模型大小: {transcriber_config.get('model_size')}")

    transcriber = get_transcriber("fast_whisper", **transcriber_config)
    llm_w = await get_llm_worker()
    transcriber_worker = TranscriberWorker(
        name="TranscriberWorker",
        transcriber=transcriber,
        next_worker=llm_w
    )
    transcription_settings_manager.bind_transcriber_worker(transcriber_worker)
    transcriber_worker.start()
    return transcriber_worker


async def get_downloader_worker():
    """获取 Downloader Worker（懒初始化）"""
    global downloader_worker
    if downloader_worker is not None:
        return downloader_worker

    from .downloader.video_downloader_worker import VideoDownloaderWorker

    transcriber_w = await get_transcriber_worker()
    llm_w = await get_llm_worker()

    downloader_worker = VideoDownloaderWorker(
        name="VideoDownloaderWorker",
        next_worker=transcriber_w,
        summary_worker=llm_w,
        transcription_settings_manager=transcription_settings_manager,
    )
    downloader_worker.start()
    return downloader_worker


async def get_file_upload_worker():
    """获取 File Upload Worker（懒初始化）"""
    global file_upload_worker
    if file_upload_worker is not None:
        return file_upload_worker

    from .downloader.file_upload_worker import FileUploadWorker

    transcriber_w = await get_transcriber_worker()
    llm_w = await get_llm_worker()

    file_upload_worker = FileUploadWorker(
        name="FileUploadWorker",
        next_worker=transcriber_w,
        summary_worker=llm_w,
    )
    file_upload_worker.start()
    return file_upload_worker


async def stop_all_workers():
    """停止所有已初始化的 workers"""
    workers = [downloader_worker, file_upload_worker, transcriber_worker, llm_worker]
    for worker in workers:
        if worker is not None:
            try:
                await worker.stop()
                logger.info(f"[Shutdown] {worker.name} 已停止")
            except Exception as e:
                logger.warning(f"[Shutdown] 停止 {worker.name} 失败: {e}")


def _is_loopback_client(request: Request) -> bool:
    """仅允许本机请求使用本地路径提交，避免任意文件读取风险。"""
    client = request.client
    if client is None or not client.host:
        return False

    host = client.host.strip().lower()
    if host == "localhost":
        return True

    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _resolve_file_url_path(file_url: str) -> str:
    if not file_url.startswith("file://"):
        return ""

    # 优先兼容目前项目内保存的 "file://temp\\xxx" 格式
    raw_path = file_url.replace("file://", "", 1)
    if raw_path:
        return raw_path

    parsed = urlparse(file_url)
    path = unquote(parsed.path or "")
    if len(path) > 2 and path[0] == "/" and path[2] == ":":
        # Windows path: /E:/path -> E:/path
        path = path[1:]
    return path


def _is_bilibili_video_url(video_url: str) -> bool:
    try:
        netloc = (urlparse(video_url).netloc or "").lower()
    except Exception:
        return False
    return "bilibili.com" in netloc or "b23.tv" in netloc


def _sanitize_cookie_value(value: str | None) -> str:
    return (value or "").strip().replace("\r", "").replace("\n", "")


def _resolve_default_summary_mode() -> str:
    configured = str(config.summarization.mode or "auto").strip().lower()
    if configured in VALID_SUMMARY_MODES:
        return configured
    return "auto"


def _normalize_summary_mode(raw_value: str | None, fallback: str | None = None) -> str:
    candidate = str(raw_value or "").strip().lower()
    if candidate in VALID_SUMMARY_MODES:
        return candidate
    fb = str(fallback or "").strip().lower()
    if fb in VALID_SUMMARY_MODES:
        return fb
    return _resolve_default_summary_mode()


async def _try_resolve_and_persist_author(task_id: str, video_url: str) -> bool:
    try:
        from .task_updater import update_and_notify
        sessdata = ""
        try:
            sessdata, _source = transcription_settings_manager.resolve_bilibili_sessdata()
        except Exception as cookie_err:
            logger.info(f"[AuthorResolver] 读取 B 站 Cookie 失败，将无 Cookie 解析: {cookie_err}")
        author_info = await resolve_bilibili_author(video_url, sessdata=sessdata)
        await update_and_notify(
            task_id,
            {
                "author_name": author_info.get("author_name"),
                "author_url": author_info.get("author_url"),
            },
        )
        return True
    except BilibiliAuthorResolveError as e:
        logger.info(f"[AuthorResolver] 任务 {task_id} 作者解析失败（仅提示，不影响流程）: {e}")
        return False
    except Exception as e:
        logger.info(f"[AuthorResolver] 任务 {task_id} 作者回填失败（仅提示，不影响流程）: {e}")
        return False


def _should_trigger_author_resolution(task: dict | None) -> bool:
    if not isinstance(task, dict):
        return False

    task_id = str(task.get("id") or "")
    video_url = str(task.get("video_url") or "")
    author_name = str(task.get("author_name") or "").strip()
    author_url = str(task.get("author_url") or "").strip()
    if not task_id or not video_url:
        return False
    if video_url.startswith("file://"):
        return False
    if not _is_bilibili_video_url(video_url):
        return False
    if author_name and author_url:
        return False
    if task_id in _author_resolution_attempted_task_ids:
        return False
    if task_id in _author_resolution_inflight_task_ids:
        return False
    return True


async def _resolve_author_once_in_background(task_id: str, video_url: str):
    _author_resolution_inflight_task_ids.add(task_id)
    _author_resolution_attempted_task_ids.add(task_id)
    try:
        await _try_resolve_and_persist_author(task_id, video_url)
    finally:
        _author_resolution_inflight_task_ids.discard(task_id)


def _trigger_author_resolution_if_needed(task: dict | None):
    if not _should_trigger_author_resolution(task):
        return

    task_id = str(task.get("id") or "")
    video_url = str(task.get("video_url") or "")
    asyncio.create_task(_resolve_author_once_in_background(task_id, video_url))


def _resolve_local_media_file(task_id: str, task: dict) -> str | None:
    # 1) 优先尝试任务中记录的 file:// 路径
    video_url = str(task.get("video_url") or "")
    if video_url.startswith("file://"):
        candidate = _resolve_file_url_path(video_url)
        if candidate and os.path.exists(candidate):
            return candidate

    # 2) 尝试上传任务的惯例命名：temp/{task_id}.<ext>
    for ext in SUPPORTED_MEDIA_EXTENSIONS:
        candidate = os.path.join("temp", f"{task_id}{ext}")
        if os.path.exists(candidate):
            return candidate

    # 3) 兜底扫描：temp/{task_id}.*
    for path in glob.glob(os.path.join("temp", f"{task_id}.*")):
        ext = os.path.splitext(path)[1].lower()
        if ext in SUPPORTED_MEDIA_EXTENSIONS and os.path.exists(path):
            return path
    return None


@app.post("/upload", response_model=Task, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    summary_mode: Optional[str] = Form(default=None),
):
    """
    接收上传的视频/音频文件
    """
    # 验证文件类型
    file_ext = os.path.splitext(file.filename)[1].lower() if file.filename else ''

    if file_ext not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {file_ext}。支持的格式: {', '.join(sorted(SUPPORTED_UPLOAD_EXTENSIONS))}"
        )

    # 创建任务 ID
    task_id = str(uuid.uuid4())

    # 保存上传的文件到临时目录
    temp_dir = "temp"
    os.makedirs(temp_dir, exist_ok=True)

    # 临时保存路径（在 FileUploadWorker 处理后会重命名）
    temp_file_path = os.path.join(temp_dir, f"{task_id}_temp{file_ext}")

    try:
        # 保存文件
        with open(temp_file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        file_size = len(content)
        file_size_mb = file_size / 1024 / 1024

        # 检查文件大小限制 (500MB)
        max_size = 500 * 1024 * 1024
        if file_size > max_size:
            os.remove(temp_file_path)
            raise HTTPException(
                status_code=400,
                detail=f"文件过大 ({file_size_mb:.1f}MB)，最大支持 {max_size / 1024 / 1024:.0f}MB"
            )

        resolved_summary_mode = _normalize_summary_mode(summary_mode)

        # 创建任务记录
        task_data = {
            "id": task_id,
            "video_url": f"file://{temp_file_path}",
            "status": TaskStatus.UPLOADING,
            "created_at": datetime.utcnow(),
            "latest_modified_at": datetime.utcnow(),
            "progress": 0.0,
            "title": os.path.splitext(file.filename)[0] if file.filename else "Uploaded File",
            "author_name": None,
            "author_url": None,
            "summary_mode": resolved_summary_mode,
            "summary_chunk_total": None,
            "summary_chunk_done": None,
            "summary_meta": None,
        }
        db.save_task(task_id, task_data)

        # 提交给 FileUploadWorker 处理（懒初始化）
        worker = await _resolve_worker_or_raise(get_file_upload_worker, task_id=task_id)
        await worker.add_task({
            "task_id": task_id,
            "file_path": temp_file_path,
            "filename": file.filename or "uploaded_file",
                "summary_mode": resolved_summary_mode,
            })

        await notify_task_update(task_id)
        return task_data

    except HTTPException:
        # 重新抛出 HTTP 异常
        raise
    except Exception as e:
        # 清理临时文件
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        logger.error(f"文件上传失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")


@app.get("/local-path/check")
async def check_local_path(file_path: str, request: Request):
    """
    检查本地路径类型（仅允许 localhost）。
    返回: { "type": "file" | "folder" | "not_found", "path": "..." }
    """
    if not _is_loopback_client(request):
        raise HTTPException(
            status_code=403,
            detail="仅允许本机 localhost 请求。"
        )

    raw_path = (file_path or "").strip().strip('"').strip("'")
    if not raw_path:
        return {"type": "not_found", "path": ""}

    local_path = os.path.abspath(os.path.expandvars(os.path.expanduser(raw_path)))

    if not os.path.exists(local_path):
        return {"type": "not_found", "path": local_path}

    if os.path.isfile(local_path):
        return {"type": "file", "path": local_path}

    if os.path.isdir(local_path):
        return {"type": "folder", "path": local_path}

    return {"type": "not_found", "path": local_path}


@app.get("/local-folder/scan")
async def scan_local_folder(folder_path: str, request: Request):
    """
    扫描本地文件夹，返回支持的视频/音频文件列表（仅允许 localhost）。
    """
    if not _is_loopback_client(request):
        raise HTTPException(
            status_code=403,
            detail="仅允许本机 localhost 请求。"
        )

    raw_path = (folder_path or "").strip().strip('"').strip("'")
    if not raw_path:
        raise HTTPException(status_code=400, detail="folder_path 不能为空")

    local_path = os.path.abspath(os.path.expandvars(os.path.expanduser(raw_path)))
    if not os.path.exists(local_path) or not os.path.isdir(local_path):
        raise HTTPException(status_code=400, detail=f"文件夹不存在: {local_path}")

    files = []
    try:
        for entry in os.scandir(local_path):
            if not entry.is_file():
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            if ext not in SUPPORTED_MEDIA_EXTENSIONS:
                continue
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            files.append({
                "name": entry.name,
                "path": entry.path,
                "size": size,
            })
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"扫描文件夹失败: {e}")

    # 按文件名排序
    files.sort(key=lambda x: x["name"].lower())

    return {"folder_path": local_path, "files": files, "total": len(files)}


@app.post("/upload/local-path", response_model=Task, status_code=201)
async def upload_local_path(payload: LocalPathTaskCreate, request: Request):
    """
    本机路径直读提交（仅允许 localhost/127.0.0.1/::1 请求）。
    """
    if not _is_loopback_client(request):
        raise HTTPException(
            status_code=403,
            detail="仅允许本机 localhost 请求使用本地路径直读。"
        )

    raw_path = (payload.file_path or "").strip().strip('"')
    if not raw_path:
        raise HTTPException(status_code=400, detail="file_path 不能为空")

    local_path = os.path.abspath(os.path.expandvars(os.path.expanduser(raw_path)))
    if not os.path.exists(local_path) or not os.path.isfile(local_path):
        raise HTTPException(status_code=400, detail=f"文件不存在或不可访问: {local_path}")

    file_ext = os.path.splitext(local_path)[1].lower()
    if file_ext not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {file_ext}。支持的格式: {', '.join(sorted(SUPPORTED_UPLOAD_EXTENSIONS))}"
        )

    task_id = str(uuid.uuid4())
    title = os.path.splitext(os.path.basename(local_path))[0] or "Local File"
    resolved_summary_mode = _normalize_summary_mode(payload.summary_mode)
    os.makedirs("temp", exist_ok=True)
    task_data = {
        "id": task_id,
        "video_url": f"file://{local_path}",
        "status": TaskStatus.TRANSCRIBING,
        "created_at": datetime.utcnow(),
        "latest_modified_at": datetime.utcnow(),
        "progress": 0.0,
        "title": title,
        "author_name": None,
        "author_url": None,
        "summary_mode": resolved_summary_mode,
        "summary_chunk_total": None,
        "summary_chunk_done": None,
        "summary_meta": None,
    }
    db.save_task(task_id, task_data)

    # 字幕/文稿文件：交给 FileUploadWorker 直接解析为转录文本进入总结，跳过语音识别。
    if is_subtitle_text_file(local_path):
        upload_worker = await _resolve_worker_or_raise(get_file_upload_worker, task_id=task_id)
        await upload_worker.add_task({
            "task_id": task_id,
            "file_path": local_path,
            "filename": os.path.basename(local_path),
            "summary_mode": resolved_summary_mode,
            "move_file": False,
        })
        await notify_task_update(task_id)
        return task_data

    payload_data = build_transcriber_payload(
        task_id=task_id,
        media_path=local_path,
        output_dir="temp",
        summary_mode=resolved_summary_mode,
    )

    worker = await _resolve_worker_or_raise(get_transcriber_worker, task_id=task_id)
    await worker.add_task(payload_data)
    await notify_task_update(task_id)
    return task_data

async def _get_bilibili_video_title_and_parts(video_url: str) -> tuple[str, list]:
    """获取 B 站视频标题和分P信息。返回 (title, parts_list)。"""
    from bilibili_api import video, sync
    import re
    from urllib.request import Request, urlopen

    # 解析 BV 号
    candidate = video_url
    if "b23.tv" in video_url:
        try:
            request = Request(video_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=15) as response:
                candidate = response.geturl()
        except Exception:
            pass

    match = re.search(r"/video/(BV[0-9A-Za-z]+)", candidate)
    if not match:
        fallback = re.search(r"(BV[0-9A-Za-z]+)", candidate)
        if fallback:
            bvid = fallback.group(1)
        else:
            return ("未知标题", [])
    else:
        bvid = match.group(1)

    video_obj = video.Video(bvid=bvid)
    info = sync(video_obj.get_info())

    title = str(info.get("title") or "未知标题")
    pages = info.get("pages", [])
    parts = []
    for page in pages:
        if isinstance(page, dict):
            parts.append({
                "index": int(page.get("page", 0)) - 1,  # 0-based
                "title": str(page.get("part") or ""),
            })
    return (title, parts)


@app.post("/tasks/", response_model=Task, status_code=201)
async def create_task(task_in: TaskCreate):
    """
    提交一个新的视频处理任务
    """
    # 处理 B 站分P拆分模式
    if task_in.bilibili_parts and task_in.bilibili_parts.mode == "separate":
        # 获取视频标题和分P信息
        try:
            video_title, parts_info = await _get_bilibili_video_title_and_parts(str(task_in.video_url))
        except Exception as e:
            logger.warning(f"获取 B 站视频标题失败: {e}")
            video_title = "未知标题"
            parts_info = []

        # 自动创建文件夹，将所有分P任务归入
        folder_id = str(uuid.uuid4())
        folder_data = {
            "id": folder_id,
            "name": video_title,
            "parent_id": None,
            "folder_type": "auto",
            "source_video_url": str(task_in.video_url),
            "sort_order": 0,
            "created_at": datetime.utcnow(),
        }
        db.create_folder(folder_data)
        await manager.broadcast(json.dumps({"type": "folder_created", "folder": db.get_folder(folder_id)}))

        # 为每个选中的分P创建独立任务
        first_task_data = None
        for part_index in task_in.bilibili_parts.indices:
            task_id = str(uuid.uuid4())
            resolved_summary_mode = _normalize_summary_mode(task_in.summary_mode)

            # 获取分P标题
            part_title = ""
            for p in parts_info:
                if p["index"] == part_index:
                    part_title = p["title"]
                    break

            # 构建任务标题
            task_title = f"{video_title} - P{part_index + 1}"
            if part_title:
                task_title = f"{video_title} - P{part_index + 1}: {part_title}"

            task_data = {
                "id": task_id,
                "video_url": str(task_in.video_url),
                "status": TaskStatus.PENDING,
                "created_at": datetime.utcnow(),
                "latest_modified_at": datetime.utcnow(),
                "progress": 0.0,
                "title": task_title,
                "folder_id": folder_id,
                "author_name": None,
                "author_url": None,
                "summary_mode": resolved_summary_mode,
                "summary_chunk_total": None,
                "summary_chunk_done": None,
                "summary_meta": None,
            }
            db.save_task(task_id, task_data)

            worker = await _resolve_worker_or_raise(get_downloader_worker, task_id=task_id)
            task_payload = {
                "task_id": task_id,
                "video_url": str(task_in.video_url),
                "quality": task_in.quality,
                "summary_mode": resolved_summary_mode,
                # 传递单个分P索引，让 worker 处理该分P
                "bilibili_parts": {
                    "mode": "merge",  # 单个分P用 merge 模式即可
                    "indices": [part_index],
                },
            }
            task_cookie = _sanitize_cookie_value(task_in.bilibili_sessdata)
            if task_cookie:
                task_payload["bilibili_sessdata"] = task_cookie

            await worker.add_task(task_payload)
            await notify_task_update(task_id)

            # 记录第一个任务用于返回
            if first_task_data is None:
                first_task_data = task_data

        return first_task_data

    # 普通任务或 merge 模式
    task_id = str(uuid.uuid4())
    resolved_summary_mode = _normalize_summary_mode(task_in.summary_mode)
    task_data = {
        "id": task_id,
        "video_url": str(task_in.video_url),
        "status": TaskStatus.PENDING,
        "created_at": datetime.utcnow(),
        "latest_modified_at": datetime.utcnow(),
        "progress": 0.0,
        "author_name": None,
        "author_url": None,
        "summary_mode": resolved_summary_mode,
        "summary_chunk_total": None,
        "summary_chunk_done": None,
        "summary_meta": None,
    }
    db.save_task(task_id, task_data)

    worker = await _resolve_worker_or_raise(get_downloader_worker, task_id=task_id)
    task_payload = {
        "task_id": task_id,
        "video_url": str(task_in.video_url),
        "quality": task_in.quality,
        "summary_mode": resolved_summary_mode,
    }
    task_cookie = _sanitize_cookie_value(task_in.bilibili_sessdata)
    if task_cookie:
        task_payload["bilibili_sessdata"] = task_cookie

    # 添加 B 站分P处理配置（merge 模式或单P视频）
    if task_in.bilibili_parts:
        task_payload["bilibili_parts"] = {
            "mode": task_in.bilibili_parts.mode,
            "indices": task_in.bilibili_parts.indices,
        }

    await worker.add_task(task_payload)

    await notify_task_update(task_id)
    return task_data

@app.get("/tasks/", response_model=List[Task])
async def list_tasks():
    """
    获取所有任务列表
    """
    tasks = db.list_tasks()
    # 返回按创建时间倒序排列的任务
    return sorted(tasks, key=lambda x: x["created_at"], reverse=True)

@app.get("/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str):
    """
    获取特定任务的详细信息
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    _trigger_author_resolution_if_needed(task)
    return task

def _sync_summary_file(task_id: str, content: str) -> None:
    """将编辑后的总结内容同步写回本地产物文件（temp/{task_id}_summary.md）。"""
    try:
        os.makedirs("temp", exist_ok=True)
        summary_file = os.path.join("temp", f"{task_id}_summary.md")
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"[API] 总结内容已同步到本地文件: {summary_file}")
    except Exception as e:
        logger.warning(f"[API] 同步总结文件失败: task_id={task_id}, error={e}")


@app.patch("/tasks/{task_id}", response_model=Task)
async def update_task(task_id: str, task_update: TaskUpdate):
    """
    更新任务信息 (支持 topic、summary)
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    updates = task_update.dict(exclude_unset=True)
    if updates:
        # 总结内容被编辑时，同步写回本地 .md 文件，保持本地产物一致
        if updates.get("summary") is not None:
            _sync_summary_file(task_id, updates["summary"])
        from .task_updater import update_and_notify
        updated_task = await update_and_notify(task_id, updates)
        return updated_task

    return task

@app.post("/tasks/{task_id}/open-local")
async def open_task_local(task_id: str, request: Request):
    """
    在服务器本地打开该任务的总结 Markdown 文件（使用系统默认编辑器）。
    仅允许本机 localhost 请求，避免远程触发服务器弹窗。
    """
    if not _is_loopback_client(request):
        raise HTTPException(
            status_code=403,
            detail="仅允许本机 localhost 请求使用本地打开功能。"
        )

    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.get("summary"):
        raise HTTPException(status_code=400, detail="该任务暂无总结内容，无法打开本地文件")

    summary_file = os.path.join("temp", f"{task_id}_summary.md")
    abs_path = os.path.abspath(summary_file)

    # 确保本地产物文件存在且与数据库一致
    _sync_summary_file(task_id, task["summary"])

    try:
        if os.name == "nt":
            # Windows: 用系统默认程序打开（如 Typora、VS Code、记事本等）
            os.startfile(abs_path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", abs_path])
        else:
            subprocess.Popen(["xdg-open", abs_path])
        logger.info(f"[API] 已请求在本地打开总结文件: {abs_path}")
    except Exception as e:
        logger.error(f"[API] 打开本地文件失败: {abs_path}, error={e}")
        raise HTTPException(status_code=500, detail=f"打开本地文件失败: {e}")

    return {"success": True, "file_path": abs_path}

@app.post("/tasks/{task_id}/reload-local", response_model=Task)
async def reload_task_local(task_id: str, request: Request):
    """
    从本地 temp/{task_id}_summary.md 文件重新载入总结内容并更新数据库。
    用户在本地编辑器修改文件后，可通过此接口一键同步回网页。
    仅允许本机 localhost 请求。
    """
    if not _is_loopback_client(request):
        raise HTTPException(
            status_code=403,
            detail="仅允许本机 localhost 请求使用本地文件重新载入功能。"
        )

    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    summary_file = os.path.join("temp", f"{task_id}_summary.md")
    if not os.path.exists(summary_file):
        raise HTTPException(status_code=400, detail="本地总结文件不存在，请先点击「本地打开」生成文件")

    try:
        with open(summary_file, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.error(f"[API] 读取本地总结文件失败: {summary_file}, error={e}")
        raise HTTPException(status_code=500, detail=f"读取本地总结文件失败: {e}")

    if not content.strip():
        raise HTTPException(status_code=400, detail="本地总结文件内容为空")

    # 更新数据库并广播，使网页展示与本地文件保持一致
    from .task_updater import update_and_notify
    updated_task = await update_and_notify(task_id, {"summary": content})
    if not updated_task:
        raise HTTPException(status_code=500, detail="更新任务失败")

    logger.info(f"[API] 已从本地文件重新载入总结: {os.path.abspath(summary_file)}")
    return updated_task

@app.post("/tasks/{task_id}/re-summarize", response_model=Task)
async def re_summarize_task(task_id: str, payload: ReSummarizeRequest | None = None):
    """
    重新生成任务摘要
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if not task.get("transcript"):
        raise HTTPException(status_code=400, detail="No transcript available for re-summarization")
    
    requested_mode = payload.summary_mode if payload else None
    resolved_summary_mode = _normalize_summary_mode(
        requested_mode,
        fallback=str(task.get("summary_mode") or ""),
    )

    from .task_updater import update_and_notify
    worker = await get_llm_worker()
    await update_and_notify(
        task_id,
        {
            "status": TaskStatus.SUMMARIZING,
            "summary": "",
            "progress": 0.0,
            "summary_mode": resolved_summary_mode,
            "summary_chunk_total": None,
            "summary_chunk_done": None,
            "summary_meta": None,
        },
    )

    temp_file = os.path.join("temp", f"{task_id}_re.txt")
    os.makedirs("temp", exist_ok=True)
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(task["transcript"])

    await worker.add_task({
        "task_id": task_id,
        "intermediate_file_path": temp_file,
        "output_file": os.path.join("temp", f"{task_id}_re_summary.md"),
        "summary_mode": resolved_summary_mode,
    })

    return db.get_task(task_id)


@app.post("/tasks/{task_id}/resolve-author", response_model=Task)
async def resolve_task_author(task_id: str):
    """
    手动触发单任务作者信息回填（仅针对 B 站 URL）。
    解析失败仅记录日志，不影响任务状态。
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    video_url = str(task.get("video_url") or "")
    if not video_url or video_url.startswith("file://") or not _is_bilibili_video_url(video_url):
        return task

    if task.get("author_name") and task.get("author_url"):
        return task

    await _try_resolve_and_persist_author(task_id, video_url)
    return db.get_task(task_id)


@app.post("/tasks/resolve-author/backfill")
async def backfill_task_authors(limit: int = 50):
    """
    批量回填历史任务作者信息（默认最多 50 条）：
    - 仅处理 B 站 URL
    - 仅处理 status=COMPLETED
    - 仅处理 author_name/author_url 为空的任务
    解析失败仅记录日志并继续处理下一条。
    """
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit 必须大于 0")

    tasks = db.list_tasks()
    scanned = 0
    updated = 0
    skipped = 0

    for task in tasks:
        if scanned >= limit:
            break
        scanned += 1

        task_id = str(task.get("id") or "")
        video_url = str(task.get("video_url") or "")
        status = str(task.get("status") or "")
        has_author = bool(task.get("author_name")) and bool(task.get("author_url"))

        if (
            not task_id
            or not video_url
            or video_url.startswith("file://")
            or not _is_bilibili_video_url(video_url)
            or status != TaskStatus.COMPLETED
            or has_author
        ):
            skipped += 1
            continue

        if await _try_resolve_and_persist_author(task_id, video_url):
            updated += 1

    return {
        "scanned": scanned,
        "updated": updated,
        "skipped": skipped,
        "limit": limit,
    }


@app.post("/tasks/{task_id}/re-transcribe", response_model=Task)
async def re_transcribe_task(task_id: str, payload: ReTranscribeRequest | None = None):
    """
    重新转录任务（并继续触发总结流程）。
    优先复用本地媒体文件；若无本地文件且原始 URL 可用，则重新下载。
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    requested_mode = payload.summary_mode if payload else None
    resolved_summary_mode = _normalize_summary_mode(
        requested_mode,
        fallback=str(task.get("summary_mode") or ""),
    )

    local_media_file = _resolve_local_media_file(task_id, task)
    video_url = str(task.get("video_url") or "")
    can_redownload = bool(video_url) and not video_url.startswith("file://")
    if not local_media_file and not can_redownload:
        raise HTTPException(
            status_code=400,
            detail="找不到可用的本地媒体文件，且原任务不是可重下载的在线 URL。"
        )

    reset_data = {
        "progress": 0.0,
        "transcript": "",
        "summary": "",
        "error_message": None,
        "topic": None,
        "status": TaskStatus.PENDING,
        "summary_mode": resolved_summary_mode,
        "summary_chunk_total": None,
        "summary_chunk_done": None,
        "summary_meta": None,
    }
    from .task_updater import update_and_notify
    await update_and_notify(task_id, reset_data)

    if local_media_file:
        transcriber_w = await _resolve_worker_or_raise(get_transcriber_worker, task_id=task_id)
        await update_and_notify(task_id, {"status": TaskStatus.TRANSCRIBING})
        await transcriber_w.add_task(
            build_transcriber_payload(
                task_id=task_id,
                media_path=local_media_file,
                output_dir="temp",
                summary_mode=resolved_summary_mode,
            )
        )
        return db.get_task(task_id)

    downloader_w = await _resolve_worker_or_raise(get_downloader_worker, task_id=task_id)
    await update_and_notify(task_id, {"status": TaskStatus.DOWNLOADING})
    await downloader_w.add_task({
        "task_id": task_id,
        "video_url": video_url,
        "quality": "audio_only",
        "summary_mode": resolved_summary_mode,
    })
    return db.get_task(task_id)


@app.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str):
    """
    删除任务
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 先通知各工作单元取消该任务，避免删除后仍继续占用计算资源。
    cancellation_reports: list[str] = []
    workers = [downloader_worker, file_upload_worker, transcriber_worker, llm_worker]
    for worker in workers:
        if worker is None:
            continue
        cancel_fn = getattr(worker, "cancel_task", None)
        if not callable(cancel_fn):
            continue
        try:
            result = cancel_fn(task_id)
            if isinstance(result, dict):
                cancellation_reports.append(
                    f"{worker.name}(removed={result.get('removed_from_queue', 0)},"
                    f" running={bool(result.get('cancelled_running', False))})"
                )
            else:
                cancellation_reports.append(f"{worker.name}(cancelled)")
        except Exception as e:
            logger.warning(f"[delete_task] 通知 {worker.name} 取消任务失败: {e}")

    if cancellation_reports:
        logger.info(f"[delete_task] 任务 {task_id} 取消结果: " + ", ".join(cancellation_reports))

    from .utils.task_temp_files import cleanup_task_temp_files
    cleanup_task_temp_files(task_id)

    db.delete_task(task_id)
    return None


# ── Folder API ──

@app.post("/folders/", response_model=Folder, status_code=201)
async def create_folder(folder_in: FolderCreate):
    folder_id = str(uuid.uuid4())
    folder_data = {
        "id": folder_id,
        "name": folder_in.name,
        "parent_id": folder_in.parent_id,
        "folder_type": "manual",
        "source_video_url": None,
        "sort_order": 0,
        "created_at": datetime.utcnow(),
    }
    result = db.create_folder(folder_data)
    await manager.broadcast(json.dumps({"type": "folder_created", "folder": result}))
    return result


@app.get("/folders/", response_model=List[Folder])
async def list_folders(include_tasks: bool = False):
    folders = db.list_folders()
    if include_tasks:
        for folder in folders:
            folder["task_ids"] = [t["id"] for t in db.list_tasks_in_folder(folder["id"])]
    return folders


@app.get("/folders/{folder_id}", response_model=Folder)
async def get_folder(folder_id: str):
    folder = db.get_folder(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


@app.patch("/folders/{folder_id}", response_model=Folder)
async def update_folder(folder_id: str, folder_update: FolderUpdate):
    folder = db.get_folder(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    updates = folder_update.dict(exclude_unset=True)
    result = db.update_folder(folder_id, updates)
    await manager.broadcast(json.dumps({"type": "folder_updated", "folder": result}))
    return result


@app.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(folder_id: str):
    folder = db.get_folder(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    db.delete_folder(folder_id)
    await manager.broadcast(json.dumps({"type": "folder_deleted", "folder_id": folder_id}))
    return None


@app.patch("/tasks/{task_id}/folder", response_model=Task)
async def assign_task_folder(task_id: str, payload: TaskFolderAssign):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.assign_task_to_folder(task_id, payload.folder_id)
    updated = db.get_task(task_id)
    await notify_task_update(task_id, updated)
    return updated


@app.post("/folders/backfill-multi-p")
async def backfill_multi_p_folders():
    """一键迁移历史多P任务到文件夹：扫描 title 匹配 "XXX - Pn" 的任务并自动建文件夹。"""
    import re
    tasks = db.list_tasks()
    pattern = re.compile(r"(.+?) - P\d+")
    groups: Dict[str, List[Dict[str, Any]]] = {}
    ungrouped = []

    for task in tasks:
        title = str(task.get("title") or "")
        m = pattern.match(title)
        if m:
            prefix = m.group(1)
            if prefix not in groups:
                groups[prefix] = []
            groups[prefix].append(task)
        else:
            ungrouped.append(task)

    created_folders = 0
    assigned_tasks = 0

    for prefix, group_tasks in groups.items():
        if len(group_tasks) < 2:
            continue
        # Check if a folder for this prefix already exists
        existing_folders = db.list_folders()
        existing = next(
            (f for f in existing_folders if f["name"] == prefix and f["folder_type"] == "auto"),
            None,
        )
        if existing:
            folder_id = existing["id"]
        else:
            folder_id = str(uuid.uuid4())
            db.create_folder({
                "id": folder_id,
                "name": prefix,
                "parent_id": None,
                "folder_type": "auto",
                "source_video_url": group_tasks[0].get("video_url"),
                "sort_order": 0,
                "created_at": datetime.utcnow(),
            })
            created_folders += 1

        for task in group_tasks:
            if not task.get("folder_id"):
                db.assign_task_to_folder(task["id"], folder_id)
                assigned_tasks += 1

    return {
        "created_folders": created_folders,
        "assigned_tasks": assigned_tasks,
        "groups_found": len(groups),
        "ungrouped_tasks": len(ungrouped),
    }


@app.post("/tasks/backfill-titles")
async def backfill_task_titles():
    """回填所有 title 为空的任务：使用 yt-dlp 从视频 URL 提取标题。"""
    tasks = db.list_tasks()
    null_title_tasks = [t for t in tasks if not t.get("title")]
    updated = 0
    skipped = 0

    for task in null_title_tasks:
        video_url = task.get("video_url", "")
        if not video_url:
            skipped += 1
            continue
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'extract_flat': True}) as ydl:
                info = ydl.extract_info(video_url, download=False)
            title = info.get("title")
            if title:
                from .task_updater import update_and_notify
                await update_and_notify(task["id"], {"title": str(title)})
                updated += 1
            else:
                skipped += 1
        except Exception as e:
            logger.warning(f"回填标题失败 (task={task['id']}, url={video_url}): {e}")
            skipped += 1

    return {"updated": updated, "skipped": skipped, "total_null_titles": len(null_title_tasks)}


@app.get("/llm/providers", response_model=List[LLMProviderInfo])
async def list_llm_providers():
    """获取可选 LLM 供应商列表。"""
    return llm_provider_manager.list_providers()


@app.get("/llm/settings", response_model=LLMProfilesSettings)
async def get_llm_settings():
    """获取所有 Profile 的 LLM 配置（API Key 仅返回掩码）。"""
    return llm_provider_manager.get_settings()


@app.put("/llm/settings", response_model=LLMProfilesSettings)
async def update_llm_profile(payload: LLMProfileUpdate):
    """更新指定 Profile 的配置并设为活跃。"""
    try:
        settings = llm_provider_manager.update_profile(
            profile_id=payload.profile_id,
            name=payload.name,
            provider=payload.provider,
            base_url=payload.base_url,
            api_key=payload.api_key,
            model_id=payload.model_id,
            temperature=payload.temperature,
            context_window_size=payload.context_window_size,
        )
        # Persist to settings.json
        config_manager.update_profile(payload.profile_id, payload.model_dump(exclude_none=True, exclude={"profile_id"}))
        return settings
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/llm/profiles", response_model=LLMProfilesSettings)
async def create_llm_profile(payload: LLMProfileCreate):
    """创建新的 LLM Profile。"""
    try:
        result = llm_provider_manager.add_profile(
            name=payload.name,
            provider=payload.provider,
            base_url=payload.base_url,
            api_key=payload.api_key,
            model_id=payload.model_id,
            temperature=payload.temperature,
        )
        new_profile_id = result.pop("new_profile_id")
        # Persist to settings.json with the same profile_id
        config_manager.add_profile(
            payload.name, payload.provider,
            payload.model_dump(exclude_none=True, exclude={"name", "provider"}),
            profile_id=new_profile_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/llm/profiles/{profile_id}", response_model=LLMProfilesSettings)
async def delete_llm_profile(profile_id: str):
    """删除 LLM Profile。不能删除最后一个。"""
    try:
        settings = llm_provider_manager.delete_profile(profile_id)
        config_manager.delete_profile(profile_id)
        return settings
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/llm/active-profile", response_model=LLMProfilesSettings)
async def set_active_llm_profile(payload: LLMActiveProfileUpdate):
    """切换活跃 LLM Profile（不修改配置）。"""
    try:
        settings = llm_provider_manager.switch_profile(payload.profile_id)
        config_manager.set_active_profile(payload.profile_id)
        return settings
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/llm/test", response_model=LLMTestResult)
async def test_llm_connection():
    """测试当前 LLM 配置是否可用。"""
    from .llm.llm import LLMMessage, LLMResponseError, LLMConnectionError, get_llm
    import asyncio

    logger.info("开始测试 LLM 连接...")

    try:
        # 使用当前运行时配置创建临时 LLM 客户端，不触发 worker 懒初始化。
        runtime_config = llm_provider_manager.get_runtime_config()
        llm_client = get_llm(runtime_config)

        # 记录当前配置
        llm_client_config = getattr(llm_client, "config", None)
        if llm_client_config:
            logger.info(
                "使用 LLM 配置: "
                f"provider={llm_client_config.provider}, "
                f"base_url={llm_client_config.base_url}, "
                f"model={llm_client_config.model_id}"
            )
        else:
            logger.warning("无法获取 LLM 配置信息")

        # 准备测试消息
        test_message = LLMMessage(role="user", content="Reply with exactly: OK")

        # 收集响应
        response_chunks = []
        error_occurred = None

        def callback(chunk):
            nonlocal error_occurred
            if isinstance(chunk, (LLMResponseError, LLMConnectionError)):
                error_occurred = chunk
            else:
                response_chunks.append(chunk)

        # 发送请求（非流式，超时 10 秒）
        await llm_client.response(
            messages=[test_message],
            resp_callback=callback,
            stream=False,
            timeout=10
        )

        # 检查是否有错误
        if error_occurred:
            logger.error(f"LLM 响应错误: {error_occurred}")
            return LLMTestResult(
                status="error",
                message=f"LLM 响应错误: {str(error_occurred)}",
                response=None
            )

        # 拼接响应
        full_response = "".join(response_chunks).strip()

        # 检查响应是否为 "OK"
        if full_response == "OK":
            logger.info("LLM 测试通过")
            return LLMTestResult(
                status="success",
                message="测试通过，模型响应正确",
                response=full_response
            )
        else:
            logger.warning(f"LLM 测试响应不符合预期: 期望 'OK'，实际 '{full_response}'")
            return LLMTestResult(
                status="warning",
                message=f"模型已响应，但内容不符合预期（期望: 'OK'，实际: '{full_response}'）",
                response=full_response
            )

    except asyncio.TimeoutError:
        logger.error("LLM 测试超时（10秒）")
        return LLMTestResult(
            status="error",
            message="请求超时（10秒），请检查网络连接或 API 地址",
            response=None
        )
    except LLMConnectionError as e:
        logger.error(f"LLM 连接失败: {e}", exc_info=True)
        return LLMTestResult(
            status="error",
            message=f"连接失败: {str(e)}",
            response=None
        )
    except Exception as e:
        logger.exception("LLM 测试失败")
        return LLMTestResult(
            status="error",
            message=f"测试失败: {str(e)}",
            response=None
        )


@app.get("/transcription/settings", response_model=TranscriptionSettings)
async def get_transcription_settings():
    """获取当前转录运行时设置。"""
    return transcription_settings_manager.get_settings()


@app.put("/transcription/settings", response_model=TranscriptionSettings)
async def update_transcription_settings(payload: TranscriptionSettingsUpdate):
    """更新转录运行时设置并应用到转录工作单元。"""
    try:
        settings = transcription_settings_manager.update_settings(
            device=payload.device,
            model_source=payload.model_source,
            model_size=payload.model_size,
            model_path=payload.model_path,
            compute_type_mode=payload.compute_type_mode,
            compute_type=payload.compute_type,
            enable_bilibili_subtitle_fetch=payload.enable_bilibili_subtitle_fetch,
            bilibili_sessdata=payload.bilibili_sessdata,
            clear_bilibili_sessdata=payload.clear_bilibili_sessdata,
        )
        config_manager.save_transcription_config(transcription_settings_manager.get_runtime_state())
        return settings
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/bilibili/video-info", response_model=BilibiliVideoInfo)
async def get_bilibili_video_info(payload: BilibiliVideoInfoRequest):
    """获取 B 站视频信息，包括是否为多P视频及分P列表。"""
    video_url = str(payload.url or "").strip()
    if not video_url:
        raise HTTPException(status_code=400, detail="URL 不能为空")

    if not _is_bilibili_video_url(video_url):
        raise HTTPException(status_code=400, detail="不是有效的 B 站视频链接")

    try:
        from bilibili_api import video, sync
        import re
        from urllib.request import Request, urlopen

        # 解析 BV 号
        candidate = video_url
        if "b23.tv" in video_url:
            try:
                request = Request(video_url, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(request, timeout=15) as response:
                    candidate = response.geturl()
            except Exception:
                pass

        match = re.search(r"/video/(BV[0-9A-Za-z]+)", candidate)
        if not match:
            fallback = re.search(r"(BV[0-9A-Za-z]+)", candidate)
            if fallback:
                bvid = fallback.group(1)
            else:
                raise HTTPException(status_code=400, detail="无法从链接中提取 BV 号")
        else:
            bvid = match.group(1)

        # 获取视频信息
        video_obj = video.Video(bvid=bvid)
        info = sync(video_obj.get_info())

        title = str(info.get("title") or "")
        duration = int(info.get("duration") or 0)

        # 检查是否为多P视频
        pages = info.get("pages")
        if isinstance(pages, list) and len(pages) > 1:
            # 多P视频
            parts = []
            for page in pages:
                if not isinstance(page, dict):
                    continue
                part_index = int(page.get("page", 0))
                cid = int(page.get("cid", 0))
                part_title = str(page.get("part") or f"第{part_index}P")
                part_duration = int(page.get("duration") or 0)
                parts.append(BilibiliVideoPartInfo(
                    index=part_index - 1,  # 转换为 0-based
                    cid=cid,
                    title=part_title,
                    duration=part_duration,
                ))

            return BilibiliVideoInfo(
                is_multi_part=True,
                title=title,
                bvid=bvid,
                duration=duration,
                parts=parts,
            )
        else:
            # 单P视频
            return BilibiliVideoInfo(
                is_multi_part=False,
                title=title,
                bvid=bvid,
                duration=duration,
                parts=None,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 B 站视频信息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取视频信息失败: {str(e)}")


@app.post("/transcription/settings/bilibili-cookie/from-browser", response_model=BilibiliCookieFromBrowserResult)
async def read_bilibili_cookie_from_browser():
    """从浏览器读取 B 站 SESSDATA 并保存到全局配置。"""
    result = transcription_settings_manager.read_cookie_from_browser()
    if result["success"]:
        config_manager.save_transcription_config(transcription_settings_manager.get_runtime_state())
    return result


@app.get("/summarization/settings", response_model=SummarizationSettings)
async def get_summarization_settings():
    """获取当前总结策略配置（含 Agent 分块参数）。"""
    cfg = config.summarization
    return SummarizationSettings(
        mode=str(cfg.mode),
        auto_chunk_min_audio_duration_sec=int(cfg.auto_chunk_min_audio_duration_sec),
        auto_chunk_min_transcript_lines=int(cfg.auto_chunk_min_transcript_lines),
        chunk_target_duration_sec=int(cfg.chunk_target_duration_sec),
        chunk_min_duration_sec=int(cfg.chunk_min_duration_sec),
        chunk_max_duration_sec=int(cfg.chunk_max_duration_sec),
        boundary_jump_sec=int(cfg.boundary_jump_sec),
        prev_tail_timestamp_lines_m=int(cfg.prev_tail_timestamp_lines_m),
        prev_summary_tail_chars_j=int(cfg.prev_summary_tail_chars_j),
        llm_call_retry_max=int(cfg.llm_call_retry_max),
        max_agent_value_chars=int(cfg.max_agent_value_chars),
        fallback_to_standard_on_agent_error=bool(cfg.fallback_to_standard_on_agent_error),
    )


@app.put("/summarization/settings", response_model=SummarizationSettings)
async def update_summarization_settings(payload: SummarizationSettingsUpdate):
    """更新总结策略配置并持久化到 config/settings.json。"""
    try:
        patch = payload.model_dump(exclude_none=True)
    except AttributeError:
        patch = payload.dict(exclude_none=True)

    try:
        config_manager.save_summarization_config(patch)
        return await get_summarization_settings()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # 连接时推送预热状态，避免客户端需要轮询
    if _prewarm_ready:
        await websocket.send_text(json.dumps({
            "type": "prewarm_status",
            "ready": True,
        }))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

