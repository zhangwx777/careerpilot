from pydantic import ValidationError

from app.intel_schemas import IntelExtraction, SourceRecord
from app.llm.provider import chat


class IntelParseError(Exception):
    pass


SYSTEM_PROMPT = """你是面经信息抽取器。只输出 JSON，不得使用原文没有的信息。
字段只能是 rounds、frequent_topics、difficulty。每个事实必须带当前 source_id。
round_type 可为笔试、技术面、HR面或原文明确的轮次名称；未知信息返回空列表或 null。"""


def extract_intel(source: SourceRecord, provider: str, feedback: str | None = None) -> IntelExtraction:
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"source_id={source.id}\n来源内容：\n{source.text}",
            },
        ]
        if feedback:
            messages.append({"role": "user", "content": f"上轮审查反馈：{feedback}\n请只依据这条来源修正抽取结果。"})
        content = chat(
            messages,
            provider=provider,
            response_format={"type": "json_object"},
        )
        return IntelExtraction.model_validate_json(content)
    except (ValidationError, ValueError, TypeError) as exc:
        raise IntelParseError(f"面经结构化结果无效：{exc}") from exc
    except Exception as exc:
        raise IntelParseError(f"面经模型调用失败：{exc}") from exc
