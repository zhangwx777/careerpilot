"""Bounded, provider-neutral ReAct execution for read-only tools."""

from dataclasses import dataclass
import json
from time import monotonic
from typing import Any, Callable

from app.agent_schemas import AgentRunResult, AgentSource, AgentStep, AgentToolResult
from app.agent_tools import AgentTool
from app.llm.provider import chat, chat_stream, chat_with_tools


@dataclass(frozen=True)
class AgentBudget:
    max_steps: int = 5
    max_tool_calls: int = 8
    max_personal_reads: int = 3
    max_public_searches: int = 2
    max_model_calls: int = 6
    max_duration_seconds: float = 90.0
    max_tool_result_chars: int = 12_000
    max_context_chars: int = 40_000


DEFAULT_BUDGET = AgentBudget()


def _assistant_message(content: str | None, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                },
            }
            for call in tool_calls
        ],
    }


def _compact_result(result: AgentToolResult, limit: int) -> str:
    payload = result.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) <= limit:
        return encoded
    payload["data"] = {"truncated": True}
    payload["sources"] = [
        {**source, "text": str(source.get("text") or "")[:1_500]}
        for source in payload.get("sources", [])
    ]
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) <= limit:
        return encoded
    payload["sources"] = [
        {
            key: source.get(key)
            for key in ("id", "title", "url", "kind", "scope")
            if source.get(key) is not None
        }
        for source in payload.get("sources", [])
    ]
    return json.dumps(payload, ensure_ascii=False)


def _finalize(
    messages: list[dict[str, Any]],
    provider: str,
    config: dict,
    on_chunk: Callable[[str], None] | None,
) -> str:
    final_messages = [
        *messages,
        {
            "role": "user",
            "content": (
                "现在结束资料检索。请只输出符合要求的 JSON，字段为 answer 和 source_ids。"
                "只能引用已经从工具结果或有效对话上下文中获得的来源 ID；资料不足时明确说明，"
                "不要编造用户经历或岗位事实。"
            ),
        },
    ]
    raw = ""
    try:
        for chunk_index, chunk in enumerate(
            chat_stream(
                final_messages,
                provider=provider,
                response_format={"type": "json_object"},
                config=config,
                generation="chat",
            ),
            1,
        ):
            if chunk_index > 500:
                raise RuntimeError("问答输出超过长度上限")
            raw += chunk
            if on_chunk:
                on_chunk(raw)
    except Exception:
        # Keep a partial final stream for the existing structured-output
        # repair path; only an empty stream needs a one-shot retry.
        if raw:
            return raw
        raw = chat(
            final_messages,
            provider=provider,
            response_format={"type": "json_object"},
            config=config,
            generation="chat",
        )
    return raw


def run_chat_agent(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_registry: dict[str, AgentTool],
    provider: str,
    config: dict,
    *,
    budget: AgentBudget = DEFAULT_BUDGET,
    on_stage: Callable[[str], None] | None = None,
    on_chunk: Callable[[str], None] | None = None,
) -> AgentRunResult:
    started = monotonic()
    working_messages = list(messages)
    source_map: dict[str, AgentSource] = {}
    steps: list[AgentStep] = []
    tool_calls_used = 0
    personal_reads = 0
    public_searches = 0
    model_calls = 0
    context_chars = sum(len(str(message.get("content") or "")) for message in working_messages)
    budget_exceeded = False

    for step_number in range(1, budget.max_steps + 1):
        # Reserve one model call for _finalize; stop tool loops one call early.
        if monotonic() - started >= budget.max_duration_seconds or model_calls >= budget.max_model_calls - 1:
            budget_exceeded = True
            break
        model_calls += 1
        turn = chat_with_tools(working_messages, tools, provider, config=config)
        calls = turn["tool_calls"]
        if not calls:
            break
        working_messages.append(_assistant_message(turn.get("content"), calls))
        step_started = monotonic()
        step_sources: set[str] = set()
        call_summaries: list[dict[str, Any]] = []
        for call in calls:
            tool = tool_registry.get(call["name"])
            category = tool.category if tool else "unknown"
            if on_stage:
                on_stage(
                    {
                        "personal": "正在读取岗位资料",
                        "public": "正在检索公开资料",
                    }.get(category, "正在处理资料")
                )
            tool_calls_used += 1
            if tool_calls_used > budget.max_tool_calls:
                budget_exceeded = True
                result = AgentToolResult(ok=False, error="本次工具调用次数已达到上限")
            elif category == "personal" and personal_reads >= budget.max_personal_reads:
                budget_exceeded = True
                result = AgentToolResult(ok=False, error="本次个人资料读取次数已达到上限")
            elif category == "public" and public_searches >= budget.max_public_searches:
                budget_exceeded = True
                result = AgentToolResult(ok=False, error="本次公开搜索次数已达到上限")
            elif tool is None:
                result = AgentToolResult(ok=False, error="未知工具")
            else:
                try:
                    result = tool.handler(call["arguments"])
                except (TypeError, ValueError):
                    result = AgentToolResult(ok=False, error="工具参数无效")
                except Exception:
                    result = AgentToolResult(ok=False, error="工具执行失败")
                if category == "personal":
                    personal_reads += 1
                elif category == "public":
                    public_searches += 1
            for source in result.sources:
                source_map[source.id] = source
                step_sources.add(source.id)
            content = _compact_result(result, budget.max_tool_result_chars)
            context_chars += len(content)
            if context_chars > budget.max_context_chars:
                budget_exceeded = True
                content = json.dumps(
                    {
                        "ok": result.ok,
                        "sources": [source.model_dump(mode="json") for source in result.sources],
                        "error": result.error,
                        "data": {"truncated": True},
                    },
                    ensure_ascii=False,
                )[:2_000]
            working_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": content,
                }
            )
            call_summaries.append(
                {
                    "name": call["name"],
                    "arguments_summary": call["arguments"],
                    "status": "completed" if result.ok else "failed",
                }
            )
            if monotonic() - started >= budget.max_duration_seconds:
                budget_exceeded = True
                break
        steps.append(
            AgentStep(
                step=step_number,
                tool_calls=call_summaries,
                source_ids=sorted(step_sources),
                elapsed_ms=int((monotonic() - step_started) * 1000),
            )
        )
        if budget_exceeded:
            break

    if not steps and model_calls >= budget.max_model_calls - 1:
        # No tool step ran and the reserved-for-finalize call is the only one left.
        budget_exceeded = True
    if monotonic() - started >= budget.max_duration_seconds:
        budget_exceeded = True
    if on_stage:
        on_stage("正在整理回答")
    raw = _finalize(working_messages, provider, config, on_chunk)
    return AgentRunResult(
        raw=raw,
        steps=steps,
        sources=list(source_map.values()),
        status="budget_exceeded" if budget_exceeded else "completed",
    )
