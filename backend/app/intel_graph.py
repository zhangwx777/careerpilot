from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
import json
from operator import add
from typing import Annotated, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.anysearch import search
from app.db import to_psycopg_connection_string
from app.intel_parsing import extract_intel
from app.intel_schemas import Fact, IntelExtraction, IntelPayload, SourceRecord
from app.llm.provider import chat
from app.models import IntelSession, InterviewIntel


class IntelGraphError(Exception):
    pass


class IntelGraphState(TypedDict, total=False):
    intel_session_id: int
    provider: str
    query: str
    user_paste: str | None
    sources: Annotated[list[dict], add]
    extractions: dict[str, dict]
    search_attempt: int
    payload: dict
    confidence: float
    reflection_count: int
    resolutions: dict
    needs_review: bool
    critic_rejected: bool
    critic_feedback: str


def _merge(extractions: list[IntelExtraction], sources: list[SourceRecord]) -> IntelPayload:
    rounds = []
    seen = set()
    topics: dict[str, set[str]] = defaultdict(set)
    difficulty: dict[str, set[str]] = defaultdict(set)
    for extraction in extractions:
        for item in extraction.rounds:
            key = (item.round_type, item.duration_minutes, tuple(f.value for f in item.question_types))
            if key not in seen:
                rounds.append(item)
                seen.add(key)
        for fact in extraction.frequent_topics:
            topics[fact.value].update(fact.source_ids)
        if extraction.difficulty:
            difficulty[extraction.difficulty.value].update(extraction.difficulty.source_ids)
    conflicts = []
    source_dates = {source.id: source.published_at or datetime.min.replace(tzinfo=timezone.utc) for source in sources}
    ranked_difficulty = sorted(
        ((len(ids), max(source_dates.get(source_id, datetime.min.replace(tzinfo=timezone.utc)) for source_id in ids), value, ids) for value, ids in difficulty.items()),
        reverse=True,
    )
    if len(ranked_difficulty) > 1 and ranked_difficulty[0][:2] == ranked_difficulty[1][:2]:
        conflicts.append({"field": "difficulty", "candidates": [{"value": value, "source_ids": sorted(ids)} for value, ids in difficulty.items()]})
    winning_difficulty = ranked_difficulty[0] if ranked_difficulty else None
    return IntelPayload(
        rounds=rounds,
        frequent_topics=[Fact(value=value, source_ids=sorted(ids)) for value, ids in topics.items()],
        difficulty=Fact(value=winning_difficulty[2], source_ids=sorted(winning_difficulty[3])) if winning_difficulty and not conflicts else None,
        conflicts=conflicts,
    )


def build_intel_graph(checkpointer: PostgresSaver, session_factory: Callable[[], Session]):
    def planner(state: IntelGraphState):
        return {"search_attempt": 0}

    def search_node(state: IntelGraphState):
        attempt = state["search_attempt"] + 1
        suffix = ("面经", "面经 技术面 算法 项目 八股", "面经 笔试 高频题")[attempt - 1]
        results = search(f"{state['query']} {suffix}")
        return {"search_attempt": attempt, "sources": [{"id": f"anysearch-{attempt}-{index}", **item} for index, item in enumerate(results, 1)]}

    def paste_node(state: IntelGraphState):
        if not state.get("user_paste"):
            return {"sources": []}
        return {"sources": [{"id": "user-paste", "title": "用户粘贴", "url": None, "text": state["user_paste"]}]}

    def aggregate(state: IntelGraphState):
        sources = [SourceRecord.model_validate(item) for item in state["sources"]]
        feedback = state.get("critic_feedback", "")
        extractions = {} if feedback else dict(state.get("extractions", {}))
        for source in sources:
            if source.id not in extractions:
                extractions[source.id] = extract_intel(source, state["provider"], feedback=feedback).model_dump(mode="json")
        payload = _merge([IntelExtraction.model_validate(item) for item in extractions.values()], sources)
        confidence = min(1.0, 0.35 + 0.2 * len(sources) - 0.25 * len(payload.conflicts))
        return {"extractions": extractions, "payload": payload.model_dump(mode="json"), "confidence": confidence, "critic_feedback": ""}

    def decide_search(state: IntelGraphState):
        return "search" if state["confidence"] < 0.7 and state["search_attempt"] < 3 else "critic"

    def critic(state: IntelGraphState):
        payload = IntelPayload.model_validate(state["payload"])
        content = chat(
            [{"role": "user", "content": "审查以下面经 JSON 是否含无来源、编造或遗漏。只输出 {\"approved\": true/false, \"feedback\": \"...\"}。\n" + payload.model_dump_json()}],
            provider=state["provider"], response_format={"type": "json_object"},
        )
        try:
            result = json.loads(content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise IntelGraphError(f"反思模型返回的不是合法 JSON：{exc}") from exc
        if not isinstance(result, dict) or not isinstance(result.get("approved"), bool) or not isinstance(result.get("feedback", ""), str):
            raise IntelGraphError("反思模型返回结构无效")
        rejected = not result["approved"]
        return {"reflection_count": state.get("reflection_count", 0) + 1, "needs_review": bool(payload.conflicts), "critic_rejected": rejected, "critic_feedback": result["feedback"] if rejected else ""}

    def decide_review(state: IntelGraphState):
        if state.get("critic_rejected") and state["reflection_count"] < 2:
            return "aggregate"
        return "review" if state["needs_review"] or state.get("critic_rejected") else "persist"

    def review(state: IntelGraphState):
        with session_factory() as db:
            item = db.get(IntelSession, state["intel_session_id"])
            if item is None:
                raise IntelGraphError("面经会话不存在")
            item.draft_payload = state["payload"]
            item.conflicts = state["payload"].get("conflicts", [])
            item.status = "待裁决"
            item.error_message = state.get("critic_feedback") or None
            db.commit()
        resolutions = interrupt({"intel_session_id": state["intel_session_id"], "payload": state["payload"], "critic_feedback": state.get("critic_feedback", "")})
        return {"resolutions": resolutions}

    def persist(state: IntelGraphState):
        with session_factory() as db:
            with db.begin():
                item = db.scalar(select(IntelSession).where(IntelSession.id == state["intel_session_id"]).with_for_update())
                if item is None:
                    raise IntelGraphError("面经会话不存在")
                if item.status == "已完成":
                    return {}
                payload = IntelPayload.model_validate(state["payload"])
                if state.get("resolutions"):
                    for conflict in payload.conflicts:
                        chosen = state["resolutions"].get(conflict.field)
                        candidate = next(
                            (item for item in conflict.candidates if item.value == chosen),
                            None,
                        )
                        if candidate is None:
                            raise IntelGraphError(f"裁决值不是 {conflict.field} 的候选项")
                        if conflict.field == "difficulty":
                            payload.difficulty = candidate
                    payload.conflicts = []
                intel = InterviewIntel(application_id=item.application_id, payload=payload.model_dump(mode="json"), confidence=state["confidence"], sources=state["sources"])
                db.add(intel); db.flush()
                item.draft_payload = payload.model_dump(mode="json"); item.conflicts = []; item.status = "已完成"; item.interview_intel_id = intel.id; item.resolved_at = datetime.now(timezone.utc)
            return {}

    builder = StateGraph(IntelGraphState)
    for name, node in (("planner", planner), ("search", search_node), ("paste", paste_node), ("aggregate", aggregate), ("critic", critic), ("review", review), ("persist", persist)):
        builder.add_node(name, node)
    builder.add_edge(START, "planner"); builder.add_edge("planner", "search"); builder.add_edge("planner", "paste")
    builder.add_edge("search", "aggregate"); builder.add_edge("paste", "aggregate")
    builder.add_conditional_edges("aggregate", decide_search, {"search": "search", "critic": "critic"})
    builder.add_conditional_edges("critic", decide_review, {"aggregate": "aggregate", "review": "review", "persist": "persist"})
    builder.add_edge("review", "persist"); builder.add_edge("persist", END)
    return builder.compile(checkpointer=checkpointer)


def start_intel_graph(session_id: int, thread_id: str, provider: str, query: str, user_paste: str | None, database_url: str, session_factory: sessionmaker):
    with PostgresSaver.from_conn_string(to_psycopg_connection_string(database_url)) as checkpointer:
        return build_intel_graph(checkpointer, session_factory).invoke({"intel_session_id": session_id, "provider": provider, "query": query, "user_paste": user_paste, "sources": [], "extractions": {}}, {"configurable": {"thread_id": thread_id}})


def resume_intel_graph(thread_id: str, resolutions: dict, database_url: str, session_factory: sessionmaker):
    with PostgresSaver.from_conn_string(to_psycopg_connection_string(database_url)) as checkpointer:
        return build_intel_graph(checkpointer, session_factory).invoke(Command(resume=resolutions), {"configurable": {"thread_id": thread_id}})
