from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.db import SessionLocal, get_db
from app.intel_graph import _merge, resume_intel_graph, start_intel_graph
from app.intel_insight import rebuild_position_insight
from app.intel_reminders import cached_intel_payload
from app.intel_schemas import IntelInsight, IntelPayload, IntelRoundType, SourceRecord
from app.llm.provider import chat, chat_stream
from app.models import Application, Company, IntelChatMessage, IntelSession, InterviewIntel, Position, TimelineNode
from app.schemas import ApplicationRead, PositiveId

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
Provider = Literal["qwen", "openai", "anthropic", "deepseek"]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
logger = logging.getLogger(__name__)
CHAT_SYSTEM_PROMPT = (
    "你是面试准备助手。请直接回答用户的问题，不能因为当前面经没有标准答案就停止回答。"
    "面经只用于提供岗位背景和参考，答案可以结合通用专业知识推导；明确区分资料事实与通用建议，"
    "不要编造用户经历。技术题给出原理、思路和注意事项，行为题给出结构化答题思路。"
    "返回 JSON：answer 是完整回答，source_ids 是实际参考过的来源 id 数组。"
)


class IntelImageText(BaseModel):
    name: str
    text: str


class IntelCreate(BaseModel):
    application_id: PositiveId
    provider: Provider
    round_type: IntelRoundType = "未注明"
    user_paste: str | None = Field(default=None, max_length=20000)
    image_texts: list[IntelImageText] = Field(default_factory=list, max_length=6)
    supplement_web: bool = False


class IntelImage(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    data_url: str = Field(min_length=32)


class IntelImageExtractCreate(BaseModel):
    provider: Provider
    images: list[IntelImage] = Field(min_length=1, max_length=6)


class IntelImageExtractRead(BaseModel):
    images: list[IntelImageText]
    combined_text: str


class IntelResolve(BaseModel):
    resolutions: dict = Field(default_factory=dict)


class IntelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    application_id: int
    title: str
    round_type: str
    provider: str
    payload: dict
    confidence: float | None
    sources: list
    created_at: datetime
    application: ApplicationRead


class IntelPage(BaseModel):
    items: list[IntelRead]
    total: int
    page: int
    page_size: int


class IntelSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    thread_id: str
    application_id: int
    provider: str
    user_paste: str | None
    draft_payload: dict | None
    conflicts: list | None
    progress_payload: dict | None
    status: str
    interview_intel_id: int | None
    error_message: str | None
    created_at: datetime
    resolved_at: datetime | None


class IntelDossierRead(BaseModel):
    application_id: int
    position_id: int
    company_name: str
    position_title: str
    payload: IntelPayload
    materials: list[IntelRead]
    sources: list[SourceRecord]
    insight: IntelInsight
    reminder: dict | None = None


class IntelRebuildCreate(BaseModel):
    application_id: PositiveId
    provider: Provider


class IntelChatCreate(BaseModel):
    application_id: PositiveId
    provider: Provider
    question: str = Field(min_length=1, max_length=4000)


class IntelChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: Literal["user", "assistant"]
    content: str
    status: Literal["生成中", "已完成", "失败"]
    source_ids: list[str]
    created_at: datetime


class IntelChatReply(BaseModel):
    message: IntelChatMessageRead
    source_ids: list[str]


def _session_read(item: IntelSession) -> IntelSessionRead:
    data = {column.name: getattr(item, column.name) for column in IntelSession.__table__.columns}
    data["thread_id"] = str(data["thread_id"])
    return IntelSessionRead.model_validate(data)


def _run_intel_session(
    session_id: int,
    thread_id: str,
    provider: str,
    query: str,
    user_paste: str | None,
    supplement_web: bool,
    round_type: str,
    image_texts: list[dict],
) -> None:
    try:
        start_intel_graph(
            session_id,
            thread_id,
            provider,
            query,
            user_paste,
            settings.database_url,
            SessionLocal,
            supplement_web,
            round_type,
            image_texts,
        )
    except Exception:
        logger.exception("面经会话 %s 后台任务失败", session_id)
        with SessionLocal() as task_db:
            item = task_db.get(IntelSession, session_id)
            if item is not None and item.status == "聚合中":
                item.status = "失败"
                item.error_message = "面经分析失败，请稍后重试"
                item.progress_payload = {"stage": "聚合失败", "sources": []}
                item.resolved_at = datetime.now(timezone.utc)
                task_db.commit()


@router.post("/intel", response_model=IntelSessionRead, status_code=status.HTTP_201_CREATED)
def create_intel(
    payload: IntelCreate, background_tasks: BackgroundTasks, db: DbSession
):
    if not payload.supplement_web and not (payload.user_paste or "").strip() and not any(item.text.strip() for item in payload.image_texts):
        raise HTTPException(422, "关闭联网补充时必须提供手动面经内容")
    application = db.scalar(select(Application).options(joinedload(Application.position).joinedload(Position.company)).where(Application.id == payload.application_id))
    if application is None:
        raise HTTPException(404, "投递记录不存在")
    item = IntelSession(
        application_id=application.id,
        provider=payload.provider,
        round_type=payload.round_type,
        user_paste=payload.user_paste,
        image_texts=[item.model_dump(mode="json") for item in payload.image_texts],
        status="聚合中",
        progress_payload={"stage": "分析任务已创建", "sources": []},
    )
    db.add(item); db.commit(); db.refresh(item)
    query = f"{application.position.company.name} {application.position.title}"
    background_tasks.add_task(
        _run_intel_session,
        item.id,
        str(item.thread_id),
        item.provider,
        query,
        item.user_paste,
        payload.supplement_web,
        item.round_type,
        item.image_texts,
    )
    return _session_read(item)


def _application_with_position(db: Session, application_id: int) -> Application:
    application = db.scalar(
        select(Application)
        .options(joinedload(Application.position).joinedload(Position.company))
        .where(Application.id == application_id)
    )
    if application is None:
        raise HTTPException(404, "投递记录不存在")
    return application


def _position_intels(db: Session, position_id: int) -> list[InterviewIntel]:
    return list(
        db.scalars(
            select(InterviewIntel)
            .join(InterviewIntel.application)
            .where(Application.position_id == position_id)
            .options(
                joinedload(InterviewIntel.application)
                .joinedload(Application.position)
                .joinedload(Position.company)
            )
            .order_by(InterviewIntel.created_at.asc(), InterviewIntel.id.asc())
        ).all()
    )


def _namespace_payload(value, source_map: dict[str, str]):
    if isinstance(value, dict):
        return {
            key: ([source_map.get(source_id, source_id) for source_id in item] if key == "source_ids" else _namespace_payload(item, source_map))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_namespace_payload(item, source_map) for item in value]
    return value


def _dossier_payload(intels: list[InterviewIntel]) -> tuple[IntelPayload, list[SourceRecord]]:
    payloads = []
    sources = []
    for material in intels:
        source_map = {
            source.get("id"): f"material-{material.id}:{source.get('id')}"
            for source in (material.sources or [])
            if source.get("id")
        }
        payloads.append(IntelPayload.model_validate(_namespace_payload(material.payload, source_map)))
        for source in material.sources or []:
            if source.get("id"):
                sources.append(SourceRecord.model_validate({**source, "id": source_map[source["id"]]}))
    return _merge(payloads, sources), sources


def _dossier_sources(intels: list[InterviewIntel]) -> list[SourceRecord]:
    return [
        SourceRecord.model_validate({**source, "id": f"material-{material.id}:{source['id']}"})
        for material in intels
        for source in (material.sources or [])
        if source.get("id")
    ]


@router.post("/intel/images/extract", response_model=IntelImageExtractRead)
def extract_intel_images(payload: IntelImageExtractCreate):
    total_size = sum(len(image.data_url.encode("utf-8")) for image in payload.images)
    if total_size > 40_000_000 or any(len(image.data_url.encode("utf-8")) > 14_000_000 for image in payload.images):
        raise HTTPException(413, "图片总大小不能超过 40 MB，单张不能超过 14 MB")
    if any(not image.data_url.startswith(f"data:{image.mime_type};base64,") for image in payload.images):
        raise HTTPException(422, "图片必须使用匹配的 base64 data URL")
    content = [{"type": "text", "text": "请逐张提取图片中的面经文字。只输出 JSON：{\"images\":[{\"name\":\"原文件名\",\"text\":\"完整文字\"}]}，不要总结，不要编造。"}]
    for image in payload.images:
        content.extend([
            {"type": "text", "text": f"接下来是文件：{image.name}"},
            {"type": "image_url", "image_url": {"url": image.data_url}},
        ])
    try:
        raw = chat(
            [{"role": "user", "content": content}],
            provider=payload.provider,
            response_format={"type": "json_object"},
        )
        data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE))
        raw_images = data.get("images")
        if not isinstance(raw_images, list):
            raise ValueError("模型未返回 images 数组")
        images = [
            IntelImageText(
                name=str(item.get("name") or (payload.images[index].name if index < len(payload.images) else "")),
                text=str(item.get("text") or ""),
            )
            for index, item in enumerate(raw_images)
            if isinstance(item, dict)
        ]
        if not any(item.text.strip() for item in images):
            raise ValueError("模型未识别出可编辑文字")
    except Exception as exc:
        logger.exception("图片识别失败")
        raise HTTPException(422, "当前模型无法识别这些图片，请检查图片内容或稍后重试") from exc
    by_name = {item.name: item.text for item in images}
    normalized = [
        IntelImageText(
            name=image.name,
            text=by_name.get(image.name, images[index].text if index < len(images) else ""),
        )
        for index, image in enumerate(payload.images)
    ]
    combined_text = "\n\n".join(item.text for item in normalized if item.text.strip())
    if not combined_text:
        raise HTTPException(422, "当前模型未提取到可编辑文字")
    return IntelImageExtractRead(images=normalized, combined_text=combined_text)


@router.get("/intel/dossier", response_model=IntelDossierRead)
def get_intel_dossier(application_id: PositiveId, db: DbSession):
    application = _application_with_position(db, application_id)
    materials = _position_intels(db, application.position_id)
    payload = cached_intel_payload(application.position)
    if payload is None:
        payload, sources = _dossier_payload(materials) if materials else (IntelPayload(), [])
    else:
        sources = _dossier_sources(materials)
    reminder = db.scalar(
        select(TimelineNode)
        .join(TimelineNode.application)
        .where(
            Application.position_id == application.position_id,
            TimelineNode.source.like("面经准备:%"),
            TimelineNode.status == "待处理",
        )
        .order_by(TimelineNode.scheduled_at.asc().nulls_last(), TimelineNode.id.desc())
    )
    return IntelDossierRead(
        application_id=application.id,
        position_id=application.position_id,
        company_name=application.position.company.name,
        position_title=application.position.title,
        payload=payload,
        materials=[IntelRead.model_validate(item) for item in materials],
        sources=sources,
        insight=IntelInsight.model_validate(application.position.intel_insight or ({"status": "暂无资料"} if not materials else {"status": "未生成"})),
        reminder={"id": reminder.id, "scheduled_at": reminder.scheduled_at, "title": reminder.title} if reminder else None,
    )


@router.post("/intel/dossier/rebuild", response_model=IntelDossierRead)
def rebuild_intel_dossier(payload: IntelRebuildCreate, db: DbSession):
    application = _application_with_position(db, payload.application_id)
    rebuild_position_insight(application.position_id, payload.provider, SessionLocal)
    db.expire_all()
    return get_intel_dossier(payload.application_id, db)


@router.delete("/intel/materials/{material_id}")
def delete_intel_material(material_id: PositiveId, background_tasks: BackgroundTasks, db: DbSession):
    material = db.scalar(
        select(InterviewIntel)
        .options(joinedload(InterviewIntel.application))
        .where(InterviewIntel.id == material_id)
    )
    if material is None:
        raise HTTPException(404, "面经材料不存在")
    position_id = material.application.position_id
    provider = material.provider
    remaining = db.scalar(
        select(InterviewIntel.provider)
        .join(InterviewIntel.application)
        .where(Application.position_id == position_id, InterviewIntel.id != material_id)
        .order_by(InterviewIntel.created_at.desc(), InterviewIntel.id.desc())
    )
    db.delete(material)
    db.commit()
    background_tasks.add_task(rebuild_position_insight, position_id, remaining or provider, SessionLocal)
    return {"deleted": material_id}


def _chat_context(db: Session, application_id: int) -> tuple[Application, IntelPayload, list[SourceRecord]]:
    application = _application_with_position(db, application_id)
    intels = _position_intels(db, application.position_id)
    if not intels:
        raise HTTPException(409, "该岗位还没有可供问答的面经资料")
    payload = cached_intel_payload(application.position)
    if payload is None:
        payload, sources = _dossier_payload(intels)
    else:
        sources = _dossier_sources(intels)
    return application, payload, sources


def _chat_messages(application: Application, dossier: IntelPayload, sources: list[SourceRecord], question: str) -> list[dict]:
    source_text = "\n".join(f"[{source.id}] {source.title}\n{source.text}" for source in sources)
    return [
        {"role": "system", "content": CHAT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"岗位：{application.position.company.name} {application.position.title}\n汇总：{dossier.model_dump_json()}\n来源：{source_text}\n问题：{question}",
        },
    ]


def _partial_chat_answer(content: str) -> str:
    match = re.search(r'"answer"\s*:\s*"((?:\\.|[^"\\])*)', content)
    if match:
        try:
            return json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            return match.group(1).replace("\\n", "\n")
    if content.lstrip() and not content.lstrip().startswith(("{", "```")):
        return content
    return ""


def _update_chat_preview(message_id: int, content: str) -> None:
    with SessionLocal() as db:
        assistant = db.get(IntelChatMessage, message_id)
        if assistant is not None and assistant.status == "生成中":
            assistant.content = content
            db.commit()


def _run_intel_chat(message_id: int, application_id: int, provider: str, question: str) -> None:
    try:
        with SessionLocal() as db:
            assistant = db.get(IntelChatMessage, message_id)
            if assistant is None or assistant.status != "生成中":
                return
            application, dossier, sources = _chat_context(db, application_id)
            messages = _chat_messages(application, dossier, sources, question)

        raw = ""
        last_preview = ""
        last_persisted_at = time.monotonic() - 0.3
        try:
            for chunk_index, chunk in enumerate(
                chat_stream(messages, provider=provider, response_format={"type": "json_object"}),
                1,
            ):
                if chunk_index > 500:
                    raise RuntimeError("问答输出超过长度上限")
                raw += chunk
                preview = _partial_chat_answer(raw)
                if preview and preview != last_preview and time.monotonic() - last_persisted_at >= 0.3:
                    _update_chat_preview(message_id, preview)
                    last_preview = preview
                    last_persisted_at = time.monotonic()
        except Exception:
            if raw:
                raise
            raw = chat(messages, provider=provider, response_format={"type": "json_object"})
        try:
            data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE))
            answer = str(data["answer"])
            source_ids = [source_id for source_id in data.get("source_ids", []) if source_id in {source.id for source in sources}]
        except (KeyError, TypeError, ValueError):
            answer = _partial_chat_answer(raw) or raw.strip()
            if not answer:
                raise ValueError("问答模型没有返回可显示内容")
            source_ids = []
        with SessionLocal() as db:
            assistant = db.get(IntelChatMessage, message_id)
            if assistant is not None and assistant.status == "生成中":
                assistant.content = answer
                assistant.source_ids = source_ids
                assistant.status = "已完成"
                db.commit()
    except Exception:
        logger.exception("面经问答消息 %s 后台生成失败", message_id)
        with SessionLocal() as db:
            assistant = db.get(IntelChatMessage, message_id)
            if assistant is not None and assistant.status == "生成中":
                assistant.status = "失败"
                assistant.content = "问答生成失败，请稍后重试"
                assistant.source_ids = []
                db.commit()


@router.get("/intel/chat", response_model=list[IntelChatMessageRead])
def list_intel_chat(application_id: PositiveId, db: DbSession):
    application = _application_with_position(db, application_id)
    messages = db.scalars(
        select(IntelChatMessage)
        .where(IntelChatMessage.position_id == application.position_id)
        .order_by(IntelChatMessage.created_at.asc(), IntelChatMessage.id.asc())
    ).all()
    return list(messages)


@router.post("/intel/chat", response_model=IntelChatReply)
def create_intel_chat(payload: IntelChatCreate, background_tasks: BackgroundTasks, db: DbSession):
    application, _, _ = _chat_context(db, payload.application_id)
    db.add(IntelChatMessage(position_id=application.position_id, role="user", content=payload.question, status="已完成", source_ids=[]))
    assistant = IntelChatMessage(position_id=application.position_id, role="assistant", content="", status="生成中", source_ids=[])
    db.add(assistant)
    db.commit()
    db.refresh(assistant)
    background_tasks.add_task(_run_intel_chat, assistant.id, payload.application_id, payload.provider, payload.question)
    return IntelChatReply(message=assistant, source_ids=[])


@router.get("/intel-sessions", response_model=list[IntelSessionRead])
def list_intel_sessions(db: DbSession, session_status: str | None = Query(default=None, alias="status")):
    statuses = {session_status} if session_status else {"聚合中", "待裁决"}
    items = db.scalars(
        select(IntelSession)
        .where(IntelSession.status.in_(statuses))
        .order_by(IntelSession.created_at.desc(), IntelSession.id.desc())
    ).all()
    return [_session_read(item) for item in items]


@router.get("/intel", response_model=IntelPage)
def list_intel(
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 20,
    application_id: PositiveId | None = None,
    q: str | None = None,
):
    filters = []
    if application_id is not None:
        filters.append(InterviewIntel.application_id == application_id)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(or_(Company.name.ilike(pattern), Position.title.ilike(pattern)))
    query = (
        select(InterviewIntel)
        .join(InterviewIntel.application)
        .join(Application.position)
        .join(Position.company)
        .options(joinedload(InterviewIntel.application).joinedload(Application.position).joinedload(Position.company))
        .where(*filters)
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(InterviewIntel.created_at.desc(), InterviewIntel.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return IntelPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/intel-sessions/{session_id}", response_model=IntelSessionRead)
def get_intel_session(session_id: int, db: DbSession):
    item = db.get(IntelSession, session_id)
    if item is None: raise HTTPException(404, "面经会话不存在")
    return _session_read(item)


@router.post("/intel-sessions/{session_id}/resolve", response_model=IntelSessionRead)
def resolve_intel(session_id: int, payload: IntelResolve, db: DbSession):
    item = db.get(IntelSession, session_id)
    if item is None: raise HTTPException(404, "面经会话不存在")
    if item.status == "已完成": return _session_read(item)
    if item.status != "待裁决": raise HTTPException(409, "当前会话不能裁决")
    resume_intel_graph(str(item.thread_id), payload.resolutions, settings.database_url, SessionLocal)
    db.expire_all(); return _session_read(db.get(IntelSession, session_id))


@router.post("/intel-sessions/{session_id}/discard", response_model=IntelSessionRead)
def discard_intel(session_id: int, db: DbSession):
    item = db.get(IntelSession, session_id)
    if item is None:
        raise HTTPException(404, "面经会话不存在")
    if item.status == "已丢弃":
        return _session_read(item)
    if item.status == "已完成":
        raise HTTPException(409, "已写入的面经不能舍弃")
    if item.status not in {"聚合中", "待裁决", "失败"}:
        raise HTTPException(409, "当前面经会话不能舍弃")
    item.status = "已丢弃"
    item.resolved_at = datetime.now(timezone.utc)
    item.progress_payload = {**(item.progress_payload or {}), "stage": "已丢弃"}
    db.commit()
    db.refresh(item)
    return _session_read(item)
