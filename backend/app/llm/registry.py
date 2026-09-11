"""四家模型的 registry：把厂商配置（key / base_url / model）从 .env 汇总。

所有值均来自 .env，代码不预设任何默认。LiteLLM 用统一的 OpenAI 兼容接口调所有厂商。
"""

from app.config import settings

# provider -> {api_key, api_base, model}，全部来自 .env。
# base_url 为空则传 None（走 LiteLLM 官方默认）。
PROVIDERS = {
    "anthropic": {
        "api_key": settings.anthropic_api_key,
        "api_base": settings.anthropic_base_url or None,
        "model": settings.anthropic_model,
    },
    "openai": {
        "api_key": settings.openai_api_key,
        "api_base": settings.openai_base_url or None,
        "model": settings.openai_model,
    },
    "deepseek": {
        "api_key": settings.deepseek_api_key,
        "api_base": settings.deepseek_base_url or None,
        "model": settings.deepseek_model,
    },
    "qwen": {
        "api_key": settings.dashscope_api_key,
        "api_base": settings.dashscope_base_url or None,
        "model": settings.dashscope_model,
    },
}

LLM_TIMEOUT_SECONDS = settings.llm_timeout_seconds
LLM_RETRIES = settings.llm_retries


def has_key(provider: str) -> bool:
    """该厂商是否已配置 key。"""
    cfg = PROVIDERS.get(provider)
    return bool(cfg and cfg["api_key"])


def default_provider() -> str:
    for name, cfg in PROVIDERS.items():
        if has_key(name) and cfg["model"]:
            return name
    raise RuntimeError("未配置可用模型")
