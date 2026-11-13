"""Real PostgreSQL lock-order and follow-up fingerprint races; synthetic schema only."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import followup as f
from app.db import Base
from app.models import Application, Company, Position, PlannerSession, PreparationTask, ResumeProfile, TimelineNode, FollowupCheck

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='需要独立TEST_DATABASE_URL')

@pytest.fixture
def pg():
    base=make_url(os.environ['TEST_DATABASE_URL'])
    schema='followup_race_'+uuid4().hex[:12]
    admin=create_engine(base)
    with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine=create_engine(base.update_query_dict({'options':f'-csearch_path={schema} -clock_timeout=4000 -cstatement_timeout=7000'}))
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            company=Company(name='Synthetic race');db.add(company);db.flush()
            position=Position(company_id=company.id,title='Synthetic',jd_text='Original JD');db.add(position);db.flush()
            for _ in range(2):db.add(Application(position_id=position.id))
            db.add(ResumeProfile(id=1,resume_text='Original resume'));db.flush()
            for application_id in (1,2):
                db.add(PlannerSession(application_id=application_id,position_id_snapshot=position.id,provider='qwen',resume_snapshot='synthetic',jd_snapshot='synthetic',available_windows=[],status='已完成'))
            db.flush()
            node=TimelineNode(application_id=1,node_type='一面',scheduled_at=datetime.now(timezone.utc)+timedelta(days=5));db.add(node)
            db.add(PreparationTask(application_id=1,planner_session_id=1,title='Unstarted'))
            db.add(PreparationTask(application_id=2,planner_session_id=2,title='Reviewed',status='已完成',answer_payload={'question':'Synthetic question'},user_answer='Original answer',feedback_payload={'rewrite':'Original review'}));db.commit()
            goal=f.create_goal(db,1,1);snapshot=f.input_snapshot(db,goal)
            suggestion={'operation':'add_practice','task_id':None,'title':'New practice','reason':'Synthetic evidence','source_ids':['position-1:jd'],'before':None,'after':{'title':'New practice'}}
            check=FollowupCheck(goal_id=goal.id,provider='qwen',status='待确认',input_snapshot=snapshot,business_version=f.version(snapshot),goal_revision=goal.revision,suggestions=[suggestion],sources=[])
            db.add(check);db.commit()
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def change_input(db,kind):
    if kind=='application':
        p=Position(company_id=1,title='Other synthetic',jd_text='Other JD');db.add(p);db.flush();db.get(Application,1).position_id=p.id
    elif kind=='jd':db.get(Position,1).jd_text='Changed JD'
    elif kind=='resume':db.get(ResumeProfile,1).resume_text='Changed resume'
    else:db.get(PreparationTask,2).feedback_payload={'rewrite':'Changed review'}
    db.flush()


@pytest.mark.parametrize('kind',['application','jd','resume','feedback'])
def test_input_writer_cannot_commit_between_validation_and_apply(pg,monkeypatch,kind):
    validated=Event();release=Event();writer_started=Event();writer_done=Event();order=[]
    original=f._current
    def gate(db,check,goal):
        result=original(db,check,goal)
        validated.set()
        assert release.wait(4)
        return result
    monkeypatch.setattr(f,'_current',gate)
    def apply():
        with Session(pg) as db:f.apply_check(db,1,[0]);order.append('apply')
    def writer():
        with Session(pg) as db:
            writer_started.set();change_input(db,kind)
            assert db.get(FollowupCheck,1).execution_result is not None
            db.commit();writer_done.set()
    with ThreadPoolExecutor(2) as pool:
        applied=pool.submit(apply)
        assert validated.wait(4)
        edited=pool.submit(writer)
        assert writer_started.wait(2)
        try:assert not writer_done.wait(.2)
        finally:release.set()
        applied.result(timeout=6);edited.result(timeout=6)
    assert writer_done.is_set()


@pytest.mark.parametrize('kind',['application','jd','resume','feedback'])
def test_committed_concurrent_input_edit_is_refreshed_and_rejected(pg,kind):
    edited=Event();release=Event()
    def writer():
        with Session(pg) as db:
            change_input(db,kind);edited.set();assert release.wait(4);db.commit()
    def apply():
        with Session(pg) as db:
            # Warm an ORM identity map before the concurrent commit.
            db.get(Application,1);db.get(Position,1);db.get(ResumeProfile,1)
            with pytest.raises(HTTPException) as error:f.apply_check(db,1,[0])
            assert error.value.status_code==409
    with ThreadPoolExecutor(2) as pool:
        written=pool.submit(writer);assert edited.wait(4)
        applied=pool.submit(apply);release.set()
        written.result(timeout=6);applied.result(timeout=6)
    with Session(pg) as db:
        assert db.get(FollowupCheck,1).execution_result is None
        assert len(db.scalars(select(PreparationTask)).all())==2


@pytest.mark.parametrize('operation',['goal','timeline','scope'])
def test_app_first_writers_and_followup_do_not_reverse_locks(pg,monkeypatch,operation):
    writer_locked=Event();apply_attempt=Event()
    original=f.locked
    def observe(db,model,identifier):
        if model is Application:apply_attempt.set()
        return original(db,model,identifier)
    monkeypatch.setattr(f,'locked',observe)
    def writer():
        with Session(pg) as db:
            db.scalar(select(Application).where(Application.id==1).with_for_update(key_share=True));writer_locked.set()
            assert apply_attempt.wait(4)
            if operation=='goal':f.create_goal(db,1,1)
            elif operation=='timeline':
                from app.phase3_api import update_timeline_status
                from app.phase3_schemas import TimelineStatusTransition
                update_timeline_status(1,TimelineStatusTransition(status='已取消'),db)
            else:
                from app.planner_api import confirm_practice_scope
                from app.planner_schemas import PracticeScopeConfirmation
                confirm_practice_scope(1,PracticeScopeConfirmation(position_id=1,planner_session_ids=[1]),db)
            db.commit()
    def apply():
        with Session(pg) as db:
            try:f.apply_check(db,1,[0])
            except HTTPException as error:
                assert operation=='timeline' and error.status_code==409
    with ThreadPoolExecutor(2) as pool:
        written=pool.submit(writer);assert writer_locked.wait(4)
        applied=pool.submit(apply)
        written.result(timeout=7);applied.result(timeout=7)


def test_app_no_key_update_allows_session_first_fk_materialization(pg):
    from app.planner_api import materialize_planner_actions
    with Session(pg) as db:
        db.get(PlannerSession,1).draft_payload={'actions':[{'title':'Extra synthetic','priority':2}]};db.commit()
    plan_locked=Event();app_locked=Event()
    def materialize():
        with Session(pg) as db:
            plan=db.scalar(select(PlannerSession).where(PlannerSession.id==1).with_for_update());plan_locked.set()
            assert app_locked.wait(4)
            materialize_planner_actions(db,plan);db.commit()
    def application_holder():
        with Session(pg) as db:
            assert plan_locked.wait(4)
            db.scalar(select(Application).where(Application.id==1).with_for_update(key_share=True));app_locked.set()
            # The planner writer must complete despite this application lock.
            completed.result(timeout=4)
            db.commit()
    with ThreadPoolExecutor(2) as pool:
        completed=pool.submit(materialize);held=pool.submit(application_holder)
        completed.result(timeout=6);held.result(timeout=6)

@pytest.mark.parametrize('parent',['position','company'])
def test_parent_delete_waits_for_apply_without_cascade_lock_cycle(pg,monkeypatch,parent):
    from app.api import delete_position,delete_company
    with Session(pg) as db:
        other_company=Company(name='Unrelated synthetic');db.add(other_company);db.flush()
        other_position=Position(company_id=other_company.id,title='Unrelated synthetic');db.add(other_position);db.flush()
        other_application=Application(position_id=other_position.id);db.add(other_application);db.commit()
        other_application_id=other_application.id;other_position_id=other_position.id
    validated=Event();release=Event();started=Event();done=Event()
    original=f._current
    def gate(db,check,goal):
        result=original(db,check,goal);validated.set();assert release.wait(4);return result
    monkeypatch.setattr(f,'_current',gate)
    def apply():
        with Session(pg) as db:f.apply_check(db,1,[0])
    def remove():
        with Session(pg) as db:
            started.set()
            (delete_position if parent=='position' else delete_company)(1,db)
            done.set()
    with ThreadPoolExecutor(2) as pool:
        applied=pool.submit(apply);assert validated.wait(4)
        deleted=pool.submit(remove);assert started.wait(2)
        try:assert not done.wait(.2)
        finally:release.set()
        applied.result(timeout=6);deleted.result(timeout=6)
    with Session(pg) as db:
        assert not db.scalars(select(Application).where(Application.position_id==1)).all()
        assert not db.scalars(select(PreparationTask)).all()
        assert db.get(Application,other_application_id) is not None and db.get(Position,other_position_id) is not None
        assert db.get(Position,1) is None
        assert (db.get(Company,1) is None)==(parent=='company')
        assert db.get(ResumeProfile,1) is not None


@pytest.mark.parametrize('parent',['position','company'])
def test_parent_delete_locks_applications_before_apply_can_lock_position(pg,monkeypatch,parent):
    from sqlalchemy import event
    from app.api import delete_position,delete_company
    deletion_ready=Event();apply_attempt=Event()
    original=f.locked
    def observe(db,model,identifier):
        if model is Application:apply_attempt.set()
        return original(db,model,identifier)
    monkeypatch.setattr(f,'locked',observe)
    def remove():
        with Session(pg) as db:
            def before_position(execution):
                statement=execution.statement
                if getattr(statement,'_for_update_arg',None) is not None and statement.column_descriptions[0]['entity'] is Position:
                    deletion_ready.set();assert apply_attempt.wait(4)
            event.listen(db,'do_orm_execute',before_position)
            (delete_position if parent=='position' else delete_company)(1,db)
    def apply():
        with Session(pg) as db:
            with pytest.raises(HTTPException) as error:f.apply_check(db,1,[0])
            assert error.value.status_code==404
    with ThreadPoolExecutor(2) as pool:
        deleted=pool.submit(remove);assert deletion_ready.wait(4)
        applied=pool.submit(apply)
        deleted.result(timeout=6);applied.result(timeout=6)


@pytest.mark.parametrize('membership',['application','company_application','position'])
def test_parent_delete_membership_race_conflicts_without_partial_cascade(pg,membership):
    from sqlalchemy import event
    from app.api import delete_position,delete_company
    with Session(pg) as db:
        inserted=[False]
        def concurrent_member(execution):
            statement=execution.statement
            entity=statement.column_descriptions[0]['entity'] if hasattr(statement,'column_descriptions') else None
            target=Company if membership=='position' else Position
            if not inserted[0] and getattr(statement,'_for_update_arg',None) is not None and entity is target:
                inserted[0]=True
                with Session(pg) as writer:
                    if membership!='position':writer.add(Application(position_id=1))
                    else:writer.add(Position(company_id=1,title='Concurrent synthetic'))
                    writer.commit()
        event.listen(db,'do_orm_execute',concurrent_member)
        with pytest.raises(HTTPException) as error:
            (delete_position if membership=='application' else delete_company)(1,db)
        assert error.value.status_code==409
        db.rollback()
    with Session(pg) as db:
        assert db.get(Company,1) is not None and db.get(Position,1) is not None
        assert db.get(PreparationTask,1) is not None
