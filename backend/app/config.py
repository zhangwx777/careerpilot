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

    # 四家厂商各自的三件套，全部由 .env 提供，代码不预设任何值。
    # 空字符串表示未配置。
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    anthropic_model: str = ""

    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = ""

    deepseek_api_key: str = ""
    deepseek_base_url: str = ""
    deepseek_model: str = ""

    dashscope_api_key: str = ""
    dashscope_base_url: str = ""
    dashscope_model: str = ""


settings = Settings()
