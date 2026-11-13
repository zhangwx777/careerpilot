from typing import Annotated
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import FollowupGoal, FollowupCheck
from app import followup as service
from app.llm.config_store import LlmConfigError
from app.followup_schemas import Apply, GoalCreate, FollowupCheckRead, FollowupGoalRead

router = APIRouter(prefix='/api', tags=['followup'])
Db = Annotated[Session, Depends(get_db)]

@router.get('/followup-goals', response_model=list[FollowupGoalRead])
def list_goals(db: Db, application_id: int | None = Query(default=None,gt=0)):
    query=select(FollowupGoal).order_by(FollowupGoal.id.desc())
    if application_id is not None:
        query=query.where(FollowupGoal.application_id==application_id)
    return [service.goal_read(db,goal) for goal in db.scalars(query).all()]

@router.post('/followup-goals', response_model=FollowupGoalRead)
def create_goal(payload: GoalCreate,db: Db):
    return service.goal_read(db,service.create_goal(db,payload.application_id,payload.timeline_node_id))

@router.get('/followup-goals/{identifier}', response_model=FollowupGoalRead)
def get_goal(identifier: int,db: Db):
    goal=db.get(FollowupGoal,identifier)
    if goal is None:
        from fastapi import HTTPException
        raise HTTPException(404,'目标不存在')
    return service.goal_read(db,goal)

@router.post('/followup-goals/{identifier}/pause', response_model=FollowupGoalRead)
def pause(identifier: int,db: Db):
    return service.goal_read(db,service.set_goal_status(db,identifier,'paused'))

@router.post('/followup-goals/{identifier}/resume', response_model=FollowupGoalRead)
def resume(identifier: int,db: Db):
    return service.goal_read(db,service.set_goal_status(db,identifier,'active'))

@router.post('/followup-goals/{identifier}/check', response_model=FollowupCheckRead)
def check(identifier: int,db: Db):
    try:
        return service.check_read(db,service.create_check(db,identifier))
    except LlmConfigError:
        raise HTTPException(422,'请先配置可用的规划模型') from None

@router.get('/followup-proposals/{identifier}', response_model=FollowupCheckRead)
def get_proposal(identifier: int,db: Db):
    proposal=db.get(FollowupCheck,identifier)
    if proposal is None:
        from fastapi import HTTPException
        raise HTTPException(404,'检查不存在')
    return service.check_read(db,proposal)

@router.post('/followup-proposals/{identifier}/apply', response_model=FollowupCheckRead)
def apply(identifier: int,payload: Apply,db: Db):
    return service.check_read(db,service.apply_check(db,identifier,payload.suggestion_indexes))

@router.post('/followup-proposals/{identifier}/discard', response_model=FollowupCheckRead)
def discard(identifier: int,db: Db):
    return service.check_read(db,service.discard_check(db,identifier))
