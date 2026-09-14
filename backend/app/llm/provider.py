"""统一的多模型调用入口。

用 LiteLLM 把 claude/openai/deepseek/qwen 收敛到一个 chat() 函数。
调用时显式指定 provider，模型名/key/base_url 来自调用方传入的快照或 .env 兼容配置。
"""

import litellm

from app.llm.registry import LLM_RETRIES, LLM_TIMEOUT_SECONDS, PROVIDERS


_FALLBACK_PARAMETERS = ("temperature", "response_format")


def _unsupported_parameter_fallback(
    kwargs: dict, exc: Exception
) -> dict | None:
    """Return a safer retry payload for provider/model parameter mismatches.

    LiteLLM can identify unsupported parameters for known models when
    ``drop_params`` is enabled.  OpenAI-compatible gateways may still reject a
    parameter at request time, however, so we also handle an explicit 400/422
    response.  Only parameters named by the error are removed; credentials and
    required request fields are never changed.
    """

    error_name = type(exc).__name__.lower()
    error_text = str(exc).lower()
    status = getattr(exc, "status_code", None)
    is_parameter_error = (
        "unsupportedparam" in error_name
        or "unsupported parameter" in error_text
        or "doesn't support" in error_text
        or "does not support" in error_text
        or (status in {400, 422} and "parameter" in error_text)
        or (
            status in {400, 422}
            and any(parameter in error_text for parameter in _FALLBACK_PARAMETERS)
        )
    )
    if not is_parameter_error:
        return None

    retry_kwargs = dict(kwargs)
    removed = False
    for parameter in _FALLBACK_PARAMETERS:
        if parameter not in retry_kwargs:
            continue
        if parameter == "temperature" and "temperature" not in error_text:
            continue
        if parameter == "response_format" and not any(
            token in error_text
            for token in (
                "response_format",
                "response format",
                "json mode",
                "structured output",
                "json",
            )
        ):
            continue
        retry_kwargs.pop(parameter, None)
        removed = True
    return retry_kwargs if removed else None


def _completion_with_fallback(kwargs: dict):
    """Call LiteLLM once, retrying only explicit parameter incompatibilities."""

    try:
        return litellm.completion(**kwargs)
    except Exception as exc:
        retry_kwargs = _unsupported_parameter_fallback(kwargs, exc)
        if retry_kwargs is None:
            raise
        return litellm.completion(**retry_kwargs)


class LlmCallError(RuntimeError):
    """安全的模型调用错误；不携带 LiteLLM 原始信息或请求密钥。"""

    def __init__(self, kind: str):
        messages = {
            "auth": "模型认证失败，请检查 API key",
            "timeout": "模型请求超时，请稍后重试",
            "unavailable": "模型服务暂时不可用，请检查 Base URL 或网络",
            "response": "模型返回异常，请稍后重试",
        }
        self.kind = kind if kind in messages else "response"
        super().__init__(messages[self.kind])


def _error_kind(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    status = getattr(exc, "status_code", None)
    if "auth" in name or "permission" in name or status in {401, 403}:
        return "auth"
    if "timeout" in name or "timedout" in name:
        return "timeout"
    if isinstance(status, int) and status >= 500:
        return "unavailable"
    if any(token in name for token in ("connection", "proxy", "serviceunavailable", "ratelimit")):
        return "unavailable"
    return "response"


def _request_kwargs(
    messages: list[dict],
    provider: str,
    response_format: dict | None,
    config: dict | None,
    *,
    stream: bool = False,
    generation: str = "structured",
) -> dict:
    cfg = config if config is not None else PROVIDERS.get(provider)
    if cfg is None:
        raise ValueError(f"未知 provider: {provider}")
    if not cfg.get("api_key"):
        raise RuntimeError(f"厂商 {provider} 未配置 API key")
    if not cfg.get("model"):
        raise RuntimeError(f"厂商 {provider} 未配置 model")
    kwargs: dict = {
        "model": cfg["model"],
        "messages": messages,
        "api_key": cfg["api_key"],
        "timeout": LLM_TIMEOUT_SECONDS,
        "num_retries": LLM_RETRIES,
        # Model capabilities vary across the four providers and compatible
        # gateways.  Let LiteLLM remove unsupported optional parameters (for
        # example temperature on reasoning models) before sending a request.
        "drop_params": True,
        # Some OpenAI-compatible gateways reject the SDK's default user agent
        # even though the API key and endpoint are valid. Use one stable,
        # non-sensitive application identity for every provider request.
        "extra_headers": {
            "Accept": "application/json",
            "User-Agent": "qiuzhao-agent/0.1",
        },
    }
    if stream:
        kwargs["stream"] = True
    if cfg.get("api_base"):
        kwargs["api_base"] = cfg["api_base"]
    if response_format is not None:
        kwargs["response_format"] = response_format
    if generation == "structured":
        kwargs["temperature"] = 0
    return kwargs


def chat(
    messages: list[dict],
    provider: str,
    response_format: dict | None = None,
    config: dict | None = None,
    generation: str = "structured",
) -> str:
    """调用指定厂商的模型，返回文本内容。

    messages: [{"role": "user"/"system"/"assistant", "content": "..."}]
    provider: "anthropic" / "openai" / "deepseek" / "qwen"
    """
    kwargs = _request_kwargs(
        messages, provider, response_format, config, generation=generation
    )
    try:
        resp = _completion_with_fallback(kwargs)
        return resp.choices[0].message.content
    except Exception as exc:
        raise LlmCallError(_error_kind(exc)) from None


def chat_stream(
    messages: list[dict],
    provider: str,
    response_format: dict | None = None,
    config: dict | None = None,
    generation: str = "chat",
):
    kwargs = _request_kwargs(
        messages,
        provider,
        response_format,
        config,
        stream=True,
        generation=generation,
    )
    try:
        for attempt in range(2):
            received_chunk = False
            try:
                stream = litellm.completion(**kwargs)
                for chunk in stream:
                    # Do not replay a partially delivered stream.  A retry is
                    # safe only when the provider rejected the request before
                    # yielding any chunk.
                    received_chunk = True
                    content = getattr(
                        getattr(chunk.choices[0], "delta", None), "content", None
                    )
                    if isinstance(content, str) and content:
                        yield content
                return
            except Exception as exc:
                retry_kwargs = _unsupported_parameter_fallback(kwargs, exc)
                if attempt or received_chunk or retry_kwargs is None:
                    raise
                kwargs = retry_kwargs
    except Exception as exc:
        raise LlmCallError(_error_kind(exc)) from None
