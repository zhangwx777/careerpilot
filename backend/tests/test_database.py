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
                    (4, "application_stage_history"),
                    (5, "practice_history"),
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
            self.assertIn("application_stage_change", tables)
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

    def test_stage_history_upgrade_preserves_rows_and_does_not_infer_audit(self):
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url
        from scripts.init_db import initialize_database

        base_url = make_url(os.environ["TEST_DATABASE_URL"])
        schema = f"stage_upgrade_{uuid4().hex[:12]}"
        admin = create_engine(base_url)
        isolated_url = base_url.update_query_dict({"options": f"-csearch_path={schema}"})
        engine = create_engine(isolated_url)
        try:
            with admin.begin() as db:
                db.execute(text(f'CREATE SCHEMA "{schema}"'))
            url = isolated_url.render_as_string(hide_password=False)
            initialize_database(url)
            with engine.begin() as db:
                db.execute(text("DROP TABLE application_stage_change"))
                db.execute(text("ALTER TABLE timeline_node DROP COLUMN revision"))
                db.execute(text("DELETE FROM careerpilot_schema_migrations WHERE version >= 4"))
                db.execute(text("INSERT INTO company (id,name,created_at) VALUES (810,'升级测试公司',now())"))
                db.execute(text("INSERT INTO position (id,company_id,title,created_at,intel_revision) VALUES (811,810,'测试岗位',now(),0)"))
                db.execute(text("INSERT INTO application (id,position_id,status,created_at) VALUES (812,811,'已投递',now())"))
                db.execute(text("INSERT INTO timeline_node (id,application_id,node_type,status,time_mode,scheduled_at,created_at) VALUES (813,812,'笔试','已完成','固定时间',now(),now())"))
            initialize_database(url)
            initialize_database(url)
            with engine.connect() as db:
                self.assertEqual(db.execute(text("SELECT status FROM application WHERE id=812")).scalar_one(), "已投递")
                self.assertEqual(db.execute(text("SELECT count(*) FROM application_stage_change")).scalar_one(), 0)
                self.assertEqual(db.execute(text("SELECT count(*) FROM careerpilot_schema_migrations WHERE version=4")).scalar_one(), 1)
                self.assertIn("revision", {column["name"] for column in inspect(engine).get_columns("timeline_node")})
                self.assertEqual(db.execute(text("SELECT revision FROM timeline_node WHERE id=813")).scalar_one(), 0)
        finally:
            engine.dispose()
            with admin.begin() as db:
                db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            admin.dispose()

    def test_practice_history_upgrade_preserves_unknown_scope_and_actual_review_time(self):
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url
        from sqlalchemy.orm import Session
        from scripts.init_db import initialize_database
        from app.models import PlannerSession, PreparationTask

        base_url = make_url(os.environ["TEST_DATABASE_URL"])
        schema = f"practice_upgrade_{uuid4().hex[:12]}"
        admin = create_engine(base_url)
        isolated_url = base_url.update_query_dict({"options": f"-csearch_path={schema}"})
        engine = create_engine(isolated_url)
        try:
            with admin.begin() as db:
                db.execute(text(f'CREATE SCHEMA "{schema}"'))
            url = isolated_url.render_as_string(hide_password=False)
            initialize_database(url)
            with engine.begin() as db:
                db.execute(text("ALTER TABLE planner_session DROP COLUMN position_id_snapshot, DROP COLUMN practice_snapshot"))
                db.execute(text("ALTER TABLE preparation_task DROP COLUMN feedback_completed_at, DROP COLUMN feedback_answer_snapshot, DROP COLUMN feedback_question_snapshot"))
                db.execute(text("DELETE FROM careerpilot_schema_migrations WHERE version=5"))
                db.execute(text("INSERT INTO company (id,name,created_at) VALUES (910,'迁移测试公司',now())"))
                db.execute(text("INSERT INTO position (id,company_id,title,created_at,intel_revision) VALUES (911,910,'测试岗位',now(),0)"))
                db.execute(text("INSERT INTO application (id,position_id,status,created_at) VALUES (912,911,'已投递',now())"))
                db.execute(text("INSERT INTO planner_session (id,thread_id,application_id,provider,resume_snapshot,jd_snapshot,intel_snapshot,available_windows,status,created_at) VALUES (913,'00000000-0000-0000-0000-000000000913',912,'openai','resume','jd','[]','[]','已完成',now())"))
                db.execute(text("INSERT INTO preparation_task (id,planner_session_id,application_id,title,category,source_ids,evidence,priority,practice_status,status,created_at,user_answer,feedback_payload) VALUES (914,913,912,'历史练习','八股','[]','[]',2,'idle','已完成',now(),'原始回答','{\"rewrite\":\"原始点评\"}')"))
            initialize_database(url)
            initialize_database(url)
            with Session(engine) as db:
                session = db.get(PlannerSession, 913)
                task = db.get(PreparationTask, 914)
                self.assertIsNone(session.position_id_snapshot)
                self.assertEqual(session.practice_snapshot, [])
                self.assertIsNone(task.feedback_completed_at)
                self.assertIsNone(task.feedback_answer_snapshot)
                self.assertIsNone(task.feedback_question_snapshot)
                self.assertEqual(task.user_answer, "原始回答")
                self.assertEqual(task.feedback_payload, {"rewrite": "原始点评"})
                self.assertEqual(db.execute(text("SELECT count(*) FROM careerpilot_schema_migrations WHERE version=5")).scalar_one(), 1)
        finally:
            engine.dispose()
            with admin.begin() as db:
                db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            admin.dispose()

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
