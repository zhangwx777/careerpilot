from fastapi import FastAPI
from sqlalchemy import text

from app.api import router
from app.db import engine

app = FastAPI(title="求职作战台")
app.include_router(router)


@app.get("/health")
def health():
    """健康检查：确认服务活着且能连库。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        return {"status": "error", "db": False, "detail": str(e)}
    return {"status": "ok", "db": db_ok}
