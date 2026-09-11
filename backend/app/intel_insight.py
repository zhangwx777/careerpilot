import json
import logging
import re
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.intel_schemas import IntelInsight
from app.llm.provider import chat
from app.models import Application, InterviewIntel, Position


class IntelInsightError(Exception):
    pass


logger = logging.getLogger(__name__)


def _clean_json(content: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)


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
    prompt = (
        "你是岗位面试洞察整理器。只依据输入中的面经问题、准备事项和岗位 JD 输出 JSON。\n"
        "高频考察方向必须按能力方向语义聚合，不要求问题文字相同；同一来源只能计一次。"
        "只有至少来自两个不同 source_ids 的方向才能进入 high_frequency_directions。"
        "高频统计不受 round_type 限制，但必须保留涉及轮次。"
        "core_questions 最多 8 条，选择最值得准备的问题，可包含只出现一次但重要的问题。"
        "preparation_items 只能围绕 high_frequency_directions 和 core_questions 生成。"
        "所有 source_ids 必须来自输入的 source_ids，不能创造新的来源 ID。"
        "不要输出代码变量名、schema 字段解释或内部实现名称。\n"
        f"JSON Schema：{schema}\n输入：{content}"
    )
    return prompt, allowed


def _parse(content: str, allowed: set[str]) -> IntelInsight:
    result = IntelInsight.model_validate_json(_clean_json(content))
    directions = []
    for item in result.high_frequency_directions:
        ids = sorted(set(item.source_ids) & allowed)
        if len(ids) < 2:
            continue
        directions.append(item.model_copy(update={"source_ids": ids}))
    core = [
        item.model_copy(update={"source_ids": sorted(set(item.source_ids) & allowed)})
        for item in result.core_questions
        if set(item.source_ids) & allowed
    ]
    preparation = [
        item.model_copy(update={"source_ids": sorted(set(item.source_ids) & allowed)})
        for item in result.preparation_items
        if set(item.source_ids) & allowed
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


def _generate(prompt: str, provider: str, allowed: set[str]) -> IntelInsight:
    raw = chat([{"role": "user", "content": prompt}], provider=provider, response_format={"type": "json_object"})
    try:
        return _parse(raw, allowed)
    except (ValidationError, ValueError, TypeError) as first_error:
        repaired = chat(
            [
                {"role": "user", "content": prompt},
                {"role": "user", "content": f"上一次输出无效，请只返回修正后的 JSON。错误：{first_error}\n上一次结果：{raw}"},
            ],
            provider=provider,
            response_format={"type": "json_object"},
        )
        try:
            return _parse(repaired, allowed)
        except (ValidationError, ValueError, TypeError) as exc:
            raise IntelInsightError(f"岗位面试洞察结构化结果无效：{exc}") from exc


def rebuild_position_insight(position_id: int, provider: str, session_factory: Callable[[], Session] | sessionmaker) -> None:
    try:
        with session_factory() as db:
            position = db.scalar(select(Position).where(Position.id == position_id))
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
        insight = _generate(prompt, provider, allowed)
        with session_factory() as db:
            position = db.get(Position, position_id)
            if position is not None:
                position.intel_insight = insight.model_dump(mode="json")
                db.commit()
    except Exception:
        logger.exception("岗位 %s 洞察生成失败", position_id)
        with session_factory() as db:
            position = db.get(Position, position_id)
            if position is not None:
                position.intel_insight = IntelInsight(status="失败", error_message="岗位洞察生成失败，请稍后重试").model_dump(mode="json")
                db.commit()
