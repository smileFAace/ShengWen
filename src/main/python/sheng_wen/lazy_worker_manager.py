"""
懒初始化 Worker 管理器
在第一次调用时才初始化 workers，避免启动时的长时间等待
"""
import asyncio
from typing import Optional
from .utils.logger import logger
from .config.settings import config


class LazyWorkerManager:
    """懒初始化 Worker 管理器"""

    def __init__(self):
        self._downloader_worker: Optional[object] = None
        self._file_upload_worker: Optional[object] = None
        self._transcriber_worker: Optional[object] = None
        self._llm_worker: Optional[object] = None
        self._worker_manager: Optional[object] = None

        self._init_lock = asyncio.Lock()
        self._initialized = False
        self._initializing = False

    async def _initialize_workers(self):
        """初始化所有 workers（仅执行一次）"""
        async with self._init_lock:
            if self._initialized or self._initializing:
                return

            self._initializing = True
            logger.info("--- [LazyInit] 开始初始化 Workers（首次调用触发）---")

            try:
                # 导入必要的模块
                from .transcriber.transcriber import get_transcriber
                from .llm.llm import get_llm
                from .transcriber.transcriber_worker import TranscriberWorker
                from .llm.llm_worker import LLMWorker
                from .downloader.video_downloader_worker import VideoDownloaderWorker
                from .downloader.file_upload_worker import FileUploadWorker
                from .worker_manager import WorkerManager
                import src.main.python.sheng_wen.api as api_module

                # 配置转录器
                runtime_transcription_state = api_module.transcription_settings_manager.get_runtime_state()
                transcriber_config = api_module.transcription_settings_manager.build_transcriber_kwargs()
                model_source = str(runtime_transcription_state.get("model_source") or "auto_download")
                if model_source == "manual_path":
                    logger.info(f"--- [Transcriber] 使用本地模型路径: {transcriber_config.get('model_size_or_path')} ---")
                else:
                    logger.info(f"--- [Transcriber] 使用模型大小: {transcriber_config.get('model_size')} ---")
                    logger.info("--- [Transcriber] 未指定本地模型路径，若本地缓存不存在将自动下载（首次可能较慢）---")

                # LLM 配置
                llm_config = api_module.llm_provider_manager.get_runtime_config()
                prompt_file = config.app.prompt_file

                logger.info("--- [LazyInit] 1/5 初始化转录器（此阶段可能触发模型下载）... ---")
                transcriber = get_transcriber("fast_whisper", **transcriber_config)
                logger.info("--- [LazyInit] 1/5 转录器初始化完成 ---")

                logger.info("--- [LazyInit] 2/5 初始化 LLM 客户端... ---")
                llm_client = get_llm(llm_config)
                logger.info("--- [LazyInit] 2/5 LLM 客户端初始化完成 ---")

                logger.info("--- [LazyInit] 3/5 创建 Worker 实例... ---")
                self._llm_worker = LLMWorker(name="LLMWorker", llm_client=llm_client)
                self._transcriber_worker = TranscriberWorker(
                    name="TranscriberWorker",
                    transcriber=transcriber,
                    next_worker=self._llm_worker
                )
                self._downloader_worker = VideoDownloaderWorker(
                    name="VideoDownloaderWorker",
                    next_worker=self._transcriber_worker,
                    summary_worker=self._llm_worker,
                    transcription_settings_manager=api_module.transcription_settings_manager,
                )
                self._file_upload_worker = FileUploadWorker(
                    name="FileUploadWorker",
                    next_worker=self._transcriber_worker,
                    summary_worker=self._llm_worker,
                )
                logger.info("--- [LazyInit] 3/5 Worker 实例创建完成 ---")

                logger.info("--- [LazyInit] 4/5 加载系统提示词并注入依赖... ---")
                self._llm_worker.load_system_prompt(prompt_file)

                # 依赖注入
                api_module.downloader_worker = self._downloader_worker
                api_module.file_upload_worker = self._file_upload_worker
                api_module.llm_worker = self._llm_worker
                api_module.transcriber_worker = self._transcriber_worker
                api_module.llm_provider_manager.bind_llm_worker(self._llm_worker)
                api_module.transcription_settings_manager.bind_transcriber_worker(self._transcriber_worker)

                workers = [
                    self._downloader_worker,
                    self._file_upload_worker,
                    self._transcriber_worker,
                    self._llm_worker
                ]
                self._worker_manager = WorkerManager(workers=workers)
                logger.info("--- [LazyInit] 4/5 依赖注入完成 ---")

                logger.info("--- [LazyInit] 5/5 启动后台 Worker 循环... ---")
                self._worker_manager.start_all()
                logger.info("--- [LazyInit] 5/5 后台 Worker 启动完成 ---")
                logger.info("--- [LazyInit] Workers 初始化完成 ---")

                self._initialized = True

            except Exception as e:
                logger.error(f"--- [LazyInit] Workers 初始化失败: {e}", exc_info=True)
                self._initializing = False
                raise
            finally:
                self._initializing = False

    async def get_downloader_worker(self):
        """获取 downloader_worker（懒初始化）"""
        if not self._initialized:
            await self._initialize_workers()
        return self._downloader_worker

    async def get_file_upload_worker(self):
        """获取 file_upload_worker（懒初始化）"""
        if not self._initialized:
            await self._initialize_workers()
        return self._file_upload_worker

    async def get_transcriber_worker(self):
        """获取 transcriber_worker（懒初始化）"""
        if not self._initialized:
            await self._initialize_workers()
        return self._transcriber_worker

    async def get_llm_worker(self):
        """获取 llm_worker（懒初始化）"""
        if not self._initialized:
            await self._initialize_workers()
        return self._llm_worker

    async def get_worker_manager(self):
        """获取 worker_manager（懒初始化）"""
        if not self._initialized:
            await self._initialize_workers()
        return self._worker_manager

    async def stop_all(self):
        """停止所有 workers"""
        if self._worker_manager:
            logger.info("--- [LazyInit] 正在停止工作单元... ---")
            await self._worker_manager.stop_all()
            logger.info("--- [LazyInit] 所有工作单元已停止 ---")

    @property
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._initialized

    def get_initialized_workers(self) -> list[object]:
        """获取已初始化的 worker 列表（未初始化时返回空列表）。"""
        if not self._initialized:
            return []
        return [
            self._downloader_worker,
            self._file_upload_worker,
            self._transcriber_worker,
            self._llm_worker,
        ]
