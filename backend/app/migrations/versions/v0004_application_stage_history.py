"""Add stage provenance without inferring history from existing records."""

from sqlalchemy import Connection, text


def upgrade(connection: Connection) -> None:
    from app.models import ApplicationStageChange

    ApplicationStageChange.__table__.create(connection, checkfirst=True)
    connection.execute(text("ALTER TABLE timeline_node ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 0"))
