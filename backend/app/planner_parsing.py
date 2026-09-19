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


def _validate(content: str, intel_snapshot: list) -> PlannerDraft:
    result = PlannerDraft.model_validate_json(content)
    allowed = _allowed_source_ids(intel_snapshot)
    used = {
        source_id
        for action in result.actions
        for source_id in action.source_ids
    }
    if used - allowed:
        raise ValueError("准备行动引用了不存在的面经来源")
    return result


def extract_plan(
    resume_text: str,
    jd_text: str,
    intel_snapshot: list,
    provider: str,
    llm_config: dict | None = None,
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
                + "\n</interview_intel>",
            },
        ]
        return complete_structured(
            messages,
            provider,
            lambda content: _validate(content, intel_snapshot),
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
                + "\n</interview_intel>",
            },
        ]

        def validate(content: str) -> PlannerDraft:
            result = PlannerDraft.model_validate_json(content)
            if not result.tasks:
                raise ValueError("排期模型未返回 tasks")
            allowed = _allowed_source_ids(intel_snapshot)
            used = {source_id for task in result.tasks for source_id in task.source_ids}
            if used - allowed:
                raise ValueError("排期任务引用了不存在的面经来源")
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
