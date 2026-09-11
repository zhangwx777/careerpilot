from datetime import datetime, timezone
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.db import SessionLocal, get_db
from app.models import Application, InterviewIntel, PlannerSession, Position, PreparationTask, ResumeProfile, TimelineNode
from app.planner_graph import PlannerGraphError, resume_planner_graph, start_planner_graph
from app.planner_parsing import extract_plan
from app.resume_extract import ResumeExtractError, extract_resume
from app.planner_schemas import (
    PlannerConfirmation,
    PlannerSessionCreate,
    PlannerSessionRead,
    PlannerSessionStatus,
    PreparationTaskPage,
    PreparationTaskRead,
    PreparationTaskStatus,
    PreparationTaskStatusUpdate,
    ResumeProfileRead,
    ResumeProfileUpdate,
)

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
logger = logging.getLogger(__name__)


def _get_session(db: Session, planner_session_id: int) -> PlannerSession:
    item = db.scalar(
        select(PlannerSession)
        .options(joinedload(PlannerSession.application).joinedload(Application.position).joinedload(Position.company))
        .where(PlannerSession.id == planner_session_id)
    )
    if item is None:
        raise HTTPException(404, "备战计划会话不存在")
    return item


def _session_read(item: PlannerSession) -> PlannerSessionRead:
    data = {column.name: getattr(item, column.name) for column in PlannerSession.__table__.columns}
    data["application"] = item.application
    return PlannerSessionRead.model_validate(data)


def _run_planner_session(session_id: int, thread_id: str) -> None:
    try:
        with SessionLocal() as task_db:
            item = task_db.get(PlannerSession, session_id)
            if item is None:
                raise PlannerGraphError("备战计划会话不存在")
            if not item.available_windows:
                draft = extract_plan(
                    item.resume_snapshot,
                    item.jd_snapshot,
                    item.intel_snapshot,
                    item.provider,
                )
                item.draft_payload = draft.model_dump(mode="json")
                item.status = "已完成"
                item.resolved_at = datetime.now(timezone.utc)
                task_db.commit()
                return
        result = start_planner_graph(session_id, thread_id, settings.database_url, SessionLocal)
        if "__interrupt__" not in result:
            raise PlannerGraphError("备战计划图未停在确认节点")
    except Exception:
        logger.exception("备战计划会话 %s 后台任务失败", session_id)
        with SessionLocal() as task_db:
            item = task_db.get(PlannerSession, session_id)
            if item is not None and item.status == "生成中":
                item.status = "失败"
                item.error_message = "备战分析失败，请稍后重试"
                item.resolved_at = datetime.now(timezone.utc)
                task_db.commit()


@router.get("/resume-profile", response_model=ResumeProfileRead)
def get_resume_profile(db: DbSession):
    item = db.get(ResumeProfile, 1)
    if item is None:
        raise HTTPException(404, "请先保存简历")
    return item


@router.put("/resume-profile", response_model=ResumeProfileRead)
def save_resume_profile(payload: ResumeProfileUpdate, db: DbSession):
    item = db.get(ResumeProfile, 1)
    if item is None:
        item = ResumeProfile(id=1, resume_text=payload.resume_text, file_name=None)
        db.add(item)
    else:
        item.resume_text = payload.resume_text
    db.commit()
    db.refresh(item)
    return item


@router.post("/resume-profile/upload", response_model=ResumeProfileRead)
def upload_resume_profile(db: DbSession, file: UploadFile = File(...)):
    content = file.file.read()
    try:
        resume_text = extract_resume(file.filename, content)
    except (ResumeExtractError, ImportError, ValueError) as exc:
        logger.exception("简历文件读取失败")
        raise HTTPException(status_code=422, detail="无法读取简历文件，请检查文件内容或稍后重试") from exc
    item = db.get(ResumeProfile, 1)
    if item is None:
        item = ResumeProfile(id=1, resume_text=resume_text, file_name=file.filename)
        db.add(item)
    else:
        item.resume_text = resume_text
        item.file_name = file.filename
    db.commit()
    db.refresh(item)
    return item


@router.post("/planner-sessions", response_model=PlannerSessionRead, status_code=status.HTTP_201_CREATED)
def create_planner_session(
    payload: PlannerSessionCreate, background_tasks: BackgroundTasks, db: DbSession
):
    application = db.scalar(
        select(Application)
        .options(joinedload(Application.position).joinedload(Position.company))
        .where(Application.id == payload.application_id)
    )
    if application is None:
        raise HTTPException(404, "投递记录不存在")
    resume = db.get(ResumeProfile, 1)
    if resume is None:
        raise HTTPException(422, "请先保存简历")
    jd_text = (application.position.jd_text or "").strip()
    if not jd_text:
        raise HTTPException(422, "目标岗位缺少 JD")
    intel_snapshot = [
        {"id": intel.id, "payload": intel.payload, "confidence": intel.confidence}
        for intel in db.scalars(
            select(InterviewIntel)
            .where(InterviewIntel.application_id == application.id)
            .order_by(InterviewIntel.created_at.desc())
            .limit(3)
        ).all()
    ]
    item = PlannerSession(
        application_id=application.id,
        provider=payload.provider,
        resume_snapshot=resume.resume_text,
        jd_snapshot=jd_text,
        intel_snapshot=intel_snapshot,
        available_windows=[],
        status="生成中",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    background_tasks.add_task(_run_planner_session, item.id, str(item.thread_id))
    return _session_read(item)


@router.get("/planner-sessions", response_model=list[PlannerSessionRead])
def list_planner_sessions(db: DbSession, session_status: str | None = Query(default=None, alias="status")):
    statuses = {session_status} if session_status else {"生成中", "待确认"}
    items = db.scalars(
        select(PlannerSession)
        .options(joinedload(PlannerSession.application).joinedload(Application.position).joinedload(Position.company))
        .where(PlannerSession.status.in_(statuses))
        .order_by(PlannerSession.created_at.desc(), PlannerSession.id.desc())
    ).all()
    return [_session_read(item) for item in items]


@router.get("/planner-sessions/{planner_session_id}", response_model=PlannerSessionRead)
def get_planner_session(planner_session_id: int, db: DbSession):
    return _session_read(_get_session(db, planner_session_id))


@router.post("/planner-sessions/{planner_session_id}/confirm", response_model=PlannerSessionRead)
def confirm_planner_session(planner_session_id: int, payload: PlannerConfirmation, db: DbSession):
    item = _get_session(db, planner_session_id)
    if item.status == "已确认":
        return _session_read(item)
    if item.status == "已丢弃":
        raise HTTPException(409, "已丢弃的备战计划不能确认")
    if item.status != "待确认":
        raise HTTPException(409, "当前备战计划不能确认")
    try:
        resume_planner_graph(str(item.thread_id), payload, settings.database_url, SessionLocal)
    except (PlannerGraphError, ValueError):
        logger.exception("备战计划会话 %s 确认失败", planner_session_id)
        raise HTTPException(409, "计划确认失败，请稍后重试") from None
    db.expire_all()
    return _session_read(_get_session(db, planner_session_id))


@router.post("/planner-sessions/{planner_session_id}/discard", response_model=PlannerSessionRead)
def discard_planner_session(planner_session_id: int, db: DbSession):
    item = _get_session(db, planner_session_id)
    if item.status == "已丢弃":
        return _session_read(item)
    if item.status == "已确认":
        raise HTTPException(409, "已确认的备战计划不能丢弃")
    if item.status != "待确认":
        raise HTTPException(409, "当前备战计划不能丢弃")
    item.status = "已丢弃"
    item.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return _session_read(_get_session(db, planner_session_id))


@router.get("/preparation-tasks", response_model=PreparationTaskPage)
def list_preparation_tasks(
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 20,
    application_id: int | None = Query(default=None, gt=0),
    task_status: PreparationTaskStatus | None = Query(default=None, alias="status"),
):
    filters = []
    if application_id is not None:
        filters.append(PreparationTask.application_id == application_id)
    if task_status is not None:
        filters.append(PreparationTask.status == task_status)
    total = db.scalar(select(func.count()).select_from(PreparationTask).where(*filters)) or 0
    items = list(
        db.scalars(
            select(PreparationTask)
            .where(*filters)
            .order_by(PreparationTask.scheduled_at.asc(), PreparationTask.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return PreparationTaskPage(items=items, total=total, page=page, page_size=page_size)


@router.patch("/preparation-tasks/{task_id}/status", response_model=PreparationTaskRead)
def update_preparation_task_status(task_id: int, payload: PreparationTaskStatusUpdate, db: DbSession):
    task = db.get(PreparationTask, task_id)
    if task is None:
        raise HTTPException(404, "备战任务不存在")
    task.status = payload.status
    if task.timeline_node_id is not None:
        node = db.get(TimelineNode, task.timeline_node_id)
        if node is not None:
            node.status = {"待处理": "待处理", "已完成": "已完成", "已跳过": "已取消"}[payload.status]
    db.commit()
    db.refresh(task)
    return task
