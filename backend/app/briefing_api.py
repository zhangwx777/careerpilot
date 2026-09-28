from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.briefing_schemas import DailyBriefingPage, DailyBriefingRead
from app.daily_briefing import retry_briefing_analysis, run_daily_briefing
from app.db import get_db
from app.models import DailyBriefing

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.post("/daily-briefings/run", response_model=DailyBriefingRead)
def run_briefing(db: DbSession):
    return run_daily_briefing(db, datetime.now(timezone.utc))


@router.get("/daily-briefings", response_model=DailyBriefingPage)
def list_briefings(db: DbSession, page: Page = 1, page_size: PageSize = 20, briefing_date: date | None = None):
    query = select(DailyBriefing)
    if briefing_date is not None:
        query = query.where(DailyBriefing.briefing_date == briefing_date)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(
            query
            .order_by(DailyBriefing.briefing_date.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return DailyBriefingPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/daily-briefings/{briefing_id}", response_model=DailyBriefingRead)
def get_briefing(briefing_id: int, db: DbSession):
    item = db.get(DailyBriefing, briefing_id)
    if item is None:
        raise HTTPException(404, "每日简报不存在")
    return item


@router.post("/daily-briefings/{briefing_id}/analyze", response_model=DailyBriefingRead)
def analyze_briefing(briefing_id: int, db: DbSession):
    item = db.get(DailyBriefing, briefing_id)
    if item is None:
        raise HTTPException(404, "每日简报不存在")
    return retry_briefing_analysis(db, item)
