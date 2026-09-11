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


class PlannerAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyText = Field(max_length=200)
    detail: str | None = Field(default=None, max_length=5000)
    priority: int = Field(ge=1, le=5)
    source_ids: list[str] = Field(default_factory=list)


class PlannerTaskDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyText = Field(max_length=200)
    detail: str | None = Field(default=None, max_length=5000)
    gap: NonEmptyText = Field(max_length=200)
    source_ids: list[str] = Field(default_factory=list)
    estimated_minutes: int = Field(ge=15, le=480)


class PlannerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str | None = Field(default=None, max_length=5000)
    strengths: list[Gap] = Field(default_factory=list, max_length=20)
    gaps: list[Gap] = Field(default_factory=list)
    actions: list[PlannerAction] = Field(default_factory=list, max_length=20)
    tasks: list[PlannerTaskDraft] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def normalize_legacy_tasks(self):
        if not self.actions and self.tasks:
            self.actions = [
                PlannerAction(
                    title=task.title,
                    detail=task.detail,
                    priority=index,
                    source_ids=task.source_ids,
                )
                for index, task in enumerate(self.tasks, 1)
            ]
        if not self.actions:
            raise ValueError("至少需要一项准备行动")
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
    provider: Provider


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


class PreparationTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    planner_session_id: int
    application_id: int
    title: str
    detail: str | None
    gap: str | None
    source_ids: list[str]
    scheduled_at: datetime
    ends_at: datetime
    estimated_minutes: int
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
