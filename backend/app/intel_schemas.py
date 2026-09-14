from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


INTEL_ROUNDS = ("测评", "笔试", "AI面", "一面", "二面", "三面", "HR面", "多轮综合", "未注明")
IntelRoundType = Literal["测评", "笔试", "AI面", "一面", "二面", "三面", "HR面", "多轮综合", "未注明"]


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    url: str | None = None
    published_at: datetime | None = None
    text: str
    kind: Literal["manual", "image", "web", "unknown"] = "unknown"
    file_name: str | None = None


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    source_ids: list[str] = Field(min_length=1, max_length=20)


class IntelQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    category: str = Field(min_length=1)
    round_type: str = Field(min_length=1)
    answer_outline: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class PreparationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    priority: int = Field(default=3, ge=1, le=5)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class InterviewRound(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_type: str
    duration_minutes: int | None = Field(default=None, ge=1, le=600)
    question_types: list[Fact] = Field(default_factory=list, max_length=20)
    focus_topics: list[Fact] = Field(default_factory=list, max_length=20)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class IntelExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: Fact | None = None
    rounds: list[InterviewRound] = Field(default_factory=list, max_length=12)
    questions: list[IntelQuestion] = Field(default_factory=list, max_length=50)
    frequent_topics: list[Fact] = Field(default_factory=list, max_length=30)
    difficulty: Fact | None = None
    preparation_items: list[PreparationItem] = Field(default_factory=list, max_length=30)


class ConflictItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    candidates: list[Fact] = Field(min_length=2, max_length=10)


class IntelPayload(IntelExtraction):
    conflicts: list[ConflictItem] = Field(default_factory=list, max_length=20)


IntelSessionStatus = Literal["聚合中", "待裁决", "已完成", "已丢弃", "失败"]


class InsightDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1, max_length=20)
    round_types: list[str] = Field(default_factory=list)
    representative_questions: list[str] = Field(default_factory=list)


class InsightCoreQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    category: str = Field(min_length=1)
    round_type: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class InsightPreparationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    priority: int = Field(ge=1, le=5)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class IntelInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["未生成", "生成中", "已生成", "失败", "暂无资料"] = "未生成"
    high_frequency_directions: list[InsightDirection] = Field(default_factory=list, max_length=10)
    core_questions: list[InsightCoreQuestion] = Field(default_factory=list, max_length=8)
    preparation_items: list[InsightPreparationItem] = Field(default_factory=list, max_length=30)
    error_message: str | None = None


class IntelChatAnswer(BaseModel):
    """岗位问答的结构化响应契约。"""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=20000)
    source_ids: list[str] = Field(default_factory=list, max_length=20)
