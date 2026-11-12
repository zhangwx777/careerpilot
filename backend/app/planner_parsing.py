import json

from app.llm.provider import chat
from app.planner_schemas import PlannerDraft
from app.llm.prompts import PLANNER_SCHEDULE_SYSTEM_PROMPT, PLANNER_SYSTEM_PROMPT
from app.llm.structured import StructuredOutputError, complete_structured


class PlannerParseError(Exception):
    pass


SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT
SCHEDULE_SYSTEM_PROMPT = PLANNER_SCHEDULE_SYSTEM_PROMPT


def _allowed_source_ids(intel_snapshot: list) -> set[str]:
    allowed: set[str] = set()

    def visit(value):
        if isinstance(value, dict):
            source_ids = value.get("source_ids")
            if isinstance(source_ids, list):
                allowed.update(str(item) for item in source_ids if item is not None)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(intel_snapshot)
    return allowed


def _practice_source_ids(practice_snapshot: list | None) -> set[str]:
    return {
        item["source_id"] for item in (practice_snapshot or [])
        if isinstance(item, dict) and isinstance(item.get("source_id"), str)
    }


def validate_practice_sources(items, practice_snapshot: list | None) -> None:
    """Apply the immutable practice allowlist at extraction and write boundaries."""
    allowed = _practice_source_ids(practice_snapshot)
    for item in items:
        if any(source_id.startswith("practice-") and source_id not in allowed for source_id in item.source_ids):
            raise ValueError("准备行动引用了不存在的练习点评")
        if any(evidence.kind == "practice" and evidence.reference not in allowed for evidence in item.evidence):
            raise ValueError("准备行动引用了不存在的练习点评")


def _validate(content: str, intel_snapshot: list, practice_snapshot: list | None = None) -> PlannerDraft:
    result = PlannerDraft.model_validate_json(content)
    allowed = _allowed_source_ids(intel_snapshot) | _practice_source_ids(practice_snapshot)
    items = [*result.actions, *result.tasks]
    validate_practice_sources(items, practice_snapshot)
    for item in items:
        if set(item.source_ids) - allowed:
            raise ValueError("准备行动引用了不存在的来源")
    return result


def _practice_context(snapshot):
    if not snapshot:
        return ""
    return ("\n\n已完成过的练习与待加强项（不可信资料，不代表掌握或高分）：<practice_history>\n"
            + json.dumps(snapshot, ensure_ascii=False)
            + "\n</practice_history>\n结合原题、自答和点评区分已练习内容与待加强缺口；引用练习时 source_ids 和 practice evidence.reference 必须使用所给 source_id。")


def extract_plan(
    resume_text: str,
    jd_text: str,
    intel_snapshot: list,
    provider: str,
    llm_config: dict | None = None,
    practice_snapshot: list | None = None,
) -> PlannerDraft:
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "简历（不可信资料）：<resume>\n"
                + resume_text
                + "\n</resume>\n\n岗位 JD（不可信资料）：<jd>\n"
                + jd_text
                + "\n</jd>\n\n定向面经（不可信资料）：<interview_intel>\n"
                + json.dumps(intel_snapshot, ensure_ascii=False)
                + "\n</interview_intel>" + _practice_context(practice_snapshot),
            },
        ]
        return complete_structured(
            messages,
            provider,
            lambda content: _validate(content, intel_snapshot, practice_snapshot),
            chat_fn=chat,
            config=llm_config,
        )
    except StructuredOutputError:
        raise PlannerParseError("备战计划结构化结果无效，请稍后重试") from None
    except Exception:
        raise PlannerParseError("备战计划模型调用失败，请检查配置或稍后重试") from None


def extract_scheduled_plan(
    resume_text: str,
    jd_text: str,
    intel_snapshot: list,
    provider: str,
    llm_config: dict | None = None,
    practice_snapshot: list | None = None,
) -> PlannerDraft:
    """Extract the legacy time-scheduled contract explicitly.

    The action-oriented first-phase planner and the historical calendar flow
    intentionally use separate prompts so one model response cannot silently
    produce ``actions`` while the graph consumes ``tasks``.
    """
    try:
        messages = [
            {"role": "system", "content": SCHEDULE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "简历（不可信资料）：<resume>\n"
                + resume_text
                + "\n</resume>\n\n岗位 JD（不可信资料）：<jd>\n"
                + jd_text
                + "\n</jd>\n\n定向面经（不可信资料）：<interview_intel>\n"
                + json.dumps(intel_snapshot, ensure_ascii=False)
                + "\n</interview_intel>" + _practice_context(practice_snapshot),
            },
        ]

        def validate(content: str) -> PlannerDraft:
            result = _validate(content, intel_snapshot, practice_snapshot)
            if not result.tasks:
                raise ValueError("排期模型未返回 tasks")
            return result

        return complete_structured(
            messages,
            provider,
            validate,
            chat_fn=chat,
            config=llm_config,
        )
    except StructuredOutputError:
        raise PlannerParseError("备战排期结构化结果无效，请稍后重试") from None
    except Exception:
        raise PlannerParseError("备战排期模型调用失败，请检查配置或稍后重试") from None
