from typing import Annotated
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.application_records import materialize_position
from app.llm.config_store import (
    LlmConfigError,
    get_effective_config,
    get_role_status,
    save_search_config,
    search_status,
    list_available_models,
    list_provider_status,
    resolve_provider,
    save_role_providers,
    save_provider,
    set_default_provider,
    touch_validation,
    touch_capabilities,
    validate_base_url,
    validate_provider,
)
from app.llm.provider import LlmCallError, chat, chat_stream, chat_with_tools
from app.llm_schemas import (
    DefaultProviderUpdate,
    ProviderConfigWrite,
    ProviderRead,
    ProviderTestWrite,
    ProviderTestRead,
    ProviderModelsRead,
    SearchConfigRead,
    SearchConfigWrite,
    LlmRolesRead,
    LlmRolesWrite,
)
from app.models import Application, Company, Position
from app.schemas import (
    ApplicationCreate,
    ApplicationPage,
    ApplicationRead,
    ApplicationStatus,
    ApplicationUpdate,
    CompanyCreate,
    CompanyPage,
    CompanyRead,
    CompanyUpdate,
    PositionCreate,
    PositionPage,
    PositionRead,
    PositionUpdate,
    StatusTransition,
)

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
@router.get("/providers", response_model=list[ProviderRead])
@router.get("/llm/providers", response_model=list[ProviderRead], include_in_schema=False)
def list_providers(db: DbSession):
    """返回四家 provider 的脱敏状态，供任务选择和设置页使用。"""
    try:
        return list_provider_status(db)
    except LlmConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.put("/llm/providers/{provider}", response_model=ProviderRead)
def update_provider(provider: str, payload: ProviderConfigWrite, db: DbSession):
    try:
        save_provider(
            db,
            provider,
            api_key=payload.api_key,
            model=payload.model,
            base_url=payload.base_url,
        )
    except LlmConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    try:
        return next(item for item in list_provider_status(db) if item["name"] == provider)
    except LlmConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.delete("/llm/providers/{provider}", response_model=list[ProviderRead])
def delete_provider(provider: str, db: DbSession):
    from app.models import LlmProviderConfig, LlmSettings

    try:
        validate_provider(provider)
    except LlmConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    row = db.get(LlmProviderConfig, provider)
    if row is not None:
        db.delete(row)
        settings_row = db.get(LlmSettings, 1)
        if settings_row:
            if settings_row.default_provider == provider:
                settings_row.default_provider = None
            for field in ("interview_provider", "planner_provider", "briefing_provider", "vision_provider"):
                if getattr(settings_row, field, None) == provider:
                    setattr(settings_row, field, None)
        db.commit()
    try:
        return list_provider_status(db)
    except LlmConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.post("/llm/providers/{provider}/test", response_model=ProviderTestRead)
def test_provider(provider: str, payload: ProviderTestWrite, db: DbSession):
    started = time.perf_counter()
    try:
        validate_provider(provider)
        saved = {}
        if not payload.api_key or not payload.model or "base_url" not in payload.model_fields_set:
            saved = get_effective_config(db, provider)
        model = payload.model or saved.get("model")
        api_key = payload.api_key or saved.get("api_key")
        # An omitted Base URL reuses the saved endpoint; an explicit null/empty
        # value from the settings page intentionally tests the official URL.
        base_url_value = payload.base_url if "base_url" in payload.model_fields_set else saved.get("api_base")
        base_url = validate_base_url(base_url_value)
        config = {
            "api_key": api_key,
            "api_base": base_url,
            "model": model,
        }
        chat(
            [
                {
                    "role": "system",
                    "content": "这是结构化输出连通性检查。只返回 JSON：{\"ok\":true}。",
                },
                {"role": "user", "content": "执行连通性检查。"},
            ],
            provider=provider,
            response_format={"type": "json_object"},
            config=config,
            generation="structured",
        )
        supports_tools: bool | None = None
        supports_streaming: bool | None = None
        try:
            tool_probe = chat_with_tools(
                [
                    {"role": "system", "content": "请调用工具 probe_capability。"},
                    {"role": "user", "content": "执行工具能力检查。"},
                ],
                [{"type": "function", "function": {"name": "probe_capability", "description": "能力测试工具", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}],
                provider=provider,
                config=config,
            )
            supports_tools = bool(tool_probe.get("tool_calls"))
        except LlmCallError as exc:
            # A successful ordinary JSON call still proves the endpoint is
            # usable. Tool capability is recorded independently so a gateway
            # that rejects tools can remain available to fixed Workflows.
            supports_tools = False if exc.kind == "tool_call_unsupported" else None
        except Exception:
            supports_tools = None
        try:
            stream = chat_stream(
                [{"role": "user", "content": "只回复 ok"}],
                provider=provider,
                config=config,
                generation="chat",
            )
            supports_streaming = next(iter(stream), None) is not None
        except Exception:
            supports_streaming = None
        touch_capabilities(
            db,
            provider,
            supports_tools=supports_tools,
            supports_json=True,
            supports_streaming=supports_streaming,
        )
    except (LlmConfigError, ValueError) as exc:
        touch_validation(db, provider, "验证失败", str(exc))
        return ProviderTestRead(
            provider=provider,
            ok=False,
            message=str(exc),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
    except LlmCallError as exc:
        touch_validation(db, provider, "验证失败", str(exc))
        if exc.kind == "tool_call_unsupported":
            touch_capabilities(db, provider, supports_tools=False, supports_json=None, supports_streaming=None)
        return ProviderTestRead(
            provider=provider,
            ok=False,
            message=str(exc),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
    except Exception:
        touch_validation(db, provider, "验证失败", "连接失败，请检查 API key、model、Base URL 或网络。")
        return ProviderTestRead(
            provider=provider,
            ok=False,
            message="连接失败，请检查 API key、model、Base URL 或网络。",
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
    touch_validation(db, provider, "已验证", "连接成功")
    return ProviderTestRead(
        provider=provider,
        ok=True,
        message="连接成功",
        latency_ms=round((time.perf_counter() - started) * 1000),
    )


@router.post("/llm/providers/{provider}/models", response_model=ProviderModelsRead)
def list_provider_models(provider: str, payload: ProviderTestWrite, db: DbSession):
    """读取 provider 的模型目录；请求字段只作临时覆盖，不会保存。"""
    try:
        overrides = {}
        if payload.api_key:
            overrides["api_key"] = payload.api_key
        if payload.model:
            overrides["model"] = payload.model
        if "base_url" in payload.model_fields_set:
            overrides["api_base"] = validate_base_url(payload.base_url)
        models = list_available_models(db, provider, overrides=overrides)
        return ProviderModelsRead(provider=provider, models=models)
    except (LlmConfigError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception as exc:
        # Keep provider/network details and credentials out of the response.
        from app.llm.config_store import LlmModelsError
        if isinstance(exc, LlmModelsError):
            raise HTTPException(status_code=502, detail=str(exc)) from None
        raise HTTPException(status_code=502, detail="读取模型目录失败，请检查 API key、Base URL 或网络") from None


@router.put("/llm/default", response_model=list[ProviderRead])
def update_default_provider(payload: DefaultProviderUpdate, db: DbSession):
    try:
        set_default_provider(db, payload.provider)
    except LlmConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    try:
        return list_provider_status(db)
    except LlmConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.get("/llm/roles", response_model=LlmRolesRead)
def get_llm_roles(db: DbSession):
    return {"roles": get_role_status(db), "providers": list_provider_status(db)}


@router.put("/llm/roles", response_model=LlmRolesRead)
def update_llm_roles(payload: LlmRolesWrite, db: DbSession):
    try:
        save_role_providers(db, payload.model_dump())
        return {"roles": get_role_status(db), "providers": list_provider_status(db)}
    except LlmConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/llm/search", response_model=SearchConfigRead)
def get_search_config(db: DbSession):
    return search_status(db)


@router.put("/llm/search", response_model=SearchConfigRead)
def update_search_config(payload: SearchConfigWrite, db: DbSession):
    return save_search_config(db, api_key=payload.api_key, endpoint=payload.endpoint, tool_name=payload.tool_name)


@router.delete("/llm/search", response_model=SearchConfigRead)
def delete_search_config(db: DbSession):
    return save_search_config(db, api_key=None, endpoint=None, tool_name=None)


def _get_company(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="公司不存在")
    return company


def _get_position(db: Session, position_id: int) -> Position:
    position = db.scalar(
        select(Position)
        .options(joinedload(Position.company))
        .where(Position.id == position_id)
    )
    if position is None:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return position


def _get_application(db: Session, application_id: int) -> Application:
    application = db.scalar(
        select(Application)
        .options(
            joinedload(Application.position).joinedload(Position.company)
        )
        .where(Application.id == application_id)
    )
    if application is None:
        raise HTTPException(status_code=404, detail="投递记录不存在")
    return application


@router.get("/companies", response_model=CompanyPage)
def list_companies(
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 20,
    q: str | None = Query(default=None, max_length=200),
):
    filters = []
    if q and (keyword := q.strip()):
        filters.append(Company.name.ilike(f"%{keyword}%"))

    total = db.scalar(select(func.count()).select_from(Company).where(*filters)) or 0
    companies = db.scalars(
        select(Company)
        .where(*filters)
        .order_by(Company.created_at.desc(), Company.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return CompanyPage(items=list(companies), total=total, page=page, page_size=page_size)


@router.post("/companies", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: DbSession):
    company = Company(**payload.model_dump())
    db.add(company)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="公司名称已存在")
    db.refresh(company)
    return company


@router.get("/companies/{company_id}", response_model=CompanyRead)
def get_company(company_id: int, db: DbSession):
    return _get_company(db, company_id)


@router.patch("/companies/{company_id}", response_model=CompanyRead)
def update_company(company_id: int, payload: CompanyUpdate, db: DbSession):
    company = _get_company(db, company_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="公司名称已存在")
    db.refresh(company)
    return company


@router.delete("/companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company(company_id: int, db: DbSession):
    _get_company(db, company_id)
    db.execute(delete(Company).where(Company.id == company_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/positions", response_model=PositionPage)
def list_positions(
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 20,
    company_id: int | None = Query(default=None, gt=0),
    q: str | None = Query(default=None, max_length=200),
):
    filters = []
    if company_id is not None:
        filters.append(Position.company_id == company_id)
    if q and (keyword := q.strip()):
        filters.append(
            or_(Position.title.ilike(f"%{keyword}%"), Company.name.ilike(f"%{keyword}%"))
        )

    total = db.scalar(
        select(func.count())
        .select_from(Position)
        .join(Position.company)
        .where(*filters)
    ) or 0
    positions = db.scalars(
        select(Position)
        .join(Position.company)
        .options(joinedload(Position.company))
        .where(*filters)
        .order_by(Position.created_at.desc(), Position.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PositionPage(items=list(positions), total=total, page=page, page_size=page_size)


@router.post("/positions", response_model=PositionRead, status_code=status.HTTP_201_CREATED)
def create_position(payload: PositionCreate, db: DbSession):
    _get_company(db, payload.company_id)
    position = Position(**payload.model_dump())
    db.add(position)
    db.commit()
    return _get_position(db, position.id)


@router.get("/positions/{position_id}", response_model=PositionRead)
def get_position(position_id: int, db: DbSession):
    return _get_position(db, position_id)


@router.patch("/positions/{position_id}", response_model=PositionRead)
def update_position(position_id: int, payload: PositionUpdate, db: DbSession):
    position = _get_position(db, position_id)
    changes = payload.model_dump(exclude_unset=True)
    if "company_id" in changes:
        _get_company(db, changes["company_id"])
    for field, value in changes.items():
        setattr(position, field, value)
    db.commit()
    return _get_position(db, position.id)


@router.delete("/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_position(position_id: int, db: DbSession):
    _get_position(db, position_id)
    db.execute(delete(Position).where(Position.id == position_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/applications", response_model=ApplicationPage)
def list_applications(
    db: DbSession,
    page: Page = 1,
    page_size: PageSize = 20,
    q: str | None = Query(default=None, max_length=200),
    application_status: ApplicationStatus | None = Query(default=None, alias="status"),
    company_id: int | None = Query(default=None, gt=0),
    position_id: int | None = Query(default=None, gt=0),
):
    filters = []
    if q and (keyword := q.strip()):
        filters.append(
            or_(
                Company.name.ilike(f"%{keyword}%"),
                Position.title.ilike(f"%{keyword}%"),
                Application.note.ilike(f"%{keyword}%"),
            )
        )
    if application_status is not None:
        filters.append(Application.status == application_status)
    if company_id is not None:
        filters.append(Position.company_id == company_id)
    if position_id is not None:
        filters.append(Application.position_id == position_id)

    total = db.scalar(
        select(func.count())
        .select_from(Application)
        .join(Application.position)
        .join(Position.company)
        .where(*filters)
    ) or 0
    applications = db.scalars(
        select(Application)
        .join(Application.position)
        .join(Position.company)
        .options(joinedload(Application.position).joinedload(Position.company))
        .where(*filters)
        .order_by(Application.created_at.desc(), Application.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ApplicationPage(
        items=list(applications), total=total, page=page, page_size=page_size
    )


@router.post(
    "/applications",
    response_model=ApplicationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_application(payload: ApplicationCreate, db: DbSession):
    position = materialize_position(
        db,
        payload.company_name,
        payload.position_title,
        payload.jd_text,
    )
    application = Application(
        position_id=position.id,
        status=payload.status,
        applied_at=payload.applied_at,
        note=payload.note,
    )
    db.add(application)
    db.commit()
    return _get_application(db, application.id)


@router.get("/applications/{application_id}", response_model=ApplicationRead)
def get_application(application_id: int, db: DbSession):
    return _get_application(db, application_id)


@router.patch("/applications/{application_id}", response_model=ApplicationRead)
def update_application(
    application_id: int, payload: ApplicationUpdate, db: DbSession
):
    application = _get_application(db, application_id)
    changes = payload.model_dump(exclude_unset=True)
    if "company_name" in changes or "position_title" in changes or "jd_text" in changes:
        position = materialize_position(
            db,
            changes.pop("company_name", application.position.company.name),
            changes.pop("position_title", application.position.title),
            changes.pop("jd_text", None),
        )
        application.position_id = position.id
    for field, value in changes.items():
        setattr(application, field, value)
    db.commit()
    return _get_application(db, application.id)


@router.delete(
    "/applications/{application_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_application(application_id: int, db: DbSession):
    _get_application(db, application_id)
    db.execute(delete(Application).where(Application.id == application_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/applications/{application_id}/status", response_model=ApplicationRead
)
def transition_application_status(
    application_id: int, payload: StatusTransition, db: DbSession
):
    application = _get_application(db, application_id)
    current_status = application.status
    next_status = payload.status

    if current_status == next_status:
        return application

    application.status = next_status
    db.commit()
    return _get_application(db, application.id)
