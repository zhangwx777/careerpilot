"""Contracts shared by the bounded Agent runtime and domain tools."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    url: str | None = None
    kind: str = Field(default="unknown", max_length=30)
    published_at: datetime | None = None
    text: str = Field(default="", max_length=12000)
    scope: Literal["current_position", "related_position", "public", "conversation"] = "current_position"
    file_name: str | None = Field(default=None, max_length=255)


class AgentToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    sources: list[AgentSource] = Field(default_factory=list, max_length=20)
    error: str | None = None


class AgentStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int
    tool_calls: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    elapsed_ms: int = Field(ge=0)


class AgentRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw: str
    steps: list[AgentStep] = Field(default_factory=list, max_length=10)
    sources: list[AgentSource] = Field(default_factory=list, max_length=100)
    status: Literal["completed", "budget_exceeded"] = "completed"
