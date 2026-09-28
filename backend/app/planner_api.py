from datetime import datetime, timezone
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.db import SessionLocal, get_db
from app.models import Application, InterviewIntel, PlannerSession, Position, PreparationTask, ResumeProfile, TimelineNode
from app.planner_graph import PlannerGraphError, resume_planner_graph, start_planner_graph
from app.planner_parsing import extract_plan
from app.resume_extract import ResumeExtractError, extract_resume
from app.llm.config_store import LlmConfigError, config_from_snapshot, resolve_role_provider, snapshot_for
from app.llm.prompts import PLANNER_ACTION_PROMPT_VERSION
from app.planner_schemas import (
    PlannerConfirmation,
    PlannerAction,
    PlannerActionSelection,
    PlannerSessionCreate,
    PlannerSessionRead,
    PlannerSessionStatus,
    PreparationReview,
    PreparationTaskPage,
    PreparationTaskRead,
    PreparationTaskStatus,
    PreparationTaskStatusUpdate,
    ResumeProfileRead,
    ResumeProfileUpdate,
)
from app.planner_coach import generate_preparation_answer, review_preparation_answer as run_review_preparation_answer
from app.task_queue import TaskQueueUnavailable, enqueue, run_planner_session_task, rebuild_insight_task

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
logger = logging.getLogger(__name__)


def materialize_planner_actions(
    db: Session, item: PlannerSession, action_indexes: list[int] | None = None
) -> int:
    """Persist only the selected planner actions, idempotently."""

    actions = (item.draft_payload or {}).get("actions")
    if not isinstance(actions, list):
        return 0
    if action_indexes is None:
        action_indexes = list(range(len(actions)))
    existing = set(
        db.scalars(
            select(PreparationTask.action_index).where(
                PreparationTask.planner_session_id == item.id,
                PreparationTask.action_index.is_not(None),
            )
        ).all()
    )
    created = 0
    for action_index in action_indexes:
        raw_action = actions[action_index]
        if action_index in existing:
            continue
        action = PlannerAction.model_validate(raw_action)
        db.add(
            PreparationTask(
                planner_session_id=item.id,
                application_id=item.application_id,
                title=action.title,
                detail=action.detail,
                gap=action.gap,
                category=action.category,
                source_ids=action.source_ids,
                evidence=[item.model_dump(mode="json") for item in action.evidence],
                priority=action.priority,
                action_index=action_index,
                status="待处理",
            )
        )
        created += 1
    return created


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
            if item.status != "生成中":
                return
            if not item.available_windows:
                draft = extract_plan(
                    item.resume_snapshot,
                    item.jd_snapshot,
                    item.intel_snapshot,
                    item.provider,
                    llm_config=config_from_snapshot(item.llm_snapshot, task_db, item.provider),
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


@router.delete("/resume-profile", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume_profile(db: DbSession):
    item = db.get(ResumeProfile, 1)
    if item is not None:
        db.delete(item)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    try:
        provider = resolve_role_provider(db, "planner", payload.provider)
        llm_snapshot = snapshot_for(db, provider)
    except LlmConfigError as exc:
        raise HTTPException(503, str(exc)) from None
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
        provider=provider,
        llm_snapshot=llm_snapshot,
        prompt_version=PLANNER_ACTION_PROMPT_VERSION,
        resume_snapshot=resume.resume_text,
        jd_snapshot=jd_text,
        intel_snapshot=intel_snapshot,
        available_windows=[],
        status="生成中",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    try:
        task = enqueue(run_planner_session_task, item.id, str(item.thread_id))
    except TaskQueueUnavailable as exc:
        item.status = "失败"
        item.error_message = str(exc)
        item.resolved_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(503, str(exc)) from None
    item.queue_task_id = task.id
    db.commit()
    return _session_read(item)


@router.delete("/planner-sessions/{planner_session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_planner_session(planner_session_id: int, db: DbSession):
    item = _get_session(db, planner_session_id)
    if item.status in {"生成中", "待确认"}:
        raise HTTPException(status_code=409, detail="当前备战分析仍在处理中，暂不能删除")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/planner-sessions", response_model=list[PlannerSessionRead])
def list_planner_sessions(db: DbSession, session_status: str | None = Query(default=None, alias="status")):
    statement = (
        select(PlannerSession)
        .options(joinedload(PlannerSession.application).joinedload(Application.position).joinedload(Position.company))
        .order_by(PlannerSession.created_at.desc(), PlannerSession.id.desc())
    )
    if session_status:
        statement = statement.where(PlannerSession.status == session_status)
    items = db.scalars(statement).all()
    return [_session_read(item) for item in items]


@router.get("/planner-sessions/{planner_session_id}", response_model=PlannerSessionRead)
def get_planner_session(planner_session_id: int, db: DbSession):
    return _session_read(_get_session(db, planner_session_id))


@router.post("/planner-sessions/{planner_session_id}/materialize-actions", response_model=PlannerSessionRead)
def materialize_planner_session_actions(
    planner_session_id: int, payload: PlannerActionSelection, db: DbSession
):
    item = _get_session(db, planner_session_id)
    if item.status != "已完成":
        raise HTTPException(status_code=409, detail="只有已完成的备战分析可以生成准备行动")
    actions = (item.draft_payload or {}).get("actions")
    if not isinstance(actions, list) or any(index >= len(actions) for index in payload.action_indexes):
        raise HTTPException(status_code=422, detail="选择的准备行动不存在")
    materialize_planner_actions(db, item, payload.action_indexes)
    db.commit()
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


@router.post("/planner-sessions/{planner_session_id}/retry", response_model=PlannerSessionRead)
def retry_planner_session(planner_session_id: int, db: DbSession):
    item = _get_session(db, planner_session_id)
    if item.status != "失败":
        raise HTTPException(409, "只有失败的备战分析可以重试")
    item.status = "生成中"
    item.error_message = None
    item.resolved_at = None
    item.draft_payload = None
    db.commit()
    try:
        task = enqueue(run_planner_session_task, item.id, str(item.thread_id))
    except TaskQueueUnavailable as exc:
        item.status = "失败"
        item.error_message = str(exc)
        item.resolved_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(503, str(exc)) from None
    item.queue_task_id = task.id
    db.commit()
    return _session_read(_get_session(db, planner_session_id))


@router.get("/preparation-tasks", response_model=PreparationTaskPage)
def list_preparation_tasks(
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 20,
    application_id: int | None = Query(default=None, gt=0),
    task_status: PreparationTaskStatus | None = Query(default=None, alias="status"),
    include_deferred: bool = Query(default=False),
):
    filters = []
    if application_id is not None:
        filters.append(PreparationTask.application_id == application_id)
    if task_status is not None:
        filters.append(PreparationTask.status == task_status)
    if not include_deferred:
        filters.append(
            (PreparationTask.deferred_until.is_(None))
            | (PreparationTask.deferred_until <= datetime.now(timezone.utc))
        )
    total = db.scalar(select(func.count()).select_from(PreparationTask).where(*filters)) or 0
    items = list(
        db.scalars(
            select(PreparationTask)
            .where(*filters)
            .order_by(
                PreparationTask.scheduled_at.asc().nulls_last(),
                PreparationTask.priority.asc(),
                PreparationTask.created_at.asc(),
                PreparationTask.id.asc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return PreparationTaskPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/preparation-tasks/{task_id}", response_model=PreparationTaskRead)
def get_preparation_task(task_id: int, db: DbSession):
    task = db.get(PreparationTask, task_id)
    if task is None:
        raise HTTPException(404, "备战任务不存在")
    return task


@router.patch("/preparation-tasks/{task_id}/status", response_model=PreparationTaskRead)
def update_preparation_task_status(task_id: int, payload: PreparationTaskStatusUpdate, db: DbSession):
    task = db.get(PreparationTask, task_id)
    if task is None:
        raise HTTPException(404, "备战任务不存在")
    if payload.status == "已完成" and not task.feedback_payload:
        raise HTTPException(409, "请先提交自答并完成点评")
    if payload.status is not None:
        task.status = payload.status
    if payload.status is not None and payload.status != "待处理":
        task.deferred_until = None
    elif "deferred_until" in payload.model_fields_set:
        if payload.deferred_until is not None and payload.deferred_until.utcoffset() is None:
            raise HTTPException(422, "延期时间必须包含时区")
        task.deferred_until = payload.deferred_until
    if payload.category is not None:
        task.category = payload.category
    if payload.status is not None and task.timeline_node_id is not None:
        node = db.get(TimelineNode, task.timeline_node_id)
        if node is not None:
            node.status = {"待处理": "待处理", "已完成": "已完成", "已跳过": "已取消"}[payload.status]
    db.commit()
    db.refresh(task)
    return task


@router.delete("/preparation-tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_preparation_task(task_id: int, db: DbSession):
    task = db.get(PreparationTask, task_id)
    if task is None:
        raise HTTPException(404, "备战任务不存在")
    if task.status != "待处理" or task.answer_payload or task.user_answer or task.feedback_payload:
        raise HTTPException(409, "已有学习记录的任务不能移出计划")
    db.delete(task)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/preparation-tasks/{task_id}/answer", response_model=PreparationTaskRead)
def create_preparation_answer(task_id: int, db: DbSession):
    task = db.scalar(
        select(PreparationTask)
        .options(joinedload(PreparationTask.planner_session))
        .where(PreparationTask.id == task_id)
    )
    if task is None:
        raise HTTPException(404, "备战任务不存在")
    try:
        task.answer_payload = generate_preparation_answer(
            task,
            task.planner_session,
            config_from_snapshot(task.planner_session.llm_snapshot, db, task.planner_session.provider),
        ).model_dump(mode="json")
    except Exception as exc:
        logger.exception("备战任务 %s 答案生成失败", task_id)
        raise HTTPException(503, "答案生成失败，请稍后重试") from exc
    db.commit()
    db.refresh(task)
    return task


@router.post("/preparation-tasks/{task_id}/review", response_model=PreparationTaskRead)
def review_preparation_answer(task_id: int, payload: PreparationReview, db: DbSession):
    task = db.scalar(
        select(PreparationTask)
        .options(joinedload(PreparationTask.planner_session))
        .where(PreparationTask.id == task_id)
    )
    if task is None:
        raise HTTPException(404, "备战任务不存在")
    if not task.answer_payload:
        raise HTTPException(409, "请先生成参考答案")
    try:
        feedback = run_review_preparation_answer(
            task,
            task.planner_session,
            payload.user_answer,
            config_from_snapshot(task.planner_session.llm_snapshot, db, task.planner_session.provider),
        )
    except Exception as exc:
        logger.exception("备战任务 %s 自答点评失败", task_id)
        raise HTTPException(503, "自答点评失败，请稍后重试") from exc
    task.user_answer = payload.user_answer
    task.feedback_payload = feedback.model_dump(mode="json")
    task.status = "已完成"
    db.commit()
    db.refresh(task)
    return task
