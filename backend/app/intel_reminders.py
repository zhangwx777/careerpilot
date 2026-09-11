import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intel_schemas import IntelInsight, IntelPayload, IntelQuestion, PreparationItem, SourceRecord
from app.models import Application, InterviewIntel, Position, TimelineNode

INTERVIEW_NODE_TYPES = ("AI面", "一面", "二面", "三面", "HR面")
REMINDER_SOURCE_PREFIX = "面经准备:"


def reminder_start(interview_at: datetime, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    planned = interview_at - timedelta(days=1)
    return planned if planned > current else current


def _detail(payload: IntelPayload, interview_id: int) -> str:
    questions = sorted(payload.questions, key=lambda item: len(item.source_ids), reverse=True)[:5]
    preparation = sorted(payload.preparation_items, key=lambda item: item.priority)[:5]
    return json.dumps(
        {
            "interview_node_id": interview_id,
            "questions": [item.model_dump(mode="json") for item in questions],
            "preparation_items": [item.model_dump(mode="json") for item in preparation],
        },
        ensure_ascii=False,
    )


def cached_intel_payload(position: Position) -> IntelPayload | None:
    cached = IntelInsight.model_validate(position.intel_insight or {})
    if cached.status != "已生成":
        return None
    return IntelPayload(
        questions=[
            IntelQuestion(
                question=item.question,
                category=item.category,
                round_type=item.round_type,
                answer_outline=item.reason,
                source_ids=item.source_ids,
            )
            for item in cached.core_questions
        ],
        preparation_items=[
            PreparationItem(
                title=item.title,
                detail=item.detail,
                priority=item.priority,
                source_ids=item.source_ids,
            )
            for item in cached.preparation_items
        ],
    )


def sync_intel_reminder(db: Session, application_id: int, payload: IntelPayload) -> TimelineNode | None:
    application = db.get(Application, application_id)
    if application is None:
        return None
    now = datetime.now(timezone.utc)
    interview = db.scalar(
        select(TimelineNode)
        .join(TimelineNode.application)
        .where(
            Application.position_id == application.position_id,
            TimelineNode.node_type.in_(INTERVIEW_NODE_TYPES),
            TimelineNode.status == "待处理",
            TimelineNode.time_mode == "固定时间",
            TimelineNode.scheduled_at.is_not(None),
            TimelineNode.scheduled_at > now,
        )
        .order_by(TimelineNode.scheduled_at.asc(), TimelineNode.id.asc())
    )
    if interview is None or interview.scheduled_at is None:
        stale = db.scalars(
            select(TimelineNode)
            .join(TimelineNode.application)
            .where(
                Application.position_id == application.position_id,
                TimelineNode.source.like(f"{REMINDER_SOURCE_PREFIX}%"),
                TimelineNode.status == "待处理",
            )
        ).all()
        for item in stale:
            item.status = "已取消"
        return None
    source = f"{REMINDER_SOURCE_PREFIX}{interview.id}"
    reminder = db.scalar(
        select(TimelineNode).where(
            TimelineNode.application_id == interview.application_id,
            TimelineNode.source == source,
        )
    )
    start = reminder_start(interview.scheduled_at, now)
    if reminder is None:
        reminder = TimelineNode(
            application_id=interview.application_id,
            node_type="其他",
            scheduled_at=start,
            ends_at=start + timedelta(hours=1),
            time_mode="固定时间",
            status="待处理",
            source=source,
            title="面经准备",
            detail=_detail(payload, interview.id),
        )
        db.add(reminder)
    else:
        reminder.scheduled_at = start
        reminder.ends_at = start + timedelta(hours=1)
        reminder.detail = _detail(payload, interview.id)
        reminder.status = "待处理"
    return reminder


def sync_intel_reminder_for_application(db: Session, application_id: int) -> TimelineNode | None:
    application = db.get(Application, application_id)
    if application is None:
        return None
    payload = cached_intel_payload(application.position)
    if payload is not None:
        return sync_intel_reminder(db, application_id, payload)
    intels = db.scalars(
        select(InterviewIntel).join(InterviewIntel.application).where(
            Application.position_id == application.position_id
        )
    ).all()
    if not intels:
        return None
    from app.intel_graph import _merge

    payload = _merge(
        [IntelPayload.model_validate(item.payload) for item in intels],
        [SourceRecord.model_validate(source) for item in intels for source in item.sources],
    )
    return sync_intel_reminder(db, application_id, payload)
