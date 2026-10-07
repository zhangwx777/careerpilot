"""Reliable local task dispatch; no model credentials are stored in job arguments."""

import asyncio
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import logging
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.llm.budget import BudgetExceeded, execution_budget
from app.models import AgentRun, IntelChatMessage, IntelSession, ParseSession, PlannerSession, Position, PreparationTask, TaskDispatch

logger = logging.getLogger(__name__)
_active_dispatch = ContextVar("active_dispatch", default=None)
LEASE_SECONDS = 60
SESSION_TASKS = {
    "careerpilot.intel_session": (IntelSession, "聚合中", "失败"),
    "careerpilot.planner_session": (PlannerSession, "生成中", "失败"),
    "careerpilot.parse_session": (ParseSession, "解析中", "解析失败"),
}


class TaskLeaseLost(RuntimeError):
    pass


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def assert_dispatch_owner(db) -> None:
    """Lock ownership through the caller's result transaction; direct workflows stay usable."""
    active = _active_dispatch.get()
    if active is None:
        return
    job = db.scalar(select(TaskDispatch).where(TaskDispatch.id == active[0]).with_for_update())
    if job is None or job.status != "running" or job.lease_token != active[1]:
        raise TaskLeaseLost("任务已由新的执行接管")


def prepare_dispatch(db, task, *args) -> TaskDispatch:
    if task.name == "careerpilot.rebuild_insight" and (not isinstance(args[2], str) or not args[2]):
        raise ValueError("后台模型配置必须保存加密快照")
    job = TaskDispatch(task_name=task.name, args=list(args))
    db.add(job)
    db.flush()
    return job


def submit_task(db, task, *args) -> TaskDispatch:
    job = prepare_dispatch(db, task, *args)
    db.commit()
    publish_dispatch(job.id)
    return job


def publish_dispatch(job_id: str) -> None:
    from app.task_queue import execute_dispatch

    with SessionLocal() as db:
        job = db.scalar(select(TaskDispatch).where(TaskDispatch.id == job_id).with_for_update())
        if job is None or job.status != "pending":
            return
        if settings.celery_task_always_eager:
            job.status = "dispatched"
            job.heartbeat_at = datetime.now(timezone.utc)
            db.commit()
            execute_dispatch.apply_async(args=[job_id], task_id=job_id, queue=settings.celery_queue)
            return
        try:
            execute_dispatch.apply_async(args=[job.id], task_id=job.id, queue=settings.celery_queue)
        except Exception:
            job.error_message = "任务等待队列恢复，系统会自动重新派发"
            job.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=10)
        else:
            job.status = "dispatched"
            job.heartbeat_at = datetime.now(timezone.utc)
            job.error_message = None
        db.commit()


def _reset_domain(db, job) -> None:
    if job.task_name == "careerpilot.practice":
        task = db.get(PreparationTask, job.args[0])
        if task is None or task.practice_status == "idle":
            return False
        task.practice_status = job.args[1]
        task.practice_error = None
    elif job.task_name == "careerpilot.intel_chat":
        message = db.get(IntelChatMessage, job.args[0])
        run = db.scalar(select(AgentRun).where(AgentRun.assistant_message_id == job.args[0]).with_for_update())
        if message is not None and run is not None:
            if message.status == "已完成":
                return False
            message.status = "生成中"
            message.source_ids = []
            run.status = "retrying"
            run.stage = "等待重试"
            run.error_kind = None
            run.error_message = None
            run.finished_at = None
        else:
            return False
    elif job.task_name in SESSION_TASKS:
        model, pending, _ = SESSION_TASKS[job.task_name]
        item = db.get(model, job.args[0])
        if item is None or item.status in {"待确认", "待裁决", "已完成", "已确认", "已丢弃"}:
            return False
        if item is not None and item.status in {pending, "失败", "解析失败"}:
            item.status = pending
            item.error_message = None
            item.resolved_at = None
    elif job.task_name == "careerpilot.rebuild_insight":
        position = db.get(Position, job.args[0])
        if position is None or position.intel_revision != job.args[3] or (position.intel_insight or {}).get("status") in {"已生成", "暂无资料"}:
            return False
    return True


def _domain_failure(db, job):
    if job.task_name == "careerpilot.practice":
        task = db.get(PreparationTask, job.args[0])
        if task is not None and task.practice_status == "failed":
            return task.practice_error or "练习生成失败", False
    elif job.task_name == "careerpilot.intel_chat":
        run = db.scalar(select(AgentRun).where(AgentRun.assistant_message_id == job.args[0]))
        if run is not None and run.status == "failed":
            return run.error_message or "问答执行失败", run.last_error_kind in {"timeout", "unavailable", "rate_limit", "search_timeout", "search_failed"}
    elif job.task_name in SESSION_TASKS:
        model, _, failed = SESSION_TASKS[job.task_name]
        item = db.get(model, job.args[0])
        if item is not None and item.status == failed:
            return item.error_message or "后台分析失败", False
    elif job.task_name == "careerpilot.rebuild_insight":
        position = db.get(Position, job.args[0])
        if position is not None and position.intel_revision == job.args[3] and (position.intel_insight or {}).get("status") == "失败":
            return "岗位洞察生成失败", False
    return None, False


def recover_dispatches() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        jobs = db.scalars(
            select(TaskDispatch).where(TaskDispatch.status.in_(["pending", "dispatched", "running"]))
            .with_for_update(skip_locked=True)
        ).all()
        pending_ids = []
        for job in jobs:
            if job.status != "pending":
                heartbeat = job.heartbeat_at
                if heartbeat is not None and _utc(heartbeat) > now - timedelta(seconds=LEASE_SECONDS):
                    continue
                job.lease_token = None
                failure, retryable = _domain_failure(db, job)
                if failure and not retryable:
                    job.status = "failed"
                    job.error_message = failure
                    continue
                if not _reset_domain(db, job):
                    job.status = "completed"
                    continue
                if job.attempt > settings.celery_max_retries:
                    job.status = "failed"
                    job.error_message = "任务执行中断，请重新发起或重试"
                    _mark_interrupted(db, job)
                    continue
                job.status = "pending"
                job.next_attempt_at = now
            if _utc(job.next_attempt_at) <= now:
                pending_ids.append(job.id)
        db.commit()
    for job_id in pending_ids:
        publish_dispatch(job_id)
    recover_legacy_sessions()


def recover_legacy_sessions() -> None:
    """Pre-upgrade records without an outbox become actionable failures, never blind replays."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=settings.celery_task_timeout + LEASE_SECONDS)
    with SessionLocal() as db:
        for task_name, (model, pending, failed) in SESSION_TASKS.items():
            has_dispatch = select(TaskDispatch.id).where(TaskDispatch.task_name == task_name, TaskDispatch.args[0].as_integer() == model.id).exists()
            items = db.scalars(select(model).where(model.status == pending, model.created_at < cutoff, ~has_dispatch).with_for_update(skip_locked=True)).all()
            for item in items:
                item.status = failed
                item.error_message = "旧任务执行中断，请重试；原始资料仍已保留"
                item.resolved_at = now
        has_dispatch = select(TaskDispatch.id).where(TaskDispatch.task_name == "careerpilot.intel_chat", TaskDispatch.args[0].as_integer() == AgentRun.assistant_message_id).exists()
        runs = db.scalars(select(AgentRun).join(IntelChatMessage, IntelChatMessage.id == AgentRun.assistant_message_id).where(AgentRun.status.in_(["queued", "running", "retrying"]), func.coalesce(AgentRun.heartbeat_at, IntelChatMessage.created_at) < cutoff, ~has_dispatch).with_for_update(skip_locked=True)).all()
        for run in runs:
            message = db.get(IntelChatMessage, run.assistant_message_id)
            if message.status == "生成中":
                message.status = "失败"
                message.source_ids = []
            run.status = "failed"
            run.error_kind = "worker_lost"
            run.error_message = "旧问答任务执行中断，请重试"
            run.finished_at = now
        for position in db.scalars(select(Position).where(Position.intel_revision == 0, Position.intel_insight["status"].as_string() == "生成中").with_for_update(skip_locked=True)).all():
            position.intel_insight = {"status": "失败", "error_message": "旧洞察生成中断，请重新生成"}
        db.commit()


def _mark_interrupted(db, job) -> None:
    if job.task_name == "careerpilot.practice":
        task = db.get(PreparationTask, job.args[0])
        if task is not None and task.practice_status in {"answer", "review"}:
            task.practice_status = "failed"
            task.practice_error = job.error_message
    elif job.task_name == "careerpilot.intel_chat":
        message = db.get(IntelChatMessage, job.args[0])
        run = db.scalar(select(AgentRun).where(AgentRun.assistant_message_id == job.args[0]))
        if message is not None and message.status == "生成中":
            message.status = "失败"
        if run is not None and run.status in {"queued", "running", "retrying"}:
            run.status = "failed"
            run.error_kind = "worker_lost"
            run.error_message = job.error_message
            run.finished_at = datetime.now(timezone.utc)
    elif job.task_name in SESSION_TASKS:
        model, _, failed = SESSION_TASKS[job.task_name]
        item = db.get(model, job.args[0])
        if item is not None and item.status in {"生成中", "聚合中", "解析中"}:
            item.status = failed
            item.error_message = job.error_message
            item.resolved_at = datetime.now(timezone.utc)
    elif job.task_name == "careerpilot.rebuild_insight":
        position = db.scalar(select(Position).where(Position.id == job.args[0]).with_for_update().execution_options(populate_existing=True))
        if position is not None and position.intel_revision == job.args[3] and (position.intel_insight or {}).get("status") == "生成中":
            position.intel_insight = {"status": "失败", "error_message": job.error_message}


def _heartbeat(job_id: str, token: str, stop: Event) -> None:
    while not stop.wait(10):
        try:
            with SessionLocal() as db:
                job = db.scalar(select(TaskDispatch).where(TaskDispatch.id == job_id).with_for_update())
                if job is None or job.status != "running" or job.lease_token != token:
                    return
                job.heartbeat_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            logger.warning("任务心跳未能更新，执行结果仍需验证所有权")


def execute_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.scalar(select(TaskDispatch).where(TaskDispatch.id == job_id).with_for_update())
        if job is None or job.status not in {"pending", "dispatched"}:
            return
        token = str(uuid4())
        job.status = "running"
        job.lease_token = token
        job.attempt += 1
        job.heartbeat_at = datetime.now(timezone.utc)
        task_name, args = job.task_name, job.args
        db.commit()
    context_token = _active_dispatch.set((job_id, token))
    stop = Event()
    heartbeat = Thread(target=_heartbeat, args=(job_id, token, stop), daemon=True)
    heartbeat.start()
    error = None
    try:
        with execution_budget(6 if task_name == "careerpilot.intel_chat" else 12, 90 if task_name == "careerpilot.intel_chat" else settings.celery_task_timeout - 15) as limits:
            if task_name == "careerpilot.practice":
                from app.planner_api import _run_practice
                _run_practice(*args)
            elif task_name == "careerpilot.intel_chat":
                from app.intel_api import _run_intel_chat
                _run_intel_chat(*args)
            elif task_name == "careerpilot.intel_session":
                from app.intel_api import _run_intel_session
                _run_intel_session(*args)
            elif task_name == "careerpilot.planner_session":
                from app.planner_api import _run_planner_session
                _run_planner_session(*args)
            elif task_name == "careerpilot.parse_session":
                from app.task_queue import run_parse_session_task
                run_parse_session_task.run(*args)
            elif task_name == "careerpilot.rebuild_insight":
                from app.intel_insight import rebuild_position_insight
                from app.llm.config_store import config_from_snapshot
                position_id, provider, snapshot, revision = args
                with SessionLocal() as db:
                    config = config_from_snapshot(snapshot, db, provider)
                rebuild_position_insight(position_id, provider, SessionLocal, llm_config=config, expected_revision=revision)
            else:
                raise ValueError("未知后台任务")
    except TaskLeaseLost:
        return
    except BudgetExceeded as exc:
        error = str(exc)
    except Exception:
        error = "后台任务执行失败，请重试"
    finally:
        stop.set()
        heartbeat.join(timeout=2)
        _active_dispatch.reset(context_token)
    with SessionLocal() as db:
        job = db.scalar(select(TaskDispatch).where(TaskDispatch.id == job_id).with_for_update())
        if job is None or job.lease_token != token or job.status != "running":
            return
        failure, retryable = _domain_failure(db, job)
        error = error or failure
        job.metrics = {**limits.snapshot(), "attempt": job.attempt}
        job.status = "failed" if error else "completed"
        job.error_message = error
        job.heartbeat_at = datetime.now(timezone.utc)
        if retryable and job.attempt <= settings.celery_max_retries:
            job.status = "pending"
            job.lease_token = None
            job.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=min(30, 2 ** job.attempt))
            _reset_domain(db, job)
        elif error:
            _mark_interrupted(db, job)
        db.commit()


async def recovery_loop() -> None:
    while True:
        await asyncio.sleep(10)
        try:
            await asyncio.to_thread(recover_dispatches)
        except Exception:
            logger.warning("后台任务恢复暂不可用，将在下次巡检重试")
