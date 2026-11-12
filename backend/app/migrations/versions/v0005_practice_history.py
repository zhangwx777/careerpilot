"""Preserve original position and review provenance without inferred backfill."""
from sqlalchemy import Connection, text


def upgrade(connection: Connection) -> None:
    connection.execute(text("ALTER TABLE planner_session ADD COLUMN IF NOT EXISTS position_id_snapshot INTEGER"))
    connection.execute(text("ALTER TABLE planner_session ADD COLUMN IF NOT EXISTS practice_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb"))
    connection.execute(text("ALTER TABLE preparation_task ADD COLUMN IF NOT EXISTS feedback_completed_at TIMESTAMPTZ"))
    connection.execute(text("ALTER TABLE preparation_task ADD COLUMN IF NOT EXISTS feedback_answer_snapshot TEXT"))
    connection.execute(text("ALTER TABLE preparation_task ADD COLUMN IF NOT EXISTS feedback_question_snapshot TEXT"))
