"""Read-only domain tools exposed to the bounded Agent runtime."""

from dataclasses import dataclass, field
import json
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.agent_schemas import AgentSource, AgentToolResult
from app.anysearch import AnySearchError, search
from app.models import AgentRun, Application, IntelChatMessage, InterviewIntel, TimelineNode


MAX_RESULT_TEXT = 12_000


class _KeywordArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str | None = Field(default=None, max_length=200)
    round_type: str | None = Field(default=None, max_length=20)


class _RelatedArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str | None = Field(default=None, max_length=200)
    position_title: str | None = Field(default=None, max_length=200)


class _PublicSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    category: str
    handler: Callable[[dict[str, Any]], AgentToolResult]

    def spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class AgentToolContext:
    application_id: int
    position_id: int
    company_id: int
    run_id: int
    session_factory: Callable[[], Session]
    public_source_counter: list[int] = field(default_factory=lambda: [0])


def _text(value: object, limit: int = MAX_RESULT_TEXT) -> str:
    return str(value or "")[:limit]


def _source(value: dict[str, Any], *, scope: str = "current_position") -> AgentSource:
    payload = {
        **value,
        "id": _text(value.get("id"), 200),
        "title": _text(value.get("title"), 200) or "未命名来源",
        "kind": _text(value.get("kind"), 30) or "unknown",
        "text": _text(value.get("text")),
        "scope": scope,
    }
    if payload.get("file_name"):
        payload["file_name"] = _text(payload["file_name"], 255)
    return AgentSource.model_validate(payload)


def _current_intels(db: Session, position_id: int) -> list[InterviewIntel]:
    return list(
        db.scalars(
            select(InterviewIntel)
            .join(InterviewIntel.application)
            .where(Application.position_id == position_id)
            .order_by(InterviewIntel.created_at.asc(), InterviewIntel.id.asc())
        ).all()
    )


def _material_sources(material: InterviewIntel) -> list[AgentSource]:
    return [
        _source(
            {**raw, "id": f"material-{material.id}:{raw['id']}"},
            scope="current_position",
        )
        for raw in (material.sources or [])
        if isinstance(raw, dict) and raw.get("id")
    ]


def _source_matches(source: AgentSource, keyword: str | None) -> bool:
    return not keyword or keyword.strip().lower() in f"{source.title}\n{source.text}".lower()


def _read_current_jd(context: AgentToolContext, _arguments: dict[str, Any]) -> AgentToolResult:
    with context.session_factory() as db:
        position = db.get(Application, context.application_id)
        if position is None:
            return AgentToolResult(ok=False, error="投递记录不存在")
        text = _text(position.position.jd_text if position.position else "")
        if not text:
            return AgentToolResult(ok=True, data={"text": "", "available": False})
        source = _source(
            {
                "id": f"position-{context.position_id}:jd",
                "title": "当前岗位 JD",
                "text": text,
                "kind": "unknown",
            }
        )
        return AgentToolResult(ok=True, data={"text": text, "available": True}, sources=[source])


def _search_current_intel(context: AgentToolContext, arguments: dict[str, Any]) -> AgentToolResult:
    parsed = _KeywordArgs.model_validate(arguments)
    with context.session_factory() as db:
        materials = _current_intels(db, context.position_id)
    sources = [source for material in materials for source in _material_sources(material)]
    if parsed.round_type:
        materials = [item for item in materials if item.round_type == parsed.round_type]
        allowed = {item.id for material in materials for item in _material_sources(material)}
        sources = [source for source in sources if source.id in allowed]
    sources = [source for source in sources if _source_matches(source, parsed.keyword)]
    return AgentToolResult(
        ok=True,
        data={"count": len(sources), "round_type": parsed.round_type, "keyword": parsed.keyword},
        sources=sources[:20],
    )


def _read_resume(context: AgentToolContext, _arguments: dict[str, Any]) -> AgentToolResult:
    from app.models import ResumeProfile

    with context.session_factory() as db:
        resume = db.get(ResumeProfile, 1)
    if resume is None:
        return AgentToolResult(ok=True, data={"available": False, "text": ""})
    source = _source(
        {
            "id": "resume:current",
            "title": resume.file_name or "当前简历",
            "text": resume.resume_text,
            "kind": "unknown",
            "file_name": resume.file_name,
        }
    )
    return AgentToolResult(ok=True, data={"available": True, "text": source.text}, sources=[source])


def _search_timeline(context: AgentToolContext, _arguments: dict[str, Any]) -> AgentToolResult:
    with context.session_factory() as db:
        nodes = list(
            db.scalars(
                select(TimelineNode)
                .where(TimelineNode.application_id == context.application_id)
                .order_by(TimelineNode.scheduled_at.asc().nulls_last(), TimelineNode.id.asc())
                .limit(30)
            ).all()
        )
    sources = [
        _source(
            {
                "id": f"timeline-{node.id}",
                "title": node.title or node.node_type,
                "text": json.dumps(
                    {
                        "node_type": node.node_type,
                        "scheduled_at": node.scheduled_at.isoformat() if node.scheduled_at else None,
                        "ends_at": node.ends_at.isoformat() if node.ends_at else None,
                        "status": node.status,
                        "detail": node.detail,
                    },
                    ensure_ascii=False,
                ),
                "kind": "unknown",
            }
        )
        for node in nodes
    ]
    return AgentToolResult(ok=True, data={"count": len(sources)}, sources=sources)


def _search_related_intel(context: AgentToolContext, arguments: dict[str, Any]) -> AgentToolResult:
    parsed = _RelatedArgs.model_validate(arguments)
    with context.session_factory() as db:
        materials = list(
            db.scalars(
                select(InterviewIntel)
                .join(InterviewIntel.application)
                .join(Application.position)
                .where(
                    Application.position.has(company_id=context.company_id),
                    Application.position_id != context.position_id,
                )
                .options(joinedload(InterviewIntel.application).joinedload(Application.position))
                .order_by(InterviewIntel.created_at.desc(), InterviewIntel.id.desc())
                .limit(20)
            ).all()
        )
    sources = []
    for material in materials:
        title = material.application.position.title if material.application and material.application.position else "相关岗位"
        if parsed.position_title and parsed.position_title.lower() not in title.lower():
            continue
        for source in _material_sources(material):
            sources.append(source.model_copy(update={"scope": "related_position", "title": f"{title} · {source.title}"}))
    sources = [source for source in sources if _source_matches(source, parsed.keyword)]
    return AgentToolResult(ok=True, data={"count": len(sources), "scope": "related_position"}, sources=sources[:20])


def _read_chat_history(context: AgentToolContext, _arguments: dict[str, Any]) -> AgentToolResult:
    with context.session_factory() as db:
        runs = list(
            db.scalars(
                select(AgentRun)
                .where(
                    AgentRun.kind == "chat",
                    AgentRun.position_id == context.position_id,
                    AgentRun.status.in_(["completed", "budget_exceeded"]),
                )
                .order_by(AgentRun.id.desc())
                .limit(6)
            ).all()
        )
        valid_material_ids = {
            source.id
            # ponytail: 全表扫描面经材料，材料量大时按 position_id/company_id 收窄
            for material in db.scalars(select(InterviewIntel)).all()
            for source in _material_sources(material)
        }
        records: list[tuple[dict[str, Any], list[AgentSource]]] = []
        for run in reversed(runs):
            assistant = db.get(IntelChatMessage, run.assistant_message_id) if run.assistant_message_id else None
            if assistant is None:
                continue
            user = db.scalar(
                select(IntelChatMessage)
                .where(
                    IntelChatMessage.position_id == context.position_id,
                    IntelChatMessage.role == "user",
                    IntelChatMessage.id < assistant.id,
                )
                .order_by(IntelChatMessage.id.desc())
                .limit(1)
            )
            snapshot_sources = []
            for raw in run.sources or []:
                try:
                    source = AgentSource.model_validate(raw)
                except Exception:
                    continue
                if source.id.startswith("material-") and source.id not in valid_material_ids:
                    continue
                snapshot_sources.append(
                    source.model_copy(
                        update={"scope": "conversation", "text": source.text[:1000]}
                    )
                )
            records.append(
                (
                    {
                        "question": _text(user.content if user else "", 4000),
                        "answer": _text(assistant.content, 6000),
                        "source_ids": [source.id for source in snapshot_sources],
                    },
                    snapshot_sources,
                )
            )
    while records and len(json.dumps([item[0] for item in records], ensure_ascii=False)) > 12_000:
        if len(records) > 1:
            records.pop(0)
            continue
        turn, _ = records[0]
        turn["question"] = _text(turn["question"], 1500)
        turn["answer"] = _text(turn["answer"], 4000)
        break
    turns = [item[0] for item in records]
    sources = [source for _, items in records for source in items]
    return AgentToolResult(ok=True, data={"turns": turns, "count": len(turns)}, sources=sources[:20])


def _search_public_intel(context: AgentToolContext, arguments: dict[str, Any]) -> AgentToolResult:
    parsed = _PublicSearchArgs.model_validate(arguments)
    try:
        results = search(parsed.query, timeout_seconds=30)
    except AnySearchError:
        return AgentToolResult(ok=False, error="公开检索暂时失败")
    sources = []
    for item in results[:5]:
        context.public_source_counter[0] += 1
        sources.append(
            _source(
                {
                    "id": f"agent-run-{context.run_id}:web-{context.public_source_counter[0]}",
                    "title": item.get("title") or "公开来源",
                    "url": item.get("url"),
                    "published_at": item.get("published_at"),
                    "text": item.get("text", ""),
                    "kind": "web",
                },
                scope="public",
            )
        )
    return AgentToolResult(ok=True, data={"query": parsed.query, "count": len(sources)}, sources=sources)


def build_chat_toolset(context: AgentToolContext) -> tuple[list[dict[str, Any]], dict[str, AgentTool]]:
    tools = [
        AgentTool(
            "read_current_jd",
            "读取当前岗位 JD。没有 JD 时返回空资料。",
            {"type": "object", "properties": {}, "additionalProperties": False},
            "personal",
            lambda args: _read_current_jd(context, args),
        ),
        AgentTool(
            "search_current_intel",
            "按轮次或关键词读取当前岗位已有面经来源。",
            _KeywordArgs.model_json_schema(),
            "personal",
            lambda args: _search_current_intel(context, args),
        ),
        AgentTool(
            "search_related_intel",
            "读取同公司其他岗位的面经，仅作为跨岗位参考。",
            _RelatedArgs.model_json_schema(),
            "personal",
            lambda args: _search_related_intel(context, args),
        ),
        AgentTool(
            "read_resume",
            "读取当前保存的简历。没有简历时返回空资料。",
            {"type": "object", "properties": {}, "additionalProperties": False},
            "personal",
            lambda args: _read_resume(context, args),
        ),
        AgentTool(
            "search_timeline",
            "读取当前投递的时间线节点，只读。",
            {"type": "object", "properties": {}, "additionalProperties": False},
            "personal",
            lambda args: _search_timeline(context, args),
        ),
        AgentTool(
            "read_chat_history",
            "读取当前岗位最近几轮已完成问答，供理解追问上下文。",
            {"type": "object", "properties": {}, "additionalProperties": False},
            "personal",
            lambda args: _read_chat_history(context, args),
        ),
        AgentTool(
            "search_public_intel",
            "使用公开搜索补充资料，返回带来源的网页结果。",
            _PublicSearchArgs.model_json_schema(),
            "public",
            lambda args: _search_public_intel(context, args),
        ),
    ]
    return [tool.spec() for tool in tools], {tool.name: tool for tool in tools}
