"""Celery application and task helpers for long-running LLM workflows."""

from __future__ import annotations

from celery import Celery

from app.config import settings


class TaskQueueUnavailable(RuntimeError):
    """The API cannot submit a durable task to the configured broker."""


celery_app = Celery(
    "careerpilot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_track_started=True,
    task_time_limit=settings.celery_task_timeout,
    task_soft_time_limit=max(30, settings.celery_task_timeout - 15),
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=settings.celery_task_always_eager,
)


def queue_available() -> bool:
    """Check Redis broker connectivity without raising into health endpoints."""
    try:
        with celery_app.connection_for_read() as connection:
            connection.ensure_connection(max_retries=1)
        return True
    except Exception:
        return False


@celery_app.task(name="careerpilot.intel_chat", bind=True, max_retries=settings.celery_max_retries)
def run_intel_chat_task(self, message_id: int, application_id: int, provider: str, question: str) -> None:
    from app.intel_api import _run_intel_chat
    from app.db import SessionLocal
    from app.models import AgentRun, IntelChatMessage

    _run_intel_chat(message_id, application_id, provider, question)
    with SessionLocal() as db:
        run = db.query(AgentRun).filter(AgentRun.assistant_message_id == message_id).first()
        if run is None or run.status != "failed":
            return
        if run.last_error_kind not in {"timeout", "unavailable", "rate_limit", "search_timeout", "search_failed"}:
            return
        if self.request.retries >= settings.celery_max_retries:
            return
        assistant = db.get(IntelChatMessage, message_id)
        if assistant is not None:
            assistant.status = "生成中"
        run.status = "retrying"
        db.commit()
    raise self.retry(countdown=min(30, 2 ** (self.request.retries + 1)))


@celery_app.task(name="careerpilot.intel_session", bind=True, max_retries=settings.celery_max_retries)
def run_intel_session_task(
    self,
    session_id: int,
    thread_id: str,
    provider: str,
    query: str,
    user_paste: str | None,
    supplement_web: bool,
    round_type: str,
    image_texts: list[dict],
) -> None:
    from app.intel_api import _run_intel_session

    _run_intel_session(session_id, thread_id, provider, query, user_paste, supplement_web, round_type, image_texts)


@celery_app.task(name="careerpilot.planner_session", bind=True, max_retries=settings.celery_max_retries)
def run_planner_session_task(self, session_id: int, thread_id: str) -> None:
    from app.planner_api import _run_planner_session

    _run_planner_session(session_id, thread_id)


@celery_app.task(name="careerpilot.rebuild_insight", bind=True, max_retries=settings.celery_max_retries)
def rebuild_insight_task(self, position_id: int, provider: str, llm_config: dict | None = None) -> None:
    from app.db import SessionLocal
    from app.intel_insight import rebuild_position_insight

    rebuild_position_insight(position_id, provider, SessionLocal, llm_config=llm_config)


def enqueue(task, *args, **kwargs):
    try:
        return task.apply_async(args=args, kwargs=kwargs)
    except Exception as exc:
        # In eager mode this exception is the task body itself, not a broker
        # submission failure; preserve it for tests and local diagnostics.
        if settings.celery_task_always_eager:
            raise
        # Do not leak broker credentials or Kombu internals through the API.
        raise TaskQueueUnavailable(
            "Agent 任务队列不可用，请启动 Redis 和 CareerPilot worker"
        ) from exc


@celery_app.task(name="careerpilot.dispatch")
def execute_dispatch(job_id: str) -> None:
    from app.task_execution import execute_job

    execute_job(job_id)


@celery_app.task(name="careerpilot.parse_session")
def run_parse_session_task(session_id: int, thread_id: str, raw_text: str, provider: str, requested_at: str) -> None:
    from datetime import datetime
    from app.phase3_api import _run_parse_session

    _run_parse_session(session_id, thread_id, raw_text, provider, datetime.fromisoformat(requested_at))
