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
from app import phase3_api, parse_graph, planner_api, task_execution
from app.llm.config_store import save_provider
from app.models import Application, Company, DailyBriefing, Position, TimelineNode, PlannerSession, PreparationTask, ResumeProfile
from app.parsing import NoticeExtraction
from app.planner_schemas import PlannerDraft, PreparationAnswer, PreparationFeedback
from app.planner_coach import PlannerCoachError

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
    job = task_execution.prepare_dispatch(db, task, *args)
    db.commit()
    task_execution.execute_job(job.id)
    db.expire_all()
    return job


answer = PreparationAnswer(question="缓存失效时如何保证一致性？", core_answer="先明确失效策略和回源边界。", personalized_answer="结合合成岗位说明失效后的回源步骤。", follow_ups=["并发回源如何处理？"])
feedback = PreparationFeedback(strengths=["能解释缓存的用途"], gaps=["未解释失效与回源的边界"], rewrite="先说明失效条件，再解释并发回源的边界。")
review_failure = False


def review_browser_answer(*_args, **_kwargs):
    if review_failure:
        raise PlannerCoachError("synthetic review failure")
    return feedback


def fail_browser_review():
    global review_failure
    review_failure = True
    return {"ok": True}


def extract_browser_plan(*_args, **kwargs):
    practices = kwargs.get("practice_snapshot") or []
    return PlannerDraft.model_validate({"summary": "基于合成资料的准备建议", "actions": [{
        "title": "补练缓存失效与回源边界" if practices else "讲解缓存的用途",
        "detail": "明确失效条件，再解释并发回源的处理。", "category": "八股", "priority": 1,
        "gap": "未解释失效与回源的边界" if practices else None,
        "source_ids": [practices[0]["source_id"]] if practices else [],
        "evidence": [{"kind": "practice", "reference": practices[0]["source_id"]}] if practices else [],
    }]})


def preparation_fixture(legacy: bool = False):
    global review_failure
    review_failure = False
    reset()
    with sessions() as db:
        application = db.get(Application, 1)
        application.position.jd_text = "合成后端岗位：解释缓存失效和并发回源机制。"
        foreign = Application(position=Position(company=Company(name="其他岗位公司"), title="设计岗位", jd_text="合成设计岗位说明"), status="已投递")
        db.add_all([ResumeProfile(id=1, resume_text="合成简历：参与缓存练习项目。"), foreign])
        if legacy:
            session = PlannerSession(application_id=1, provider="qwen", resume_snapshot="合成历史简历", jd_snapshot="合成历史岗位", intel_snapshot=[], available_windows=[], status="已完成")
            db.add(session)
            db.flush()
            db.add(PreparationTask(planner_session_id=session.id, application_id=1, title="历史缓存练习", status="已完成", answer_payload=answer.model_dump(), user_answer="缓存能减少回源，但还没有解释边界。", feedback_payload=feedback.model_dump()))
        db.commit()
        return {"original_application_id": 1, "same_position_application_id": 2, "other_position_application_id": foreign.id}

parse_graph.extract_notice = lambda *_args, **_kwargs: NoticeExtraction(
    company_name="浏览器测试公司", position_title="后端工程师", node_type="笔试", time_mode="固定时间",
    scheduled_at=datetime.now(timezone.utc) + timedelta(days=1), source="测试通知")
phase3_api.SessionLocal = sessions
phase3_api.start_parse_graph = start
phase3_api.resume_parse_graph = resume
phase3_api.submit_task = dispatch
planner_api.SessionLocal = sessions
task_execution.SessionLocal = sessions
planner_api.submit_task = dispatch
planner_api.extract_plan = extract_browser_plan
planner_api.generate_preparation_answer = lambda *_args, **_kwargs: answer
planner_api.run_review_preparation_answer = review_browser_answer
app.dependency_overrides[get_db] = database
test_app = FastAPI()
test_app.post("/__test/reset")(reset)
test_app.post("/__test/preparation")(preparation_fixture)
test_app.post("/__test/fail-review")(fail_browser_review)
test_app.mount("/", app)
reset()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(test_app, host="127.0.0.1", port=18765, lifespan="off")
