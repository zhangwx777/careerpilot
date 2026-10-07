from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Application, Company, ParseSession, PlannerSession, Position, TaskDispatch
from app.task_execution import assert_dispatch_owner, execute_job, prepare_dispatch, recover_dispatches, submit_task


class TaskExecutionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.factory_patch = patch("app.task_execution.SessionLocal", self.sessions)
        self.factory_patch.start()
        with self.sessions.begin() as db:
            application = Application(position=Position(company=Company(name="任务测试"), title="后端"), status="已投递")
            db.add(application)
            db.flush()
            item = PlannerSession(application_id=application.id, provider="qwen", resume_snapshot="测试", jd_snapshot="后端", intel_snapshot=[], available_windows=[], status="生成中")
            db.add(item)
            db.flush()
            self.session_id = item.id
        self.task = SimpleNamespace(name="careerpilot.planner_session")

    def tearDown(self):
        self.factory_patch.stop()
        self.engine.dispose()

    def prepare(self):
        with self.sessions.begin() as db:
            return prepare_dispatch(db, self.task, self.session_id, "thread").id

    def test_domain_and_dispatch_are_rolled_back_together(self):
        with self.sessions() as db:
            db.add(Company(name="不应保存"))
            prepare_dispatch(db, self.task, self.session_id, "thread")
            db.rollback()
        with self.sessions() as db:
            self.assertIsNone(db.scalar(select(Company).where(Company.name == "不应保存")))
            self.assertEqual(db.scalars(select(TaskDispatch)).all(), [])

    def test_broker_failure_preserves_pending_dispatch_without_secrets(self):
        with patch("app.task_queue.execute_dispatch.apply_async", side_effect=OSError("password=do-not-persist")):
            with self.sessions() as db:
                db.add(Company(name="应保存"))
                job = submit_task(db, self.task, self.session_id, "thread")
                job_id = job.id
        with self.sessions() as db:
            job = db.get(TaskDispatch, job_id)
            self.assertEqual(job.status, "pending")
            self.assertNotIn("do-not-persist", job.error_message)
            self.assertIsNotNone(db.scalar(select(Company).where(Company.name == "应保存")))
            job.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        with patch("app.task_queue.execute_dispatch.apply_async") as send:
            recover_dispatches()
        self.assertEqual(send.call_args.kwargs["args"], [job_id])

    def test_duplicate_delivery_executes_domain_once(self):
        job_id = self.prepare()

        def finish(*args):
            execute_job(job_id)
            with self.sessions() as db:
                assert_dispatch_owner(db)
                db.get(PlannerSession, self.session_id).status = "已完成"
                db.commit()

        with patch("app.planner_api._run_planner_session", side_effect=finish) as work:
            execute_job(job_id)
            execute_job(job_id)
        self.assertEqual(work.call_count, 1)
        with self.sessions() as db:
            self.assertEqual(db.get(TaskDispatch, job_id).attempt, 1)
            self.assertEqual(db.get(TaskDispatch, job_id).status, "completed")

    def test_reclaimed_execution_cannot_write_or_mark_new_owner_failed(self):
        job_id = self.prepare()

        def lose_ownership(*args):
            with self.sessions.begin() as db:
                db.get(TaskDispatch, job_id).lease_token = "new-owner"
            with self.sessions() as db:
                assert_dispatch_owner(db)

        with patch("app.planner_api._run_planner_session", side_effect=lose_ownership):
            execute_job(job_id)
        with self.sessions() as db:
            job = db.get(TaskDispatch, job_id)
            self.assertEqual(job.status, "running")
            self.assertEqual(job.lease_token, "new-owner")
            self.assertIsNone(job.error_message)

    def test_committed_result_is_not_repeated_after_worker_loss(self):
        job_id = self.prepare()
        with self.sessions.begin() as db:
            job = db.get(TaskDispatch, job_id)
            job.status = "running"
            job.attempt = 3
            job.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
            db.get(PlannerSession, self.session_id).status = "已完成"
        with patch("app.task_execution.publish_dispatch") as send:
            recover_dispatches()
        send.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.get(TaskDispatch, job_id).status, "completed")

    def test_exhausted_worker_recovery_exposes_failure(self):
        job_id = self.prepare()
        with self.sessions.begin() as db:
            job = db.get(TaskDispatch, job_id)
            job.status = "running"
            job.attempt = 3
            job.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        recover_dispatches()
        with self.sessions() as db:
            self.assertEqual(db.get(TaskDispatch, job_id).status, "failed")
            self.assertEqual(db.get(PlannerSession, self.session_id).status, "失败")

    def test_pre_upgrade_orphan_is_failed_but_new_durable_job_is_preserved(self):
        with self.sessions.begin() as db:
            db.get(PlannerSession, self.session_id).created_at = datetime.now(timezone.utc) - timedelta(hours=1)
        recover_dispatches()
        with self.sessions() as db:
            item = db.get(PlannerSession, self.session_id)
            self.assertEqual(item.status, "失败")
            item.status = "生成中"
            job = prepare_dispatch(db, self.task, self.session_id, "thread")
            job.next_attempt_at = datetime.now(timezone.utc) + timedelta(hours=1)
            db.commit()
        recover_dispatches()
        with self.sessions() as db:
            self.assertEqual(db.get(PlannerSession, self.session_id).status, "生成中")

    def test_plaintext_provider_configuration_is_not_saved(self):
        with self.sessions() as db:
            with self.assertRaises(ValueError):
                prepare_dispatch(db, SimpleNamespace(name="careerpilot.rebuild_insight"), 1, "qwen", {"api_key": "do-not-store"}, 1)
            self.assertEqual(db.scalars(select(TaskDispatch)).all(), [])

    def test_lease_ownership_propagates_into_real_graph_nodes(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from app.parse_graph import build_parse_graph
        from app.parsing import NoticeExtraction

        requested_at = datetime.now(timezone.utc).isoformat()
        with self.sessions.begin() as db:
            item = ParseSession(raw_text="测试通知", provider="qwen", status="解析中")
            db.add(item)
            db.flush()
            session_id = item.id
            job_id = prepare_dispatch(db, SimpleNamespace(name="careerpilot.parse_session"), session_id, "lease-test", item.raw_text, "qwen", requested_at).id

        def extract(*args, **kwargs):
            with self.sessions.begin() as db:
                db.get(TaskDispatch, job_id).lease_token = "new-owner"
            return NoticeExtraction(company_name="测试")

        def start(*args):
            return build_parse_graph(InMemorySaver(), self.sessions).invoke(
                {"parse_session_id": session_id, "raw_text": "测试通知", "provider": "qwen", "requested_at": requested_at},
                {"configurable": {"thread_id": "lease-test"}},
            )

        with patch("app.phase3_api.SessionLocal", self.sessions), patch("app.phase3_api.start_parse_graph", side_effect=start), patch("app.parse_graph.config_from_snapshot", return_value={}), patch("app.parse_graph.extract_notice", side_effect=extract):
            execute_job(job_id)
        with self.sessions() as db:
            self.assertEqual(db.get(ParseSession, session_id).status, "解析中")
            self.assertIsNone(db.get(ParseSession, session_id).extracted_payload)
            self.assertEqual(db.get(TaskDispatch, job_id).lease_token, "new-owner")
            self.assertIsNone(db.get(TaskDispatch, job_id).error_message)

    def test_terminal_analysis_failure_is_not_blindly_replayed_after_worker_loss(self):
        job_id = self.prepare()
        with self.sessions.begin() as db:
            job = db.get(TaskDispatch, job_id)
            job.status = "running"
            job.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
            item = db.get(PlannerSession, self.session_id)
            item.status = "失败"
            item.error_message = "模型结果无效"
        with patch("app.task_execution.publish_dispatch") as send:
            recover_dispatches()
        send.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.get(TaskDispatch, job_id).status, "failed")
            self.assertEqual(db.get(PlannerSession, self.session_id).error_message, "模型结果无效")
