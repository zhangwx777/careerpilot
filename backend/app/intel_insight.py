import json
import logging
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from app.task_execution import TaskLeaseLost, assert_dispatch_owner
from sqlalchemy.orm import Session, sessionmaker

from app.intel_schemas import IntelInsight
from app.llm.provider import chat
from app.llm.prompts import insight_prompt, insight_system_prompt
from app.llm.structured import StructuredOutputError, clean_json, complete_structured
from app.models import Application, InterviewIntel, Position


class IntelInsightError(Exception):
    pass


logger = logging.getLogger(__name__)


def _clean_json(content: str) -> str:
    """Compatibility wrapper; new structured tasks use app.llm.structured."""
    return clean_json(content)


def _source_alias(material_id: int, source_id: str) -> str:
    return f"material-{material_id}:{source_id}"


def _canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, ""))


def _build_input(position: Position, materials: list[InterviewIntel]) -> tuple[str, set[str]]:
    rows = []
    allowed: set[str] = set()
    seen_urls: dict[str, str] = {}
    for material in materials:
        source_ids = {}
        for source in material.sources or []:
            source_id = source.get("id")
            if not source_id:
                continue
            canonical = _canonical_url(source.get("url"))
            alias = seen_urls.get(canonical) if canonical else None
            alias = alias or _source_alias(material.id, source_id)
            if canonical:
                seen_urls[canonical] = alias
            source_ids[source_id] = alias
        aliases = set(source_ids.values())
        allowed.update(aliases)
        payload = material.payload or {}
        for question in payload.get("questions", []):
            original_ids = question.get("source_ids") or list(source_ids)
            rows.append(
                {
                    "material_id": material.id,
                    "round_type": question.get("round_type") or material.round_type,
                    "category": question.get("category", "其他"),
                    "question": question.get("question", ""),
                    "answer_outline": question.get("answer_outline", ""),
                    "source_ids": [source_ids.get(item, item) for item in original_ids],
                }
            )
        for item in payload.get("preparation_items", []):
            rows.append(
                {
                    "material_id": material.id,
                    "round_type": material.round_type,
                    "category": "准备事项",
                    "question": item.get("title", ""),
                    "answer_outline": item.get("detail", ""),
                    "source_ids": [source_ids.get(source_id, source_id) for source_id in (item.get("source_ids") or list(source_ids))],
                }
            )
    schema = json.dumps(IntelInsight.model_json_schema(), ensure_ascii=False)
    content = json.dumps(
        {
            "position": f"{position.company.name} · {position.title}",
            "jd": position.jd_text or "",
            "materials": rows,
            "source_ids": sorted(allowed),
        },
        ensure_ascii=False,
    )
    prompt = insight_prompt(schema, content)
    return prompt, allowed


def _parse(content: str, allowed: set[str]) -> IntelInsight:
    result = IntelInsight.model_validate_json(clean_json(content))
    referenced = {
        source_id
        for item in result.high_frequency_directions
        for source_id in item.source_ids
    }
    referenced.update(source_id for item in result.core_questions for source_id in item.source_ids)
    referenced.update(source_id for item in result.preparation_items for source_id in item.source_ids)
    unknown = referenced - allowed
    if unknown:
        raise ValueError(f"洞察引用了不存在的来源：{sorted(unknown)}")
    directions = []
    for item in result.high_frequency_directions:
        ids = sorted(set(item.source_ids))
        if len(ids) < 2:
            continue
        directions.append(item.model_copy(update={"source_ids": ids}))
    core = [
        item.model_copy(update={"source_ids": sorted(set(item.source_ids))})
        for item in result.core_questions
        if item.source_ids
    ]
    preparation = [
        item.model_copy(update={"source_ids": sorted(set(item.source_ids))})
        for item in result.preparation_items
        if item.source_ids
    ]
    return result.model_copy(
        update={
            "status": "已生成",
            "high_frequency_directions": directions[:10],
            "core_questions": core[:8],
            "preparation_items": preparation,
            "error_message": None,
        }
    )


def _generate(prompt: str, provider: str, allowed: set[str], llm_config: dict | None = None) -> IntelInsight:
    try:
        return complete_structured(
            [
                {"role": "system", "content": insight_system_prompt("见用户资料中的 schema")},
                {"role": "user", "content": prompt},
            ],
            provider,
            lambda content: _parse(content, allowed),
            chat_fn=chat,
            config=llm_config,
        )
    except StructuredOutputError:
        raise IntelInsightError("岗位面试洞察结构化结果无效，请稍后重试") from None


def rebuild_position_insight(
    position_id: int,
    provider: str,
    session_factory: Callable[[], Session] | sessionmaker,
    llm_config: dict | None = None,
    expected_revision: int | None = None,
) -> None:
    revision = None
    try:
        with session_factory() as db:
            assert_dispatch_owner(db)
            position = db.scalar(select(Position).where(Position.id == position_id).with_for_update())
            if position is None:
                return
            if expected_revision is not None and position.intel_revision != expected_revision:
                return
            if expected_revision is None:
                position.intel_revision += 1
            revision = position.intel_revision
            materials = list(
                db.scalars(
                    select(InterviewIntel)
                    .join(InterviewIntel.application)
                    .where(Application.position_id == position_id)
                    .order_by(InterviewIntel.created_at.asc(), InterviewIntel.id.asc())
                ).all()
            )
            if position is None:
                raise IntelInsightError("岗位不存在")
            if not materials:
                position.intel_insight = IntelInsight(status="暂无资料").model_dump(mode="json")
                db.commit()
                return
            position.intel_insight = IntelInsight(status="生成中").model_dump(mode="json")
            db.commit()
            prompt, allowed = _build_input(position, materials)
        insight = _generate(prompt, provider, allowed, llm_config=llm_config)
        with session_factory() as db:
            assert_dispatch_owner(db)
            position = db.scalar(select(Position).where(Position.id == position_id).with_for_update())
            if position is not None and position.intel_revision == revision:
                position.intel_insight = insight.model_dump(mode="json")
                db.commit()
    except TaskLeaseLost:
        raise
    except Exception:
        logger.exception("岗位 %s 洞察生成失败", position_id)
        with session_factory() as db:
            assert_dispatch_owner(db)
            position = db.scalar(select(Position).where(Position.id == position_id).with_for_update())
            if position is not None and revision is not None and position.intel_revision == revision:
                position.intel_insight = IntelInsight(status="失败", error_message="岗位洞察生成失败，请稍后重试").model_dump(mode="json")
                db.commit()
