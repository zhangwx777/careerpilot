from datetime import datetime, timezone
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.application_records import materialize_position
from app.db import SessionLocal, get_db
from app.models import (
    APPLICATION_STATUS,
    Application,
    Company,
    ParseSession,
    Position,
    PreparationTask,
    TimelineNode,
)
from app.intel_reminders import INTERVIEW_NODE_TYPES, sync_intel_reminder_for_application
from app.llm.config_store import LlmConfigError, resolve_provider, snapshot_for
from app.llm.prompts import NOTICE_PROMPT_VERSION
from app.parse_graph import ParseGraphStateError, resume_parse_graph, start_parse_graph
from app.parsing import NoticeParseError
from app.schemas import ApplicationRead
from app.phase3_schemas import (
    DashboardActionRead,
    DashboardActionsRead,
    DashboardRead,
    ParseConfirmation,
    NoticeApplicationCreate,
    ParseSessionCreate,
    ParseSessionDetail,
    ParseSessionPage,
    ParseSessionStatus,
    PipelineBucket,
    TimelineNodeRead,
    TimelinePage,
    TimelineStatusTransition,
    NodeStatus,
)
from app.timeline import alert_types, conflict_map

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
logger = logging.getLogger(__name__)


def _get_parse_session(db: Session, parse_session_id: int) -> ParseSession:
    parse_session = db.get(ParseSession, parse_session_id)
    if parse_session is None:
        raise HTTPException(status_code=404, detail="解析会话不存在")
    return parse_session


def _recommend_applications(
    db: Session, parse_session: ParseSession
) -> list[Application]:
    extraction = parse_session.extracted_payload or {}
    company_name = extraction.get("company_name")
    position_title = extraction.get("position_title")
    if not company_name or not position_title:
        return []
    return list(
        db.scalars(
            select(Application)
            .join(Application.position)
            .join(Position.company)
            .options(joinedload(Application.position).joinedload(Position.company))
            .where(
                Company.name == company_name,
                Position.title == position_title,
            )
            .order_by(Application.created_at.desc(), Application.id.desc())
        ).all()
    )


def _session_detail(
    db: Session,
    parse_session: ParseSession,
    recommended_applications: list[Application] | None = None,
) -> ParseSessionDetail:
    data = {
        column.name: getattr(parse_session, column.name)
        for column in ParseSession.__table__.columns
    }
    data["recommended_applications"] = (
        _recommend_applications(db, parse_session)
        if recommended_applications is None
        else recommended_applications
    )
    return ParseSessionDetail.model_validate(data)


def _run_parse_session(
    parse_session_id: int,
    thread_id: str,
    raw_text: str,
    provider: str,
    requested_at: datetime,
) -> None:
    try:
        result = start_parse_graph(
            parse_session_id,
            thread_id,
            raw_text,
            requested_at,
            provider,
            settings.database_url,
            SessionLocal,
        )
        if "__interrupt__" not in result:
            raise ParseGraphStateError("解析图未停在人工确认节点")
    except Exception as exc:
        logger.exception("解析会话 %s 后台任务失败", parse_session_id)
        error_message = (
            str(exc)
            if isinstance(exc, NoticeParseError)
            else "解析失败，请检查通知内容或稍后重试"
        )
        with SessionLocal() as task_db:
            parse_session = task_db.get(ParseSession, parse_session_id)
            if parse_session is not None and parse_session.status == "解析中":
                parse_session.status = "解析失败"
                parse_session.error_message = error_message
                parse_session.resolved_at = datetime.now(timezone.utc)
                task_db.commit()


@router.post(
    "/parse-sessions",
    response_model=ParseSessionDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_parse_session(
    payload: ParseSessionCreate, background_tasks: BackgroundTasks, db: DbSession
):
    try:
        provider = resolve_provider(db, payload.provider)
        llm_snapshot = snapshot_for(db, provider)
    except LlmConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    parse_session = ParseSession(
        raw_text=payload.raw_text,
        provider=provider,
        llm_snapshot=llm_snapshot,
        prompt_version=NOTICE_PROMPT_VERSION,
        status="解析中",
    )
    db.add(parse_session)
    db.commit()
    db.refresh(parse_session)

    background_tasks.add_task(
        _run_parse_session,
        parse_session.id,
        str(parse_session.thread_id),
        parse_session.raw_text,
        parse_session.provider,
        datetime.now(timezone.utc),
    )
    return _session_detail(db, _get_parse_session(db, parse_session.id))


@router.get("/parse-sessions", response_model=ParseSessionPage)
def list_parse_sessions(
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 20,
    parse_status: ParseSessionStatus | None = Query(default=None, alias="status"),
):
    filters = []
    if parse_status is not None:
        filters.append(ParseSession.status == parse_status)
    total = (
        db.scalar(select(func.count()).select_from(ParseSession).where(*filters)) or 0
    )
    sessions = list(db.scalars(
        select(ParseSession)
        .where(*filters)
        .order_by(ParseSession.created_at.desc(), ParseSession.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all())
    pairs = {
        (payload.get("company_name"), payload.get("position_title"))
        for item in sessions
        if (payload := item.extracted_payload or {}).get("company_name")
        and payload.get("position_title")
    }
    recommendations: dict[tuple[str, str], list[Application]] = {}
    if pairs:
        applications = db.scalars(
            select(Application)
            .join(Application.position)
            .join(Position.company)
            .options(joinedload(Application.position).joinedload(Position.company))
            .where(or_(*(
                (Company.name == company_name) & (Position.title == position_title)
                for company_name, position_title in pairs
            )))
            .order_by(Application.created_at.desc(), Application.id.desc())
        ).all()
        for application in applications:
            key = (application.position.company.name, application.position.title)
            recommendations.setdefault(key, []).append(application)
    return ParseSessionPage(
        items=[
            _session_detail(
                db,
                item,
                recommendations.get(
                    (
                        (item.extracted_payload or {}).get("company_name"),
                        (item.extracted_payload or {}).get("position_title"),
                    ),
                    [],
                ),
            )
            for item in sessions
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/parse-sessions/{parse_session_id}", response_model=ParseSessionDetail)
def get_parse_session(parse_session_id: int, db: DbSession):
    return _session_detail(db, _get_parse_session(db, parse_session_id))


@router.post(
    "/parse-sessions/{parse_session_id}/application",
    response_model=ApplicationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_application_from_notice(
    parse_session_id: int, payload: NoticeApplicationCreate, db: DbSession
):
    parse_session = _get_parse_session(db, parse_session_id)
    if parse_session.status != "待确认":
        raise HTTPException(status_code=409, detail="当前解析会话不能创建投递")

    position = materialize_position(db, payload.company_name, payload.position_title)
    application = Application(
        position_id=position.id,
        status="已投递",
        applied_at=parse_session.created_at,
    )
    db.add(application)
    db.flush()
    application_id = application.id
    db.commit()
    return db.scalar(
        select(Application)
        .options(joinedload(Application.position).joinedload(Position.company))
        .where(Application.id == application_id)
    )


@router.post(
    "/parse-sessions/{parse_session_id}/confirm",
    response_model=ParseSessionDetail,
)
def confirm_parse_session(
    parse_session_id: int, payload: ParseConfirmation, db: DbSession
):
    parse_session = _get_parse_session(db, parse_session_id)
    if parse_session.status == "已确认":
        return _session_detail(db, parse_session)
    if parse_session.status == "已丢弃":
        raise HTTPException(status_code=409, detail="已丢弃的解析会话不能确认")
    if parse_session.status != "待确认":
        raise HTTPException(status_code=409, detail="当前解析会话不能确认")
    if db.get(Application, payload.application_id) is None:
        raise HTTPException(status_code=404, detail="投递记录不存在")

    try:
        resume_parse_graph(
            str(parse_session.thread_id),
            payload,
            settings.database_url,
            SessionLocal,
        )
    except ParseGraphStateError:
        logger.exception("解析会话 %s 确认失败", parse_session_id)
        raise HTTPException(status_code=409, detail="解析确认失败，请稍后重试") from None

    db.expire_all()
    return _session_detail(db, _get_parse_session(db, parse_session_id))


@router.post(
    "/parse-sessions/{parse_session_id}/discard",
    response_model=ParseSessionDetail,
)
def discard_parse_session(parse_session_id: int, db: DbSession):
    parse_session = db.scalar(
        select(ParseSession)
        .where(ParseSession.id == parse_session_id)
        .with_for_update()
    )
    if parse_session is None:
        raise HTTPException(status_code=404, detail="解析会话不存在")
    if parse_session.status == "已丢弃":
        return _session_detail(db, parse_session)
    if parse_session.status == "已确认":
        raise HTTPException(status_code=409, detail="已确认的解析会话不能丢弃")
    if parse_session.status != "待确认":
        raise HTTPException(status_code=409, detail="当前解析会话不能丢弃")

    parse_session.status = "已丢弃"
    parse_session.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(parse_session)
    return _session_detail(db, parse_session)


def _validate_timeline_range(
    start_at: datetime | None, end_at: datetime | None
) -> None:
    for name, value in (("start", start_at), ("end", end_at)):
        if value is not None and value.utcoffset() is None:
            raise HTTPException(status_code=422, detail=f"{name} 必须包含时区")
    if start_at is not None and end_at is not None and end_at <= start_at:
        raise HTTPException(status_code=422, detail="end 必须晚于 start")


def _conflict_candidates(
    db: Session, target_nodes: list[TimelineNode]
) -> list[TimelineNode]:
    collision_targets = [
        node
        for node in target_nodes
        if node.status == "待处理"
        and node.node_type in {"笔试", "AI面", "一面", "二面", "三面", "HR面"}
        and node.scheduled_at is not None
    ]
    if not collision_targets:
        return []
    window_start = min(node.scheduled_at for node in collision_targets)
    window_end = max(node.ends_at or node.scheduled_at for node in collision_targets)
    return list(
        db.scalars(
            select(TimelineNode).where(
                TimelineNode.status == "待处理",
                TimelineNode.time_mode == "固定时间",
                TimelineNode.node_type.in_(
                    ["笔试", "AI面", "一面", "二面", "三面", "HR面"]
                ),
                TimelineNode.scheduled_at.is_not(None),
                TimelineNode.scheduled_at <= window_end,
                or_(
                    TimelineNode.ends_at.is_(None),
                    TimelineNode.ends_at >= window_start,
                ),
            )
        ).all()
    )


def _timeline_read(
    node: TimelineNode,
    conflicts: dict[int, list[int]],
    now: datetime,
) -> TimelineNodeRead:
    conflict_ids = conflicts.get(node.id, [])
    data = {column.name: getattr(node, column.name) for column in TimelineNode.__table__.columns}
    data.update(
        {
            "application": node.application,
            "alert_types": alert_types(node, conflict_ids, now),
            "conflict_node_ids": conflict_ids,
        }
    )
    return TimelineNodeRead.model_validate(data)


@router.get("/timeline", response_model=TimelinePage)
def list_timeline(
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 20,
    start_at: datetime | None = Query(default=None, alias="start"),
    end_at: datetime | None = Query(default=None, alias="end"),
    node_status: NodeStatus | None = Query(default=None, alias="status"),
):
    _validate_timeline_range(start_at, end_at)
    filters = []
    if start_at is not None:
        filters.append(TimelineNode.scheduled_at >= start_at)
    if end_at is not None:
        filters.append(TimelineNode.scheduled_at < end_at)
    if node_status is not None:
        filters.append(TimelineNode.status == node_status)

    total = (
        db.scalar(select(func.count()).select_from(TimelineNode).where(*filters)) or 0
    )
    nodes = list(
        db.scalars(
            select(TimelineNode)
            .options(
                joinedload(TimelineNode.application)
                .joinedload(Application.position)
                .joinedload(Position.company)
            )
            .where(*filters)
            .order_by(
                TimelineNode.scheduled_at.asc().nulls_last(), TimelineNode.id.asc()
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    conflicts = conflict_map(nodes, _conflict_candidates(db, nodes))
    now = datetime.now(timezone.utc)
    return TimelinePage(
        items=[_timeline_read(node, conflicts, now) for node in nodes],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/dashboard", response_model=DashboardRead)
def get_dashboard(db: DbSession):
    """作战总览：各阶段投递数 + 需要关注（临期/逾期/冲突）的待处理节点。"""
    counts = dict(
        db.execute(
            select(Application.status, func.count()).group_by(Application.status)
        ).all()
    )
    total_applications = sum(counts.values())
    pipeline = [
        PipelineBucket(
            status=application_status,
            count=total_applications if application_status == "已投递" else counts.get(application_status, 0),
        )
        for application_status in APPLICATION_STATUS
    ]

    nodes = list(
        db.scalars(
            select(TimelineNode)
            .options(
                joinedload(TimelineNode.application)
                .joinedload(Application.position)
                .joinedload(Position.company)
            )
            .where(TimelineNode.status == "待处理")
            .order_by(
                TimelineNode.scheduled_at.asc().nulls_last(), TimelineNode.id.asc()
            )
        ).all()
    )
    conflicts = conflict_map(nodes, _conflict_candidates(db, nodes))
    now = datetime.now(timezone.utc)
    reads = [_timeline_read(node, conflicts, now) for node in nodes]
    attention = [read for read in reads if read.alert_types]
    visible_tasks = list(
        db.scalars(
            select(PreparationTask)
            .options(
                joinedload(PreparationTask.application)
                .joinedload(Application.position)
                .joinedload(Position.company)
            )
            .where(
                PreparationTask.status == "待处理",
                (PreparationTask.deferred_until.is_(None))
                | (PreparationTask.deferred_until <= now),
            )
            .order_by(
                PreparationTask.priority.asc(),
                PreparationTask.scheduled_at.asc().nulls_last(),
                PreparationTask.created_at.asc(),
                PreparationTask.id.asc(),
            )
        ).all()
    )
    today_actions = DashboardActionsRead(
        items=[
            DashboardActionRead(
                task_id=task.id,
                planner_session_id=task.planner_session_id,
                application_id=task.application_id,
                company_name=task.application.position.company.name,
                position_title=task.application.position.title,
                title=task.title,
                detail=task.detail,
                priority=task.priority,
                status=task.status,
                estimated_minutes=task.estimated_minutes,
                scheduled_at=task.scheduled_at,
                deferred_until=task.deferred_until,
                source_ids=task.source_ids or [],
            )
            for task in visible_tasks[:5]
        ],
        total=len(visible_tasks),
        pending_count=len(visible_tasks),
    )
    return DashboardRead(
        pipeline=pipeline,
        attention=attention,
        today_actions=today_actions,
    )


@router.patch("/timeline/{timeline_node_id}/status", response_model=TimelineNodeRead)
def update_timeline_status(
    timeline_node_id: int, payload: TimelineStatusTransition, db: DbSession
):
    node = db.scalar(
        select(TimelineNode)
        .options(
            joinedload(TimelineNode.application)
            .joinedload(Application.position)
            .joinedload(Position.company)
        )
        .where(TimelineNode.id == timeline_node_id)
    )
    if node is None:
        raise HTTPException(status_code=404, detail="时间线节点不存在")
    node.status = payload.status
    if node.node_type in INTERVIEW_NODE_TYPES:
        sync_intel_reminder_for_application(db, node.application_id)
    db.commit()
    db.refresh(node)
    candidates = _conflict_candidates(db, [node])
    conflicts = conflict_map([node], candidates)
    return _timeline_read(node, conflicts, datetime.now(timezone.utc))
