from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 位于项目根目录（backend 的上一级）
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""

    model_parse: str = "deepseek/deepseek-chat"
    model_reason: str = "anthropic/claude-sonnet-4-20250514"


settings = Settings()
