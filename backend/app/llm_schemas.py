from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

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
    source: Literal["database"] | None
    validation_status: Literal["未验证", "已验证", "验证失败"]
    validation_message: str | None
    last_tested_at: datetime | None
    is_default: bool
    supports_tools: bool | None = None
    supports_json: bool | None = None
    supports_streaming: bool | None = None
    supports_vision: bool | None = None
    capability_checked_at: datetime | None = None


class DefaultProviderUpdate(BaseModel):
    provider: str | None = None


class LlmRolesWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interview: str | None = None
    planner: str | None = None
    briefing: str | None = None
    vision: str | None = None


class LlmRolesRead(BaseModel):
    roles: dict[str, dict]
    providers: list[ProviderRead]


class SearchConfigWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str | None = Field(default=None, max_length=500)
    endpoint: str | None = Field(default=None, max_length=1000)
    tool_name: str | None = Field(default=None, max_length=100)

    @field_validator("api_key", "endpoint", "tool_name")
    @classmethod
    def trim_api_key(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value):
        if value and urlsplit(value).scheme not in {"http", "https"}:
            raise ValueError("联网工具地址必须使用 http 或 https")
        return value


class SearchConfigRead(BaseModel):
    configured: bool
    api_key_masked: str | None
    endpoint: str | None
    tool_name: str
    validation_message: str | None = None
