from datetime import date, datetime, time, timedelta
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.anysearch import AnySearchError, search
from app.models import Application, DailyBriefing, Position, PreparationTask, ReportedSource, TimelineNode
from app.timeline import alert_types, conflict_map

SHANGHAI = ZoneInfo("Asia/Shanghai")
MAX_SEARCH_APPLICATIONS = 10
logger = logging.getLogger(__name__)


def run_daily_briefing(db: Session, now: datetime, search_fn=search) -> DailyBriefing:
    local_now = now.astimezone(SHANGHAI)
    briefing_date = local_now.date()
    existing = db.scalar(select(DailyBriefing).where(DailyBriefing.briefing_date == briefing_date))
    if existing is not None:
        return existing

    nodes = list(
        db.scalars(
            select(TimelineNode).where(
                TimelineNode.status == "待处理",
                TimelineNode.scheduled_at.is_not(None),
            )
        ).all()
    )
    conflicts = conflict_map(nodes, nodes)
    alerts = [
        {
            "timeline_node_id": node.id,
            "title": node.title or node.node_type,
            "scheduled_at": node.scheduled_at.isoformat(),
            "alert_types": alert_types(node, conflicts.get(node.id, []), now),
        }
        for node in nodes
        if alert_types(node, conflicts.get(node.id, []), now)
    ]
    day_start = datetime.combine(briefing_date, time.min, SHANGHAI)
    day_end = day_start + timedelta(days=1)
    tasks = [
        {
            "task_id": task.id,
            "title": task.title,
            "scheduled_at": task.scheduled_at.isoformat(),
            "ends_at": task.ends_at.isoformat(),
            "application_id": task.application_id,
        }
        for task in db.scalars(
            select(PreparationTask).where(
                PreparationTask.status == "待处理",
                PreparationTask.scheduled_at >= day_start,
                PreparationTask.scheduled_at < day_end,
            )
        ).all()
    ]
    applications = list(
        db.scalars(
            select(Application)
            .join(Application.position)
            .options(joinedload(Application.position).joinedload(Position.company))
            .where(Application.status.not_in(["offer", "挂"]))
        ).all()
    )
    known_urls = set(db.scalars(select(ReportedSource.url)).all())
    new_sources = []
    search_errors = []
    searched_position_ids = set()
    for application in applications:
        if application.position_id in searched_position_ids:
            continue
        if len(searched_position_ids) >= MAX_SEARCH_APPLICATIONS:
            break
        searched_position_ids.add(application.position_id)
        query = f"{application.position.company.name} {application.position.title} 面经"
        try:
            results = search_fn(query)
        except AnySearchError:
            logger.exception("每日简报搜索岗位 %s 失败", application.position_id)
            search_errors.append({"application_id": application.id, "message": "公开面经搜索暂时失败"})
            continue
        for result in results:
            url = result.get("url")
            if not url or url in known_urls:
                continue
            known_urls.add(url)
            new_sources.append(
                {
                    "application_id": application.id,
                    "title": result.get("title") or url,
                    "url": url,
                }
            )
    briefing = DailyBriefing(
        briefing_date=briefing_date,
        payload={"alerts": alerts, "today_tasks": tasks, "new_sources": new_sources, "search_errors": search_errors},
    )
    db.add(briefing)
    db.flush()
    for source in new_sources:
        db.add(
            ReportedSource(
                briefing_id=briefing.id,
                application_id=source["application_id"],
                url=source["url"],
                title=source["title"],
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(DailyBriefing).where(DailyBriefing.briefing_date == briefing_date))
    db.refresh(briefing)
    return briefing
