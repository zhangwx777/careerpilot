from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    url: str | None = None
    published_at: datetime | None = None
    text: str


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    source_ids: list[str] = Field(min_length=1)


class InterviewRound(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_type: str
    duration_minutes: int | None = Field(default=None, ge=1, le=600)
    question_types: list[Fact] = Field(default_factory=list)
    focus_topics: list[Fact] = Field(default_factory=list)
    source_ids: list[str] = Field(min_length=1)


class IntelExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rounds: list[InterviewRound] = Field(default_factory=list)
    frequent_topics: list[Fact] = Field(default_factory=list)
    difficulty: Fact | None = None


class ConflictItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    candidates: list[Fact] = Field(min_length=2)


class IntelPayload(IntelExtraction):
    conflicts: list[ConflictItem] = Field(default_factory=list)


IntelSessionStatus = Literal["聚合中", "待裁决", "已完成", "已丢弃", "失败"]
