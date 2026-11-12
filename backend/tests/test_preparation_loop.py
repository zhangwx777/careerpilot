import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.db import Base, get_db
from app.main import app
from app.models import Application, Company, Position, PlannerSession, PreparationTask, ResumeProfile, TimelineNode
from app.planner_parsing import _validate

@pytest.fixture
def context():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)
        a = Application(position=Position(company=Company(name='测试'), title='后端', jd_text='Python'), status='已投递')
        db.add_all([a, ResumeProfile(id=1, resume_text='经验')]); db.commit()
        yield db, client, a
        app.dependency_overrides.clear()
    engine.dispose()

def session(db, a, **kwargs):
    s = PlannerSession(application_id=a.id, provider='openai', resume_snapshot='经验', jd_snapshot='Python', available_windows=[], status='已完成', **kwargs)
    db.add(s); db.flush(); return s

def task(db, a, s, **kwargs):
    t = PreparationTask(application_id=a.id, planner_session_id=s.id, title='练习', **kwargs)
    db.add(t); db.flush(); return t

def feedback(db,a,s,**kwargs):
    return task(db,a,s,status='已完成',answer_payload={'question':'原题'},user_answer='我的回答',feedback_payload={'strengths': [], 'gaps':['细节待补'], 'rewrite':'示例'},**kwargs)

def create(client,a):
    with patch('app.planner_api.resolve_role_provider',return_value='openai'), patch('app.planner_api.snapshot_for',return_value='snapshot'), patch('app.planner_api.submit_task',side_effect=lambda db,*args: (db.commit() or SimpleNamespace(id='task'))):
        r=client.post('/api/planner-sessions',json={'application_id':a.id})
    assert r.status_code==201,r.text
    return r.json()

def test_dashboard_due_deferrals_linked_suppression_and_reasons(context):
    db,client,a=context
    s=session(db,a)
    now=datetime.now(timezone.utc)
    linked=TimelineNode(application_id=a.id,node_type='其他',status='待处理',time_mode='固定时间',scheduled_at=now-timedelta(days=1))
    overdue=TimelineNode(application_id=a.id,node_type='笔试',status='待处理',time_mode='截止窗口',ends_at=now-timedelta(hours=1))
    db.add_all([linked,overdue]); db.flush()
    task(db,a,s,timeline_node_id=linked.id,deferred_until=now+timedelta(days=1))
    due=task(db,a,s,deferred_until=now-timedelta(seconds=1))
    task(db,a,s,status='已跳过')
    db.commit()
    result=client.get('/api/dashboard').json()
    assert {(i['kind'],i['id']) for i in result['feed']}=={('timeline',overdue.id),('preparation',due.id)}
    assert result['recommendations'][0]['reason']['code']=='overdue'
    assert result['recommendations'][1]['reason']['code']=='unscheduled'
    assert result==client.get('/api/dashboard').json()

def test_position_scope_confirmation_and_immutable_snapshot(context):
    db,client,a=context
    legacy=session(db,a)
    f=feedback(db,a,legacy)
    db.commit()
    url=f'/api/applications/{a.id}/practice-history'
    history=client.get(url).json()
    assert history['unconfirmed_session_ids']==[legacy.id]
    assert history['items'][0]['scope_confirmed'] is False
    assert create(client,a)['practice_snapshot']==[]
    r=client.post(url+'/confirm-scope',json={'position_id':a.position_id,'planner_session_ids':[legacy.id]})
    assert r.status_code==200,r.text
    saved=create(client,a)
    assert saved['position_id_snapshot']==a.position_id
    snap=saved['practice_snapshot']
    assert snap[0]['source_id']==f'practice-{f.id}' and snap[0]['question']=='原题'
    f.user_answer='改动'
    other=Position(company=a.position.company,title='不同岗位',jd_text='Other'); db.add(other);db.flush()
    old_position=a.position_id;a.position_id=other.id;db.commit()
    assert create(client,a)['practice_snapshot']==[]
    assert client.get(f"/api/planner-sessions/{saved['id']}").json()['practice_snapshot']==snap
    assert client.post(url+'/confirm-scope',json={'position_id':other.id,'planner_session_ids':[legacy.id]}).status_code==409
    assert client.post(url+'/confirm-scope',json={'position_id':old_position,'planner_session_ids':[legacy.id]}).status_code==409

def test_latest_twenty_valid_feedback_repeated_applications(context):
    db,client,a=context
    s=session(db,a,position_id_snapshot=a.position_id)
    for n in range(22): feedback(db,a,s,feedback_completed_at=datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(days=n))
    bad=feedback(db,a,s);bad.feedback_payload={}
    restored=feedback(db,a,s);restored.status='待处理'
    b=Application(position_id=a.position_id,status='已投递');db.add(b);db.commit()
    snap=create(client,b)['practice_snapshot']
    assert len(snap)==20
    assert f'practice-{bad.id}' not in {i['source_id'] for i in snap}
    history=client.get(f'/api/applications/{b.id}/practice-history?page_size=100').json()
    assert len(history['items'])==24
    assert any(i['task_id']==restored.id and i['has_feedback'] for i in history['items'])

@pytest.mark.parametrize('field',['actions','tasks'])
def test_practice_references_allowlist_for_both_actions_and_tasks(field):
    value={'title':'复习','priority':1} if field=='actions' else {'title':'复习','gap':'细节','estimated_minutes':30}
    value.update(source_ids=['practice-8'], evidence=[{'kind':'practice','reference':'practice-8'}])
    snap=[{'source_id':'practice-8'}]
    assert _validate(json.dumps({field:[value]}),[],snap)
    value['evidence'][0]['reference']='practice-999'
    with pytest.raises(ValueError): _validate(json.dumps({field:[value]}),[],snap)


@pytest.mark.parametrize("extractor,field", [("extract_plan", "actions"), ("extract_scheduled_plan", "tasks")])
def test_both_model_routes_receive_feedback_and_reject_fabricated_evidence(extractor, field):
    from app import planner_parsing
    action = {"title": "加强边界", "priority": 2} if field == "actions" else {"title": "加强边界", "gap": "边界", "estimated_minutes": 30}
    action.update(source_ids=["practice-3"], evidence=[{"kind": "practice", "reference": "practice-3"}])
    snapshot = [{"source_id": "practice-3", "question": "原问题", "user_answer": "原回答", "feedback_payload": {"rewrite": "点评"}}]
    run = getattr(planner_parsing, extractor)
    with patch("app.planner_parsing.chat", return_value=json.dumps({field: [action]})) as chat:
        run("resume", "jd", [], "openai", practice_snapshot=snapshot)
        assert "原问题" in chat.call_args.args[0][1]["content"]
    action["evidence"][0]["reference"] = "practice-other-position"
    with patch("app.planner_parsing.chat", return_value=json.dumps({field: [action]})):
        with pytest.raises(planner_parsing.PlannerParseError):
            run("resume", "jd", [], "openai", practice_snapshot=snapshot)


def test_recommendations_top_three_preserve_full_feed_and_priority_ties(context):
    db, client, a = context
    s = session(db, a)
    when = datetime.now(timezone.utc) + timedelta(days=10)
    lower = task(db, a, s, priority=3, scheduled_at=when)
    higher = task(db, a, s, priority=1, scheduled_at=when)
    same = task(db, a, s, priority=1, scheduled_at=when)
    for _ in range(3):
        task(db, a, s)
    db.commit()
    result = client.get("/api/dashboard").json()
    assert len(result["feed"]) == 6
    assert [item["id"] for item in result["recommendations"]] == [higher.id, same.id, lower.id]
    assert all(item["reason"]["code"] == "scheduled" for item in result["recommendations"])


def test_scope_confirmation_foreign_session_is_atomic_and_paginated(context):
    db, client, a = context
    legacy = session(db, a)
    feedback(db, a, legacy)
    feedback(db, a, legacy)
    b = Application(position=Position(company=a.position.company, title="其他岗位", jd_text="Other"), status="已投递")
    db.add(b)
    db.flush()
    foreign = session(db, b)
    feedback(db, b, foreign)
    db.commit()
    url = f"/api/applications/{a.id}/practice-history"
    result = client.post(url + "/confirm-scope", json={"position_id": a.position_id, "planner_session_ids": [legacy.id, foreign.id]})
    assert result.status_code == 409
    db.refresh(legacy)
    assert legacy.position_id_snapshot is None
    page = client.get(url + "?page=2&page_size=1").json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert page["items"][0]["feedback_completed_at"] is None


def test_snapshot_survives_original_task_deletion(context):
    db, client, a = context
    s = session(db, a, position_id_snapshot=a.position_id)
    original = feedback(db, a, s)
    db.commit()
    saved = create(client, a)
    db.delete(original)
    db.commit()
    assert client.get(f"/api/planner-sessions/{saved['id']}").json()["practice_snapshot"] == saved["practice_snapshot"]


def test_actual_successful_review_sets_timestamp_but_failure_does_not(context):
    from app import planner_api
    from app.planner_schemas import PreparationFeedback
    from sqlalchemy.orm import sessionmaker
    db, client, a = context
    s = session(db, a, position_id_snapshot=a.position_id)
    t = task(db, a, s, practice_status="review", user_answer="已保存的回答", answer_payload={"question": "问题"})
    db.commit()
    factory = sessionmaker(bind=db.bind)
    with patch.object(planner_api, "SessionLocal", factory), patch.object(planner_api, "config_from_snapshot", return_value={}), patch.object(planner_api, "run_review_preparation_answer", side_effect=ValueError("模拟失败")):
        with pytest.raises(ValueError):
            planner_api._run_practice(t.id, "review")
    db.refresh(t)
    assert t.feedback_completed_at is None and t.user_answer == "已保存的回答"
    before = datetime.now(timezone.utc)
    with patch.object(planner_api, "SessionLocal", factory), patch.object(planner_api, "config_from_snapshot", return_value={}), patch.object(planner_api, "run_review_preparation_answer", return_value=PreparationFeedback(rewrite="点评", gaps=["加强细节"])):
        planner_api._run_practice(t.id, "review")
    db.refresh(t)
    assert t.feedback_completed_at.replace(tzinfo=timezone.utc) >= before
    assert t.status == "已完成" and t.feedback_payload["gaps"] == ["加强细节"]
    assert t.feedback_answer_snapshot == "已保存的回答"
    assert t.feedback_question_snapshot == "问题"


def test_failed_or_active_review_does_not_pair_new_answer_with_old_feedback(context):
    db, client, a = context
    s = session(db, a, position_id_snapshot=a.position_id)
    failed = feedback(db, a, s)
    failed.practice_error = "点评失败"
    failed.user_answer = "重试的新回答"
    active = feedback(db, a, s)
    active.practice_status = "review"
    db.commit()
    assert create(client, a)["practice_snapshot"] == []


def test_successful_feedback_answer_survives_failed_retry(context):
    from app.practice_history import feedback_snapshot
    db, client, a = context
    s = session(db, a, position_id_snapshot=a.position_id)
    t = feedback(db, a, s)
    t.feedback_answer_snapshot = "真正点评的自答"
    t.feedback_question_snapshot = "真正点评的问题"
    t.user_answer = "新的未成功自答"
    t.practice_error = "重试点评失败"
    db.commit()
    snapshot = feedback_snapshot(db, a.position_id)
    assert len(snapshot) == 1 and snapshot[0]["user_answer"] == "真正点评的自答"
    history = client.get(f"/api/applications/{a.id}/practice-history").json()
    assert history["items"][0]["user_answer"] == "真正点评的自答"
    assert history["items"][0]["has_feedback"] is True


def test_reviewed_question_does_not_follow_regenerated_question(context):
    from app.practice_history import feedback_snapshot
    db, client, a = context
    s = session(db, a, position_id_snapshot=a.position_id)
    t = feedback(db, a, s)
    t.feedback_answer_snapshot = "原始自答"
    t.feedback_question_snapshot = "真正点评的问题"
    t.answer_payload = {"question": "后来生成的新问题"}
    t.practice_error = "生成失败"
    db.commit()
    snapshot = feedback_snapshot(db, a.position_id)
    assert snapshot[0]["question"] == "真正点评的问题"


def test_recruitment_conflict_due_overdue_precede_preparation(context):
    db, client, a = context
    s = session(db, a)
    now = datetime.now(timezone.utc)
    task(db, a, s, scheduled_at=now-timedelta(days=5), priority=1)
    for offset in (1, 1):
        db.add(TimelineNode(application_id=a.id, node_type="笔试", status="待处理", time_mode="固定时间", scheduled_at=now+timedelta(hours=offset), ends_at=now+timedelta(hours=offset+1)))
    due = TimelineNode(application_id=a.id, node_type="笔试", status="待处理", time_mode="截止窗口", ends_at=now+timedelta(hours=3))
    db.add(due)
    db.commit()
    result = client.get("/api/dashboard").json()
    assert len(result["feed"]) == 4
    assert [item["reason"]["code"] for item in result["recommendations"]] == ["conflict", "conflict", "due"]
    assert all(item["kind"] == "timeline" for item in result["recommendations"])


def test_shared_legacy_confirmation_locks_all_applications_before_sessions(context):
    from sqlalchemy import event
    from sqlalchemy.dialects import postgresql

    db, client, a = context
    b = Application(position_id=a.position_id, status="已投递")
    db.add(b)
    db.flush()
    legacy = session(db, a)
    db.commit()
    a_id, b_id, session_id, position_id = a.id, b.id, legacy.id, a.position_id
    locks = []

    def capture_lock(execution):
        statement = execution.statement
        if getattr(statement, "_for_update_arg", None) is not None:
            compiled = statement.compile(dialect=postgresql.dialect())
            locks.append((statement.column_descriptions[0]["entity"], str(compiled), compiled.params))

    event.listen(db, "do_orm_execute", capture_lock)
    try:
        for target in (a_id, b_id):
            locks.clear()
            result = client.post(
                f"/api/applications/{target}/practice-history/confirm-scope",
                json={"position_id": position_id, "planner_session_ids": [session_id]},
            )
            assert result.status_code == 200, result.text
            assert [entity for entity, _, _ in locks] == [Application, PlannerSession]
            app_sql, app_params = locks[0][1:]
            assert "ORDER BY application.id" in app_sql
            assert "FOR NO KEY UPDATE" in app_sql
            assert any(set(value) == {a_id, target} for value in app_params.values() if isinstance(value, list))
    finally:
        event.remove(db, "do_orm_execute", capture_lock)


@pytest.mark.parametrize("extractor,field", [("extract_plan", "actions"), ("extract_scheduled_plan", "tasks")])
def test_system_prompt_practice_example_is_valid_for_real_extractor(extractor, field):
    import re
    from app import planner_parsing

    def model_reply(messages, **kwargs):
        system = messages[0]["content"]
        example = re.search(r"<practice_example>\s*(.*?)\s*</practice_example>", system, re.S)
        assert example, "System prompt must provide a valid practice citation example"
        assert "不等于掌握" in system
        result = json.loads(example.group(1))
        assert result[field][0]["evidence"][0] == {"kind": "practice", "reference": "practice-42"}
        return json.dumps(result)

    with patch("app.planner_parsing.chat", side_effect=model_reply):
        result = getattr(planner_parsing, extractor)(
            "resume", "jd", [], "openai", practice_snapshot=[{"source_id": "practice-42"}],
        )
    assert getattr(result, field)[0].source_ids == ["practice-42"]


@pytest.mark.parametrize("reference", ["source_ids", "evidence"])
def test_materialization_rejects_forged_practice_before_any_write(context, reference):
    db, client, a = context
    s = session(db, a, practice_snapshot=[{"source_id": "practice-42"}])
    valid = {"title": "有效行动", "priority": 2, "source_ids": ["practice-42"]}
    invalid = {"title": "伪造行动", "priority": 2, "source_ids": []}
    if reference == "source_ids":
        invalid["source_ids"] = ["practice-other-position"]
    else:
        invalid["evidence"] = [{"kind": "practice", "reference": "practice-other-position"}]
    s.draft_payload = {"actions": [valid, invalid]}
    db.commit()
    result = client.post(f"/api/planner-sessions/{s.id}/materialize-actions", json={"action_indexes": [0, 1]})
    assert result.status_code == 422, result.text
    assert db.query(PreparationTask).count() == 0
    assert db.query(TimelineNode).count() == 0


@pytest.mark.parametrize("reference", ["source_ids", "evidence"])
def test_legacy_graph_persist_rejects_forged_practice_without_partial_write(context, reference):
    from sqlalchemy.orm import sessionmaker
    from app.planner_graph import build_planner_graph

    db, client, a = context
    s = session(db, a, practice_snapshot=[{"source_id": "practice-42"}])
    s.status = "待确认"
    db.commit()
    when = datetime.now(timezone.utc) + timedelta(days=30)
    valid = {"title": "有效任务", "gap": "知识", "estimated_minutes": 30, "scheduled_at": when.isoformat(), "ends_at": (when+timedelta(minutes=30)).isoformat(), "source_ids": ["practice-42"]}
    invalid = dict(valid, title="伪造任务", scheduled_at=(when+timedelta(hours=1)).isoformat(), ends_at=(when+timedelta(hours=2)).isoformat())
    if reference == "source_ids":
        invalid["source_ids"] = ["practice-other-position"]
    else:
        invalid["evidence"] = [{"kind": "practice", "reference": "practice-other-position"}]
    graph = build_planner_graph(None, sessionmaker(bind=db.bind))
    with pytest.raises(ValueError):
        graph.nodes["persist"].bound.invoke({"planner_session_id": s.id, "confirmation": {"tasks": [valid, invalid]}, "draft": {}})
    db.expire_all()
    assert db.query(PreparationTask).count() == 0
    assert db.query(TimelineNode).count() == 0
    assert db.get(PlannerSession, s.id).status == "待确认"


def test_write_allowlist_preserves_manual_intel_and_valid_practice(context):
    from sqlalchemy.orm import sessionmaker
    from app.planner_graph import build_planner_graph
    db, client, a = context
    s = session(db, a, practice_snapshot=[{"source_id": "practice-42"}])
    s.status = "待确认"
    db.commit()
    when = datetime.now(timezone.utc) + timedelta(days=30)
    task = {"title": "人工确认任务", "gap": "知识", "estimated_minutes": 30, "scheduled_at": when.isoformat(), "ends_at": (when+timedelta(minutes=30)).isoformat(), "source_ids": ["manual-intel-id", "practice-42"], "evidence": [{"kind": "practice", "reference": "practice-42"}]}
    graph = build_planner_graph(None, sessionmaker(bind=db.bind))
    graph.nodes["persist"].bound.invoke({"planner_session_id": s.id, "confirmation": {"tasks": [task]}, "draft": {}})
    db.expire_all()
    saved = db.query(PreparationTask).one()
    assert saved.source_ids == ["manual-intel-id", "practice-42"]
    assert saved.evidence == [{"kind": "practice", "reference": "practice-42"}]
    assert db.query(TimelineNode).count() == 1
    assert db.get(PlannerSession, s.id).status == "已确认"
