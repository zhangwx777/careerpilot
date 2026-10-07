import os
import unittest
from uuid import uuid4

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
        from sqlalchemy import create_engine, text

        from scripts.init_db import initialize_database

        database_url = os.environ["TEST_DATABASE_URL"]
        initialize_database(database_url)
        initialize_database(database_url)

        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            self.assertIn("parse_session", tables)
            self.assertTrue({"resume_profile", "planner_session", "preparation_task", "daily_briefing", "reported_source", "llm_provider_config", "llm_settings", "agent_run"} <= tables)
            self.assertIn("checkpoints", tables)
            self.assertIn("checkpoint_writes", tables)

            with engine.connect() as connection:
                migrations = connection.execute(
                    text(
                        "SELECT version, name FROM careerpilot_schema_migrations "
                        "ORDER BY version"
                    )
                ).all()
            self.assertEqual(
                [(row.version, row.name) for row in migrations],
                [
                    (1, "bootstrap_tables"),
                    (2, "adopt_legacy_schema"),
                    (3, "task_dispatch_metrics"),
                ],
            )

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

            dispatch_columns = {
                column["name"] for column in inspector.get_columns("task_dispatch")
            }
            self.assertIn("metrics", dispatch_columns)
        finally:
            engine.dispose()

    def test_unknown_future_schema_version_fails_closed(self):
        from sqlalchemy import create_engine, text

        from scripts.init_db import initialize_database

        database_url = os.environ["TEST_DATABASE_URL"]
        initialize_database(database_url)
        engine = create_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO careerpilot_schema_migrations (version, name) "
                        "VALUES (999, 'future_version')"
                    )
                )
            with self.assertRaisesRegex(RuntimeError, "迁移版本账本"):
                initialize_database(database_url)
        finally:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "DELETE FROM careerpilot_schema_migrations "
                        "WHERE version = 999"
                    )
                )
            engine.dispose()

    def test_legacy_position_schema_is_adopted_without_losing_rows(self):
        from sqlalchemy import create_engine, inspect, text
        from sqlalchemy.engine import make_url

        from scripts.init_db import initialize_database

        base_url = make_url(os.environ["TEST_DATABASE_URL"])
        schema = f"migration_compat_{uuid4().hex[:12]}"
        admin_engine = create_engine(base_url)
        try:
            with admin_engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))

            isolated_url = base_url.update_query_dict(
                {"options": f"-csearch_path={schema}"}
            )
            with create_engine(isolated_url).begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE position ("
                        "id SERIAL PRIMARY KEY, "
                        "company_id INTEGER NOT NULL, "
                        "title VARCHAR(200) NOT NULL)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO position (id, company_id, title) "
                        "VALUES (41, 7, 'Legacy position')"
                    )
                )

            initialize_database(isolated_url.render_as_string(hide_password=False))
            check_engine = create_engine(isolated_url)
            try:
                columns = {
                    column["name"]
                    for column in inspect(check_engine).get_columns("position")
                }
                self.assertTrue({"intel_revision", "intel_insight"} <= columns)
                with check_engine.connect() as connection:
                    title = connection.execute(
                        text("SELECT title FROM position WHERE id = 41")
                    ).scalar_one()
                self.assertEqual(title, "Legacy position")
            finally:
                check_engine.dispose()
        finally:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            admin_engine.dispose()


if __name__ == "__main__":
    unittest.main()
