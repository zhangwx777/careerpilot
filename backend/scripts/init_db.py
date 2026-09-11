"""数据库初始化脚本。运行 `python -m scripts.init_db [--test]`。"""

import argparse

from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import create_engine, text

from app.config import settings
from app.db import Base, to_psycopg_connection_string

# 导入 models 触发 ORM 注册（否则 Base.metadata 里没有表）
import app.models  # noqa: F401


def initialize_database(database_url: str) -> None:
    target_engine = create_engine(database_url, echo=False)
    try:
        Base.metadata.create_all(target_engine)
        with target_engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TYPE application_status ADD VALUE IF NOT EXISTS '测评' "
                    "BEFORE '笔试'"
                )
            )
            connection.execute(
                text(
                    "ALTER TYPE application_status ADD VALUE IF NOT EXISTS 'AI面' "
                    "BEFORE '一面'"
                )
            )
            connection.execute(
                text(
                    "ALTER TYPE node_type ADD VALUE IF NOT EXISTS '测评' "
                    "BEFORE '笔试'"
                )
            )
            connection.execute(
                text(
                    "ALTER TYPE node_type ADD VALUE IF NOT EXISTS 'AI面' "
                    "BEFORE '一面'"
                )
            )
            connection.execute(
                text(
                    "ALTER TYPE planner_session_status ADD VALUE IF NOT EXISTS '已完成' "
                    "BEFORE '已丢弃'"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE timeline_node "
                    "ADD COLUMN IF NOT EXISTS ends_at TIMESTAMPTZ"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE resume_profile "
                    "ADD COLUMN IF NOT EXISTS file_name VARCHAR(255)"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE timeline_node "
                    "ADD COLUMN IF NOT EXISTS time_mode VARCHAR(20) "
                    "NOT NULL DEFAULT '固定时间'"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE timeline_node "
                    "ADD COLUMN IF NOT EXISTS title VARCHAR(200)"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE timeline_node "
                    "ADD COLUMN IF NOT EXISTS detail TEXT"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_timeline_node_scheduled_at "
                    "ON timeline_node (scheduled_at)"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE intel_session "
                    "ADD COLUMN IF NOT EXISTS progress_payload JSONB"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE position "
                    "ADD COLUMN IF NOT EXISTS intel_insight JSONB"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE intel_session "
                    "ADD COLUMN IF NOT EXISTS round_type VARCHAR(20) NOT NULL DEFAULT '未注明'"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE intel_session "
                    "ADD COLUMN IF NOT EXISTS image_texts JSONB NOT NULL DEFAULT '[]'::jsonb"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE interview_intel "
                    "ADD COLUMN IF NOT EXISTS title VARCHAR(200) NOT NULL DEFAULT '未命名面经'"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE interview_intel "
                    "ADD COLUMN IF NOT EXISTS round_type VARCHAR(20) NOT NULL DEFAULT '未注明'"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE interview_intel "
                    "ADD COLUMN IF NOT EXISTS provider VARCHAR(50) NOT NULL DEFAULT 'qwen'"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE intel_chat_message "
                    "ADD COLUMN IF NOT EXISTS status VARCHAR(20) "
                    "NOT NULL DEFAULT '已完成'"
                )
            )

        with PostgresSaver.from_conn_string(
            to_psycopg_connection_string(database_url)
        ) as checkpointer:
            checkpointer.setup()
    finally:
        target_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="初始化 TEST_DATABASE_URL")
    args = parser.parse_args()

    if args.test:
        if not settings.test_database_url:
            raise SystemExit("未配置 TEST_DATABASE_URL")
        database_url = settings.test_database_url
    else:
        database_url = settings.database_url

    initialize_database(database_url)
    tables = ", ".join(sorted(Base.metadata.tables.keys()))
    print(f"数据库初始化完成：{tables}；LangGraph checkpoint 表已就绪")


if __name__ == "__main__":
    main()
