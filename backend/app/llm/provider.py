"""统一的多模型调用入口。

用 LiteLLM 把 claude/openai/deepseek/qwen 收敛到一个 chat() 函数。
调用时显式指定 provider，模型名/key/base_url 必须来自网页配置或任务快照。
"""

import json
from time import monotonic
from typing import Any, TypedDict

import litellm

from app.llm.registry import LLM_RETRIES, LLM_TIMEOUT_SECONDS
from app.llm.budget import BudgetExceeded, current_budget


_FALLBACK_PARAMETERS = ("temperature", "response_format")


class ToolCall(TypedDict):
    id: str
    name: str
    arguments: dict[str, Any]


class LlmTurn(TypedDict):
    content: str | None
    tool_calls: list[ToolCall]


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
        return _completion(kwargs)
    except Exception as exc:
        retry_kwargs = _unsupported_parameter_fallback(kwargs, exc)
        if retry_kwargs is None:
            raise
        return _completion(retry_kwargs)


def _completion(kwargs):
    budget = current_budget.get()
    if budget:
        kwargs = {**kwargs, "timeout": min(kwargs["timeout"], budget.claim_call()), "num_retries": 0}
    started = monotonic()
    streaming = False
    try:
        response = litellm.completion(**kwargs)
        if budget and kwargs.get("stream"):
            streaming = True
            def timed_stream():
                try:
                    yield from response
                finally:
                    with budget.lock:
                        budget.provider_ms += int((monotonic() - started) * 1000)

            return timed_stream()
        if budget:
            budget.remaining()
            budget.record_tokens(response)
        return response
    finally:
        if budget and not streaming:
            with budget.lock:
                budget.provider_ms += int((monotonic() - started) * 1000)


class LlmCallError(RuntimeError):
    """安全的模型调用错误；不携带 LiteLLM 原始信息或请求密钥。"""

    def __init__(self, kind: str):
        messages = {
            "auth": "模型认证失败，请检查 API Key 是否有效或已过期",
            "permission": "模型账户无权限或余额不足，请检查供应商账户",
            "model_or_endpoint": "模型或 Base URL 不存在，请检查 Model 和 Base URL",
            "rate_limit": "请求过于频繁或额度受限，请稍后重试",
            "timeout": "模型请求超时，请稍后重试",
            "unavailable": "模型服务暂时不可用，请稍后重试或检查 Base URL/网络",
            "tool_call_unsupported": "当前模型不支持工具调用",
            "response": "模型返回异常，请稍后重试",
        }
        self.kind = kind if kind in messages else "response"
        super().__init__(messages[self.kind])


def _error_kind(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    error_text = str(exc).lower()
    status = getattr(exc, "status_code", None)
    if status == 401 or any(
        token in error_text
        for token in ("invalid api key", "incorrect api key", "authentication failed", "unauthorized")
    ):
        return "auth"
    if status in {402, 403} or any(
        token in error_text
        for token in ("insufficient balance", "insufficient quota", "payment required", "forbidden")
    ):
        return "permission"
    if status == 404 or any(
        token in error_text
        for token in (
            "model not found",
            "model does not exist",
            "model not exist",
            "invalid model",
            "model_not_found",
            "unknown model",
            "endpoint not found",
        )
    ):
        return "model_or_endpoint"
    if status == 429 or "rate limit" in error_text or "too many requests" in error_text:
        return "rate_limit"
    if "timeout" in name or "timedout" in name:
        return "timeout"
    if isinstance(status, int) and status >= 500:
        return "unavailable"
    if any(
        token in name or token in error_text
        for token in (
            "connection",
            "proxy",
            "serviceunavailable",
            "bad gateway",
            "gateway timeout",
            "connection refused",
            "network is unreachable",
            "name or service not known",
            "temporary failure in name resolution",
            "ssl",
        )
    ):
        return "unavailable"
    return "response"


def _tool_call_unsupported(exc: Exception) -> bool:
    error_name = type(exc).__name__.lower()
    error_text = str(exc).lower()
    if "unsupported" in error_name and "param" not in error_name:
        return "tool" in error_name or "function" in error_name
    return (
        ("tool" in error_text or "function call" in error_text or "function_call" in error_text)
        and any(token in error_text for token in ("unsupported", "not support", "not implemented", "doesn't support", "does not support"))
    )


def _request_kwargs(
    messages: list[dict],
    provider: str,
    response_format: dict | None,
    config: dict | None,
    *,
    stream: bool = False,
    generation: str = "structured",
) -> dict:
    cfg = config
    if cfg is None:
        raise RuntimeError("模型配置必须来自网页设置或任务快照")
    if not cfg.get("api_key"):
        raise RuntimeError(f"厂商 {provider} 未配置 API key")
    if not cfg.get("model"):
        raise RuntimeError(f"厂商 {provider} 未配置 model")
    kwargs: dict = {
        "model": cfg["model"],
        # 网页配置里存的是厂商自己的裸模型名（如 deepseek-chat），LiteLLM 只能从
        # claude-/gpt- 这类前缀反推厂商，deepseek/qwen 会直接报 Provider NOT
        # provided。调用方已经知道 provider，显式传给 LiteLLM 完成路由。
        "custom_llm_provider": provider,
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
    except BudgetExceeded:
        raise
    except Exception as exc:
        raise LlmCallError(_error_kind(exc)) from None


def _normalize_tool_calls(message: Any) -> list[ToolCall]:
    normalized: list[ToolCall] = []
    for index, raw_call in enumerate(getattr(message, "tool_calls", None) or []):
        function = raw_call.get("function") if isinstance(raw_call, dict) else getattr(raw_call, "function", None)
        if function is None:
            raise ValueError("工具调用缺少 function")
        if isinstance(function, dict):
            name = function.get("name")
            arguments = function.get("arguments")
        else:
            name = getattr(function, "name", None)
            arguments = getattr(function, "arguments", None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("工具调用缺少名称")
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            raise ValueError("工具调用参数不是 JSON 对象")
        call_id = raw_call.get("id") if isinstance(raw_call, dict) else getattr(raw_call, "id", None)
        normalized.append(
            {
                "id": str(call_id or f"tool-call-{index + 1}"),
                "name": name.strip(),
                "arguments": arguments,
            }
        )
    return normalized


def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    provider: str,
    config: dict | None = None,
) -> LlmTurn:
    """Call a model with tools and normalize provider-specific tool calls."""

    kwargs = _request_kwargs(messages, provider, None, config, generation="chat")
    kwargs["tools"] = tools
    kwargs["tool_choice"] = "auto"
    try:
        response = _completion_with_fallback(kwargs)
        message = response.choices[0].message
        return {
            "content": getattr(message, "content", None),
            "tool_calls": _normalize_tool_calls(message),
        }
    except BudgetExceeded:
        raise
    except Exception as exc:
        if _tool_call_unsupported(exc):
            raise LlmCallError("tool_call_unsupported") from None
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
                stream = _completion(kwargs)
                for chunk in stream:
                    budget = current_budget.get()
                    if budget:
                        budget.remaining()
                        budget.record_tokens(chunk)
                    if not chunk.choices:
                        continue
                    # Do not replay a partially delivered stream.  A retry is
                    # safe only when the provider rejected the request before
                    # yielding any chunk.
                    received_chunk = True
                    content = getattr(
                        getattr(chunk.choices[0], "delta", None), "content", None
                    )
                    if isinstance(content, str) and content:
                        yield content
                budget = current_budget.get()
                if budget:
                    budget.remaining()
                return
            except Exception as exc:
                retry_kwargs = _unsupported_parameter_fallback(kwargs, exc)
                if attempt or received_chunk or retry_kwargs is None:
                    raise
                kwargs = retry_kwargs
    except BudgetExceeded:
        raise
    except Exception as exc:
        raise LlmCallError(_error_kind(exc)) from None
