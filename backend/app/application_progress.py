"""Application-local stage transitions and explicitly confirmed reconciliation."""

import hashlib
import json
from datetime import datetime

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import APPLICATION_STATUS, Application, ApplicationStageChange, Position, TimelineNode


class ProgressSelection(BaseModel):
    application_id: int = Field(gt=0)
    token: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProgressApply(BaseModel):
    items: list[ProgressSelection] = Field(min_length=1, max_length=1000)


class ProgressEvidence(BaseModel):
    id: int
    node_type: str
    status: str
    scheduled_at: datetime | None
    ends_at: datetime | None


class ProgressCandidate(BaseModel):
    application_id: int
    company_name: str
    position_title: str
    current_status: str
    suggested_status: str
    evidence: list[ProgressEvidence]
    token: str


class ProgressPage(BaseModel):
    items: list[ProgressCandidate]


class ProgressApplyResult(BaseModel):
    applied_ids: list[int]


class StageHistoryEntry(BaseModel):
    id: int
    from_status: str
    to_status: str
    source: str
    timeline_node_id: int | None
    created_at: datetime


class StageHistoryPage(BaseModel):
    items: list[StageHistoryEntry]


def change_stage(db: Session, application: Application, status: str, source: str,
                 node_id: int | None = None, token: str | None = None) -> None:
    with db.no_autoflush:
        application = db.scalar(select(Application).where(Application.id == application.id).with_for_update(key_share=True).execution_options(populate_existing=True))
    if application is None:
        raise HTTPException(409, "投递已变化，请刷新后重试")
    if application.status == status:
        return
    db.add(ApplicationStageChange(
        application_id=application.id, from_status=application.status, to_status=status,
        source=source, timeline_node_id=node_id, reconciliation_token=token,
    ))
    application.status = status


def progress_candidate(db: Session, application: Application, *, lock: bool = False) -> dict | None:
    query = select(TimelineNode).where(TimelineNode.application_id == application.id).order_by(TimelineNode.id)
    nodes = list(db.scalars(query.with_for_update() if lock else query))
    eligible = [node for node in nodes if node.status in {"待处理", "已完成"} and node.node_type in APPLICATION_STATUS]
    if application.status in {"offer", "挂"} or not eligible:
        return None
    target = max(eligible, key=lambda node: APPLICATION_STATUS.index(node.node_type)).node_type
    if APPLICATION_STATUS.index(target) <= APPLICATION_STATUS.index(application.status):
        return None
    last_change = db.scalar(select(func.max(ApplicationStageChange.id)).where(ApplicationStageChange.application_id == application.id))
    fingerprint = json.dumps({"application_id": application.id, "status": application.status, "last_change_id": last_change, "nodes": [
        {"id": n.id, "revision": n.revision, "type": n.node_type, "status": n.status, "time_mode": n.time_mode,
         "scheduled_at": n.scheduled_at.isoformat() if n.scheduled_at else None,
         "ends_at": n.ends_at.isoformat() if n.ends_at else None} for n in nodes
    ]}, sort_keys=True)
    return {
        "application_id": application.id, "company_name": application.position.company.name,
        "position_title": application.position.title, "current_status": application.status,
        "suggested_status": target, "token": hashlib.sha256(fingerprint.encode()).hexdigest(),
        "evidence": [{"id": n.id, "node_type": n.node_type, "status": n.status,
                      "scheduled_at": n.scheduled_at, "ends_at": n.ends_at} for n in eligible],
    }


def preview_progress(db: Session) -> dict:
    applications = db.scalars(select(Application).options(joinedload(Application.position).joinedload(Position.company)).order_by(Application.id)).all()
    return {"items": [item for application in applications if (item := progress_candidate(db, application)) is not None]}


def apply_progress(db: Session, payload: ProgressApply) -> dict:
    # A stable application lock order makes overlapping selections safe.
    selections = {item.application_id: item for item in payload.items}
    if len(selections) != len(payload.items):
        raise HTTPException(422, "不能重复选择同一投递")
    applications = {}
    for application_id in sorted(selections):
        application = db.scalar(select(Application).where(Application.id == application_id).with_for_update(key_share=True).execution_options(populate_existing=True))
        if application is None:
            raise HTTPException(409, "投递已变化，请重新检查进度")
        applications[application_id] = application
    for application_id, selection in sorted(selections.items()):
        application = applications[application_id]
        previous = db.scalar(select(ApplicationStageChange).where(
            ApplicationStageChange.reconciliation_token == selection.token,
            ApplicationStageChange.application_id == application_id,
        ))
        if previous:
            continue
        candidate = progress_candidate(db, application, lock=True)
        if candidate is None or candidate["token"] != selection.token:
            raise HTTPException(409, "投递或日程已变化，请重新检查进度")
        evidence = next(n for n in candidate["evidence"] if n["node_type"] == candidate["suggested_status"])
        change_stage(db, application, candidate["suggested_status"], "历史校正", evidence["id"], selection.token)
    db.commit()
    return {"applied_ids": sorted(selections)}


def stage_history(db: Session, application_id: int) -> dict:
    if db.get(Application, application_id) is None:
        raise HTTPException(404, "投递记录不存在")
    items = db.scalars(select(ApplicationStageChange).where(ApplicationStageChange.application_id == application_id).order_by(ApplicationStageChange.id.desc())).all()
    return {"items": [{"id": item.id, "from_status": item.from_status, "to_status": item.to_status,
                       "source": item.source, "timeline_node_id": item.timeline_node_id,
                       "created_at": item.created_at} for item in items]}
