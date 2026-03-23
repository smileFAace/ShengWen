"""
ShengWen JSON 配置模块

统一使用项目根目录下的 `config/settings.json` 作为唯一配置来源。
"""

from __future__ import annotations

import copy
import json
from dataclasses import MISSING, dataclass, fields as dataclass_fields
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from ..utils.logger import logger
from ..utils.project_root import get_project_root


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_project_path(path_str: str) -> str:
    path = Path(path_str)
    if path.is_absolute():
        return str(path)
    return str(get_project_root() / path)


@dataclass
class AppConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    enable_progress_test: bool = False
    enable_mdns: bool = False
    frontend_dist_dir: str = "frontend/dist"
    prompt_file: str = "src/main/python/sheng_wen/prompt.md"

    def __post_init__(self):
        self.frontend_dist_dir = _resolve_project_path(self.frontend_dist_dir)
        self.prompt_file = _resolve_project_path(self.prompt_file)


@dataclass
class WhisperConfig:
    model_source: Literal["auto_download", "manual_path"] = "auto_download"
    model_path: str | None = None
    model_size: Literal["tiny", "base", "small", "medium", "large"] = "tiny"
    device: Literal["cpu", "cuda"] = "cpu"
    enable_bilibili_subtitle_fetch: bool = True
    enable_youtube_subtitle_fetch: bool = True
    bilibili_sessdata: str = ""
    faster_whisper_model_path: str | None = None
    convert_traditional_to_simplified: bool = True

    @property
    def configured_model_path(self) -> str | None:
        direct = str(self.model_path or "").strip()
        if direct:
            return direct
        legacy = str(self.faster_whisper_model_path or "").strip()
        if legacy:
            return legacy
        return None

    @property
    def effective_model_path(self) -> str | None:
        configured = self.configured_model_path
        if configured and Path(configured).exists():
            return configured
        return None


@dataclass
class LLMConfig:
    provider: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model_id: str = ""
    temperature: float = 0.7
    context_window_size: int = 1000000


@dataclass
class DatabaseConfig:
    sqlite_path: str = "ShengWen.db"
    json_file_path: str = "tasks.json"


@dataclass
class CORSConfig:
    allow_origins: str = "*"
    allow_credentials: bool = True
    allow_methods: str = "*"
    allow_headers: str = "*"

    @property
    def origins_list(self) -> list[str]:
        if self.allow_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.allow_origins.split(",")]

    @property
    def methods_list(self) -> list[str]:
        if self.allow_methods == "*":
            return ["*"]
        return [method.strip() for method in self.allow_methods.split(",")]

    @property
    def headers_list(self) -> list[str]:
        if self.allow_headers == "*":
            return ["*"]
        return [header.strip() for header in self.allow_headers.split(",")]


@dataclass
class OutputConfig:
    transcript_dir: str = "temp"
    summary_dir: str = "temp"

    def __post_init__(self):
        self.transcript_dir = _resolve_project_path(self.transcript_dir)
        self.summary_dir = _resolve_project_path(self.summary_dir)


@dataclass
class SummarizationConfig:
    mode: Literal["auto", "standard", "agent"] = "auto"
    auto_chunk_min_audio_duration_sec: int = 2400
    auto_chunk_min_transcript_lines: int = 1800
    chunk_target_duration_sec: int = 2400
    chunk_min_duration_sec: int = 1800
    chunk_max_duration_sec: int = 3000
    boundary_jump_sec: int = 10
    prev_tail_timestamp_lines_m: int = 10
    prev_summary_tail_chars_j: int = 500
    llm_call_retry_max: int = 3
    fallback_to_standard_on_agent_error: bool = True
    chunk_prompt_file: str = "src/main/python/sheng_wen/prompt_for_chunk.md"
    max_agent_value_chars: int = 500
    chunk_debug_dump_enabled: bool = False
    chunk_debug_dump_dir: str = "temp/chunk_debug"
    enable_agent_pipeline: bool = False
    transcript_chunk_emit_duration_sec: int = 600
    enable_summarization: bool = False

    def __post_init__(self):
        normalized_mode = (self.mode or "auto").lower()
        if normalized_mode not in {"auto", "standard", "agent"}:
            normalized_mode = "auto"
        self.mode = normalized_mode  # type: ignore[assignment]

        self.auto_chunk_min_audio_duration_sec = max(300, int(self.auto_chunk_min_audio_duration_sec))
        self.auto_chunk_min_transcript_lines = max(100, int(self.auto_chunk_min_transcript_lines))
        self.chunk_target_duration_sec = max(60, int(self.chunk_target_duration_sec))
        self.chunk_min_duration_sec = max(30, int(self.chunk_min_duration_sec))
        self.chunk_max_duration_sec = max(self.chunk_target_duration_sec, int(self.chunk_max_duration_sec))
        self.boundary_jump_sec = max(1, int(self.boundary_jump_sec))
        self.prev_tail_timestamp_lines_m = max(0, int(self.prev_tail_timestamp_lines_m))
        self.prev_summary_tail_chars_j = max(0, int(self.prev_summary_tail_chars_j))
        self.llm_call_retry_max = max(1, int(self.llm_call_retry_max))
        self.max_agent_value_chars = max(100, int(self.max_agent_value_chars))
        self.transcript_chunk_emit_duration_sec = max(30, int(self.transcript_chunk_emit_duration_sec))
        self.chunk_prompt_file = _resolve_project_path(self.chunk_prompt_file)
        self.chunk_debug_dump_dir = _resolve_project_path(self.chunk_debug_dump_dir)


def _dataclass_defaults(cls: type[Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for field in dataclass_fields(cls):
        if field.default is not MISSING:
            defaults[field.name] = copy.deepcopy(field.default)
            continue
        if field.default_factory is not MISSING:
            defaults[field.name] = field.default_factory()
            continue
        raise ValueError(f"{cls.__name__}.{field.name} 缺少默认值，无法生成默认配置")
    return defaults


def _build_default_settings() -> dict[str, Any]:
    return {
        "app": _dataclass_defaults(AppConfig),
        "whisper": _dataclass_defaults(WhisperConfig),
        "llm": _dataclass_defaults(LLMConfig),
        "database": _dataclass_defaults(DatabaseConfig),
        "cors": _dataclass_defaults(CORSConfig),
        "summarization": _dataclass_defaults(SummarizationConfig),
        "output": _dataclass_defaults(OutputConfig),
    }


DEFAULT_SETTINGS: dict[str, Any] = _build_default_settings()


class JSONConfigManager:
    """JSON 配置管理器，负责加载、校验、持久化。"""

    def __init__(self, config_path: str | None = None):
        self._lock = Lock()
        project_root = get_project_root()
        default_path = project_root / "config" / "settings.json"
        self._config_path = Path(config_path) if config_path else default_path
        self._config: dict[str, Any] = {}
        self._ensure_initialized()

    @property
    def config_path(self) -> Path:
        return self._config_path

    def _sync_example_file_locked(self):
        example_path = self._config_path.with_name("settings.example.json")
        expected = copy.deepcopy(DEFAULT_SETTINGS)
        try:
            if example_path.exists():
                with example_path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict) and loaded == expected:
                    return
        except Exception as e:
            logger.warning(f"[JSONConfigManager] 读取 example 配置失败，将重写: {e}")

        temp_path = example_path.with_suffix(example_path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(expected, f, ensure_ascii=False, indent=2)
        temp_path.replace(example_path)

    def _ensure_initialized(self):
        with self._lock:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._sync_example_file_locked()
            if not self._config_path.exists():
                self._config = copy.deepcopy(DEFAULT_SETTINGS)
                self._write_locked()
                return
            self._reload_locked()

    def _reload_locked(self):
        try:
            with self._config_path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("配置文件根节点必须是 JSON 对象")
            self._config = _deep_merge(DEFAULT_SETTINGS, loaded)
        except Exception as e:
            logger.warning(f"[JSONConfigManager] 读取配置失败，回退默认值: {e}")
            self._config = copy.deepcopy(DEFAULT_SETTINGS)
            self._write_locked()

    def _write_locked(self):
        temp_path = self._config_path.with_suffix(self._config_path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(self._config, f, ensure_ascii=False, indent=2)
        temp_path.replace(self._config_path)

    def get_raw_config(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._config)

    def update_section(self, section: str, payload: dict[str, Any]):
        if not isinstance(payload, dict):
            raise ValueError("配置更新 payload 必须是 JSON 对象")
        with self._lock:
            current = self._config.get(section, {})
            if not isinstance(current, dict):
                current = {}
            self._config[section] = _deep_merge(current, payload)
            self._write_locked()

    def save_llm_config(self, payload: dict[str, Any]):
        defaults = DEFAULT_SETTINGS["llm"]
        llm_patch = {
            "provider": str(payload.get("provider") or defaults["provider"]),
            "base_url": str(payload.get("base_url") or defaults["base_url"]),
            "api_key": str(payload.get("api_key") or defaults["api_key"]),
            "model_id": str(payload.get("model_id") or defaults["model_id"]),
            "temperature": float(payload.get("temperature", defaults["temperature"])),
            "context_window_size": int(payload.get("context_window_size", defaults["context_window_size"])),
        }
        self.update_section("llm", llm_patch)

    def save_transcription_config(self, payload: dict[str, Any]):
        whisper_patch = {}
        resolved_model_source = None
        if "device" in payload:
            whisper_patch["device"] = str(payload["device"] or "cpu").lower()
        if "model_source" in payload:
            source = str(payload.get("model_source") or "auto_download").strip().lower()
            resolved_model_source = source if source in {"auto_download", "manual_path"} else "auto_download"
            whisper_patch["model_source"] = resolved_model_source
        if "model_size" in payload:
            size = str(payload.get("model_size") or "tiny").strip().lower()
            whisper_patch["model_size"] = size if size in {"tiny", "base", "small", "medium", "large"} else "tiny"
        if "model_path" in payload:
            whisper_patch["model_path"] = str(payload.get("model_path") or "").strip() or None
        if resolved_model_source == "auto_download":
            # 用户显式切回自动下载时，清空手动路径，避免重启后被兼容逻辑回推到 manual_path。
            whisper_patch["model_path"] = None
            whisper_patch["faster_whisper_model_path"] = None
        if "enable_bilibili_subtitle_fetch" in payload:
            whisper_patch["enable_bilibili_subtitle_fetch"] = bool(payload["enable_bilibili_subtitle_fetch"])
        if "bilibili_sessdata" in payload:
            whisper_patch["bilibili_sessdata"] = str(payload.get("bilibili_sessdata") or "")
        if "convert_traditional_to_simplified" in payload:
            whisper_patch["convert_traditional_to_simplified"] = bool(payload["convert_traditional_to_simplified"])
        if whisper_patch:
            self.update_section("whisper", whisper_patch)

    def save_summarization_config(self, payload: dict[str, Any]):
        if not isinstance(payload, dict):
            raise ValueError("summarization payload 必须是 JSON 对象")
        patch: dict[str, Any] = {}
        if "mode" in payload:
            patch["mode"] = str(payload.get("mode") or "auto").lower()

        int_fields = [
            "auto_chunk_min_audio_duration_sec",
            "auto_chunk_min_transcript_lines",
            "chunk_target_duration_sec",
            "chunk_min_duration_sec",
            "chunk_max_duration_sec",
            "boundary_jump_sec",
            "prev_tail_timestamp_lines_m",
            "prev_summary_tail_chars_j",
            "llm_call_retry_max",
            "max_agent_value_chars",
            "transcript_chunk_emit_duration_sec",
        ]
        for field in int_fields:
            if field in payload and payload.get(field) is not None:
                patch[field] = int(payload[field])

        bool_fields = [
            "fallback_to_standard_on_agent_error",
            "chunk_debug_dump_enabled",
            "enable_agent_pipeline",
            "enable_summarization",
        ]
        for field in bool_fields:
            if field in payload and payload.get(field) is not None:
                patch[field] = bool(payload[field])

        str_fields = ["chunk_prompt_file", "chunk_debug_dump_dir"]
        for field in str_fields:
            if field in payload and payload.get(field) is not None:
                patch[field] = str(payload[field])

        # output 配置项
        output_fields = ["transcript_dir", "summary_dir"]
        output_patch = {}
        for field in output_fields:
            if field in payload and payload.get(field) is not None:
                output_patch[field] = str(payload[field])
        if output_patch:
            self.update_section("output", output_patch)

        if patch:
            self.update_section("summarization", patch)

    def get_app_config(self) -> AppConfig:
        raw = self.get_raw_config().get("app", {})
        defaults = DEFAULT_SETTINGS["app"]
        return AppConfig(
            host=str(raw.get("host", defaults["host"])),
            port=int(raw.get("port", defaults["port"])),
            enable_progress_test=bool(raw.get("enable_progress_test", defaults["enable_progress_test"])),
            enable_mdns=bool(raw.get("enable_mdns", defaults["enable_mdns"])),
            frontend_dist_dir=str(raw.get("frontend_dist_dir", defaults["frontend_dist_dir"])),
            prompt_file=str(raw.get("prompt_file", defaults["prompt_file"])),
        )

    def get_whisper_config(self) -> WhisperConfig:
        raw = self.get_raw_config().get("whisper", {})
        defaults = DEFAULT_SETTINGS["whisper"]
        model_source = str(raw.get("model_source", defaults.get("model_source", "auto_download"))).lower()
        if model_source not in {"auto_download", "manual_path"}:
            model_source = "auto_download"
        model_size = str(raw.get("model_size", defaults["model_size"])).lower()
        if model_size not in {"tiny", "base", "small", "medium", "large"}:
            model_size = str(defaults["model_size"])
        device = str(raw.get("device", defaults["device"])).lower()
        if device not in {"cpu", "cuda"}:
            device = str(defaults["device"])
        model_path = raw.get("model_path", defaults["model_path"])
        faster_whisper_model_path = raw.get("faster_whisper_model_path", defaults["faster_whisper_model_path"])
        if model_source == "auto_download":
            fallback_manual_path = str(model_path or "").strip() or str(faster_whisper_model_path or "").strip()
            if fallback_manual_path:
                model_source = "manual_path"
        return WhisperConfig(
            model_source=model_source,  # type: ignore[arg-type]
            model_path=model_path,
            model_size=model_size,  # type: ignore[arg-type]
            device=device,  # type: ignore[arg-type]
            enable_bilibili_subtitle_fetch=bool(
                raw.get("enable_bilibili_subtitle_fetch", defaults["enable_bilibili_subtitle_fetch"])
            ),
            bilibili_sessdata=str(raw.get("bilibili_sessdata", defaults["bilibili_sessdata"]) or ""),
            faster_whisper_model_path=faster_whisper_model_path,
        )

    def get_llm_config(self) -> LLMConfig:
        raw = self.get_raw_config().get("llm", {})
        defaults = DEFAULT_SETTINGS["llm"]
        return LLMConfig(
            provider=str(raw.get("provider", defaults["provider"])),
            base_url=str(raw.get("base_url", defaults["base_url"])),
            api_key=str(raw.get("api_key", defaults["api_key"])),
            model_id=str(raw.get("model_id", defaults["model_id"])),
            temperature=float(raw.get("temperature", defaults["temperature"])),
            context_window_size=int(raw.get("context_window_size", defaults["context_window_size"])),
        )

    def get_database_config(self) -> DatabaseConfig:
        raw = self.get_raw_config().get("database", {})
        defaults = DEFAULT_SETTINGS["database"]
        return DatabaseConfig(
            sqlite_path=str(raw.get("sqlite_path", defaults["sqlite_path"])),
            json_file_path=str(raw.get("json_file_path", defaults["json_file_path"])),
        )

    def get_cors_config(self) -> CORSConfig:
        raw = self.get_raw_config().get("cors", {})
        defaults = DEFAULT_SETTINGS["cors"]
        return CORSConfig(
            allow_origins=str(raw.get("allow_origins", defaults["allow_origins"])),
            allow_credentials=bool(raw.get("allow_credentials", defaults["allow_credentials"])),
            allow_methods=str(raw.get("allow_methods", defaults["allow_methods"])),
            allow_headers=str(raw.get("allow_headers", defaults["allow_headers"])),
        )

    def get_summarization_config(self) -> SummarizationConfig:
        raw = self.get_raw_config().get("summarization", {})
        defaults = DEFAULT_SETTINGS["summarization"]
        return SummarizationConfig(
            mode=str(raw.get("mode", defaults["mode"])),
            auto_chunk_min_audio_duration_sec=int(
                raw.get("auto_chunk_min_audio_duration_sec", defaults["auto_chunk_min_audio_duration_sec"])
            ),
            auto_chunk_min_transcript_lines=int(
                raw.get("auto_chunk_min_transcript_lines", defaults["auto_chunk_min_transcript_lines"])
            ),
            chunk_target_duration_sec=int(raw.get("chunk_target_duration_sec", defaults["chunk_target_duration_sec"])),
            chunk_min_duration_sec=int(raw.get("chunk_min_duration_sec", defaults["chunk_min_duration_sec"])),
            chunk_max_duration_sec=int(raw.get("chunk_max_duration_sec", defaults["chunk_max_duration_sec"])),
            boundary_jump_sec=int(raw.get("boundary_jump_sec", defaults["boundary_jump_sec"])),
            prev_tail_timestamp_lines_m=int(
                raw.get("prev_tail_timestamp_lines_m", defaults["prev_tail_timestamp_lines_m"])
            ),
            prev_summary_tail_chars_j=int(raw.get("prev_summary_tail_chars_j", defaults["prev_summary_tail_chars_j"])),
            llm_call_retry_max=int(raw.get("llm_call_retry_max", defaults["llm_call_retry_max"])),
            fallback_to_standard_on_agent_error=bool(
                raw.get("fallback_to_standard_on_agent_error", defaults["fallback_to_standard_on_agent_error"])
            ),
            chunk_prompt_file=str(raw.get("chunk_prompt_file", defaults["chunk_prompt_file"])),
            max_agent_value_chars=int(raw.get("max_agent_value_chars", defaults["max_agent_value_chars"])),
            chunk_debug_dump_enabled=bool(raw.get("chunk_debug_dump_enabled", defaults["chunk_debug_dump_enabled"])),
            chunk_debug_dump_dir=str(raw.get("chunk_debug_dump_dir", defaults["chunk_debug_dump_dir"])),
            enable_agent_pipeline=bool(raw.get("enable_agent_pipeline", defaults["enable_agent_pipeline"])),
            transcript_chunk_emit_duration_sec=int(
                raw.get("transcript_chunk_emit_duration_sec", defaults["transcript_chunk_emit_duration_sec"])
            ),
        )


class Settings:
    """统一配置入口（上层仅依赖该对象）。"""

    def __init__(self, manager: JSONConfigManager):
        self._manager = manager

    @property
    def app(self) -> AppConfig:
        return self._manager.get_app_config()

    @property
    def whisper(self) -> WhisperConfig:
        return self._manager.get_whisper_config()

    @property
    def llm(self) -> LLMConfig:
        return self._manager.get_llm_config()

    @property
    def database(self) -> DatabaseConfig:
        return self._manager.get_database_config()

    @property
    def cors(self) -> CORSConfig:
        return self._manager.get_cors_config()

    @property
    def summarization(self) -> SummarizationConfig:
        return self._manager.get_summarization_config()

    @property
    def output(self) -> OutputConfig:
        raw = self._manager.get_raw_config().get("output", {})
        defaults = DEFAULT_SETTINGS["output"]
        return OutputConfig(
            transcript_dir=str(raw.get("transcript_dir", defaults["transcript_dir"])),
            summary_dir=str(raw.get("summary_dir", defaults["summary_dir"])),
        )


_config_manager: JSONConfigManager | None = None
_config: Settings | None = None


def get_config_manager() -> JSONConfigManager:
    global _config_manager
    if _config_manager is None:
        _config_manager = JSONConfigManager()
    return _config_manager


def get_config() -> Settings:
    global _config
    if _config is None:
        _config = Settings(get_config_manager())
    return _config


config = get_config()


def to_llm_config(settings: Settings) -> "LLMConfigDataclass":
    from src.main.python.sheng_wen.llm.llm import LLMConfig as LLMConfigDataclass

    llm_cfg = settings.llm
    return LLMConfigDataclass(
        base_url=llm_cfg.base_url,
        api_key=llm_cfg.api_key,
        model_id=llm_cfg.model_id,
        temperature=llm_cfg.temperature,
        context_window_size=llm_cfg.context_window_size,
        provider=llm_cfg.provider,
    )


