"""Create missing ORM tables for new and partially initialized databases."""

from sqlalchemy import Connection

from app.db import Base
import app.models  # noqa: F401


def upgrade(connection: Connection) -> None:
    Base.metadata.create_all(bind=connection)
