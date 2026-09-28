import json

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from app.llm.config_store import LlmConfigError, get_effective_config, resolve_role_provider
from app.llm.provider import chat
from app.llm.structured import complete_structured
from app.models import Application, InterviewIntel, Position, PreparationTask


class BriefingAnalysisItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    value: str = Field(pattern="^(high|medium|low)$")
    relation: str = Field(pattern="^(interview|preparation|both|unrelated)$")
    reason: str = Field(max_length=180)
    recommended_action: str | None = Field(default=None, max_length=180)


class BriefingAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(max_length=600)
    items: list[BriefingAnalysisItem] = Field(default_factory=list, max_length=8)


def _intel_context(payload: dict) -> dict:
    summary = payload.get("summary") or {}
    questions = payload.get("questions") or []
    return {
        "summary": str(summary.get("value") if isinstance(summary, dict) else summary)[:500],
        "questions": [str(item.get("question") or "")[:180] for item in questions[:3] if isinstance(item, dict)],
    }


def analyze_briefing(db: Session, payload: dict) -> dict:
    try:
        provider = resolve_role_provider(db, "briefing")
        config = get_effective_config(db, provider)
    except LlmConfigError:
        return {"analysis_status": "不可用"}
    sources = payload.get("new_sources", [])[:8]
    if not sources:
        return {"analysis_status": "不可用", "analysis": {"summary": "今天没有新增公开来源。", "items": []}}
    application_ids = {item.get("application_id") for item in sources if item.get("application_id")}
    applications = {
        item.id: item
        for item in db.scalars(
            select(Application)
            .options(joinedload(Application.position).joinedload(Position.company))
            .where(Application.id.in_(application_ids))
        )
    }
    intels: dict[int, list[dict]] = {}
    for item in db.scalars(select(InterviewIntel).where(InterviewIntel.application_id.in_(application_ids))).all():
        intels.setdefault(item.application_id, []).append(_intel_context(item.payload or {}))
    actions: dict[int, list[str]] = {}
    for item in db.scalars(select(PreparationTask).where(PreparationTask.application_id.in_(application_ids), PreparationTask.status == "待处理")).all():
        actions.setdefault(item.application_id, []).append(item.title)
    context = {
        "alerts": payload.get("alerts", []),
        "today_tasks": payload.get("today_tasks", []),
        "sources": [{
            **{key: (item.get(key) or "")[:1600] for key in ("url", "title", "company_name", "position_title", "snippet")},
            "job": {
                "jd": (applications[item["application_id"]].position.jd_text or "")[:2000] if item.get("application_id") in applications else "",
                "intel": intels.get(item.get("application_id"), [])[:4],
                "actions": actions.get(item.get("application_id"), [])[:6],
            },
        } for item in sources],
    }
    messages = [
        {"role": "system", "content": "你是求职简报判断助手。只输出 JSON。只根据当前岗位资料和公开来源判断价值；不要编造岗位事实。summary 不超过 600 字，每条来源给出 value、relation、reason，可选 recommended_action。"},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]
    result = complete_structured(
        messages,
        provider,
        lambda raw: BriefingAnalysis.model_validate_json(raw),
        chat_fn=chat,
        config=config,
    )
    return {"analysis_status": "已完成", "analysis": result.model_dump(mode="json")}
