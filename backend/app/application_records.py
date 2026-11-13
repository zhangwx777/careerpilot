from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, Company, Position


def materialize_position(
    db: Session, company_name: str, position_title: str, jd_text: str | None = None
) -> Position:
    company = db.scalar(select(Company).where(Company.name == company_name))
    if company is None:
        company = Company(name=company_name)
        db.add(company)
        db.flush()

    position = db.scalar(
        select(Position).where(
            Position.company_id == company.id,
            Position.title == position_title,
        )
    )
    if position is None:
        position = Position(
            company_id=company.id,
            title=position_title,
            jd_text=jd_text,
        )
        db.add(position)
        db.flush()
    elif jd_text:
        position.jd_text = jd_text
    return position


def lock_parent_deletion(db: Session, *, position_id: int | None = None, company_id: int | None = None) -> None:
    """Keep cascade deletion in Application -> Position -> Company lock order.

    Parent FOR UPDATE blocks new FK members. Recheck after acquiring it rather
    than chasing newly discovered applications backwards through the lock order.
    Membership races are retryable, with no deletion having happened.
    """
    positions_query = select(Position.id).order_by(Position.id)
    if company_id is not None:
        positions_query = positions_query.where(Position.company_id == company_id)
    else:
        positions_query = positions_query.where(Position.id == position_id)
    position_ids = list(db.scalars(positions_query))
    applications_query = select(Application.id).where(Application.position_id.in_(position_ids)).order_by(Application.id)
    application_ids = list(db.scalars(applications_query))
    db.scalars(select(Application).where(Application.id.in_(application_ids)).order_by(Application.id)
               .with_for_update(key_share=True).execution_options(populate_existing=True)).all()
    db.scalars(select(Position).where(Position.id.in_(position_ids)).order_by(Position.id)
               .with_for_update().execution_options(populate_existing=True)).all()
    if company_id is not None:
        parent = db.scalar(select(Company).where(Company.id == company_id).with_for_update().execution_options(populate_existing=True))
        if parent is None:
            raise HTTPException(404, "公司不存在")
    elif not db.get(Position, position_id):
        raise HTTPException(404, "岗位不存在")
    if list(db.scalars(positions_query)) != position_ids or list(db.scalars(applications_query)) != application_ids:
        raise HTTPException(409, "关联岗位或投递已变化，请刷新后重试删除")
