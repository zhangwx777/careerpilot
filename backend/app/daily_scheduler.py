import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.daily_briefing import run_daily_briefing
from app.db import SessionLocal

SHANGHAI = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


def _run_once() -> None:
    with SessionLocal() as db:
        run_daily_briefing(db, datetime.now(timezone.utc))


async def daily_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(_run_once)
        except Exception:
            logger.exception("每日巡检执行失败")
        now = datetime.now(SHANGHAI)
        next_run = datetime.combine(now.date(), time(9), SHANGHAI)
        if now >= next_run:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
