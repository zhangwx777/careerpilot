from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.llm.registry import default_provider

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


class Position(Base):
    __tablename__ = "position"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    jd_text: Mapped[str | None] = mapped_column(Text)
    intel_insight: Mapped[dict | None] = mapped_column(JSONB)
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
    extracted_payload: Mapped[dict | None] = mapped_column(JSONB)
    confirmed_payload: Mapped[dict | None] = mapped_column(JSONB)
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

    timeline_node: Mapped["TimelineNode | None"] = relationship()


class InterviewIntel(Base):
    __tablename__ = "interview_intel"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="未命名面经")
    round_type: Mapped[str] = mapped_column(String(20), nullable=False, default="未注明")
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default=default_provider)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float | None] = mapped_column()
    sources: Mapped[list] = mapped_column(JSONB, default=list)
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
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="已完成")
    source_ids: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    position: Mapped["Position"] = relationship()


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
    image_texts: Mapped[list] = mapped_column(JSONB, default=list)
    draft_payload: Mapped[dict | None] = mapped_column(JSONB)
    conflicts: Mapped[list | None] = mapped_column(JSONB)
    progress_payload: Mapped[dict | None] = mapped_column(JSONB)
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
    intel_snapshot: Mapped[list] = mapped_column(JSONB, default=list)
    available_windows: Mapped[list] = mapped_column(JSONB, nullable=False)
    draft_payload: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        Enum(*PLANNER_SESSION_STATUS, name="planner_session_status"),
        nullable=False,
        default="生成中",
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    application: Mapped["Application"] = relationship()
    tasks: Mapped[list["PreparationTask"]] = relationship(
        back_populates="planner_session", cascade="all, delete-orphan"
    )


class PreparationTask(Base):
    __tablename__ = "preparation_task"

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
    source_ids: Mapped[list] = mapped_column(JSONB, default=list)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
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
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
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
