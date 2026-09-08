"""四家模型的 registry：把厂商 key 映射到 LiteLLM 的模型名与凭证。

LiteLLM 用统一的 OpenAI 兼容接口调所有厂商，切换模型只改配置。
"""

from app.config import settings


# provider -> (环境变量里的 key, LiteLLM 需要的 api_key 参数名, 默认 base_url)
# DeepSeek / Qwen 走各自 OpenAI 兼容端点。
PROVIDERS = {
    "anthropic": {
        "api_key": settings.anthropic_api_key,
        "api_base": None,
    },
    "openai": {
        "api_key": settings.openai_api_key,
        "api_base": None,
    },
    "deepseek": {
        "api_key": settings.deepseek_api_key,
        "api_base": None,
    },
    "qwen": {
        "api_key": settings.dashscope_api_key,
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
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
