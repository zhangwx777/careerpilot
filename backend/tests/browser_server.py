"""Local browser acceptance server: real APIs/database, synthetic data and mocked LLM."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
data = tempfile.TemporaryDirectory(prefix="careerpilot-browser-")
os.environ.update(DATABASE_URL="sqlite://", CAREERPILOT_DATA_DIR=data.name,
                  LITELLM_LOCAL_MODEL_COST_MAP="True")

from app.config import settings
settings.database_url = "sqlite://"
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.db import Base, get_db
from app.main import app
from app import phase3_api, parse_graph
from app.llm.config_store import save_provider
from app.models import Application, Company, DailyBriefing, Position, TimelineNode
from app.parsing import NoticeExtraction

engine = create_engine(f"sqlite:///{Path(data.name) / 'browser.sqlite'}", connect_args={"check_same_thread": False})
@event.listens_for(engine, "connect")
def foreign_keys(connection, _record):
    connection.execute("PRAGMA foreign_keys=ON")

sessions = sessionmaker(engine, expire_on_commit=False)
graph = None

def reset():
    global graph
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    graph = parse_graph.build_parse_graph(InMemorySaver(), sessions)
    with sessions() as db:
        position = Position(company=Company(name="历史示例公司"), title="工程师" * 20)
        for _ in range(2):
            application = Application(position=position, status="已投递")
            db.add(application)
            db.flush()
            db.add(TimelineNode(application_id=application.id, node_type="笔试", status="待处理",
                                time_mode="固定时间", scheduled_at=datetime.now(timezone.utc)))
        save_provider(db, "qwen", api_key="synthetic-browser-key", model="qwen/qwen-max", base_url=None)
        db.add(DailyBriefing(briefing_date=datetime.now(ZoneInfo("Asia/Shanghai")).date(), payload={
            "alerts": [{"timeline_node_id": 1, "title": "历史笔试", "scheduled_at": datetime.now(timezone.utc).isoformat(), "alert_types": ["临期"]}],
            "today_tasks": [], "new_sources": [], "search_errors": [],
        }))
        db.commit()
    return {"ok": True}

def database():
    with sessions() as db:
        yield db

def start(session_id, thread_id, raw_text, requested_at, provider, *_):
    return graph.invoke({"parse_session_id": session_id, "raw_text": raw_text, "provider": provider,
                         "requested_at": requested_at.isoformat()}, {"configurable": {"thread_id": thread_id}})

def resume(thread_id, confirmation, *_):
    return graph.invoke(Command(resume=confirmation.model_dump(mode="json")), {"configurable": {"thread_id": thread_id}})

def dispatch(db, task, *args):
    if task.name != "careerpilot.parse_session":
        raise RuntimeError("Unexpected browser-test background task")
    db.commit()
    phase3_api._run_parse_session(args[0], args[1], args[2], args[3], datetime.fromisoformat(args[4]))
    db.expire_all()

parse_graph.extract_notice = lambda *_args, **_kwargs: NoticeExtraction(
    company_name="浏览器测试公司", position_title="后端工程师", node_type="笔试", time_mode="固定时间",
    scheduled_at=datetime.now(timezone.utc) + timedelta(days=1), source="测试通知")
phase3_api.SessionLocal = sessions
phase3_api.start_parse_graph = start
phase3_api.resume_parse_graph = resume
phase3_api.submit_task = dispatch
app.dependency_overrides[get_db] = database
test_app = FastAPI()
test_app.post("/__test/reset")(reset)
test_app.mount("/", app)
reset()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(test_app, host="127.0.0.1", port=18765, lifespan="off")
