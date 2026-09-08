from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.db import SessionLocal, get_db
from app.intel_graph import IntelGraphError, resume_intel_graph, start_intel_graph
from app.models import Application, IntelSession, InterviewIntel, Position
from app.schemas import ApplicationRead, PositiveId

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
Provider = Literal["qwen", "openai", "anthropic", "deepseek"]


class IntelCreate(BaseModel):
    application_id: PositiveId
    provider: Provider
    user_paste: str | None = Field(default=None, max_length=20000)


class IntelResolve(BaseModel):
    resolutions: dict = Field(default_factory=dict)


class IntelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    application_id: int
    payload: dict
    confidence: float | None
    sources: list
    created_at: datetime


class IntelSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    thread_id: str
    application_id: int
    provider: str
    user_paste: str | None
    draft_payload: dict | None
    conflicts: list | None
    status: str
    interview_intel_id: int | None
    error_message: str | None
    created_at: datetime
    resolved_at: datetime | None


def _session_read(item: IntelSession) -> IntelSessionRead:
    data = {column.name: getattr(item, column.name) for column in IntelSession.__table__.columns}
    data["thread_id"] = str(data["thread_id"])
    return IntelSessionRead.model_validate(data)


@router.post("/intel", response_model=IntelSessionRead, status_code=status.HTTP_201_CREATED)
def create_intel(payload: IntelCreate, db: DbSession):
    application = db.scalar(select(Application).options(joinedload(Application.position).joinedload(Position.company)).where(Application.id == payload.application_id))
    if application is None:
        raise HTTPException(404, "投递记录不存在")
    item = IntelSession(application_id=application.id, provider=payload.provider, user_paste=payload.user_paste, status="聚合中")
    db.add(item); db.commit(); db.refresh(item)
    query = f"{application.position.company.name} {application.position.title}"
    try:
        start_intel_graph(item.id, str(item.thread_id), item.provider, query, item.user_paste, settings.database_url, SessionLocal)
    except Exception as exc:
        item.status = "失败"; item.error_message = str(exc); item.resolved_at = datetime.now(timezone.utc); db.commit()
        raise HTTPException(502, f"面经聚合失败：{exc}") from exc
    db.expire_all()
    return _session_read(db.get(IntelSession, item.id))


@router.get("/intel", response_model=list[IntelRead])
def list_intel(application_id: PositiveId, db: DbSession):
    return list(db.scalars(select(InterviewIntel).where(InterviewIntel.application_id == application_id).order_by(InterviewIntel.created_at.desc())).all())


@router.get("/intel-sessions/{session_id}", response_model=IntelSessionRead)
def get_intel_session(session_id: int, db: DbSession):
    item = db.get(IntelSession, session_id)
    if item is None: raise HTTPException(404, "面经会话不存在")
    return _session_read(item)


@router.post("/intel-sessions/{session_id}/resolve", response_model=IntelSessionRead)
def resolve_intel(session_id: int, payload: IntelResolve, db: DbSession):
    item = db.get(IntelSession, session_id)
    if item is None: raise HTTPException(404, "面经会话不存在")
    if item.status == "已完成": return _session_read(item)
    if item.status != "待裁决": raise HTTPException(409, "当前会话不能裁决")
    resume_intel_graph(str(item.thread_id), payload.resolutions, settings.database_url, SessionLocal)
    db.expire_all(); return _session_read(db.get(IntelSession, session_id))
