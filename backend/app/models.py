from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# 投递状态：网申 → 笔试 → 一面 → 二面 → 三面 → HR面 → offer / 挂
APPLICATION_STATUS = (
    "已投递",
    "笔试",
    "一面",
    "二面",
    "三面",
    "HR面",
    "offer",
    "挂",
)

# 时间线节点类型
NODE_TYPE = ("网申截止", "笔试", "一面", "二面", "三面", "HR面", "其他")

# 节点状态
NODE_STATUS = ("待处理", "已完成", "已错过", "已取消")

# 解析会话状态
PARSE_SESSION_STATUS = (
    "解析中",
    "待确认",
    "已确认",
    "已丢弃",
    "解析失败",
)

INTEL_SESSION_STATUS = ("聚合中", "待裁决", "已完成", "已丢弃", "失败")


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
    status: Mapped[str] = mapped_column(
        Enum(*NODE_STATUS, name="node_status"), nullable=False, default="待处理"
    )
    source: Mapped[str | None] = mapped_column(String(200))
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
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float | None] = mapped_column()
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped["Application"] = relationship(back_populates="intels")


class IntelSession(Base):
    __tablename__ = "intel_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(default=uuid4, unique=True, nullable=False)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    user_paste: Mapped[str | None] = mapped_column(Text)
    draft_payload: Mapped[dict | None] = mapped_column(JSONB)
    conflicts: Mapped[list | None] = mapped_column(JSONB)
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
