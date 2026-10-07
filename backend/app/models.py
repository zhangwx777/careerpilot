from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


# JSONB is useful in PostgreSQL, but the lightweight CRUD tests use SQLite.
# Keep one portable type so metadata can be created by either dialect.
PortableJSON = JSON().with_variant(JSONB, "postgresql")

# 投递状态：网申 → 笔试 → 一面 → 二面 → 三面 → HR面 → offer / 挂
APPLICATION_STATUS = (
    "已投递",
    "测评",
    "笔试",
    "AI面",
    "一面",
    "二面",
    "三面",
    "HR面",
    "offer",
    "挂",
)

# 时间线节点类型
NODE_TYPE = ("网申截止", "测评", "笔试", "AI面", "一面", "二面", "三面", "HR面", "其他")

# 节点状态
NODE_STATUS = ("待处理", "已完成", "已错过", "已取消")

TIME_MODE = ("固定时间", "截止窗口")

# 解析会话状态
PARSE_SESSION_STATUS = (
    "解析中",
    "待确认",
    "已确认",
    "已丢弃",
    "解析失败",
)

INTEL_SESSION_STATUS = ("聚合中", "待裁决", "已完成", "已丢弃", "失败")

PLANNER_SESSION_STATUS = ("生成中", "待确认", "已确认", "已完成", "已丢弃", "失败")

PREPARATION_TASK_STATUS = ("待处理", "已完成", "已跳过")
LLM_PROVIDER_NAMES = ("openai", "anthropic", "deepseek", "qwen")
LLM_VALIDATION_STATUS = ("未验证", "已验证", "验证失败")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = "company"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    industry: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    positions: Mapped[list["Position"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class LlmProviderConfig(Base):
    """本机单用户的 provider 覆盖配置；API key 只保存密文。"""

    __tablename__ = "llm_provider_config"

    provider: Mapped[str] = mapped_column(String(50), primary_key=True)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    base_url: Mapped[str | None] = mapped_column(String(1000))
    validation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="未验证"
    )
    validation_message: Mapped[str | None] = mapped_column(Text)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    supports_tools: Mapped[bool | None] = mapped_column(Boolean)
    supports_json: Mapped[bool | None] = mapped_column(Boolean)
    supports_streaming: Mapped[bool | None] = mapped_column(Boolean)
    supports_vision: Mapped[bool | None] = mapped_column(Boolean)
    capability_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LlmSettings(Base):
    __tablename__ = "llm_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    default_provider: Mapped[str | None] = mapped_column(String(50))
    encrypted_search_api_key: Mapped[str | None] = mapped_column(Text)
    search_endpoint: Mapped[str | None] = mapped_column(Text)
    search_tool_name: Mapped[str | None] = mapped_column(String(100))
    interview_provider: Mapped[str | None] = mapped_column(String(50))
    planner_provider: Mapped[str | None] = mapped_column(String(50))
    briefing_provider: Mapped[str | None] = mapped_column(String(50))
    vision_provider: Mapped[str | None] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Position(Base):
    __tablename__ = "position"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    jd_text: Mapped[str | None] = mapped_column(Text)
    intel_insight: Mapped[dict | None] = mapped_column(PortableJSON)
    intel_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    company: Mapped["Company"] = relationship(back_populates="positions")
    applications: Mapped[list["Application"]] = relationship(
        back_populates="position", cascade="all, delete-orphan"
    )


class Application(Base):
    __tablename__ = "application"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position_id: Mapped[int] = mapped_column(
        ForeignKey("position.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum(*APPLICATION_STATUS, name="application_status"),
        nullable=False,
        default="已投递",
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    position: Mapped["Position"] = relationship(back_populates="applications")
    timeline_nodes: Mapped[list["TimelineNode"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    intels: Mapped[list["InterviewIntel"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    intel_sessions: Mapped[list["IntelSession"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    preparation_tasks: Mapped[list["PreparationTask"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class TimelineNode(Base):
    __tablename__ = "timeline_node"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    node_type: Mapped[str] = mapped_column(
        Enum(*NODE_TYPE, name="node_type"), nullable=False
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="固定时间"
    )
    status: Mapped[str] = mapped_column(
        Enum(*NODE_STATUS, name="node_status"), nullable=False, default="待处理"
    )
    source: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped["Application"] = relationship(back_populates="timeline_nodes")


class ParseSession(Base):
    __tablename__ = "parse_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(default=uuid4, unique=True, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    extracted_payload: Mapped[dict | None] = mapped_column(PortableJSON)
    confirmed_payload: Mapped[dict | None] = mapped_column(PortableJSON)
    status: Mapped[str] = mapped_column(
        Enum(*PARSE_SESSION_STATUS, name="parse_session_status"),
        nullable=False,
        default="解析中",
    )
    timeline_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("timeline_node.id", ondelete="SET NULL"), unique=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    llm_snapshot: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(40))

    timeline_node: Mapped["TimelineNode | None"] = relationship()


class InterviewIntel(Base):
    __tablename__ = "interview_intel"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="未命名面经")
    round_type: Mapped[str] = mapped_column(String(20), nullable=False, default="未注明")
    # 仅用于历史材料记录的 ORM 默认值；实际任务 provider 必须来自网页配置。
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="qwen")
    payload: Mapped[dict] = mapped_column(PortableJSON, nullable=False)
    confidence: Mapped[float | None] = mapped_column()
    sources: Mapped[list] = mapped_column(PortableJSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped["Application"] = relationship(back_populates="intels")


class IntelChatMessage(Base):
    __tablename__ = "intel_chat_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position_id: Mapped[int] = mapped_column(
        ForeignKey("position.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="已完成")
    source_ids: Mapped[list] = mapped_column(PortableJSON, default=list)
    llm_snapshot: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    position: Mapped["Position"] = relationship()


class AgentRun(Base):
    """Bounded Agent execution trace and source snapshots."""

    __tablename__ = "agent_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    assistant_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("intel_chat_message.id", ondelete="CASCADE"), unique=True
    )
    user_message_id: Mapped[int | None] = mapped_column(ForeignKey("intel_chat_message.id", ondelete="CASCADE"))
    intel_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("intel_session.id", ondelete="CASCADE")
    )
    position_id: Mapped[int] = mapped_column(
        ForeignKey("position.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    stage: Mapped[str | None] = mapped_column(String(100))
    error_kind: Mapped[str | None] = mapped_column(String(50))
    budget: Mapped[dict] = mapped_column(PortableJSON, default=dict)
    steps: Mapped[list] = mapped_column(PortableJSON, default=list)
    sources: Mapped[list] = mapped_column(PortableJSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text)
    queue_task_id: Mapped[str | None] = mapped_column(String(200), index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    insufficient_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    used_tools: Mapped[list] = mapped_column(PortableJSON, default=list)
    answer_mode: Mapped[str | None] = mapped_column(String(30))
    search_status: Mapped[str | None] = mapped_column(String(30))
    last_error_kind: Mapped[str | None] = mapped_column(String(50))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskDispatch(Base):
    """Durable dispatch and execution ownership, committed with domain changes."""

    __tablename__ = "task_dispatch"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_name: Mapped[str] = mapped_column(String(100), nullable=False)
    args: Mapped[list] = mapped_column(PortableJSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class IntelSession(Base):
    __tablename__ = "intel_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(default=uuid4, unique=True, nullable=False)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    round_type: Mapped[str] = mapped_column(String(20), nullable=False, default="未注明")
    user_paste: Mapped[str | None] = mapped_column(Text)
    image_texts: Mapped[list] = mapped_column(PortableJSON, default=list)
    supplement_web: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    draft_payload: Mapped[dict | None] = mapped_column(PortableJSON)
    conflicts: Mapped[list | None] = mapped_column(PortableJSON)
    progress_payload: Mapped[dict | None] = mapped_column(PortableJSON)
    status: Mapped[str] = mapped_column(
        Enum(*INTEL_SESSION_STATUS, name="intel_session_status"),
        nullable=False,
        default="聚合中",
    )
    interview_intel_id: Mapped[int | None] = mapped_column(
        ForeignKey("interview_intel.id", ondelete="SET NULL"), unique=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    llm_snapshot: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    queue_task_id: Mapped[str | None] = mapped_column(String(200), index=True)

    application: Mapped["Application"] = relationship(back_populates="intel_sessions")
    interview_intel: Mapped["InterviewIntel | None"] = relationship()


class ResumeProfile(Base):
    __tablename__ = "resume_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resume_text: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class PlannerSession(Base):
    __tablename__ = "planner_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(default=uuid4, unique=True, nullable=False)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    resume_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    jd_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    intel_snapshot: Mapped[list] = mapped_column(PortableJSON, default=list)
    available_windows: Mapped[list] = mapped_column(PortableJSON, nullable=False)
    draft_payload: Mapped[dict | None] = mapped_column(PortableJSON)
    status: Mapped[str] = mapped_column(
        Enum(*PLANNER_SESSION_STATUS, name="planner_session_status"),
        nullable=False,
        default="生成中",
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    llm_snapshot: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    queue_task_id: Mapped[str | None] = mapped_column(String(200), index=True)

    application: Mapped["Application"] = relationship()
    tasks: Mapped[list["PreparationTask"]] = relationship(
        back_populates="planner_session", cascade="all, delete-orphan"
    )


class PreparationTask(Base):
    __tablename__ = "preparation_task"
    __table_args__ = (
        UniqueConstraint(
            "planner_session_id",
            "action_index",
            name="uq_preparation_task_session_action",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    planner_session_id: Mapped[int] = mapped_column(
        ForeignKey("planner_session.id", ondelete="CASCADE"), nullable=False
    )
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    gap: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="八股")
    source_ids: Mapped[list] = mapped_column(PortableJSON, default=list)
    evidence: Mapped[list] = mapped_column(PortableJSON, default=list)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    action_index: Mapped[int | None] = mapped_column(Integer)
    deferred_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_date: Mapped[date | None] = mapped_column(Date)
    answer_payload: Mapped[dict | None] = mapped_column(PortableJSON)
    user_answer: Mapped[str | None] = mapped_column(Text)
    feedback_payload: Mapped[dict | None] = mapped_column(PortableJSON)
    status: Mapped[str] = mapped_column(
        Enum(*PREPARATION_TASK_STATUS, name="preparation_task_status"),
        nullable=False,
        default="待处理",
    )
    timeline_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("timeline_node.id", ondelete="SET NULL"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    planner_session: Mapped["PlannerSession"] = relationship(back_populates="tasks")
    application: Mapped["Application"] = relationship(back_populates="preparation_tasks")
    timeline_node: Mapped["TimelineNode | None"] = relationship()


class DailyBriefing(Base):
    __tablename__ = "daily_briefing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    briefing_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    payload: Mapped[dict] = mapped_column(PortableJSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    reported_sources: Mapped[list["ReportedSource"]] = relationship(
        back_populates="briefing", cascade="all, delete-orphan"
    )


class ReportedSource(Base):
    __tablename__ = "reported_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    briefing_id: Mapped[int] = mapped_column(
        ForeignKey("daily_briefing.id", ondelete="CASCADE"), nullable=False
    )
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    briefing: Mapped["DailyBriefing"] = relationship(back_populates="reported_sources")
