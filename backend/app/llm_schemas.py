from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import LLM_PROVIDER_NAMES


ProviderName = Literal[*LLM_PROVIDER_NAMES]


class ProviderConfigWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str | None = Field(default=None, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=1000)

    @field_validator("api_key", "model", "base_url")
    @classmethod
    def trim_values(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProviderTestWrite(BaseModel):
    """测试接口允许只提交需要临时覆盖的字段。"""

    model_config = ConfigDict(extra="forbid")

    api_key: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=1000)

    @field_validator("api_key", "model", "base_url")
    @classmethod
    def trim_values(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProviderTestRead(BaseModel):
    provider: str
    ok: bool
    message: str
    latency_ms: int | None = None


class ProviderModelsRead(BaseModel):
    provider: str
    models: list[str]
    message: str | None = None


class ProviderRead(BaseModel):
    name: str
    label: str
    description: str
    model: str
    base_url: str | None
    api_key_masked: str | None
    configured: bool
    source: Literal["env", "database"] | None
    validation_status: Literal["未验证", "已验证", "验证失败"]
    validation_message: str | None
    last_tested_at: datetime | None
    is_default: bool


class DefaultProviderUpdate(BaseModel):
    provider: str | None = None
