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
from app.models import Application, ParseSession, TimelineNode
from app.parsing import extract_notice
from app.phase3_schemas import ParseConfirmation


class ParseGraphState(TypedDict, total=False):
    parse_session_id: int
    raw_text: str
    requested_at: str
    extraction: dict
    confirmation: dict
    timeline_node_id: int


class ParseGraphStateError(Exception):
    pass


def build_parse_graph(
    checkpointer: PostgresSaver,
    session_factory: Callable[[], Session],
):
    def extract_node(state: ParseGraphState):
        extraction = extract_notice(
            state["raw_text"], datetime.fromisoformat(state["requested_at"])
        )
        payload = extraction.model_dump(mode="json")
        with session_factory() as db:
            parse_session = db.get(ParseSession, state["parse_session_id"])
            if parse_session is None:
                raise ParseGraphStateError("解析会话不存在")
            parse_session.extracted_payload = payload
            parse_session.status = "待确认"
            db.commit()
        return {"extraction": payload}

    def review_interrupt_node(state: ParseGraphState):
        confirmation = interrupt(
            {
                "parse_session_id": state["parse_session_id"],
                "extraction": state["extraction"],
            }
        )
        return {"confirmation": confirmation}

    def persist_node(state: ParseGraphState):
        confirmation = ParseConfirmation.model_validate(state["confirmation"])
        with session_factory() as db:
            with db.begin():
                parse_session = db.scalar(
                    select(ParseSession)
                    .where(ParseSession.id == state["parse_session_id"])
                    .with_for_update()
                )
                if parse_session is None:
                    raise ParseGraphStateError("解析会话不存在")
                if parse_session.status == "已确认":
                    return {"timeline_node_id": parse_session.timeline_node_id}
                if parse_session.status != "待确认":
                    raise ParseGraphStateError("当前解析会话不能确认")
                if db.get(Application, confirmation.application_id) is None:
                    raise ParseGraphStateError("投递记录不存在")

                timeline_node = TimelineNode(
                    application_id=confirmation.application_id,
                    node_type=confirmation.node_type,
                    scheduled_at=confirmation.scheduled_at,
                    ends_at=confirmation.ends_at,
                    status="待处理",
                    source=confirmation.source,
                )
                db.add(timeline_node)
                db.flush()
                parse_session.confirmed_payload = confirmation.model_dump(mode="json")
                parse_session.status = "已确认"
                parse_session.timeline_node_id = timeline_node.id
                parse_session.resolved_at = datetime.now(timezone.utc)
            return {"timeline_node_id": timeline_node.id}

    builder = StateGraph(ParseGraphState)
    builder.add_node("extract", extract_node)
    builder.add_node("review_interrupt", review_interrupt_node)
    builder.add_node("persist", persist_node)
    builder.add_edge(START, "extract")
    builder.add_edge("extract", "review_interrupt")
    builder.add_edge("review_interrupt", "persist")
    builder.add_edge("persist", END)
    return builder.compile(checkpointer=checkpointer)


def start_parse_graph(
    parse_session_id: int,
    thread_id: str,
    raw_text: str,
    requested_at: datetime,
    database_url: str,
    session_factory: sessionmaker,
):
    config = {"configurable": {"thread_id": thread_id}}
    with PostgresSaver.from_conn_string(
        to_psycopg_connection_string(database_url)
    ) as checkpointer:
        graph = build_parse_graph(checkpointer, session_factory)
        return graph.invoke(
            {
                "parse_session_id": parse_session_id,
                "raw_text": raw_text,
                "requested_at": requested_at.isoformat(),
            },
            config,
        )


def resume_parse_graph(
    thread_id: str,
    confirmation: ParseConfirmation,
    database_url: str,
    session_factory: sessionmaker,
):
    config = {"configurable": {"thread_id": thread_id}}
    with PostgresSaver.from_conn_string(
        to_psycopg_connection_string(database_url)
    ) as checkpointer:
        graph = build_parse_graph(checkpointer, session_factory)
        return graph.invoke(
            Command(resume=confirmation.model_dump(mode="json")), config
        )
