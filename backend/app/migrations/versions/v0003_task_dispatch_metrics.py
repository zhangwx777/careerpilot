"""Persist aggregate execution measurements on durable task dispatches."""

from sqlalchemy import Connection, text


def upgrade(connection: Connection) -> None:
    connection.execute(
        text(
            "ALTER TABLE task_dispatch "
            "ADD COLUMN IF NOT EXISTS metrics JSONB NOT NULL DEFAULT '{}'::jsonb"
        )
    )
