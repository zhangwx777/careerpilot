from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Position


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
