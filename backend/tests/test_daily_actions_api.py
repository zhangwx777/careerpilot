import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    Application,
    Company,
    PlannerSession,
    Position,
    PreparationTask,
)
from app.planner_api import materialize_planner_actions


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)


class DailyActionsApiTestCase(unittest.TestCase):
    def setUp(self):
        self.session = Session(engine)
        application = Application(
            position=Position(
                company=Company(name="行动公司"),
                title="后端工程师",
                jd_text="熟悉 Python",
            ),
            status="已投递",
        )
        self.session.add(application)
        self.session.flush()
        self.application_id = application.id

        def override_db():
            yield self.session

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.rollback()
        for model in (PreparationTask, PlannerSession, Application, Position, Company):
            self.session.execute(delete(model))
        self.session.commit()
        self.session.close()

    def _planner_session(self):
        session = PlannerSession(
            application_id=self.application_id,
            provider="openai",
            resume_snapshot="Python 项目经验",
            jd_snapshot="熟悉 Python",
            intel_snapshot=[],
            available_windows=[],
            draft_payload={
                "summary": "准备重点",
                "strengths": [],
                "gaps": [],
                "actions": [
                    {
                        "title": "准备项目深挖",
                        "detail": "整理项目中的故障排查案例",
                        "priority": 1,
                        "source_ids": ["manual-1"],
                    },
                    {
                        "title": "复习数据库",
                        "detail": "复习索引和事务",
                        "priority": 3,
                        "source_ids": [],
                    },
                ],
            },
            status="已完成",
        )
        self.session.add(session)
        self.session.flush()
        return session

    def test_completed_plan_materializes_actions_idempotently(self):
        planner_session = self._planner_session()

        self.assertEqual(materialize_planner_actions(self.session, planner_session), 2)
        self.session.flush()
        self.assertEqual(materialize_planner_actions(self.session, planner_session), 0)
        self.session.commit()

        tasks = self.session.query(PreparationTask).order_by(PreparationTask.action_index).all()
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0].priority, 1)
        self.assertEqual(tasks[0].estimated_minutes, 30)
        self.assertIsNone(tasks[0].scheduled_at)

    def test_materialize_actions_endpoint_is_a_safe_recovery_operation(self):
        planner_session = self._planner_session()
        self.session.commit()

        first = self.client.post(f"/api/planner-sessions/{planner_session.id}/materialize-actions")
        second = self.client.post(f"/api/planner-sessions/{planner_session.id}/materialize-actions")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(self.session.query(PreparationTask).count(), 2)

    def test_dashboard_returns_pending_actions_and_status_update_removes_completed(self):
        planner_session = self._planner_session()
        materialize_planner_actions(self.session, planner_session)
        self.session.commit()

        response = self.client.get("/api/dashboard")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["today_actions"]
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["items"][0]["title"], "准备项目深挖")
        task_id = payload["items"][0]["task_id"]

        updated = self.client.patch(
            f"/api/preparation-tasks/{task_id}/status",
            json={"status": "已完成"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["status"], "已完成")
        self.assertEqual(self.client.get("/api/dashboard").json()["today_actions"]["total"], 1)

    def test_deferred_action_is_hidden_until_due_unless_explicitly_included(self):
        planner_session = self._planner_session()
        materialize_planner_actions(self.session, planner_session)
        self.session.commit()
        task_id = self.session.query(PreparationTask).first().id
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

        response = self.client.patch(
            f"/api/preparation-tasks/{task_id}/status",
            json={"status": "待处理", "deferred_until": future},
        )
        self.assertEqual(response.status_code, 200, response.text)
        visible = self.client.get("/api/preparation-tasks?status=待处理").json()
        self.assertEqual(visible["total"], 1)
        all_tasks = self.client.get("/api/preparation-tasks?status=待处理&include_deferred=true").json()
        self.assertEqual(all_tasks["total"], 2)


if __name__ == "__main__":
    unittest.main()
