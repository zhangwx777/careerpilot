import os
import unittest

from sqlalchemy import inspect

from app.db import to_psycopg_connection_string


class DatabaseConfigTestCase(unittest.TestCase):
    def test_converts_sqlalchemy_psycopg_url_for_checkpointer(self):
        self.assertEqual(
            to_psycopg_connection_string(
                "postgresql+psycopg://user:password@localhost/database"
            ),
            "postgresql://user:password@localhost/database",
        )


@unittest.skipUnless(
    os.getenv("TEST_DATABASE_URL"),
    "需要显式配置 TEST_DATABASE_URL，不允许回退到开发数据库",
)
class PostgresInitializationTestCase(unittest.TestCase):
    def test_initialization_is_idempotent_and_creates_required_tables(self):
        from sqlalchemy import create_engine

        from scripts.init_db import initialize_database

        database_url = os.environ["TEST_DATABASE_URL"]
        initialize_database(database_url)
        initialize_database(database_url)

        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            self.assertIn("parse_session", tables)
            self.assertTrue({"resume_profile", "planner_session", "preparation_task", "daily_briefing", "reported_source", "llm_provider_config", "llm_settings"} <= tables)
            self.assertIn("checkpoints", tables)
            self.assertIn("checkpoint_writes", tables)

            timeline_columns = {
                column["name"] for column in inspector.get_columns("timeline_node")
            }
            self.assertIn("ends_at", timeline_columns)
            self.assertTrue({"title", "detail"} <= timeline_columns)

            for table in ("parse_session", "intel_session", "planner_session"):
                columns = {column["name"] for column in inspector.get_columns(table)}
                self.assertTrue({"llm_snapshot", "prompt_version"} <= columns)
            chat_columns = {column["name"] for column in inspector.get_columns("intel_chat_message")}
            self.assertTrue({"provider", "llm_snapshot", "prompt_version"} <= chat_columns)

            timeline_indexes = {
                index["name"] for index in inspector.get_indexes("timeline_node")
            }
            self.assertIn("ix_timeline_node_scheduled_at", timeline_indexes)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
