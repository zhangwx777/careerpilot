"""Add interview follow-up records without synthesizing legacy history."""
from sqlalchemy import text
from app.models import FollowupGoal, FollowupCheck

def upgrade(connection):
    connection.execute(text("ALTER TABLE preparation_task ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1"))
    connection.execute(text("ALTER TABLE preparation_task ALTER COLUMN revision SET DEFAULT 1"))
    FollowupGoal.__table__.create(connection, checkfirst=True)
    FollowupCheck.__table__.create(connection, checkfirst=True)
