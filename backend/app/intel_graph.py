from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
import logging
from operator import add
from typing import Annotated, TypedDict
from urllib.parse import urlsplit, urlunsplit

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.anysearch import AnySearchError, search
from app.db import to_psycopg_connection_string
from app.intel_parsing import extract_intel
from app.intel_insight import rebuild_position_insight
from app.intel_schemas import Fact, IntelExtraction, IntelPayload, IntelQuestion, InterviewRound, PreparationItem, SourceRecord
from app.llm.config_store import config_from_snapshot
from app.llm.prompts import CRITIC_PROMPT
from app.llm.provider import chat
from app.llm.structured import StructuredOutputError, complete_structured
from app.models import IntelSession, InterviewIntel

logger = logging.getLogger(__name__)

# 与 InterviewRound.question_types / focus_topics 的 schema 上限一致（max_length=20）。
# 合并多份材料时按值去重后可能超过该上限，必须在此截断，否则写入库、读取时会触发校验 500。
ROUND_FACTS_LIMIT = 20


class IntelGraphError(Exception):
    pass


class CriticResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    feedback: str = Field(default="", max_length=4000)


class IntelGraphState(TypedDict, total=False):
    intel_session_id: int
    provider: str
    query: str
    user_paste: str | None
    image_texts: list[dict]
    round_type: str
    sources: Annotated[list[dict], add]
    extractions: dict[str, dict]
    search_attempt: int
    supplement_web: bool
    search_errors: list[str]
    source_errors: list[str]
    payload: dict
    confidence: float
    reflection_count: int
    resolutions: dict
    needs_review: bool
    critic_rejected: bool
    critic_feedback: str


def _session_llm_config(
    state: IntelGraphState, session_factory: Callable[[], Session]
) -> dict:
    with session_factory() as db:
        item = db.get(IntelSession, state["intel_session_id"])
        if item is None:
            raise IntelGraphError("面经会话不存在")
        return config_from_snapshot(item.llm_snapshot, db, state["provider"])


INTERVIEW_SIGNALS = ("面经", "面试经历", "面试题", "一面", "二面", "三面", "技术面", "HR面", "复盘", "问了", "笔试题", "面试流程")
RECRUITMENT_ONLY = ("招聘公告", "岗位职责", "投递入口", "校园招聘", "秋招启动", "招聘计划")


def _is_relevant_source(title: str, text: str) -> bool:
    content = f"{title}\n{text}"
    if not any(signal in content for signal in INTERVIEW_SIGNALS):
        return False
    if any(signal in content for signal in RECRUITMENT_ONLY) and not any(
        signal in content for signal in ("面经", "面试经历", "面试题", "一面", "二面", "三面", "技术面", "HR面", "复盘", "问了")
    ):
        return False
    return True


def _canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, ""))


def _decide_review(state: IntelGraphState) -> str:
    if state.get("critic_rejected") and state.get("reflection_count", 0) < 2:
        return "aggregate"
    return "review" if state.get("needs_review") else "persist"


def _decide_after_aggregate(state: IntelGraphState) -> str:
    if state.get("supplement_web", True) and state.get("confidence", 0) < 0.7 and state.get("search_attempt", 0) < 3:
        return "search"
    if not state.get("supplement_web", True) and len(state.get("sources") or []) == 1 and not (state.get("payload") or {}).get("conflicts"):
        return "persist"
    return "critic"


def _apply_round_selection(payload: IntelPayload, round_type: str) -> IntelPayload:
    if round_type == "多轮综合":
        return payload
    questions = [item.model_copy(update={"round_type": round_type}) for item in payload.questions]
    rounds = [item.model_copy(update={"round_type": round_type}) for item in payload.rounds]
    return payload.model_copy(update={"questions": questions, "rounds": rounds})


def _merge(extractions: list[IntelExtraction], sources: list[SourceRecord]) -> IntelPayload:
    rounds: dict[str, InterviewRound] = {}
    topics: dict[str, set[str]] = defaultdict(set)
    difficulty: dict[str, set[str]] = defaultdict(set)
    questions: dict[tuple[str, str], IntelQuestion] = {}
    preparation: dict[str, PreparationItem] = {}
    summary: dict[str, set[str]] = defaultdict(set)
    for extraction in extractions:
        if extraction.summary:
            summary[extraction.summary.value].update(extraction.summary.source_ids)
        for item in extraction.rounds:
            current = rounds.get(item.round_type)
            if current is None:
                rounds[item.round_type] = item
            else:
                def merge_facts(existing: list[Fact], incoming: list[Fact]) -> list[Fact]:
                    merged = {fact.value: fact for fact in existing}
                    for fact in incoming:
                        previous = merged.get(fact.value)
                        merged[fact.value] = fact if previous is None else previous.model_copy(update={"source_ids": sorted(set(previous.source_ids) | set(fact.source_ids))})
                    return list(merged.values())[:ROUND_FACTS_LIMIT]

                rounds[item.round_type] = current.model_copy(update={
                    "duration_minutes": current.duration_minutes or item.duration_minutes,
                    "question_types": merge_facts(current.question_types, item.question_types),
                    "focus_topics": merge_facts(current.focus_topics, item.focus_topics),
                    "source_ids": sorted(set(current.source_ids) | set(item.source_ids)),
                })
        for item in extraction.questions:
            key = (item.round_type, item.question)
            current = questions.get(key)
            if current is None:
                questions[key] = item
            else:
                questions[key] = current.model_copy(update={
                    "source_ids": sorted(set(current.source_ids) | set(item.source_ids)),
                    "answer_outline": item.answer_outline if len(item.answer_outline) > len(current.answer_outline) else current.answer_outline,
                })
        for fact in extraction.frequent_topics:
            topics[fact.value].update(fact.source_ids)
        for item in extraction.preparation_items:
            current = preparation.get(item.title)
            if current is None:
                preparation[item.title] = item
            else:
                preparation[item.title] = current.model_copy(update={
                    "source_ids": sorted(set(current.source_ids) | set(item.source_ids)),
                    "priority": min(current.priority, item.priority),
                    "detail": item.detail if len(item.detail) > len(current.detail) else current.detail,
                })
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
    winning_summary = max(summary.items(), key=lambda item: len(item[1])) if summary else None
    return IntelPayload(
        summary=Fact(value=winning_summary[0], source_ids=sorted(winning_summary[1])) if winning_summary else None,
        rounds=list(rounds.values())[:12],
        questions=list(questions.values())[:50],
        frequent_topics=[Fact(value=value, source_ids=sorted(ids)) for value, ids in topics.items()][:30],
        difficulty=Fact(value=winning_difficulty[2], source_ids=sorted(winning_difficulty[3])) if winning_difficulty and not conflicts else None,
        preparation_items=list(preparation.values())[:30],
        conflicts=conflicts[:20],
    )


def build_intel_graph(checkpointer: PostgresSaver, session_factory: Callable[[], Session]):
    def save_progress(state: IntelGraphState, stage: str, sources: list[dict] | None = None):
        with session_factory() as db:
            item = db.get(IntelSession, state["intel_session_id"])
            if item is None:
                raise IntelGraphError("面经会话不存在")
            current = item.progress_payload or {"sources": []}
            current.update({"stage": stage, "sources": sources if sources is not None else current.get("sources", [])})
            item.progress_payload = current
            db.commit()

    def visible_sources(sources: list[dict]) -> list[dict]:
        return [
            {"id": source["id"], "title": source["title"], "url": source.get("url"), "kind": source.get("kind", "unknown"), "file_name": source.get("file_name")}
            for source in sources
        ]

    def save_source_progress(state: IntelGraphState, stage: str, sources: list[dict], *, rejected: int = 0, errors: list[str] | None = None):
        save_progress(state, stage, visible_sources(sources))
        with session_factory() as db:
            item = db.get(IntelSession, state["intel_session_id"])
            if item is not None:
                payload = item.progress_payload or {}
                payload.update({"found": len(sources) + rejected, "accepted": len(sources), "rejected": rejected, "errors": errors or []})
                item.progress_payload = payload
                db.commit()

    def planner(state: IntelGraphState):
        save_progress(state, "正在分析手动面经" if state.get("user_paste") or state.get("image_texts") else "正在检索公开面经")
        return {"search_attempt": 0, "search_errors": [], "source_errors": []}

    def search_node(state: IntelGraphState):
        attempt = state["search_attempt"] + 1
        suffix = ("面经", "面经 技术面 算法 项目 八股", "面经 笔试 高频题")[attempt - 1]
        save_progress(state, "正在检索公开面经")
        errors = list(state.get("search_errors", []))
        try:
            results = search(f"{state['query']} {suffix}")
        except AnySearchError:
            logger.exception("面经公开检索失败：%s", state["query"])
            errors.append("公开面经搜索暂时失败")
            save_source_progress(state, "公开检索暂时失败，保留已有内容", state.get("sources", []), errors=errors)
            return {"search_attempt": attempt, "search_errors": errors, "sources": []}
        accepted = []
        rejected = 0
        existing_urls = {_canonical_url(item.get("url")) for item in state.get("sources", [])}
        for index, item in enumerate(results, 1):
            if not _is_relevant_source(item.get("title", ""), item.get("text", "")):
                rejected += 1
                continue
            if _canonical_url(item.get("url")) in existing_urls:
                continue
            accepted.append({"id": f"session-{state['intel_session_id']}:web-{attempt}-{index}", "kind": "web", **item})
            existing_urls.add(_canonical_url(item.get("url")))
        save_source_progress(state, "正在整理来源", accepted, rejected=rejected, errors=errors)
        return {"search_attempt": attempt, "search_errors": errors, "sources": accepted}

    def paste_node(state: IntelGraphState):
        sources = []
        session_prefix = f"session-{state['intel_session_id']}"
        if state.get("user_paste"):
            sources.append({"id": f"{session_prefix}:manual", "kind": "manual", "title": "用户粘贴", "url": None, "text": state["user_paste"]})
        for index, item in enumerate(state.get("image_texts", [])):
            if item.get("text", "").strip():
                sources.append({"id": f"{session_prefix}:image-{index}", "kind": "image", "file_name": item.get("name"), "title": f"截图：{item.get('name')}", "url": None, "text": item["text"]})
        return {"sources": sources}

    def decide_sources(state: IntelGraphState):
        return "search" if state.get("supplement_web", True) else "aggregate"

    def aggregate(state: IntelGraphState):
        sources = [SourceRecord.model_validate(item) for item in state["sources"]]
        if not sources:
            if state.get("supplement_web", True) and state.get("search_attempt", 0) < 3:
                return {"extractions": {}, "payload": IntelPayload().model_dump(mode="json"), "confidence": 0.0}
            return {"extractions": {}, "payload": IntelPayload().model_dump(mode="json"), "confidence": 0.0}
        save_progress(state, f"正在提取 {len(sources)} 条来源", visible_sources(state["sources"]))
        feedback = state.get("critic_feedback", "")
        llm_config = _session_llm_config(state, session_factory)
        extractions = {} if feedback else dict(state.get("extractions", {}))
        source_errors = list(state.get("source_errors", []))
        for source in sources:
            if source.id not in extractions:
                try:
                    try:
                        extracted = extract_intel(
                            source,
                            state["provider"],
                            feedback=feedback,
                            llm_config=llm_config,
                        )
                    except TypeError as exc:
                        # Keep older integrations/fakes that only implement the
                        # original three-argument extractor working.
                        if "llm_config" not in str(exc):
                            raise
                        extracted = extract_intel(source, state["provider"], feedback=feedback)
                    extractions[source.id] = extracted.model_dump(mode="json")
                except Exception:
                    if source.kind == "manual" or source.id in {"user-paste", "manual"}:
                        raise
                    logger.exception("面经来源 %s 提取失败", source.id)
                    source_errors.append(f"{source.title}：面经提取失败")
        payload = _apply_round_selection(_merge([IntelExtraction.model_validate(item) for item in extractions.values()], sources), state.get("round_type", "未注明"))
        confidence = min(1.0, 0.35 + 0.2 * len(extractions) - 0.25 * len(payload.conflicts))
        if not extractions:
            return {"extractions": {}, "payload": IntelPayload().model_dump(mode="json"), "confidence": 0.0, "source_errors": source_errors}
        return {"extractions": extractions, "payload": payload.model_dump(mode="json"), "confidence": confidence, "critic_feedback": "", "source_errors": source_errors}

    def decide_search(state: IntelGraphState):
        return _decide_after_aggregate(state)

    def critic(state: IntelGraphState):
        save_progress(state, "正在核验结论")
        payload = IntelPayload.model_validate(state["payload"])
        llm_config = _session_llm_config(state, session_factory)
        try:
            result = complete_structured(
                [{"role": "user", "content": CRITIC_PROMPT + "\n面经 JSON：<payload>\n" + payload.model_dump_json() + "\n</payload>"}],
                state["provider"],
                CriticResult.model_validate_json,
                chat_fn=chat,
                config=llm_config,
            )
        except StructuredOutputError:
            raise IntelGraphError("反思模型返回格式无效，请稍后重试") from None
        rejected = not result.approved
        return {"reflection_count": state.get("reflection_count", 0) + 1, "needs_review": bool(payload.conflicts), "critic_rejected": rejected, "critic_feedback": result.feedback if rejected else ""}

    def decide_review(state: IntelGraphState):
        return _decide_review(state)

    def review(state: IntelGraphState):
        with session_factory() as db:
            item = db.get(IntelSession, state["intel_session_id"])
            if item is None:
                raise IntelGraphError("面经会话不存在")
            if item.status == "已丢弃":
                return {}
            item.draft_payload = state["payload"]
            item.conflicts = state["payload"].get("conflicts", [])
            item.status = "待裁决"
            item.progress_payload = {
                "stage": "等待人工裁决",
                "sources": visible_sources(state["sources"]),
                "errors": state.get("source_errors", []) + state.get("search_errors", []),
            }
            item.error_message = "系统检测到这份内容可能不是完整面经，或存在需要确认的结论。请在“录入与进度”中确认后写入。"
            db.commit()
        resolutions = interrupt({"intel_session_id": state["intel_session_id"], "payload": state["payload"], "critic_feedback": state.get("critic_feedback", "")})
        return {"resolutions": resolutions}

    def persist(state: IntelGraphState):
        with session_factory() as db:
            with db.begin():
                item = db.scalar(select(IntelSession).where(IntelSession.id == state["intel_session_id"]).with_for_update())
                if item is None:
                    raise IntelGraphError("面经会话不存在")
                if item.status in {"已完成", "已丢弃"}:
                    return {}
                payload = _apply_round_selection(IntelPayload.model_validate(state["payload"]), state.get("round_type", "未注明"))
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
                kinds = {source.get("kind", "unknown") for source in state["sources"]}
                material_kind = "截图资料" if kinds == {"image"} else "手动录入" if kinds == {"manual"} else "联网补充" if kinds == {"web"} else "多源资料"
                intel = InterviewIntel(
                    application_id=item.application_id,
                    title=f"{state.get('round_type', '未注明')} · {material_kind}",
                    round_type=state.get("round_type", "未注明"),
                    provider=state["provider"],
                    payload=payload.model_dump(mode="json"),
                    confidence=state["confidence"],
                    sources=state["sources"],
                )
                db.add(intel); db.flush()
                item.draft_payload = payload.model_dump(mode="json"); item.conflicts = []; item.status = "已完成"; item.interview_intel_id = intel.id; item.resolved_at = datetime.now(timezone.utc)
                item.progress_payload = {
                    "stage": "已完成",
                    "sources": visible_sources(state["sources"]),
                    "errors": state.get("source_errors", []) + state.get("search_errors", []),
                }
                from app.intel_reminders import sync_intel_reminder

                sync_intel_reminder(db, item.application_id, payload)
                position_id = item.application.position_id
            try:
                rebuild_position_insight(
                    position_id,
                    state["provider"],
                    session_factory,
                    llm_config=_session_llm_config(state, session_factory),
                )
            except Exception:
                logger.exception("岗位 %s 洞察重建失败", position_id)
                with session_factory() as progress_db:
                    progress_item = progress_db.get(IntelSession, state["intel_session_id"])
                    if progress_item is not None:
                        progress_payload = progress_item.progress_payload or {}
                        progress_payload["insight_error"] = "岗位洞察生成失败，请稍后重试"
                        progress_item.progress_payload = progress_payload
                        progress_db.commit()
            return {}

    builder = StateGraph(IntelGraphState)
    for name, node in (("planner", planner), ("search", search_node), ("paste", paste_node), ("aggregate", aggregate), ("critic", critic), ("review", review), ("persist", persist)):
        builder.add_node(name, node)
    builder.add_edge(START, "planner"); builder.add_edge("planner", "paste")
    builder.add_conditional_edges("paste", decide_sources, {"search": "search", "aggregate": "aggregate"})
    builder.add_edge("search", "aggregate")
    builder.add_conditional_edges("aggregate", decide_search, {"search": "search", "critic": "critic", "persist": "persist"})
    builder.add_conditional_edges("critic", decide_review, {"aggregate": "aggregate", "review": "review", "persist": "persist"})
    builder.add_edge("review", "persist"); builder.add_edge("persist", END)
    return builder.compile(checkpointer=checkpointer)


def start_intel_graph(session_id: int, thread_id: str, provider: str, query: str, user_paste: str | None, database_url: str, session_factory: sessionmaker, supplement_web: bool = False, round_type: str = "未注明", image_texts: list[dict] | None = None):
    with PostgresSaver.from_conn_string(to_psycopg_connection_string(database_url)) as checkpointer:
        return build_intel_graph(checkpointer, session_factory).invoke({"intel_session_id": session_id, "provider": provider, "query": query, "user_paste": user_paste, "round_type": round_type, "image_texts": image_texts or [], "supplement_web": supplement_web, "sources": [], "extractions": {}}, {"configurable": {"thread_id": thread_id}})


def resume_intel_graph(thread_id: str, resolutions: dict, database_url: str, session_factory: sessionmaker):
    with PostgresSaver.from_conn_string(to_psycopg_connection_string(database_url)) as checkpointer:
        return build_intel_graph(checkpointer, session_factory).invoke(Command(resume=resolutions), {"configurable": {"thread_id": thread_id}})
