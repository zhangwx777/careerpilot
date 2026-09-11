from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.application_records import materialize_position
from app.llm.registry import PROVIDERS
from app.models import APPLICATION_STATUS, Application, Company, Position
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
    ProviderRead,
    StatusTransition,
)

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
STATUS_ORDER = {
    application_status: index
    for index, application_status in enumerate(APPLICATION_STATUS)
    if application_status != "挂"
}


@router.get("/providers", response_model=list[ProviderRead])
def list_providers():
    """返回 .env 里同时配好 key 和 model 的厂商及其模型名，供前端下拉展示。"""
    return [
        ProviderRead(name=name, model=cfg["model"])
        for name, cfg in PROVIDERS.items()
        if cfg["api_key"] and cfg["model"]
    ]


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
    if current_status in {"offer", "挂"}:
        raise HTTPException(status_code=409, detail="已结束的投递不能继续流转")
    if next_status != "挂" and STATUS_ORDER[next_status] <= STATUS_ORDER[current_status]:
        raise HTTPException(status_code=409, detail="投递状态只能向后续阶段流转")

    application.status = next_status
    db.commit()
    return _get_application(db, application.id)
