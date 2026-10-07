import asyncio
import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import router
from app.db import engine
from app.phase3_api import router as phase3_router
from app.intel_api import router as intel_router
from app.planner_api import router as planner_router
from app.briefing_api import router as briefing_router
from app.daily_scheduler import daily_loop
from app.task_queue import queue_available
from app.task_execution import recovery_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(daily_loop())
    recovery = asyncio.create_task(recovery_loop())
    try:
        yield
    finally:
        task.cancel()
        recovery.cancel()
        with suppress(asyncio.CancelledError):
            await task
        with suppress(asyncio.CancelledError):
            await recovery

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
    queue_ok = queue_available()
    return {"status": "ok" if queue_ok else "degraded", "db": db_ok, "queue": queue_ok}


_app_root = (
    Path(os.environ["CAREERPILOT_APP_ROOT"])
    if os.environ.get("CAREERPILOT_APP_ROOT")
    else Path(__file__).resolve().parents[2]
)
_frontend_dir = _app_root / "frontend" / "dist"
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
