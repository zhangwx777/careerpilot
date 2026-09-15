from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# .env 位于项目根目录（backend 的上一级）
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ):
        # 让 .env 优先于系统环境变量，避免系统里同名变量污染项目配置
        return (init_settings, dotenv_settings, env_settings, file_secret_settings)

    database_url: str
    test_database_url: str | None = None
    anysearch_api_key: str = ""

    llm_timeout_seconds: int = 45
    llm_retries: int = 0


settings = Settings()
