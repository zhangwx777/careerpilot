"""Public request and response contracts for interview preparation follow-up."""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent_schemas import AgentSource

FollowupStatus = Literal["生成中", "待确认", "已完成", "已丢弃", "失败"]
FollowupOperation = Literal["add_practice", "reschedule_task", "skip_task"]


class GoalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_id: int = Field(gt=0)
    timeline_node_id: int = Field(gt=0)


class Apply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggestion_indexes: list[int] = Field(min_length=1, max_length=10)


class FollowupSuggestionRead(BaseModel):
    operation: FollowupOperation
    task_id: int | None
    title: str | None
    reason: str
    source_ids: list[str]
    before: dict[str, Any] | None
    after: dict[str, Any]


class FollowupExecutionActionRead(BaseModel):
    suggestion_index: int
    operation: FollowupOperation
    task_id: int
    before: dict[str, Any] | None
    after: dict[str, Any]


class FollowupExecutionRead(BaseModel):
    suggestion_indexes: list[int]
    actions: list[FollowupExecutionActionRead]
    applied_at: str


class FollowupHistoryRead(BaseModel):
    id: int
    status: FollowupStatus
    created_at: datetime
    resolved_at: datetime | None
    message: str | None
    error_message: str | None
    duplicate_of: int | None


class FollowupCheckRead(FollowupHistoryRead):
    goal_id: int
    suggestions: list[FollowupSuggestionRead]
    sources: list[AgentSource]
    execution_result: FollowupExecutionRead | None
    input_snapshot: dict[str, Any]
    agent_run_id: int | None
    is_current: bool
    applicable: bool


class FollowupGoalRead(BaseModel):
    id: int
    application_id: int
    timeline_node_id: int
    status: Literal["active", "paused"]
    last_auto_date: date | None
    created_at: datetime
    latest_check: FollowupCheckRead | None
    history: list[FollowupHistoryRead]
