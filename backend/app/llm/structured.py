"""有限次数的结构化模型输出处理。

所有需要 JSON 的任务都经过同一条路径：清理 Markdown 包裹、Pydantic/领域
校验，失败时最多请求一次修复。修复仍由调用方提供 validator，避免把领域
规则复制到基础设施层。
"""

from collections.abc import Callable
import re
from typing import Any, TypeVar

from pydantic import ValidationError

from app.llm.prompts import json_repair_prompt

T = TypeVar("T")


class StructuredOutputError(ValueError):
    """模型两次输出都无法通过结构化校验。"""


def clean_json(content: str) -> str:
    if not isinstance(content, str):
        raise TypeError("模型未返回文本")
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def complete_structured(
    messages: list[dict[str, Any]],
    provider: str,
    validator: Callable[[str], T],
    *,
    chat_fn: Callable[..., str],
    config: dict | None = None,
    generation: str = "structured",
) -> T:
    """调用模型并进行一次有限修复，不把内部校验细节泄露给用户。"""

    call_kwargs = {"provider": provider, "response_format": {"type": "json_object"}}
    if config is not None:
        call_kwargs["config"] = config
    if generation != "structured":
        call_kwargs["generation"] = generation
    raw = chat_fn(messages, **call_kwargs)
    return parse_structured(
        raw,
        messages,
        provider,
        validator,
        chat_fn=chat_fn,
        config=config,
        generation=generation,
    )


def parse_structured(
    raw: str,
    messages: list[dict[str, Any]],
    provider: str,
    validator: Callable[[str], T],
    *,
    chat_fn: Callable[..., str],
    config: dict | None = None,
    generation: str = "structured",
) -> T:
    """Validate an already-collected response, repairing it at most once.

    Streaming callers can collect the response first and still share the same
    JSON cleaning, domain validation, and bounded repair contract as one-shot
    callers.
    """

    call_kwargs = {"provider": provider, "response_format": {"type": "json_object"}}
    if config is not None:
        call_kwargs["config"] = config
    if generation != "structured":
        call_kwargs["generation"] = generation
    try:
        return validator(clean_json(raw))
    except (ValidationError, ValueError, TypeError):
        repair_messages = [
            *messages,
            {
                "role": "user",
                "content": json_repair_prompt(raw),
            },
        ]
        repaired = chat_fn(repair_messages, **call_kwargs)
        try:
            return validator(clean_json(repaired))
        except (ValidationError, ValueError, TypeError) as exc:
            raise StructuredOutputError("模型返回格式不符合要求") from exc
