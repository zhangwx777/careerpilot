"""支持的模型厂商和统一调用参数。模型连接配置只来自网页数据库。"""

from app.config import settings

PROVIDER_NAMES = ("anthropic", "openai", "deepseek", "qwen")

LLM_TIMEOUT_SECONDS = settings.llm_timeout_seconds
LLM_RETRIES = settings.llm_retries
