import json

from pydantic import ValidationError

from app.llm.provider import chat
from app.planner_schemas import PlannerDraft


class PlannerParseError(Exception):
    pass


SYSTEM_PROMPT = """你是求职备战分析助手。只输出 JSON，不得编造简历、JD 或面经中没有的事实。
字段只能是 summary、strengths、gaps、actions。strengths 和 gaps 必须包含 name、evidence；action 必须包含 title、detail、priority、source_ids。
按优先级输出准备行动，并在 source_ids 中引用提供的面经材料编号；没有依据时使用空数组。"""


def extract_plan(resume_text: str, jd_text: str, intel_snapshot: list, provider: str) -> PlannerDraft:
    try:
        content = chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "简历：\n"
                    + resume_text
                    + "\n\n岗位 JD：\n"
                    + jd_text
                    + "\n\n定向面经：\n"
                    + json.dumps(intel_snapshot, ensure_ascii=False),
                },
            ],
            provider=provider,
            response_format={"type": "json_object"},
        )
        return PlannerDraft.model_validate_json(content)
    except (ValidationError, ValueError, TypeError) as exc:
        raise PlannerParseError(f"备战计划结构化结果无效：{exc}") from exc
    except Exception as exc:
        raise PlannerParseError(f"备战计划模型调用失败：{exc}") from exc
