from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from typing_extensions import Annotated

from app.models import NODE_STATUS, NODE_TYPE, PARSE_SESSION_STATUS
from app.parsing import NoticeExtraction, TimeMode
from app.schemas import ApplicationRead, Name, PositiveId

NodeType = Literal[*NODE_TYPE]
NodeStatus = Literal[*NODE_STATUS]
ParseSessionStatus = Literal[*PARSE_SESSION_STATUS]
RawNoticeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Provider = Literal["qwen", "openai", "anthropic", "deepseek"]


class ParseSessionCreate(BaseModel):
    raw_text: RawNoticeText
    provider: Provider | None = None


class NoticeApplicationCreate(BaseModel):
    company_name: Name
    position_title: Name


class ParseConfirmation(BaseModel):
    application_id: PositiveId
    node_type: NodeType
    time_mode: TimeMode = "固定时间"
    scheduled_at: datetime
    ends_at: datetime | None = None
    source: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_times(self):
        if self.scheduled_at.utcoffset() is None:
            raise ValueError("scheduled_at 必须包含时区")
        if self.ends_at is not None:
            if self.ends_at.utcoffset() is None:
                raise ValueError("ends_at 必须包含时区")
            if self.ends_at <= self.scheduled_at:
                raise ValueError("ends_at 必须晚于 scheduled_at")
        if self.time_mode == "截止窗口" and self.ends_at is None:
            raise ValueError("截止窗口必须填写截止时间")
        return self


class ParseSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    thread_id: UUID
    raw_text: str
    provider: str
    extracted_payload: NoticeExtraction | None
    confirmed_payload: dict | None
    status: ParseSessionStatus
    timeline_node_id: int | None
    error_message: str | None
    created_at: datetime
    resolved_at: datetime | None


class ParseSessionDetail(ParseSessionRead):
    recommended_applications: list[ApplicationRead] = Field(default_factory=list)


class ParseSessionPage(BaseModel):
    items: list[ParseSessionDetail]
    total: int
    page: int
    page_size: int


TimelineAlert = Literal["冲突", "临期", "逾期"]


class TimelineNodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    application: ApplicationRead
    node_type: NodeType
    scheduled_at: datetime | None
    ends_at: datetime | None
    time_mode: TimeMode
    status: NodeStatus
    source: str | None
    title: str | None
    detail: str | None
    created_at: datetime
    alert_types: list[TimelineAlert]
    conflict_node_ids: list[int]


class TimelinePage(BaseModel):
    items: list[TimelineNodeRead]
    total: int
    page: int
    page_size: int


class TimelineStatusTransition(BaseModel):
    status: NodeStatus


class PipelineBucket(BaseModel):
    status: str
    count: int


class DashboardFeedItem(BaseModel):
    kind: Literal["preparation", "timeline"]
    id: int
    title: str
    company_name: str
    position_title: str
    task_id: int | None = None
    planner_session_id: int | None = None
    timeline_node_id: int | None = None
    detail: str | None = None
    category: Literal["八股", "简历内容"] | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    node_type: str | None = None
    status: str
    scheduled_at: datetime | None = None
    alert_types: list[TimelineAlert] = Field(default_factory=list)


class DashboardRead(BaseModel):
    pipeline: list[PipelineBucket]
    feed: list[DashboardFeedItem]
