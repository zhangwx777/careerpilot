from datetime import datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from typing_extensions import Annotated

from app.models import PLANNER_SESSION_STATUS, PREPARATION_TASK_STATUS
from app.schemas import ApplicationRead, PositiveId

Provider = Literal["qwen", "openai", "anthropic", "deepseek"]
PlannerSessionStatus = Literal[*PLANNER_SESSION_STATUS]
PreparationTaskStatus = Literal[*PREPARATION_TASK_STATUS]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AvailabilityWindow(BaseModel):
    weekday: int = Field(ge=0, le=6, description="周一为 0")
    start: time
    end: time

    @model_validator(mode="after")
    def validate_range(self):
        if self.end <= self.start:
            raise ValueError("可用时间结束必须晚于开始")
        return self


class ResumeProfileUpdate(BaseModel):
    resume_text: NonEmptyText


class ResumeProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resume_text: str
    file_name: str | None
    updated_at: datetime


class Gap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonEmptyText
    evidence: NonEmptyText


class PlannerEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["resume", "jd", "intel", "timeline"]
    reference: NonEmptyText


class PlannerAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyText = Field(max_length=200)
    detail: str | None = Field(default=None, max_length=5000)
    gap: str | None = Field(default=None, max_length=200)
    priority: int = Field(ge=1, le=5)
    estimated_minutes: int = Field(default=30, ge=15, le=480)
    evidence: list[PlannerEvidence] = Field(default_factory=list, max_length=20)
    source_ids: list[str] = Field(default_factory=list, max_length=20)


class PlannerTaskDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyText = Field(max_length=200)
    detail: str | None = Field(default=None, max_length=5000)
    gap: NonEmptyText = Field(max_length=200)
    source_ids: list[str] = Field(default_factory=list, max_length=20)
    estimated_minutes: int = Field(ge=15, le=480)
    evidence: list[PlannerEvidence] = Field(default_factory=list, max_length=20)


class PlannerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str | None = Field(default=None, max_length=5000)
    strengths: list[Gap] = Field(default_factory=list, max_length=20)
    gaps: list[Gap] = Field(default_factory=list, max_length=20)
    actions: list[PlannerAction] = Field(default_factory=list, max_length=20)
    tasks: list[PlannerTaskDraft] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def normalize_legacy_tasks(self):
        if not self.actions and self.tasks:
            self.actions = [
                PlannerAction(
                    title=task.title,
                    detail=task.detail,
                    gap=task.gap,
                    estimated_minutes=task.estimated_minutes,
                    evidence=task.evidence,
                    priority=index,
                    source_ids=task.source_ids,
                )
                for index, task in enumerate(self.tasks, 1)
            ]
        # Missing evidence is a valid result: the model should be able to
        # explain that preparation data is insufficient without inventing an
        # action merely to satisfy the schema.
        return self


class ScheduledTask(PlannerTaskDraft):
    scheduled_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def validate_times(self):
        if self.scheduled_at.utcoffset() is None or self.ends_at.utcoffset() is None:
            raise ValueError("任务时间必须包含时区")
        if self.ends_at <= self.scheduled_at:
            raise ValueError("任务结束必须晚于开始")
        return self


class PlannerSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_id: PositiveId
    provider: Provider | None = None


class PlannerConfirmation(BaseModel):
    tasks: list[ScheduledTask] = Field(min_length=1, max_length=20)


class PlannerSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    thread_id: UUID
    application_id: int
    application: ApplicationRead
    provider: str
    available_windows: list[AvailabilityWindow]
    draft_payload: dict | None
    status: PlannerSessionStatus
    error_message: str | None
    created_at: datetime
    resolved_at: datetime | None
    queue_task_id: str | None = None


class PreparationTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    planner_session_id: int
    application_id: int
    title: str
    detail: str | None
    gap: str | None
    source_ids: list[str]
    evidence: list[PlannerEvidence] = Field(default_factory=list)
    scheduled_at: datetime | None
    ends_at: datetime | None
    estimated_minutes: int
    priority: int
    action_index: int | None
    deferred_until: datetime | None
    status: PreparationTaskStatus
    timeline_node_id: int | None
    created_at: datetime


class PreparationTaskPage(BaseModel):
    items: list[PreparationTaskRead]
    total: int
    page: int
    page_size: int


class PreparationTaskStatusUpdate(BaseModel):
    status: PreparationTaskStatus
    deferred_until: datetime | None = None
