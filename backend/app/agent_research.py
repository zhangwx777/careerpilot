"""Small, read-only research Agent used by the interview-intel Workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agent_schemas import AgentSource, AgentToolResult
from app.anysearch import AnySearchError, search
from app.llm.provider import LlmCallError, chat_with_tools


class ResearchQuery(BaseModel):
    query: str = Field(min_length=1, max_length=200)


@dataclass
class ResearchResult:
    sources: list[dict[str, Any]] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    error: str | None = None


def research_public_sources(
    *,
    session_id: int,
    query: str,
    provider: str,
    config: dict,
    max_rounds: int = 3,
    search_fn=search,
) -> ResearchResult:
    """Let the model choose up to three public-search queries.

    The model can only call the local search adapter. It never receives a
    database write capability and its final text is ignored; only validated
    search candidates are returned to the deterministic intel graph.
    """

    result = ResearchResult()
    counter = 0

    def search_public(arguments: dict[str, Any]) -> AgentToolResult:
        nonlocal counter
        try:
            parsed = ResearchQuery.model_validate(arguments)
        except ValidationError:
            result.error = "invalid_arguments"
            return AgentToolResult(ok=False, error="检索参数无效", error_kind="invalid_arguments")
        result.queries.append(parsed.query)
        try:
            items = search_fn(parsed.query, timeout_seconds=30)
        except AnySearchError as exc:
            result.error = "公开检索暂时失败"
            return AgentToolResult(ok=False, error=result.error, error_kind="search_failed")
        sources = []
        for item in items[:5]:
            counter += 1
            source = AgentSource(
                id=f"session-{session_id}:research-{counter}",
                title=item.get("title") or "公开来源",
                url=item.get("url"),
                text=item.get("text", ""),
                kind="web",
                published_at=item.get("published_at"),
                scope="public",
            )
            source_dict = source.model_dump(mode="json")
            sources.append(source_dict)
            result.sources.append(source_dict)
        return AgentToolResult(
            ok=True,
            data={"query": parsed.query, "count": len(sources)},
            sources=[AgentSource.model_validate(item) for item in sources],
            error_kind="empty_result" if not sources else None,
        )

    tool = {
        "type": "function",
        "function": {
            "name": "search_public_intel",
            "description": "检索公开面经资料，只返回候选来源，不执行写入。",
            "parameters": ResearchQuery.model_json_schema(),
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是面经公开资料研究助手。只能调用 search_public_intel，最多调用指定次数。"
                "请围绕公司、岗位和真实面试经历选择不同查询词，不要回答用户问题。"
            ),
        },
        {"role": "user", "content": f"研究目标：{query}"},
    ]
    for _ in range(max(1, min(max_rounds, 3))):
        try:
            turn = chat_with_tools(messages, [tool], provider, config=config)
        except LlmCallError as exc:
            result.error = exc.kind
            break
        except Exception:
            result.error = "response"
            break
        calls = turn["tool_calls"]
        if not calls:
            break
        call = calls[0]
        if call["name"] != "search_public_intel":
            break
        tool_result = search_public(call["arguments"])
        messages.append({
            "role": "assistant",
            "content": turn.get("content"),
            "tool_calls": [{
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call["arguments"], ensure_ascii=False)},
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": call["id"],
            "content": tool_result.model_dump_json(),
        })
        if not tool_result.ok:
            break
    return result
