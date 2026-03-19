import litellm

from .llm import LLM, LLMConfig, LLMMessage, LLMResponseError, LLMConnectionError
from typing import List, Callable, Union
import asyncio

# 映射 litellm 异常到我们自己的标准异常
EXCEPTION_MAPPING = {
    litellm.exceptions.AuthenticationError: LLMConnectionError,
    litellm.exceptions.PermissionDeniedError: LLMConnectionError,
    litellm.exceptions.InvalidRequestError: LLMResponseError,
    litellm.exceptions.RateLimitError: LLMConnectionError,
    litellm.exceptions.ServiceUnavailableError: LLMConnectionError,
    litellm.exceptions.APIConnectionError: LLMConnectionError,
    TimeoutError: LLMConnectionError,
}

class LiteLLMClient(LLM):
    """
    一个使用 litellm 库与多种 LLM 服务交互的客户端实现。
    """
    def __init__(self, config: LLMConfig, **kwargs):
        super().__init__(config, **kwargs)
        self.update_runtime_config(config)

    def update_runtime_config(self, config: LLMConfig):
        """在运行时更新客户端配置。"""
        self.config = config

    def _custom_llm_provider(self) -> str | None:
        """
        根据业务 provider 生成 LiteLLM 的 custom_llm_provider。
        注意：这里只决定路由，不改写 model_id。
        """
        provider = (self.config.provider or "").strip().lower()
        route_map = {
            "openai_compatible": "openai",
            "openai": "openai",
            "deepseek": "openai",
            "ollama": "openai",
            "openrouter": "openrouter",
        }
        return route_map.get(provider)

    def _model_candidates(self) -> List[str]:
        """
        生成模型名候选：
        - 主路径优先使用“原始 model_id”；
        - 仅在需要时追加 provider 前缀变体做兜底。
        """
        model_id = (self.config.model_id or "").strip()
        if not model_id:
            return [model_id]

        candidates: List[str] = []
        lowered = model_id.lower()
        routed_provider = self._custom_llm_provider()

        # 主路径：原始 model_id
        candidates.append(model_id)

        # 兜底：仅在 OpenAI 路由 + 含斜杠模型名时追加 openai/<model_id> 变体，
        # 修复 LiteLLM 将斜杠模型误判为 provider/model 的问题。
        if routed_provider == "openai" and "/" in model_id and not lowered.startswith("openai/"):
            candidates.append(f"openai/{model_id}")
        # 未知路由时保留历史兼容兜底，避免老配置行为突变。
        if routed_provider is None and not lowered.startswith("openai/"):
            candidates.append(f"openai/{model_id}")

        # 去重并保持顺序
        deduped: List[str] = []
        seen = set()
        for item in candidates:
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped or [model_id]

    @staticmethod
    def _is_invalid_argument_error(err: Exception) -> bool:
        text = str(err).lower()
        return ("invalid argument" in text) or ("invalid_argument" in text)

    @staticmethod
    def _is_provider_routing_error(err: Exception) -> bool:
        text = str(err).lower()
        return (
            "llm provider not provided" in text
            or "pass in the llm provider" in text
            or "pass model as" in text
        )

    def _request_base_url(self) -> str:
        return (self.config.base_url or "").strip().rstrip("/")

    async def response(
        self,
        messages: List[LLMMessage],
        resp_callback: Callable[[Union[str, LLMResponseError]], None],
        stream: bool = True,
        timeout: int = 60
    ):
        """
        使用 litellm 异步地发送请求给 LLM 并获取响应。
        """
        # 将我们的 LLMMessage 转换为 litellm 需要的字典格式
        message_dicts = [{"role": msg.role, "content": msg.content} for msg in messages]

        # 处理不支持 system role 的模型（如 Gemini）
        # 将 system 消息合并到第一条 user 消息中
        if message_dicts and message_dicts[0].get("role") == "system":
            system_content = message_dicts[0].get("content", "")
            # 查找第一条 user 消息
            user_idx = next((i for i, m in enumerate(message_dicts) if m.get("role") == "user"), None)
            if user_idx is not None:
                # 将 system 内容作为前缀添加到 user 消息中
                user_content = message_dicts[user_idx].get("content", "")
                message_dicts[user_idx]["content"] = f"{system_content}\n\n{user_content}"
                # 移除 system 消息
                message_dicts.pop(0)
        model_candidates = self._model_candidates()
        last_exception: Exception | None = None

        # 兼容不同 OpenAI 兼容网关：
        # 1) 首选流式 + temperature
        # 2) invalid argument 时尝试非流式
        # 3) 仍失败则去掉 temperature 再试
        # 4) 最后再尝试 model 前缀变体
        attempt_options = []
        attempt_options.append((stream, True))
        if stream:
            attempt_options.append((False, True))
        attempt_options.append((False, False))

        for model_idx, model_name in enumerate(model_candidates):
            for opt_idx, (stream_opt, with_temperature) in enumerate(attempt_options):
                # Ollama 等本地服务不需要 API Key，但 LiteLLM 要求 api_key 参数非空，
                # 否则会抛出 AuthenticationError。对本地服务自动填充占位值。
                effective_api_key = self.config.api_key
                if not effective_api_key or not effective_api_key.strip():
                    provider = (self.config.provider or "").strip().lower()
                    if provider in ("ollama",):
                        effective_api_key = "ollama"  # 占位值，Ollama 不校验

                kwargs = {
                    "model": model_name,
                    "messages": message_dicts,
                    "stream": stream_opt,
                    "timeout": timeout,
                    "api_key": effective_api_key,
                    "base_url": self._request_base_url(),
                    "drop_params": True,
                }
                routed_provider = self._custom_llm_provider()
                if routed_provider:
                    kwargs["custom_llm_provider"] = routed_provider
                if with_temperature:
                    kwargs["temperature"] = self.config.temperature

                can_retry_more = not (
                    model_idx == len(model_candidates) - 1 and opt_idx == len(attempt_options) - 1
                )

                try:
                    response_generator = await litellm.acompletion(**kwargs)

                    if stream_opt:
                        async for chunk in response_generator:
                            # 提取流式响应中的文本内容
                            content = chunk.choices[0].delta.content
                            if content:
                                resp_callback(content)
                    else:
                        # 非流式响应
                        content = response_generator.choices[0].message.content
                        if content:
                            resp_callback(content)
                    return
                except asyncio.CancelledError:
                    # 任务被上层主动取消（例如任务删除），直接向上传播以便立即释放 Worker。
                    raise
                except Exception as e:
                    last_exception = e
                    if can_retry_more and (
                        self._is_invalid_argument_error(e)
                        or self._is_provider_routing_error(e)
                    ):
                        continue
                    break

        if last_exception is None:
            last_exception = RuntimeError("LiteLLM 未返回响应，且无异常细节。")

        # 捕获 litellm 的特定异常并包装成我们的标准异常
        error_class = LLMResponseError # 默认为通用响应错误
        for litellm_exc, our_exc in EXCEPTION_MAPPING.items():
            if isinstance(last_exception, litellm_exc):
                error_class = our_exc
                break

        diagnostic = (
            f"provider={self.config.provider}, model={self.config.model_id}, "
            f"base_url={self._request_base_url()}"
        )
        error = error_class(
            f"LiteLLM 请求失败: {last_exception.__class__.__name__}: {last_exception} [{diagnostic}]"
        )
        resp_callback(error)
