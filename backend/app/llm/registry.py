"""四家模型的 registry：把厂商 key 映射到 LiteLLM 的模型名与凭证。

LiteLLM 用统一的 OpenAI 兼容接口调所有厂商，切换模型只改配置。
"""

from app.config import settings


# provider -> (环境变量里的 key, base_url)
# base_url 从 .env 读，留空则为 None（走 LiteLLM 官方默认）。
# Qwen 留空时兜底 DashScope 官方兼容端点。
PROVIDERS = {
    "anthropic": {
        "api_key": settings.anthropic_api_key,
        "api_base": settings.anthropic_base_url or None,
    },
    "openai": {
        "api_key": settings.openai_api_key,
        "api_base": settings.openai_base_url or None,
    },
    "deepseek": {
        "api_key": settings.deepseek_api_key,
        "api_base": settings.deepseek_base_url or None,
    },
    "qwen": {
        "api_key": settings.dashscope_api_key,
        "api_base": settings.dashscope_base_url
        or "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
}


def provider_of(model: str) -> str:
    """从 LiteLLM 模型名推断 provider 前缀，如 'deepseek/deepseek-chat' -> 'deepseek'。"""
    return model.split("/", 1)[0]


def has_key(model: str) -> bool:
    """该模型对应的厂商是否已配置 key。"""
    p = provider_of(model)
    cfg = PROVIDERS.get(p)
    return bool(cfg and cfg["api_key"])
