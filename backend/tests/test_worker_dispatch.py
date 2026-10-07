import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, get_ident
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Application, Company, IntelSession, InterviewIntel, PlannerSession, Position, PreparationTask, TaskDispatch
from fastapi import BackgroundTasks, HTTPException
from app.task_execution import prepare_dispatch, publish_dispatch, recover_dispatches
from app.task_queue import celery_app, execute_dispatch


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "真实 worker 验证需要独立 TEST_DATABASE_URL")
class WorkerDispatchTests(unittest.TestCase):
    def setUp(self):
        self.schema = f"test_worker_{uuid4().hex}"
        self.queue = f"verify-{uuid4().hex}"
        self.root_engine = create_engine(os.environ["TEST_DATABASE_URL"])
        with self.root_engine.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.database_url = make_url(os.environ["TEST_DATABASE_URL"]).update_query_dict({"options": f"-csearch_path={self.schema} -ctimezone=Asia/Shanghai"})
        self.engine = create_engine(self.database_url)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.factory_patch = patch("app.task_execution.SessionLocal", self.sessions)
        self.queue_patch = patch("app.task_execution.settings.celery_queue", self.queue)
        self.factory_patch.start()
        self.queue_patch.start()
        self.log = tempfile.TemporaryFile()
        self.workers = []
        with self.sessions.begin() as db:
            application = Application(position=Position(company=Company(name="worker 测试"), title="后端"), status="已投递")
            db.add(application)
            db.flush()
            session = PlannerSession(application_id=application.id, provider="qwen", llm_snapshot="offline-fixture", resume_snapshot="测试", jd_snapshot="后端", intel_snapshot=[], available_windows=[], status="生成中")
            db.add(session)
            db.flush()
            self.session_id = session.id
            self.job_id = prepare_dispatch(db, SimpleNamespace(name="careerpilot.planner_session"), session.id, str(session.thread_id)).id

    def start_worker(self, seconds="0.5"):
        env = dict(os.environ)
        env["DATABASE_URL"] = self.database_url.render_as_string(hide_password=False)
        env["PYTHONPATH"] = str(Path(__file__).parent) + os.pathsep + str(Path(__file__).parents[1])
        env["CAREERPILOT_TEST_WORK_SECONDS"] = seconds
        process = subprocess.Popen(
            [sys.executable, "-m", "celery", "-A", "app.task_queue.celery_app", "worker", "--pool=solo", "--loglevel=WARNING", f"--queues={self.queue}", "--include=worker_fixture", f"--hostname={self.queue}@%h"],
            env=env, stdout=self.log, stderr=subprocess.STDOUT,
        )
        self.workers.append(process)
        return process

    def wait_for(self, status):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            with self.sessions() as db:
                job = db.get(TaskDispatch, self.job_id)
                if job.status == status:
                    return job.attempt
                if job.status == "failed":
                    self.fail(job.error_message)
            time.sleep(0.1)
        self.log.seek(0)
        self.fail(f"worker 未进入 {status}: " + self.log.read().decode(errors="replace")[-3000:])

    def tearDown(self):
        for process in self.workers:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
        self.queue_patch.stop()
        self.factory_patch.stop()
        with celery_app.connection_for_write() as connection:
            queue = connection.SimpleQueue(self.queue)
            queue.clear()
            queue.close()
        self.log.close()
        self.engine.dispose()
        with self.root_engine.begin() as db:
            db.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.root_engine.dispose()

    def test_real_worker_deduplicates_two_deliveries(self):
        self.start_worker()
        publish_dispatch(self.job_id)
        execute_dispatch.apply_async(args=[self.job_id], queue=self.queue)
        self.assertEqual(self.wait_for("completed"), 1)
        with self.sessions() as db:
            self.assertEqual(db.get(PlannerSession, self.session_id).draft_payload["summary"], "真实 worker 完成离线测试")

    def test_worker_kill_then_restart_recovers_same_dispatch(self):
        worker = self.start_worker(seconds="5")
        publish_dispatch(self.job_id)
        self.assertEqual(self.wait_for("running"), 1)
        worker.kill()
        worker.wait(timeout=10)
        with self.sessions.begin() as db:
            db.get(TaskDispatch, self.job_id).heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        recover_dispatches()
        self.start_worker()
        self.assertEqual(self.wait_for("completed"), 2)
        with self.sessions() as db:
            self.assertEqual(db.get(PlannerSession, self.session_id).status, "已完成")

    def assert_concurrent_retry_is_single_dispatch(self, retry, identifier, task_name):
        barrier = Barrier(2)

        def call_retry():
            with self.sessions() as db:
                barrier.wait(timeout=5)
                try:
                    retry(identifier, db)
                    return 200
                except HTTPException as error:
                    return error.status_code

        with patch("app.task_execution.publish_dispatch"), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: call_retry(), range(2)))
        self.assertEqual(sorted(results), [200, 409])
        with self.sessions() as db:
            count = db.scalar(select(func.count()).select_from(TaskDispatch).where(TaskDispatch.task_name == task_name, TaskDispatch.args[0].as_integer() == identifier))
            self.assertEqual(count, 1)

    def test_two_planner_retries_create_one_dispatch(self):
        from app.planner_api import retry_planner_session
        with self.sessions.begin() as db:
            db.delete(db.get(TaskDispatch, self.job_id))
            db.get(PlannerSession, self.session_id).status = "失败"
        self.assert_concurrent_retry_is_single_dispatch(retry_planner_session, self.session_id, "careerpilot.planner_session")

    def test_two_intel_retries_create_one_dispatch(self):
        from app.intel_api import retry_intel
        with self.sessions.begin() as db:
            item = IntelSession(application_id=db.get(PlannerSession, self.session_id).application_id, provider="qwen", llm_snapshot="offline-fixture", user_paste="测试材料", status="失败")
            db.add(item)
            db.flush()
            identifier = item.id
        self.assert_concurrent_retry_is_single_dispatch(retry_intel, identifier, "careerpilot.intel_session")

    def test_concurrent_materialization_is_idempotent(self):
        from app.planner_api import materialize_planner_actions
        with self.sessions.begin() as db:
            item = db.get(PlannerSession, self.session_id)
            item.status = "已完成"
            item.draft_payload = {"actions": [{"title": "事务复习", "priority": 1}]}
        barrier = Barrier(2)

        def materialize():
            with self.sessions.begin() as db:
                item = db.get(PlannerSession, self.session_id)
                barrier.wait(timeout=5)
                return materialize_planner_actions(db, item, [0])

        with ThreadPoolExecutor(max_workers=2) as pool:
            counts = list(pool.map(lambda _: materialize(), range(2)))
        self.assertEqual(sorted(counts), [0, 1])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(PreparationTask)), 1)

    def test_practice_worker_loss_recovers_without_losing_saved_answer(self):
        with self.sessions.begin() as db:
            session = db.get(PlannerSession, self.session_id)
            task = PreparationTask(planner_session_id=session.id, application_id=session.application_id, title="练习", user_answer="保留草稿", practice_status="answer")
            db.add(task)
            db.flush()
            task_id = task.id
            self.job_id = prepare_dispatch(db, SimpleNamespace(name="careerpilot.practice"), task_id, "answer").id
        worker = self.start_worker("5")
        publish_dispatch(self.job_id)
        self.wait_for("running")
        worker.kill()
        worker.wait(timeout=10)
        with self.sessions.begin() as db:
            db.get(TaskDispatch, self.job_id).heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        recover_dispatches()
        self.start_worker()
        self.assertEqual(self.wait_for("completed"), 2)
        with self.sessions() as db:
            task = db.get(PreparationTask, task_id)
            self.assertEqual(task.user_answer, "保留草稿")
            self.assertEqual(task.practice_status, "idle")
            self.assertEqual(task.answer_payload["question"], "测试题")

    def test_material_delete_waits_for_new_material_before_deciding_empty(self):
        from app.intel_api import delete_intel_material
        with self.sessions.begin() as db:
            application_id = db.get(PlannerSession, self.session_id).application_id
            position_id = db.get(Application, application_id).position_id
            old = InterviewIntel(application_id=application_id, provider="qwen", payload={}, sources=[])
            db.add(old)
            db.flush()
            material_id = old.id
        waiting = Event()
        delete_thread = []

        def before_query(connection, cursor, statement, parameters, context, many):
            if delete_thread and get_ident() == delete_thread[0] and "FROM position" in statement and "FOR UPDATE" in statement:
                waiting.set()

        def delete_old():
            delete_thread.append(get_ident())
            with self.sessions() as db:
                return delete_intel_material(material_id, BackgroundTasks(), db)

        event.listen(self.engine, "before_cursor_execute", before_query)
        try:
            with patch("app.intel_api.snapshot_for", return_value="frozen-snapshot"), patch("app.task_execution.publish_dispatch"), ThreadPoolExecutor(max_workers=1) as pool:
                with self.sessions.begin() as db:
                    position = db.scalar(select(Position).where(Position.id == position_id).with_for_update())
                    future = pool.submit(delete_old)
                    self.assertTrue(waiting.wait(timeout=10))
                    db.add(InterviewIntel(application_id=application_id, provider="qwen", payload={}, sources=[]))
                    position.intel_revision += 1
                self.assertEqual(future.result(timeout=10), {"deleted": material_id})
        finally:
            event.remove(self.engine, "before_cursor_execute", before_query)
        with self.sessions() as db:
            self.assertEqual(db.get(Position, position_id).intel_insight["status"], "生成中")
            self.assertEqual(db.scalar(select(func.count()).select_from(InterviewIntel)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(TaskDispatch).where(TaskDispatch.task_name == "careerpilot.rebuild_insight")), 1)
