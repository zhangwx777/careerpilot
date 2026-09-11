import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from sqlalchemy import text

from app.api import router
from app.db import engine
from app.phase3_api import router as phase3_router
from app.intel_api import router as intel_router
from app.planner_api import router as planner_router
from app.briefing_api import router as briefing_router
from app.daily_scheduler import daily_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(daily_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

app = FastAPI(title="求职作战台", lifespan=lifespan)
app.include_router(router)
app.include_router(phase3_router)
app.include_router(intel_router)
app.include_router(planner_router)
app.include_router(briefing_router)


@app.get("/health")
def health():
    """健康检查：确认服务活着且能连库。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        logger.exception("健康检查数据库连接失败")
        return {"status": "error", "db": False, "detail": "数据库连接失败"}
    return {"status": "ok", "db": db_ok}
