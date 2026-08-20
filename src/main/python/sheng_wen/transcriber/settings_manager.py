from __future__ import annotations

import os
import re
import shutil
import subprocess
from threading import Lock
from typing import Any, Literal

from ..utils.logger import logger
from .transcriber import get_transcriber


def _read_bilibili_cookie_from_browser() -> tuple[str, str]:
    """
    尝试从浏览器中读取 B 站 SESSDATA。

    Returns:
        tuple[str, str]: (sessdata, browser_name) 或 ("", "") 如果未找到
    """
    browsers_to_try = [
        ("edge", "Microsoft Edge"),
        ("chrome", "Google Chrome"),
        ("firefox", "Firefox"),
        ("chromium", "Chromium"),
        ("opera", "Opera"),
        ("brave", "Brave"),
    ]

    try:
        import browser_cookie3  # type: ignore
    except ImportError:
        logger.warning("[TranscriptionSettingsManager] browser_cookie3 未安装，无法从浏览器读取 Cookie")
        return "", ""

    for browser_key, browser_name in browsers_to_try:
        try:
            browser_func = getattr(browser_cookie3, browser_key, None)
            if browser_func is None:
                continue

            cookies = browser_func(domain_name="bilibili.com")
            for cookie in cookies:
                if cookie.name == "SESSDATA" and cookie.value:
                    sessdata = _sanitize_cookie_value(cookie.value)
                    if sessdata:
                        logger.info(f"[TranscriptionSettingsManager] 成功从 {browser_name} 读取 B 站 Cookie")
                        return sessdata, browser_name
        except PermissionError:
            # 浏览器正在运行时会触发此错误，跳过该浏览器
            logger.debug(f"[TranscriptionSettingsManager] {browser_name} 正在运行，跳过读取")
            continue
        except Exception as e:
            logger.debug(f"[TranscriptionSettingsManager] 从 {browser_name} 读取失败: {e}")
            continue

    return "", ""

_CUDA_DLL_PATTERN = re.compile(
    r"(cublas(?:Lt)?64_(\d+)\.dll|cudart64_(\d+)\.dll|cudnn64(?:_\d+)?\.dll)",
    re.IGNORECASE,
)


def _extract_missing_cuda_runtime_dll(error_text: str) -> tuple[str | None, str | None]:
    match = _CUDA_DLL_PATTERN.search(error_text or "")
    if not match:
        return (None, None)
    dll_name = match.group(1)
    cuda_major = match.group(2) or match.group(3)
    return (dll_name, cuda_major)


def _build_cuda_fix_message(missing_dll: str | None, cuda_major: str | None) -> str:
    lines = [
        "可处理步骤：",
        "1) 临时切换到 CPU 转录（可立即继续使用）。",
        "2) 安装与当前 fast-whisper/ctranslate2 匹配的 NVIDIA CUDA Runtime（Windows 需包含 cublas）。",
    ]
    if missing_dll:
        if cuda_major:
            lines.append(f"   当前缺失：{missing_dll}（对应 CUDA {cuda_major}）。")
        else:
            lines.append(f"   当前缺失：{missing_dll}。")
    lines.extend(
        [
            "3) 确认系统 PATH 含 CUDA bin 目录，例如：",
            r"   C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.x\bin",
            "4) 重启 ShengWen 后重新选择 CUDA。",
        ]
    )
    return "\n".join(lines)


def _detect_nvidia_gpu() -> bool:
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return result.returncode == 0 and "GPU" in (result.stdout or "")
    except Exception:
        return False


def _detect_cuda_support() -> dict[str, Any]:
    has_nvidia_gpu = _detect_nvidia_gpu()

    torch_installed = False
    torch_cuda_built = False
    ctranslate2_installed = False
    ctranslate2_cuda_device_count = 0
    cuda_available = False
    reason = "unknown"
    message = "CUDA 状态未知。"

    try:
        import torch  # type: ignore

        torch_installed = True
        torch_cuda_built = bool(getattr(torch.version, "cuda", None))
        cuda_available = bool(torch.cuda.is_available())

        if cuda_available:
            try:
                import ctranslate2  # type: ignore

                ctranslate2_installed = True
                ctranslate2_cuda_device_count = int(ctranslate2.get_cuda_device_count())
                if ctranslate2_cuda_device_count > 0:
                    reason = "ok"
                    message = f"CUDA 可用（CTranslate2 检测到 {ctranslate2_cuda_device_count} 张 GPU），可使用 GPU 转录。"
                else:
                    cuda_available = False
                    reason = "ct2_no_cuda_device"
                    message = "检测到 PyTorch CUDA 可用，但 CTranslate2 未检测到可用 CUDA 设备。建议更新显卡驱动，或先切回 CPU。"
            except Exception as e:
                cuda_available = False
                error_text = str(e)
                if isinstance(e, ModuleNotFoundError):
                    reason = "ct2_missing"
                    message = (
                        "检测到 CUDA 环境，但缺少 CTranslate2（fast-whisper 依赖）。"
                        "\n可处理步骤：执行 `pip install ctranslate2` 后重启应用。"
                    )
                else:
                    missing_dll, cuda_major = _extract_missing_cuda_runtime_dll(error_text)
                    reason = "ct2_cuda_runtime_unavailable"
                    if missing_dll:
                        message = (
                            "检测到 CUDA 环境，但 fast-whisper CUDA 运行时不可用。"
                            f"\n缺少运行库：{missing_dll}"
                            f"\n{_build_cuda_fix_message(missing_dll, cuda_major)}"
                        )
                    else:
                        message = (
                            "检测到 CUDA 环境，但 fast-whisper CUDA 运行时不可用。"
                            f"\n原始错误：{error_text}"
                            "\n可处理步骤：先切换到 CPU；随后检查 CUDA Runtime 与驱动版本，并重启后重试。"
                        )
        elif not has_nvidia_gpu:
            reason = "no_gpu"
            message = "未检测到 NVIDIA 显卡（或驱动未正确安装）。"
        elif not torch_cuda_built:
            reason = "torch_cpu_only"
            message = "检测到 NVIDIA 显卡，但当前 PyTorch 为 CPU 版本（未启用 CUDA）。"
        else:
            reason = "cuda_runtime_unavailable"
            message = "检测到 NVIDIA 显卡，且 PyTorch 支持 CUDA，但当前 CUDA 运行时不可用（可能是驱动/运行库问题）。"
    except Exception:
        if has_nvidia_gpu:
            reason = "torch_missing"
            message = "检测到 NVIDIA 显卡，但未安装 PyTorch（或环境中不可导入）。"
        else:
            reason = "no_gpu"
            message = "未检测到 NVIDIA 显卡（或驱动未正确安装）。"

    return {
        "cuda_available": cuda_available,
        "has_nvidia_gpu": has_nvidia_gpu,
        "torch_installed": torch_installed,
        "torch_cuda_built": torch_cuda_built,
        "ctranslate2_installed": ctranslate2_installed,
        "ctranslate2_cuda_device_count": ctranslate2_cuda_device_count,
        "cuda_reason": reason,
        "cuda_message": message,
    }


def _sanitize_cookie_value(value: str | None) -> str:
    return (value or "").strip().replace("\r", "").replace("\n", "")


def _read_env_bilibili_sessdata() -> str:
    return _sanitize_cookie_value(os.getenv("BILIBILI_SESSDATA") or os.getenv("SESSDATA"))


def _mask_cookie_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return f"{value[:2]}****"
    return f"{value[:4]}****{value[-4:]}"


VALID_MODEL_SIZES = {"tiny", "base", "small", "medium", "large"}
VALID_MODEL_SOURCES = {"auto_download", "manual_path"}
VALID_COMPUTE_TYPE_MODES = {"auto", "manual"}
VALID_COMPUTE_TYPES = {"int8", "float16", "float32", "bfloat16"}
VALID_COMPUTE_TYPES_BY_DEVICE = {
    "cpu": {"int8", "float32"},
    "cuda": VALID_COMPUTE_TYPES,
}
REQUIRED_MANUAL_MODEL_FILES = (
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
)


def _sanitize_model_path(value: str | None) -> str:
    return str(value or "").strip().strip('"')


def _normalize_model_size(value: str | None, fallback: str = "tiny") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in VALID_MODEL_SIZES:
        return normalized
    return fallback


def _normalize_model_source(value: str | None, fallback: str = "auto_download") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in VALID_MODEL_SOURCES:
        return normalized
    return fallback


def _normalize_compute_type_mode(value: str | None, fallback: str = "auto") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in VALID_COMPUTE_TYPE_MODES:
        return normalized
    return fallback


def _normalize_compute_type(value: str | None, fallback: str = "int8") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in VALID_COMPUTE_TYPES:
        return normalized
    return fallback


def _validate_manual_model_dir(model_path: str) -> tuple[bool, str, str]:
    resolved = _sanitize_model_path(model_path)
    if not resolved:
        return (False, "请填写本地模型目录路径。", "")
    abs_path = os.path.abspath(os.path.expanduser(os.path.expandvars(resolved)))
    if not os.path.exists(abs_path):
        return (False, f"模型目录不存在: {abs_path}", abs_path)
    if not os.path.isdir(abs_path):
        return (False, f"模型路径不是目录: {abs_path}", abs_path)

    missing = [name for name in REQUIRED_MANUAL_MODEL_FILES if not os.path.isfile(os.path.join(abs_path, name))]
    if missing:
        return (
            False,
            "模型目录缺少必要文件: " + ", ".join(missing),
            abs_path,
        )
    return (True, "模型目录校验通过。", abs_path)


class TranscriptionSettingsManager:
    """运行时转录设置管理器。"""

    def __init__(
        self,
        initial_device: str,
        model_size: str,
        model_source: str = "auto_download",
        model_path: str | None = None,
        initial_compute_type_mode: str = "auto",
        initial_compute_type: str = "int8",
        initial_enable_bilibili_subtitle_fetch: bool = True,
        initial_bilibili_sessdata: str = "",
    ):
        self._lock = Lock()
        self._device = initial_device
        self._model_size = _normalize_model_size(model_size, fallback="tiny")
        self._model_source = _normalize_model_source(model_source, fallback="auto_download")
        self._model_path = _sanitize_model_path(model_path)
        self._compute_type_mode = _normalize_compute_type_mode(initial_compute_type_mode, fallback="auto")
        self._compute_type = _normalize_compute_type(initial_compute_type, fallback="int8")
        if self._model_source == "auto_download" and self._model_path:
            # 兼容旧配置：曾填写过 model_path 时默认沿用手动模式。
            self._model_source = "manual_path"
        self._enable_bilibili_subtitle_fetch = initial_enable_bilibili_subtitle_fetch
        self._bilibili_sessdata = _sanitize_cookie_value(initial_bilibili_sessdata)
        self._transcriber_worker: Any = None

    def bind_transcriber_worker(self, worker: Any) -> None:
        with self._lock:
            self._transcriber_worker = worker

    def resolve_bilibili_sessdata(self, task_override_sessdata: str | None = None) -> tuple[str, str]:
        task_override = _sanitize_cookie_value(task_override_sessdata)
        if task_override:
            return task_override, "task"

        with self._lock:
            global_sessdata = self._bilibili_sessdata
        if global_sessdata:
            return global_sessdata, "global"

        env_sessdata = _read_env_bilibili_sessdata()
        if env_sessdata:
            return env_sessdata, "env"

        return "", "none"

    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            current_device = self._device
            enable_bilibili_subtitle_fetch = self._enable_bilibili_subtitle_fetch
            model_source = self._model_source
            model_size = self._model_size
            model_path = self._model_path
            compute_type_mode = self._compute_type_mode
            manual_compute_type = self._compute_type

        sessdata, source = self.resolve_bilibili_sessdata()
        cuda_diag = _detect_cuda_support()
        cuda_available = bool(cuda_diag["cuda_available"])
        devices = ["cpu"]
        if cuda_available:
            devices.append("cuda")
        manual_valid, manual_message, manual_resolved_path = _validate_manual_model_dir(model_path)
        model_path_valid = manual_valid if model_source == "manual_path" else True
        model_path_message = (
            manual_message
            if model_source == "manual_path"
            else "自动下载模式：首次使用会自动下载/加载所选模型。"
        )

        effective_compute_type = self._resolve_compute_type(
            device=current_device,
            compute_type_mode=compute_type_mode,
            compute_type=manual_compute_type,
        )
        available_compute_types = sorted(VALID_COMPUTE_TYPES_BY_DEVICE.get(current_device, {"int8"}))

        return {
            "device": current_device,
            "model_source": model_source,
            "model_size": model_size,
            "model_path": model_path,
            "compute_type_mode": compute_type_mode,
            "compute_type": effective_compute_type,
            "manual_compute_type": manual_compute_type,
            "available_compute_types": available_compute_types,
            "model_path_valid": model_path_valid,
            "model_path_message": model_path_message,
            "model_path_resolved": manual_resolved_path if model_source == "manual_path" else "",
            "required_model_files": list(REQUIRED_MANUAL_MODEL_FILES),
            "cuda_available": cuda_available,
            "available_devices": devices,
            "has_nvidia_gpu": bool(cuda_diag["has_nvidia_gpu"]),
            "torch_installed": bool(cuda_diag["torch_installed"]),
            "torch_cuda_built": bool(cuda_diag["torch_cuda_built"]),
            "ctranslate2_installed": bool(cuda_diag["ctranslate2_installed"]),
            "ctranslate2_cuda_device_count": int(cuda_diag["ctranslate2_cuda_device_count"]),
            "cuda_reason": str(cuda_diag["cuda_reason"]),
            "cuda_message": str(cuda_diag["cuda_message"]),
            "enable_bilibili_subtitle_fetch": enable_bilibili_subtitle_fetch,
            "has_bilibili_sessdata": bool(sessdata),
            "bilibili_cookie_source": source,
            "bilibili_sessdata_masked": _mask_cookie_value(sessdata),
        }

    def _build_transcriber_kwargs(
        self,
        device: str,
        model_source: str,
        model_size: str,
        model_path: str,
        compute_type_mode: str,
        compute_type: str,
    ) -> dict[str, str]:
        resolved_compute_type = self._resolve_compute_type(
            device=device,
            compute_type_mode=compute_type_mode,
            compute_type=compute_type,
        )
        kwargs: dict[str, str] = {"device": device, "compute_type": resolved_compute_type}
        if model_source == "manual_path":
            valid, message, resolved_path = _validate_manual_model_dir(model_path)
            if not valid:
                raise ValueError(message)
            kwargs["model_size_or_path"] = resolved_path
        else:
            kwargs["model_size"] = model_size
        return kwargs

    def build_transcriber_kwargs(self) -> dict[str, str]:
        with self._lock:
            return self._build_transcriber_kwargs(
                device=self._device,
                model_source=self._model_source,
                model_size=self._model_size,
                model_path=self._model_path,
                compute_type_mode=self._compute_type_mode,
                compute_type=self._compute_type,
            )

    @staticmethod
    def _resolve_compute_type(device: str, compute_type_mode: str, compute_type: str) -> str:
        if device == "cuda":
            auto_compute_type = "float32"
        else:
            auto_compute_type = "int8"

        if compute_type_mode == "auto":
            return auto_compute_type

        normalized_manual = _normalize_compute_type(compute_type, fallback=auto_compute_type)
        supported_for_device = VALID_COMPUTE_TYPES_BY_DEVICE.get(device, {auto_compute_type})
        if normalized_manual not in supported_for_device:
            return auto_compute_type
        return normalized_manual

    def update_settings(
        self,
        device: str | None = None,
        model_source: Literal["auto_download", "manual_path"] | str | None = None,
        model_size: Literal["tiny", "base", "small", "medium", "large"] | str | None = None,
        model_path: str | None = None,
        compute_type_mode: Literal["auto", "manual"] | str | None = None,
        compute_type: Literal["int8", "float16", "float32", "bfloat16"] | str | None = None,
        enable_bilibili_subtitle_fetch: bool | None = None,
        bilibili_sessdata: str | None = None,
        clear_bilibili_sessdata: bool | None = None,
    ) -> dict[str, Any]:
        if (
            device is None
            and model_source is None
            and model_size is None
            and model_path is None
            and compute_type_mode is None
            and compute_type is None
            and enable_bilibili_subtitle_fetch is None
            and bilibili_sessdata is None
            and clear_bilibili_sessdata is None
        ):
            raise ValueError("至少需要更新一个配置项")

        with self._lock:
            current_device = self._device
            current_model_source = self._model_source
            current_model_size = self._model_size
            current_model_path = self._model_path
            current_compute_type_mode = self._compute_type_mode
            current_compute_type = self._compute_type
            worker_for_rebuild = self._transcriber_worker

        next_device = current_device
        if device is not None:
            next_device = (device or "").strip().lower()
            if next_device not in {"cpu", "cuda"}:
                raise ValueError("仅支持 cpu 或 cuda")

        next_model_source = current_model_source
        if model_source is not None:
            normalized_source = str(model_source or "").strip().lower()
            if normalized_source not in VALID_MODEL_SOURCES:
                raise ValueError("model_source 仅支持 auto_download 或 manual_path")
            next_model_source = normalized_source

        next_model_size = current_model_size
        if model_size is not None:
            normalized_size = _normalize_model_size(model_size, fallback="")
            if normalized_size not in VALID_MODEL_SIZES:
                raise ValueError("model_size 仅支持 tiny/base/small/medium/large")
            next_model_size = normalized_size

        next_model_path = current_model_path
        if model_path is not None:
            next_model_path = _sanitize_model_path(model_path)

        next_compute_type_mode = current_compute_type_mode
        if compute_type_mode is not None:
            normalized_mode = _normalize_compute_type_mode(compute_type_mode, fallback="")
            if normalized_mode not in VALID_COMPUTE_TYPE_MODES:
                raise ValueError("compute_type_mode 仅支持 auto 或 manual")
            next_compute_type_mode = normalized_mode

        next_compute_type = current_compute_type
        if compute_type is not None:
            normalized_compute_type = _normalize_compute_type(compute_type, fallback="")
            if normalized_compute_type not in VALID_COMPUTE_TYPES:
                raise ValueError("compute_type 仅支持 int8/float16/float32/bfloat16")
            next_compute_type = normalized_compute_type

        if next_device == "cuda":
            cuda_diag = _detect_cuda_support()
            if not bool(cuda_diag["cuda_available"]):
                raise ValueError(str(cuda_diag["cuda_message"]))

        if next_model_source == "manual_path":
            valid, message, _ = _validate_manual_model_dir(next_model_path)
            if not valid:
                raise ValueError(message)

        device_changed = next_device != current_device
        model_source_changed = next_model_source != current_model_source
        model_size_changed = next_model_size != current_model_size
        model_path_changed = next_model_path != current_model_path
        compute_type_mode_changed = next_compute_type_mode != current_compute_type_mode
        compute_type_changed = next_compute_type != current_compute_type
        should_rebuild = bool(worker_for_rebuild) and (
            device_changed
            or model_source_changed
            or model_size_changed
            or model_path_changed
            or compute_type_mode_changed
            or compute_type_changed
        )

        transcriber = None
        if should_rebuild:
            try:
                logger.info(
                    "[TranscriptionSettingsManager] 正在重建转录器实例，若模型未缓存可能会触发下载，请稍候..."
                )
                transcriber_kwargs = self._build_transcriber_kwargs(
                    device=next_device,
                    model_source=next_model_source,
                    model_size=next_model_size,
                    model_path=next_model_path,
                    compute_type_mode=next_compute_type_mode,
                    compute_type=next_compute_type,
                )
                transcriber = get_transcriber("fast_whisper", **transcriber_kwargs)
                logger.info("[TranscriptionSettingsManager] 转录器实例重建完成。")
            except Exception as e:
                raise ValueError(f"切换转录配置失败: {e}") from e

        with self._lock:
            self._device = next_device
            self._model_source = next_model_source
            self._model_size = next_model_size
            self._model_path = next_model_path
            self._compute_type_mode = next_compute_type_mode
            self._compute_type = next_compute_type

            if transcriber is not None and self._transcriber_worker is not None:
                self._transcriber_worker.update_transcriber(transcriber)
                logger.info(
                    "[TranscriptionSettingsManager] 已更新转录配置: "
                    f"device={self._device}, model_source={self._model_source}, "
                    f"model_size={self._model_size}, compute_type_mode={self._compute_type_mode}, "
                    f"compute_type={self._compute_type}"
                )
            elif (
                (
                    device_changed
                    or model_source_changed
                    or model_size_changed
                    or model_path_changed
                    or compute_type_mode_changed
                    or compute_type_changed
                )
                and self._transcriber_worker is None
            ):
                logger.info(
                    "[TranscriptionSettingsManager] 已保存转录配置（worker 尚未初始化，将在首次任务时生效）: "
                    f"device={self._device}, model_source={self._model_source}, "
                    f"model_size={self._model_size}, compute_type_mode={self._compute_type_mode}, "
                    f"compute_type={self._compute_type}"
                )

            if enable_bilibili_subtitle_fetch is not None:
                self._enable_bilibili_subtitle_fetch = bool(enable_bilibili_subtitle_fetch)
                logger.info(
                    "[TranscriptionSettingsManager] 已更新字幕直取开关: "
                    f"enable_bilibili_subtitle_fetch={self._enable_bilibili_subtitle_fetch}"
                )

            if clear_bilibili_sessdata:
                self._bilibili_sessdata = ""
                logger.info("[TranscriptionSettingsManager] 已清空全局 B 站 SESSDATA。")
            elif bilibili_sessdata is not None:
                self._bilibili_sessdata = _sanitize_cookie_value(bilibili_sessdata)
                logger.info(
                    "[TranscriptionSettingsManager] 已更新全局 B 站 SESSDATA。"
                    f" has_value={bool(self._bilibili_sessdata)}"
                )

        return self.get_settings()

    def read_cookie_from_browser(self) -> dict[str, Any]:
        """
        从浏览器读取 B 站 SESSDATA 并保存到全局配置。

        Returns:
            dict: 包含 success, sessdata (脱敏), sessdata_masked, source_browser, error 等字段
        """
        sessdata, browser_name = _read_bilibili_cookie_from_browser()

        if not sessdata:
            return {
                "success": False,
                "error": "未在任何浏览器中找到 B 站登录态。请确保已在浏览器中登录 bilibili.com，或关闭浏览器后重试。",
            }

        with self._lock:
            self._bilibili_sessdata = sessdata
            logger.info(
                f"[TranscriptionSettingsManager] 已从 {browser_name} 读取并保存 B 站 SESSDATA"
            )

        return {
            "success": True,
            "sessdata": sessdata,
            "sessdata_masked": _mask_cookie_value(sessdata),
            "source_browser": browser_name,
        }

    def get_runtime_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "device": self._device,
                "model_source": self._model_source,
                "model_size": self._model_size,
                "model_path": self._model_path,
                "compute_type_mode": self._compute_type_mode,
                "compute_type": self._compute_type,
                "enable_bilibili_subtitle_fetch": self._enable_bilibili_subtitle_fetch,
                "bilibili_sessdata": self._bilibili_sessdata,
            }

