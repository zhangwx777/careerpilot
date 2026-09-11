import json

from pydantic import ValidationError

from app.intel_schemas import IntelExtraction, SourceRecord
from app.llm.provider import chat


class IntelParseError(Exception):
    pass


SYSTEM_PROMPT = f"""你是面经信息抽取器。只输出 JSON，不得使用原文没有的信息。
必须严格符合下面的 JSON Schema，不得新增字段，不得把 source_ids 改成 source_id。
每个事实、问题和准备事项都必须带当前来源的 source_id；参考回答只能根据来源内容整理，不能凭空编造。
问题需要规范化为便于跨来源合并的短句，并标明 category（算法、项目、系统设计、编程、行为、HR 或其他）。
如果来源主要是岗位 JD、招聘说明或岗位职责，而不是实际面试经历：summary 用简洁中文说明“这是一份岗位描述，未包含真实面试过程”，rounds、questions、frequent_topics 不得凭空补写；preparation_items 只能提炼岗位要求。所有输出面向求职者阅读，不要出现 schema 字段名、变量名、函数名、类名、内部代码名称或冗长 JSON 解释。
JSON Schema：
{json.dumps(IntelExtraction.model_json_schema(), ensure_ascii=False)}"""


def _validate(content: str, source: SourceRecord) -> IntelExtraction:
    parsed = IntelExtraction.model_validate_json(content)
    source_ids = set()
    for field in (parsed.summary, parsed.difficulty):
        if field:
            source_ids.update(field.source_ids)
    for round_item in parsed.rounds:
        source_ids.update(round_item.source_ids)
        for fact in [*round_item.question_types, *round_item.focus_topics]:
            source_ids.update(fact.source_ids)
    for question in parsed.questions:
        source_ids.update(question.source_ids)
    for fact in parsed.frequent_topics:
        source_ids.update(fact.source_ids)
    for item in parsed.preparation_items:
        source_ids.update(item.source_ids)
    if source_ids - {source.id}:
        raise ValueError(f"来源引用必须全部为当前 source_id：{sorted(source_ids)}")
    return parsed


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
        try:
            return _validate(content, source)
        except (ValidationError, ValueError, TypeError) as first_error:
            repair_messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "上一次返回不符合 schema，请只输出修正后的 JSON。"
                        f"校验错误：{first_error}\n上一次结果：{content}"
                    ),
                },
            ]
            repaired = chat(
                repair_messages,
                provider=provider,
                response_format={"type": "json_object"},
            )
            return _validate(repaired, source)
    except (ValidationError, ValueError, TypeError) as exc:
        raise IntelParseError(f"面经结构化结果无效：{exc}") from exc
    except Exception as exc:
        raise IntelParseError(f"面经模型调用失败：{exc}") from exc
