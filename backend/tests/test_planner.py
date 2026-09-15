import os
import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.models import Application, Company, PlannerSession, Position, PreparationTask, ResumeProfile, TimelineNode
from app.llm.config_store import save_provider, snapshot_for
from app.planner import SHANGHAI, schedule_tasks
from app.planner_graph import resume_planner_graph, start_planner_graph
from app.planner_schemas import AvailabilityWindow, Gap, PlannerConfirmation, PlannerDraft, PlannerTaskDraft, ScheduledTask
from scripts.init_db import initialize_database

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

@unittest.skipUnless(TEST_DATABASE_URL, "需要配置 TEST_DATABASE_URL，Planner 测试不允许跳过")
class PlannerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database(TEST_DATABASE_URL)
        cls.engine = create_engine(TEST_DATABASE_URL)
        cls.sessions = sessionmaker(bind=cls.engine, expire_on_commit=False)
        # 图节点解析模型配置；extract_plan 已 mock，只需库里有一条可用配置。
        with cls.sessions() as db:
            save_provider(db, "qwen", api_key="test-key", model="qwen/qwen-max", base_url=None)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.sessions.begin() as db:
            db.execute(delete(PreparationTask))
            db.execute(delete(PlannerSession))
            db.execute(delete(TimelineNode))
            db.execute(delete(Application))
            db.execute(delete(Position))
            db.execute(delete(Company))
            db.execute(delete(ResumeProfile))
            application = Application(position=Position(company=Company(name="测试公司"), title="后端", jd_text="熟悉 Python 和数据库"), status="已投递")
            db.add(application)
            db.add(ResumeProfile(id=1, resume_text="有 Python 项目经验"))
            db.flush()
            self.application_id = application.id

    def test_scheduler_avoids_busy_window(self):
        busy = TimelineNode(
            scheduled_at=datetime(2026, 9, 7, 9, 0, tzinfo=SHANGHAI),
            ends_at=datetime(2026, 9, 7, 10, 0, tzinfo=SHANGHAI),
            status="待处理",
            node_type="其他",
        )
        tasks = [PlannerTaskDraft(title="补数据库", gap="数据库", estimated_minutes=60)]
        result = schedule_tasks(
            tasks,
            [AvailabilityWindow(weekday=0, start="09:00", end="12:00")],
            [busy],
            datetime(2026, 9, 7, 8, 0, tzinfo=SHANGHAI),
        )
        self.assertEqual(result[0].scheduled_at.hour, 10)

    def _planner_session(self):
        with self.sessions.begin() as db:
            item = PlannerSession(
                application_id=self.application_id,
                provider="qwen",
                llm_snapshot=snapshot_for(db, "qwen"),
                resume_snapshot="有 Python 项目经验",
                jd_snapshot="熟悉 Python 和数据库",
                intel_snapshot=[],
                available_windows=[{"weekday": 0, "start": "00:00:00", "end": "23:59:00"}],
                status="生成中",
            )
            db.add(item)
            db.flush()
            return item.id, str(item.thread_id)

    @patch("app.planner_graph.extract_plan")
    def test_graph_interrupt_resumes_once_and_persists_tasks(self, mock_extract):
        mock_extract.return_value = PlannerDraft(
            gaps=[Gap(name="数据库", evidence="JD 要求数据库")],
            tasks=[PlannerTaskDraft(title="补数据库", detail="复习索引", gap="数据库", estimated_minutes=60)],
        )
        session_id, thread_id = self._planner_session()
        result = start_planner_graph(session_id, thread_id, TEST_DATABASE_URL, self.sessions)
        self.assertIn("__interrupt__", result)
        with self.sessions() as db:
            item = db.get(PlannerSession, session_id)
            self.assertEqual(item.status, "待确认")
            task = ScheduledTask.model_validate(item.draft_payload["tasks"][0])
        confirmation = PlannerConfirmation(tasks=[task])
        resume_planner_graph(thread_id, confirmation, TEST_DATABASE_URL, self.sessions)
        resume_planner_graph(thread_id, confirmation, TEST_DATABASE_URL, self.sessions)
        with self.sessions() as db:
            item = db.get(PlannerSession, session_id)
            self.assertEqual(item.status, "已确认")
            tasks = db.scalars(select(PreparationTask)).all()
            self.assertEqual(len(tasks), 1)
            self.assertIsNotNone(tasks[0].timeline_node_id)
            self.assertEqual(db.get(TimelineNode, tasks[0].timeline_node_id).title, "补数据库")
