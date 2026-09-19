from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import to_psycopg_connection_string
from app.models import PlannerSession, PreparationTask, TimelineNode
from app.planner import schedule_tasks, validate_task_intervals
from app.planner_parsing import extract_plan as _extract_action_plan
from app.planner_parsing import extract_scheduled_plan as _extract_scheduled_plan
from app.planner_schemas import AvailabilityWindow, PlannerConfirmation, PlannerDraft, ScheduledTask
from app.llm.config_store import config_from_snapshot


class PlannerGraphError(Exception):
    pass


# Kept as a public compatibility seam for integrations/tests that used to
# patch ``app.planner_graph.extract_plan``. In production the graph uses the
# dedicated schedule contract; a patched legacy seam is honored during tests
# and downstream embedding.
extract_plan = _extract_action_plan


def extract_scheduled_plan(*args, **kwargs):
    if extract_plan is not _extract_action_plan:
        return extract_plan(*args, **kwargs)
    return _extract_scheduled_plan(*args, **kwargs)


class PlannerGraphState(TypedDict, total=False):
    planner_session_id: int
    provider: str
    llm_snapshot: str | None
    resume_text: str
    jd_text: str
    intel_snapshot: list
    available_windows: list
    draft: dict
    confirmation: dict


def build_planner_graph(checkpointer: PostgresSaver, session_factory: Callable[[], Session]):
    def collect_context(state: PlannerGraphState):
        with session_factory() as db:
            item = db.get(PlannerSession, state["planner_session_id"])
            if item is None:
                raise PlannerGraphError("备战计划会话不存在")
            return {
                "provider": item.provider,
                "llm_snapshot": item.llm_snapshot,
                "resume_text": item.resume_snapshot,
                "jd_text": item.jd_snapshot,
                "intel_snapshot": item.intel_snapshot,
                "available_windows": item.available_windows,
            }

    def analyze_gaps(state: PlannerGraphState):
        draft = extract_scheduled_plan(
            state["resume_text"],
            state["jd_text"],
            state["intel_snapshot"],
            state["provider"],
            llm_config=config_from_snapshot(
                state.get("llm_snapshot"), None, state["provider"]
            ),
        )
        return {"draft": draft.model_dump(mode="json")}

    def schedule_node(state: PlannerGraphState):
        draft = PlannerDraft.model_validate(state["draft"])
        windows = [AvailabilityWindow.model_validate(item) for item in state["available_windows"]]
        with session_factory() as db:
            busy_nodes = list(
                db.scalars(
                    select(TimelineNode).where(
                        TimelineNode.status == "待处理",
                        TimelineNode.scheduled_at.is_not(None),
                    )
                ).all()
            )
        tasks = schedule_tasks(draft.tasks, windows, busy_nodes, datetime.now(timezone.utc))
        return {"draft": {"gaps": [gap.model_dump(mode="json") for gap in draft.gaps], "tasks": [task.model_dump(mode="json") for task in tasks]}}

    def review_node(state: PlannerGraphState):
        with session_factory() as db:
            item = db.get(PlannerSession, state["planner_session_id"])
            if item is None:
                raise PlannerGraphError("备战计划会话不存在")
            item.draft_payload = state["draft"]
            item.status = "待确认"
            db.commit()
        confirmation = interrupt({"planner_session_id": state["planner_session_id"], "draft": state["draft"]})
        return {"confirmation": confirmation}

    def persist_node(state: PlannerGraphState):
        confirmation = PlannerConfirmation.model_validate(state["confirmation"])
        with session_factory() as db:
            with db.begin():
                item = db.scalar(
                    select(PlannerSession)
                    .where(PlannerSession.id == state["planner_session_id"])
                    .with_for_update()
                )
                if item is None:
                    raise PlannerGraphError("备战计划会话不存在")
                if item.status == "已确认":
                    return {}
                if item.status != "待确认":
                    raise PlannerGraphError("当前备战计划会话不能确认")
                busy_nodes = list(
                    db.scalars(
                        select(TimelineNode).where(
                            TimelineNode.status == "待处理",
                            TimelineNode.scheduled_at.is_not(None),
                        )
                    ).all()
                )
                validate_task_intervals(confirmation.tasks, busy_nodes)
                for task in confirmation.tasks:
                    node = TimelineNode(
                        application_id=item.application_id,
                        node_type="其他",
                        scheduled_at=task.scheduled_at,
                        ends_at=task.ends_at,
                        status="待处理",
                        source="备战计划",
                        title=task.title,
                        detail=task.detail,
                    )
                    db.add(node)
                    db.flush()
                    db.add(
                        PreparationTask(
                            planner_session_id=item.id,
                            application_id=item.application_id,
                            title=task.title,
                            detail=task.detail,
                            gap=task.gap,
                            source_ids=task.source_ids,
                            evidence=[item.model_dump(mode="json") for item in task.evidence],
                            scheduled_at=task.scheduled_at,
                            ends_at=task.ends_at,
                            estimated_minutes=task.estimated_minutes,
                            timeline_node_id=node.id,
                        )
                    )
                item.draft_payload = {"gaps": state["draft"].get("gaps", []), "tasks": [task.model_dump(mode="json") for task in confirmation.tasks]}
                item.status = "已确认"
                item.resolved_at = datetime.now(timezone.utc)
            return {}

    builder = StateGraph(PlannerGraphState)
    builder.add_node("collect_context", collect_context)
    builder.add_node("analyze_gaps", analyze_gaps)
    builder.add_node("schedule", schedule_node)
    builder.add_node("review", review_node)
    builder.add_node("persist", persist_node)
    builder.add_edge(START, "collect_context")
    builder.add_edge("collect_context", "analyze_gaps")
    builder.add_edge("analyze_gaps", "schedule")
    builder.add_edge("schedule", "review")
    builder.add_edge("review", "persist")
    builder.add_edge("persist", END)
    return builder.compile(checkpointer=checkpointer)


def start_planner_graph(session_id: int, thread_id: str, database_url: str, session_factory: sessionmaker):
    with PostgresSaver.from_conn_string(to_psycopg_connection_string(database_url)) as checkpointer:
        return build_planner_graph(checkpointer, session_factory).invoke(
            {"planner_session_id": session_id},
            {"configurable": {"thread_id": thread_id}},
        )


def resume_planner_graph(thread_id: str, confirmation: PlannerConfirmation, database_url: str, session_factory: sessionmaker):
    with PostgresSaver.from_conn_string(to_psycopg_connection_string(database_url)) as checkpointer:
        return build_planner_graph(checkpointer, session_factory).invoke(
            Command(resume=confirmation.model_dump(mode="json")),
            {"configurable": {"thread_id": thread_id}},
        )
