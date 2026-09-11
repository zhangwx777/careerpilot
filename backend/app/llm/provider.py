"""统一的多模型调用入口。

用 LiteLLM 把 claude/openai/deepseek/qwen 收敛到一个 chat() 函数。
调用时显式指定 provider，模型名/key/base_url 均取自 .env 中该厂商的配置。
"""

import litellm

from app.llm.registry import LLM_RETRIES, LLM_TIMEOUT_SECONDS, PROVIDERS, has_key


def chat(
    messages: list[dict],
    provider: str,
    response_format: dict | None = None,
) -> str:
    """调用指定厂商的模型，返回文本内容。

    messages: [{"role": "user"/"system"/"assistant", "content": "..."}]
    provider: "anthropic" / "openai" / "deepseek" / "qwen"
    """
    cfg = PROVIDERS.get(provider)
    if cfg is None:
        raise ValueError(f"未知 provider: {provider}")
    if not has_key(provider):
        raise RuntimeError(f"厂商 {provider} 未配置 API key")
    if not cfg["model"]:
        raise RuntimeError(f"厂商 {provider} 未在 .env 配置 model")

    kwargs: dict = {
        "model": cfg["model"],
        "messages": messages,
        "api_key": cfg["api_key"],
        "timeout": LLM_TIMEOUT_SECONDS,
        "num_retries": LLM_RETRIES,
    }
    if cfg["api_base"]:
        kwargs["api_base"] = cfg["api_base"]
    if response_format is not None:
        kwargs["response_format"] = response_format

    resp = litellm.completion(**kwargs)
    return resp.choices[0].message.content


def chat_stream(
    messages: list[dict],
    provider: str,
    response_format: dict | None = None,
):
    cfg = PROVIDERS.get(provider)
    if cfg is None:
        raise ValueError(f"未知 provider: {provider}")
    if not has_key(provider):
        raise RuntimeError(f"厂商 {provider} 未配置 API key")
    if not cfg["model"]:
        raise RuntimeError(f"厂商 {provider} 未在 .env 配置 model")

    kwargs: dict = {
        "model": cfg["model"],
        "messages": messages,
        "api_key": cfg["api_key"],
        "stream": True,
        "timeout": LLM_TIMEOUT_SECONDS,
        "num_retries": LLM_RETRIES,
    }
    if cfg["api_base"]:
        kwargs["api_base"] = cfg["api_base"]
    if response_format is not None:
        kwargs["response_format"] = response_format

    for chunk in litellm.completion(**kwargs):
        content = getattr(getattr(chunk.choices[0], "delta", None), "content", None)
        if isinstance(content, str) and content:
            yield content
