from datetime import datetime, timedelta, timezone
import json
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.db import Base
from app.models import Application, Company, Position, TimelineNode, PlannerSession, PreparationTask, FollowupCheck, ResumeProfile
from app import followup as f

@pytest.fixture
def db():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        c=Company(name='Synthetic');db.add(c);db.flush()
        p=Position(company_id=c.id,title='Synthetic',jd_text='Python');db.add(p);db.flush()
        a=Application(position_id=p.id);db.add(a);db.flush()
        n=TimelineNode(application_id=a.id,node_type='一面',scheduled_at=datetime.now(timezone.utc)+timedelta(days=5))
        plan=PlannerSession(application_id=a.id,provider='qwen',resume_snapshot='synthetic',jd_snapshot='Python',available_windows=[],position_id_snapshot=p.id,status='已完成')
        db.add_all([n,plan,ResumeProfile(id=1,resume_text='Synthetic')]);db.flush()
        db.add(PreparationTask(application_id=a.id,planner_session_id=plan.id,title='Practice'));db.commit()
        yield db

def proposal(db,ops=('skip_task',)):
    g=f.create_goal(db,1,1);s=f.input_snapshot(db,g)
    _,registry=f.build_toolset(s)
    sources=[source.model_dump(mode='json') for tool in registry.values() for source in tool.handler({}).sources]
    values=[]
    for op in ops:
        v={'operation':op,'reason':'基于真实材料','source_ids':['task-1']}
        if op=='add_practice':v.update(title='New',after={'detail':'Synthetic'})
        else:
            v['task_id']=1
            if op=='reschedule_task':v['after']={'scheduled_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
        values.append(v)
    suggestions,_,_=f.validate_output(json.dumps({'suggestions':values}),s,sources)
    check=FollowupCheck(goal_id=g.id,provider='qwen',status='待确认',input_snapshot=s,business_version=f.version(s),goal_revision=g.revision,suggestions=suggestions,sources=sources)
    db.add(check);db.commit()
    return check

def test_revision_all_writes_aba(db):
    t=db.get(PreparationTask,1);original=t.revision
    t.user_answer='draft';db.commit();t.user_answer=None;db.commit()
    assert t.revision==original+2

@pytest.mark.parametrize('change',[{'answer_payload':{'question':'q'}},{'user_answer':'answer'},{'feedback_payload':{'x':1}},{'practice_status':'answer'},{'practice_status':'failed'},{'status':'已完成'},{'status':'已跳过'}])
def test_started_rejects_batch_without_partial_add(db,change):
    c=proposal(db,('add_practice','skip_task'));t=db.get(PreparationTask,1)
    for key,value in change.items():setattr(t,key,value)
    db.commit()
    with pytest.raises(HTTPException):f.apply_check(db,c.id,[0,1])
    assert len(db.scalars(select(PreparationTask)).all())==1
    assert len(db.scalars(select(PlannerSession)).all())==1

def test_apply_replay_subset_conflict_recoverable(db):
    c=proposal(db,('add_practice','skip_task'));f.apply_check(db,c.id,[0,1])
    assert db.get(PreparationTask,1).status=='已跳过'
    assert len(db.scalars(select(PreparationTask)).all())==2
    f.apply_check(db,c.id,[1,0])
    assert len(db.scalars(select(PreparationTask)).all())==2
    with pytest.raises(HTTPException):f.apply_check(db,c.id,[0])
    from app.preparation import transition_task
    t=db.get(PreparationTask,1);transition_task(db,t,'待处理');db.commit()
    assert t.status=='待处理'

def test_task_and_node_aba_stale(db):
    from app.timeline import update_timeline_node
    c=proposal(db);t=db.get(PreparationTask,1)
    t.title='Changed';db.commit();t.title='Practice';db.commit()
    with pytest.raises(HTTPException):f.apply_check(db,c.id,[0])
    c=proposal(db);n=db.get(TimelineNode,1);date=n.scheduled_at
    update_timeline_node(n,scheduled_at=date+timedelta(hours=1));db.commit();update_timeline_node(n,scheduled_at=date);db.commit()
    with pytest.raises(HTTPException):f.apply_check(db,c.id,[0])

def test_hiring_untouched_legacy_sync(db):
    t=db.get(PreparationTask,1);t.timeline_node_id=1;db.commit()
    c=proposal(db);f.apply_check(db,c.id,[0])
    assert db.get(TimelineNode,1).status=='待处理'
    t.status='待处理';n=TimelineNode(application_id=1,node_type='其他',source='备战计划');db.add(n);db.flush();t.timeline_node_id=n.id;db.commit()
    c=proposal(db,('reschedule_task',));f.apply_check(db,c.id,[0])
    assert f.iso(n.scheduled_at)==f.iso(t.scheduled_at)

@pytest.mark.parametrize('operation',['change_stage','update_resume','delete_task'])
def test_unauthorized_rejected(operation):
    with pytest.raises(ValueError):f.validate_output(json.dumps({'suggestions':[{'operation':operation,'reason':'x','source_ids':['x']}]}),{},[])

def test_forged_sources_rejected(db):
    c=proposal(db)
    for source in ['practice-999','resume:current']:
        with pytest.raises(ValueError):f.validate_output(json.dumps({'suggestions':[{'operation':'skip_task','task_id':1,'reason':'x','source_ids':[source]}]}),c.input_snapshot,c.sources)

@pytest.mark.parametrize('state',['paused','已完成','已取消'])
def test_closed_stop(db,state):
    c=proposal(db)
    if state=='paused':f.set_goal_status(db,c.goal_id,'paused')
    else:db.get(TimelineNode,1).status=state;db.commit()
    with pytest.raises(HTTPException):f.apply_check(db,c.id,[0])
    with pytest.raises(HTTPException):f.create_check(db,c.goal_id)

def test_unchanged_auto_daily_reuses(db,monkeypatch):
    c=proposal(db);monkeypatch.setattr(f,'resolve_role_provider',lambda *a:'qwen');monkeypatch.setattr(f,'snapshot_for',lambda *a:'encrypted')
    at=datetime.now(timezone.utc)
    d=f.create_check(db,c.goal_id,automatic=True,at=at)
    assert d.duplicate_of==c.id
    assert f.create_check(db,c.goal_id,automatic=True,at=at) is None
    assert f.create_check(db,c.goal_id,automatic=True,at=at+timedelta(days=1)).duplicate_of==c.id
    assert f.check_read(db,c)['applicable']

def test_bound_readonly_tools(db):
    s=f.input_snapshot(db,f.create_goal(db,1,1));_,r=f.build_toolset(s)
    assert set(r)=={'read_followup_context','read_goal_tasks','read_position_practice'}
    assert [v.id for v in r['read_goal_tasks'].handler({}).sources]==['task-1']
    with pytest.raises(ValueError):r['read_goal_tasks'].handler({'application_id':999})
    assert not db.dirty

def run_environment(db,monkeypatch,raw):
    import app.db
    import app.agent_runtime as runtime
    monkeypatch.setattr(app.db,'SessionLocal',lambda:Session(db.bind))
    monkeypatch.setattr(f,'config_from_snapshot',lambda *args:{'model':'synthetic'})
    monkeypatch.setattr(runtime,'chat_with_tools',lambda *args,**kwargs:{'content':'','tool_calls':[]})
    monkeypatch.setattr(runtime,'chat_stream',lambda *args,**kwargs:iter([json.dumps(raw)]))
    c=proposal(db);c.status='生成中';c.suggestions=[];db.commit()
    return c


def test_real_agent_persists_sources_and_no_business_writes(db,monkeypatch):
    raw={'suggestions':[{'operation':'skip_task','task_id':1,'reason':'基于任务与岗位','source_ids':['task-1']}]}
    c=run_environment(db,monkeypatch,raw)
    f.run_check(c.id);db.expire_all();c=db.get(FollowupCheck,c.id)
    assert c.status=='待确认'
    assert db.get(PreparationTask,1).status=='待处理'
    from app.models import AgentRun
    run=db.get(AgentRun,c.agent_run_id)
    assert run.kind=='followup' and len(run.steps)==1
    assert set(run.used_tools)=={'read_followup_context','read_goal_tasks','read_position_practice'}
    assert 'task-1' in {source['id'] for source in run.sources}

@pytest.mark.parametrize('missing',['jd','resume','time'])
def test_missing_data_truthful_no_adjustment(db,monkeypatch,missing):
    c=run_environment(db,monkeypatch,{'suggestions':[]})
    if missing=='jd':db.get(Position,1).jd_text=''
    if missing=='resume':db.get(ResumeProfile,1).resume_text=''
    if missing=='time':db.get(TimelineNode,1).scheduled_at=None
    db.commit();c.input_snapshot=f.input_snapshot(db,db.get(__import__('app.models',fromlist=['FollowupGoal']).FollowupGoal,c.goal_id));c.business_version=f.version(c.input_snapshot);db.commit()
    import app.agent_runtime as runtime
    from app.models import AgentRun
    def no_call(*args,**kwargs):raise AssertionError('已知缺项不得调用模型')
    monkeypatch.setattr(runtime,'chat_with_tools',no_call)
    monkeypatch.setattr(runtime,'chat_stream',no_call)
    before=f.task_snapshot(db.get(PreparationTask,1))
    f.run_check(c.id);db.expire_all();c=db.get(FollowupCheck,c.id)
    assert c.status=='已完成' and not c.suggestions and '缺少' in c.message
    assert c.agent_run_id is None and not db.scalars(select(AgentRun)).all()
    assert f.task_snapshot(db.get(PreparationTask,1))==before


def test_budget_failure_and_lost_lease_zero_writes(db,monkeypatch):
    import app.agent_runtime as runtime
    from app.llm.budget import BudgetExceeded
    from app.task_execution import TaskLeaseLost
    c=run_environment(db,monkeypatch,{'suggestions':[]})
    def budget(*args,**kwargs):raise BudgetExceeded('limit')
    monkeypatch.setattr(runtime,'chat_with_tools',budget)
    f.run_check(c.id);db.expire_all();assert db.get(FollowupCheck,c.id).status=='失败'
    c.status='生成中';db.commit()
    def lost(*args):raise TaskLeaseLost('lost')
    monkeypatch.setattr(f,'assert_dispatch_owner',lost)
    with pytest.raises(TaskLeaseLost):f.run_check(c.id)
    db.expire_all();assert db.get(FollowupCheck,c.id).status=='生成中'


def test_unconfirmed_or_reassigned_plan_never_exposes_tasks(db):
    p=db.get(PlannerSession,1);p.position_id_snapshot=None;db.get(PreparationTask,1).user_answer='old answer';db.commit()
    g=f.create_goal(db,1,1);s=f.input_snapshot(db,g)
    assert not s['tasks'] and not s['practice']
    p.position_id_snapshot=999;db.commit()
    assert not f.input_snapshot(db,g)['tasks']


def test_dispatch_uses_saved_config_and_followup_budget(db,monkeypatch):
    import app.db
    import app.task_execution as execution
    import app.agent_runtime as runtime
    from app.task_queue import run_followup_task
    from app.models import TaskDispatch
    from app.llm.budget import current_budget
    c=run_environment(db,monkeypatch,{'suggestions':[]})
    c.llm_snapshot='encrypted-original';db.commit()
    seen=[]
    def config(token,*args):seen.append(token);return {'model':'synthetic'}
    monkeypatch.setattr(f,'config_from_snapshot',config)
    def model(*args,**kwargs):
        assert current_budget.get().max_calls==6
        assert current_budget.get().duration==90
        return {'content':'','tool_calls':[]}
    monkeypatch.setattr(runtime,'chat_with_tools',model)
    monkeypatch.setattr(execution,'SessionLocal',lambda:Session(db.bind))
    job=execution.prepare_dispatch(db,run_followup_task,c.id);db.commit()
    execution.execute_job(job.id);db.expire_all()
    assert db.get(TaskDispatch,job.id).status=='completed'
    assert seen==['encrypted-original']
    assert db.get(FollowupCheck,c.id).status=='已完成'

def test_added_plan_compatible_report_and_rematerialize_is_idempotent(db):
    from app.planner_api import materialize_planner_actions, _session_read
    c=proposal(db,('skip_task','add_practice'));f.apply_check(db,c.id,[0,1])
    plan=db.scalars(select(PlannerSession).order_by(PlannerSession.id.desc())).first()
    assert _session_read(plan).draft_payload['actions'][0]['title']=='New'
    assert plan.prompt_version=='followup-v1'
    assert db.scalars(select(PreparationTask).where(PreparationTask.planner_session_id==plan.id)).first().action_index==0
    assert materialize_planner_actions(db,plan)==0
    assert len(db.scalars(select(PreparationTask)).all())==2

def test_temporary_dispatch_retry_retains_original_config(db,monkeypatch):
    import app.task_execution as execution
    import app.agent_runtime as runtime
    from app.task_queue import run_followup_task
    from app.models import TaskDispatch
    from app.llm.provider import LlmCallError
    c=run_environment(db,monkeypatch,{'suggestions':[]});c.llm_snapshot='encrypted-original';db.commit()
    seen=[]
    monkeypatch.setattr(f,'config_from_snapshot',lambda token,*args:seen.append(token) or {'model':'original'})
    monkeypatch.setattr(execution,'SessionLocal',lambda:Session(db.bind))
    attempts=[0]
    def model(*args,**kwargs):
        attempts[0]+=1
        if attempts[0]==1:raise LlmCallError('timeout')
        return {'content':'','tool_calls':[]}
    monkeypatch.setattr(runtime,'chat_with_tools',model)
    job=execution.prepare_dispatch(db,run_followup_task,c.id);db.commit();identifier=job.id
    execution.execute_job(identifier);db.expire_all()
    assert db.get(TaskDispatch,identifier).status=='pending'
    assert db.get(FollowupCheck,c.id).status=='生成中'
    execution.execute_job(identifier);db.expire_all()
    assert db.get(TaskDispatch,identifier).status=='completed'
    assert seen==['encrypted-original','encrypted-original']


def test_discard_during_running_analysis_not_overwritten(db,monkeypatch):
    import app.agent_runtime as runtime
    c=run_environment(db,monkeypatch,{'suggestions':[]})
    def final(*args,**kwargs):
        with Session(db.bind) as concurrent:f.discard_check(concurrent,c.id)
        yield '{"suggestions":[]}'
    monkeypatch.setattr(runtime,'chat_stream',final)
    f.run_check(c.id);db.expire_all()
    assert db.get(FollowupCheck,c.id).status=='已丢弃'


def test_fixed_offline_followup_eval_corpus(db):
    from pathlib import Path
    cases=json.loads((Path(__file__).parent/'followup_eval_cases.json').read_text(encoding='utf-8'))
    assert len(cases)==10 and len({case['id'] for case in cases})==10
    c=proposal(db);snapshot=c.input_snapshot
    snapshot['tasks'][0]['user_answer']='Already started'
    for case in cases:
        raw=json.dumps(case['response'])
        if case['accepted']:
            f.validate_output(raw,snapshot,c.sources)
        else:
            with pytest.raises(ValueError):f.validate_output(raw,snapshot,c.sources)

def test_expired_suggestion_rejects_apply_and_allows_new_check(db,monkeypatch):
    c=proposal(db,('reschedule_task',))
    past=datetime.now(timezone.utc)-timedelta(hours=1)
    values=c.suggestions.copy();values[0]={**values[0],'after':{'scheduled_at':past.isoformat()}};c.suggestions=values;db.commit()
    assert not f.check_read(db,c)['applicable']
    with pytest.raises(HTTPException):f.apply_check(db,c.id,[0])
    monkeypatch.setattr(f,'resolve_role_provider',lambda *args:'qwen')
    monkeypatch.setattr(f,'snapshot_for',lambda *args:'encrypted')
    from types import SimpleNamespace
    def submit(db,*args):db.commit();return SimpleNamespace(id='synthetic')
    monkeypatch.setattr(f,'submit_task',submit)
    new=f.create_check(db,c.goal_id)
    assert new.duplicate_of is None and new.status=='生成中'


@pytest.mark.parametrize('payload',['answer_payload','feedback_payload'])
def test_empty_payload_is_started(db,payload):
    task=db.get(PreparationTask,1);setattr(task,payload,{});db.commit()
    assert not f.unstarted(f.task_snapshot(task))
    with pytest.raises(ValueError):proposal(db)


def test_manual_other_node_is_never_synchronized(db):
    task=db.get(PreparationTask,1)
    node=TimelineNode(application_id=1,node_type='其他',source='手工录入',status='待处理')
    db.add(node);db.flush();task.timeline_node_id=node.id;db.commit()
    c=proposal(db,('reschedule_task',));f.apply_check(db,c.id,[0])
    assert node.scheduled_at is None and node.status=='待处理'
    c=proposal(db);f.apply_check(db,c.id,[0])
    assert node.status=='待处理'


@pytest.mark.parametrize('invalid',['discard','past'])
def test_duplicate_chain_rechecks_when_root_unusable(db,monkeypatch,invalid):
    from types import SimpleNamespace
    c=proposal(db,('reschedule_task',))
    monkeypatch.setattr(f,'resolve_role_provider',lambda *args:'qwen')
    monkeypatch.setattr(f,'snapshot_for',lambda *args:'encrypted')
    monkeypatch.setattr(f,'submit_task',lambda db,*args: db.commit() or SimpleNamespace(id='synthetic'))
    duplicate=f.create_check(db,c.goal_id)
    assert duplicate.duplicate_of==c.id
    if invalid=='discard':f.discard_check(db,c.id)
    else:
        values=c.suggestions.copy();values[0]={**values[0],'after':{'scheduled_at':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()}};c.suggestions=values;db.commit()
    new=f.create_check(db,c.goal_id)
    assert new.duplicate_of is None and new.status=='生成中'


def test_unseen_long_tool_source_cannot_ground_proposal(db,monkeypatch):
    import app.agent_runtime as runtime
    from app.agent_schemas import AgentSource,AgentToolResult
    from app.agent_tools import AgentTool
    c=proposal(db)
    tool=AgentTool('long','long',{'type':'object','properties':{}},'personal',lambda args:AgentToolResult(ok=True,sources=[AgentSource(id='hidden',title='hidden',text='X'*12000),AgentSource(id='visible',title='visible',text='actual evidence')]))
    seen=[]
    monkeypatch.setattr(runtime,'chat_with_tools',lambda *a,**kw:{'content':'','tool_calls':[]})
    def output(messages,**kwargs):
        seen.extend(messages)
        yield '{"suggestions":[]}'
    monkeypatch.setattr(runtime,'chat_stream',output)
    result=runtime.run_chat_agent([], [tool.spec()],{'long':tool},'qwen',{},required_tools=[('long',{})],budget=runtime.AgentBudget(max_tool_result_chars=500))
    assert [source.id for source in result.sources]==['visible']
    assert 'hidden' not in json.dumps(seen)
    raw=json.dumps({'suggestions':[{'operation':'add_practice','title':'x','reason':'x','source_ids':['hidden']}]})
    with pytest.raises(ValueError):f.validate_output(raw,c.input_snapshot,[source.model_dump(mode='json') for source in result.sources])

def test_other_application_feedback_aba_invalidates_proposal(db):
    a=Application(position_id=1);db.add(a);db.flush()
    plan=PlannerSession(application_id=a.id,position_id_snapshot=1,provider='qwen',resume_snapshot='Synthetic',jd_snapshot='Synthetic',available_windows=[],status='已完成')
    db.add(plan);db.flush()
    reviewed=PreparationTask(application_id=a.id,planner_session_id=plan.id,title='Same-position review',status='已完成',answer_payload={'question':'Synthetic'},user_answer='Original',feedback_payload={'rewrite':'Synthetic review'})
    db.add(reviewed);db.commit()
    c=proposal(db)
    _,tools=f.build_toolset(c.input_snapshot)
    text=tools['read_position_practice'].handler({}).sources[0].text
    assert '原题：Synthetic' in text and '原答：Original' in text and '改写：Synthetic review' in text
    assert 'rewrite' not in text
    reviewed.user_answer='Draft';db.commit();reviewed.user_answer='Original';db.commit()
    with pytest.raises(HTTPException):f.apply_check(db,c.id,[0])

@pytest.mark.parametrize('cause',['budget','budget_status','budget_tool','tool'])
def test_analysis_failures_have_distinct_safe_reasons_and_zero_task_writes(db,monkeypatch,cause):
    import app.agent_runtime as runtime
    from app.agent_schemas import AgentToolResult
    from app.agent_tools import AgentTool
    from app.llm.budget import BudgetExceeded
    c=run_environment(db,monkeypatch,{'suggestions':[]})
    before=f.task_snapshot(db.get(PreparationTask,1))
    if cause=='budget':
        def exhausted(*args,**kwargs):raise BudgetExceeded('private provider details')
        monkeypatch.setattr(runtime,'chat_with_tools',exhausted)
    elif cause=='budget_status':
        monkeypatch.setattr(runtime,'chat_with_tools',lambda *args,**kwargs:{'content':'','tool_calls':[{'id':str(index),'name':'read_goal_tasks','arguments':{}} for index in range(9)]})
    else:
        original=f.build_toolset
        def failed_toolset(snapshot):
            _,registry=original(snapshot)
            old=registry['read_goal_tasks']
            registry['read_goal_tasks']=AgentTool(old.name,old.description,old.parameters,old.category,lambda args:AgentToolResult(ok=False,error='读取资料失败',error_kind='budget_exceeded' if cause=='budget_tool' else 'not_found'))
            return [tool.spec() for tool in registry.values()],registry
        monkeypatch.setattr(f,'build_toolset',failed_toolset)
    f.run_check(c.id);db.expire_all();check=db.get(FollowupCheck,c.id)
    text=check.error_message or check.message
    assert ('读取资料失败' if cause=='tool' else '执行预算已耗尽') in text
    assert ('执行预算已耗尽' if cause=='tool' else '读取资料失败') not in text
    assert 'private' not in text
    assert f.task_snapshot(db.get(PreparationTask,1))==before
    assert check.status=='失败'
    assert not check.suggestions and check.execution_result is None


@pytest.mark.parametrize('cause',['budget','tool'])
def test_same_snapshot_failed_check_really_reruns_and_can_propose(db,monkeypatch,cause):
    import app.agent_runtime as runtime
    import app.task_execution as execution
    from app.agent_schemas import AgentToolResult
    from app.agent_tools import AgentTool
    from app.models import TaskDispatch
    from app.task_queue import run_followup_task
    raw={'suggestions':[{'operation':'skip_task','task_id':1,'reason':'真实任务依据','source_ids':['task-1']}]}
    check=run_environment(db,monkeypatch,raw)
    monkeypatch.setattr(execution,'SessionLocal',lambda:Session(db.bind))
    real_toolset=f.build_toolset
    failed=[True];reads=[];model_calls=[]
    def tools(snapshot):
        _,registry=real_toolset(snapshot)
        old=registry['read_goal_tasks']
        def handler(args):
            reads.append(failed[0])
            if failed[0] and cause=='tool':return AgentToolResult(ok=False,error='读取资料失败',error_kind='not_found')
            return old.handler(args)
        registry['read_goal_tasks']=AgentTool(old.name,old.description,old.parameters,old.category,handler)
        return [tool.spec() for tool in registry.values()],registry
    monkeypatch.setattr(f,'build_toolset',tools)
    def model(*args,**kwargs):
        model_calls.append(failed[0])
        if failed[0] and cause=='budget':
            return {'content':'','tool_calls':[{'id':str(index),'name':'read_goal_tasks','arguments':{}} for index in range(9)]}
        return {'content':'','tool_calls':[]}
    monkeypatch.setattr(runtime,'chat_with_tools',model)
    job=execution.prepare_dispatch(db,run_followup_task,check.id);db.commit();job_id=job.id
    execution.execute_job(job_id);db.expire_all();check=db.get(FollowupCheck,check.id)
    assert check.status=='失败' and db.get(TaskDispatch,job_id).status=='failed'
    assert db.get(PreparationTask,1).status=='待处理'
    version=check.business_version;first_reads=len(reads);first_calls=len(model_calls)
    failed[0]=False
    monkeypatch.setattr(f,'resolve_role_provider',lambda *args:'qwen')
    monkeypatch.setattr(f,'snapshot_for',lambda *args:'encrypted')
    def submit(db,task,*args):
        new_job=execution.prepare_dispatch(db,task,*args);db.commit();return new_job
    monkeypatch.setattr(f,'submit_task',submit)
    again=f.create_check(db,check.goal_id)
    assert again.id!=check.id and again.duplicate_of is None and again.business_version==version
    second_job=db.scalars(select(TaskDispatch).where(TaskDispatch.args[0].as_integer()==again.id)).one()
    execution.execute_job(second_job.id);db.expire_all();again=db.get(FollowupCheck,again.id)
    assert again.status=='待确认' and again.suggestions[0]['operation']=='skip_task'
    assert len(reads)>first_reads and len(model_calls)>first_calls
    assert db.get(PreparationTask,1).status=='待处理' and again.execution_result is None


def test_successful_empty_analysis_remains_reusable(db,monkeypatch):
    check=run_environment(db,monkeypatch,{'suggestions':[],'message':'无需调整'})
    f.run_check(check.id);db.expire_all();check=db.get(FollowupCheck,check.id)
    assert check.status=='已完成' and not check.suggestions
    monkeypatch.setattr(f,'resolve_role_provider',lambda *args:'qwen')
    monkeypatch.setattr(f,'snapshot_for',lambda *args:'encrypted')
    def forbidden_submit(*args):raise AssertionError('成功且无变化不应重新派发')
    monkeypatch.setattr(f,'submit_task',forbidden_submit)
    repeated=f.create_check(db,check.goal_id)
    assert repeated.duplicate_of==check.id and repeated.status=='已完成'


@pytest.fixture
def api_client(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.db import get_db
    from app.followup_api import router
    application=FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_db]=lambda:db
    with TestClient(application) as client:
        yield client


def test_followup_openapi_has_response_contract_for_every_route(api_client):
    schema=api_client.get('/openapi.json').json()
    for path,methods in schema['paths'].items():
        for method,operation in methods.items():
            response=operation['responses']['200']['content']['application/json']['schema']
            if path=='/api/followup-goals' and method=='get':
                assert response['type']=='array'
                assert response['items']['$ref'].endswith('/FollowupGoalRead')
            elif path.startswith('/api/followup-proposals') or path.endswith('/check'):
                assert response['$ref'].endswith('/FollowupCheckRead')
            else:
                assert response['$ref'].endswith('/FollowupGoalRead')
    components=schema['components']['schemas']
    check=components['FollowupCheckRead']
    assert check['properties']['sources']['items']['$ref'].endswith('/AgentSource')
    for key in ['resolved_at','message','error_message','duplicate_of','execution_result','agent_run_id']:
        assert key in check['required']
        assert {'type':'null'} in check['properties'][key]['anyOf']
    assert check['properties']['input_snapshot']['type']=='object'
    assert set(components['FollowupHistoryRead']['properties'])=={'id','status','created_at','resolved_at','message','error_message','duplicate_of'}
    assert components['GoalCreate']['additionalProperties'] is False
    assert components['Apply']['additionalProperties'] is False


def test_followup_response_contract_filters_unpublished_fields(db,api_client,monkeypatch):
    check=proposal(db)
    original=f.check_read
    def include_internal(db,value):
        return {**original(db,value),'llm_snapshot':'private','business_version':'private'}
    monkeypatch.setattr(f,'check_read',include_internal)
    single=api_client.get(f'/api/followup-proposals/{check.id}')
    assert single.status_code==200,single.text
    data=single.json()
    assert 'llm_snapshot' not in data and 'business_version' not in data
    assert data['execution_result'] is None and data['agent_run_id'] is None
    assert data['sources'] and data['input_snapshot']==check.input_snapshot
    assert data['suggestions'][0]['before']==check.suggestions[0]['before']
    for response in [api_client.get('/api/followup-goals'),api_client.get(f'/api/followup-goals/{check.goal_id}')]:
        assert response.status_code==200,response.text
        goal=response.json()[0] if isinstance(response.json(),list) else response.json()
        assert 'llm_snapshot' not in goal['latest_check']
        assert set(goal['history'][0])=={'id','status','created_at','resolved_at','message','error_message','duplicate_of'}
        assert goal['last_auto_date'] is None


def test_followup_api_response_models_preserve_write_and_replay_behaviors(db,api_client,monkeypatch):
    import app.db
    import app.agent_runtime as runtime
    created=api_client.post('/api/followup-goals',json={'application_id':1,'timeline_node_id':1})
    assert created.status_code==200,created.text
    goal=created.json();identifier=goal['id']
    assert goal['latest_check'] is None and goal['history']==[]
    assert api_client.post(f'/api/followup-goals/{identifier}/pause').json()['status']=='paused'
    assert api_client.post(f'/api/followup-goals/{identifier}/resume').json()['status']=='active'
    monkeypatch.setattr(f,'resolve_role_provider',lambda *args:'qwen')
    monkeypatch.setattr(f,'snapshot_for',lambda *args:'encrypted')
    monkeypatch.setattr(f,'submit_task',lambda db,*args:db.commit())
    checked=api_client.post(f'/api/followup-goals/{identifier}/check')
    assert checked.status_code==200,checked.text
    check=checked.json();check_id=check['id']
    assert check['status']=='生成中' and check['execution_result'] is None
    monkeypatch.setattr(app.db,'SessionLocal',lambda:Session(db.bind))
    monkeypatch.setattr(f,'config_from_snapshot',lambda *args:{})
    monkeypatch.setattr(runtime,'chat_with_tools',lambda *args,**kwargs:{'content':'','tool_calls':[]})
    raw={'suggestions':[{'operation':'skip_task','task_id':1,'reason':'实际任务依据','source_ids':['task-1']}]}
    monkeypatch.setattr(runtime,'chat_stream',lambda *args,**kwargs:iter([json.dumps(raw)]))
    f.run_check(check_id);db.expire_all()
    ready=api_client.get(f'/api/followup-proposals/{check_id}')
    assert ready.status_code==200 and ready.json()['applicable']
    applied=api_client.post(f'/api/followup-proposals/{check_id}/apply',json={'suggestion_indexes':[0]})
    assert applied.status_code==200,applied.text
    result=applied.json()['execution_result']
    assert set(result)=={'suggestion_indexes','actions','applied_at'}
    assert result['actions'][0]['operation']=='skip_task' and result['actions'][0]['after']['status']=='已跳过'
    replay=api_client.post(f'/api/followup-proposals/{check_id}/apply',json={'suggestion_indexes':[0]})
    assert replay.status_code==200 and replay.json()['execution_result']==result
    assert api_client.post(f'/api/followup-proposals/{check_id}/discard').status_code==409
    assert api_client.post('/api/followup-goals',json={'application_id':1,'timeline_node_id':1,'status':'paused'}).status_code==422


def test_followup_discard_response_contract(db,api_client):
    check=proposal(db)
    response=api_client.post(f'/api/followup-proposals/{check.id}/discard')
    assert response.status_code==200,response.text
    assert response.json()['status']=='已丢弃'
    assert response.json()['execution_result'] is None and not response.json()['applicable']


@pytest.mark.parametrize('failure_stage',['provider','snapshot'])
def test_auto_missing_model_records_one_daily_failure_and_manual_can_retry(db,api_client,monkeypatch,failure_stage):
    from app.llm.config_store import LlmConfigError
    from app.models import FollowupGoal,TaskDispatch
    import app.agent_runtime as runtime
    goal=f.create_goal(db,1,1)
    def missing(*args):raise LlmConfigError('private config details')
    monkeypatch.setattr(f,'resolve_role_provider',missing if failure_stage=='provider' else lambda *args:'qwen')
    monkeypatch.setattr(f,'snapshot_for',missing)
    def no_model(*args,**kwargs):raise AssertionError('缺配置不得调用模型')
    monkeypatch.setattr(runtime,'chat_with_tools',no_model)
    monkeypatch.setattr(runtime,'chat_stream',no_model)
    at=datetime.now(timezone.utc)
    first=f.create_check(db,goal.id,automatic=True,at=at)
    assert first.status=='失败' and first.resolved_at is not None
    assert first.provider=='unconfigured' and first.llm_snapshot is None and first.queue_task_id is None
    assert '请先配置' in first.error_message and 'private' not in first.error_message
    assert db.get(FollowupGoal,goal.id).last_auto_date==at.astimezone(f.SHANGHAI).date()
    assert f.create_check(db,goal.id,automatic=True,at=at+timedelta(minutes=1)) is None
    assert len(db.scalars(select(FollowupCheck)).all())==1 and not db.scalars(select(TaskDispatch)).all()
    visible=api_client.get(f'/api/followup-goals/{goal.id}')
    assert visible.status_code==200 and visible.json()['latest_check']['status']=='失败'
    assert api_client.post(f'/api/followup-goals/{goal.id}/check').status_code==422
    monkeypatch.setattr(f,'resolve_role_provider',lambda *args:'qwen')
    monkeypatch.setattr(f,'snapshot_for',lambda *args:'encrypted')
    dispatched=[]
    def submit(db,task,*args):dispatched.append(args);db.commit()
    monkeypatch.setattr(f,'submit_task',submit)
    retried=api_client.post(f'/api/followup-goals/{goal.id}/check')
    assert retried.status_code==200,retried.text
    assert retried.json()['id']!=first.id and retried.json()['status']=='生成中'
    assert retried.json()['duplicate_of'] is None and len(dispatched)==1
    assert first.business_version==db.get(FollowupCheck,retried.json()['id']).business_version


@pytest.mark.parametrize('paired',[True,False])
def test_scheduling_tool_excludes_unpaired_content_after_review_retry_failure(db,paired):
    task=db.get(PreparationTask,1)
    task.answer_payload={'question':'未配对的新问题','reference_answer':'未配对的参考答案'}
    task.user_answer='重试失败的新自答'
    task.feedback_payload={'strengths':['上一轮优点'],'gaps':['上一轮不足'],'rewrite':'上一轮点评改写'}
    task.practice_status='failed';task.practice_error='重试点评失败'
    if paired:
        task.feedback_question_snapshot='真正已点评的原题'
        task.feedback_answer_snapshot='真正已点评的原答'
    db.commit()
    goal=f.create_goal(db,1,1);snapshot=f.input_snapshot(db,goal)
    assert snapshot['tasks'][0]['user_answer']=='重试失败的新自答'
    assert snapshot['tasks'][0]['feedback_payload']['rewrite']=='上一轮点评改写'
    _,tools=f.build_toolset(snapshot)
    scheduling=tools['read_goal_tasks'].handler({})
    data=scheduling.data['tasks'][0]
    assert set(data)=={'id','title','category','status','practice_status','priority','estimated_minutes','scheduled_at','ends_at','planned_date','deferred_until','executing_job','unstarted','has_generated_answer','has_user_answer','has_feedback'}
    assert not data['unstarted'] and data['has_generated_answer'] and data['has_user_answer'] and data['has_feedback']
    encoded=scheduling.model_dump_json()
    for private in ['未配对的新问题','未配对的参考答案','重试失败的新自答','上一轮优点','上一轮不足','上一轮点评改写','真正已点评的原题','真正已点评的原答']:
        assert private not in encoded
    feedback=tools['read_position_practice'].handler({})
    if paired:
        record=feedback.data['practice'][0]
        assert record['question']=='真正已点评的原题' and record['user_answer']=='真正已点评的原答'
        assert record['feedback_payload']['rewrite']=='上一轮点评改写'
        assert feedback.sources[0].id=='practice-1'
        assert '真正已点评的原答' in feedback.sources[0].text
        assert '重试失败的新自答' not in feedback.model_dump_json()
        assert '未配对的新问题' not in feedback.model_dump_json()
    else:
        assert feedback.data['practice']==[] and feedback.sources==[]


def test_scheduling_content_flags_treat_empty_payloads_as_existing(db):
    task=db.get(PreparationTask,1);task.answer_payload={};task.feedback_payload={};task.user_answer='  '
    db.commit()
    _,tools=f.build_toolset(f.input_snapshot(db,f.create_goal(db,1,1)))
    data=tools['read_goal_tasks'].handler({}).data['tasks'][0]
    assert data['has_generated_answer'] and data['has_feedback']
    assert not data['has_user_answer'] and not data['unstarted']
