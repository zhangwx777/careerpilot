import unittest
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Application, Company, InterviewIntel, PlannerSession, Position, ResumeProfile
from app.planner_parsing import _allowed_source_ids, _validate


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)


class PlannerHistoryApiTestCase(unittest.TestCase):
    def setUp(self):
        self.session = Session(engine)

        def override_db():
            yield self.session

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.rollback()
        for model in (PlannerSession, InterviewIntel, Application, Position, Company, ResumeProfile):
            self.session.execute(delete(model))
        self.session.commit()
        self.session.close()

    def test_completed_analysis_is_in_session_history(self):
        application = Application(
            position=Position(
                company=Company(name="历史记录公司"),
                title="后端工程师",
                jd_text="熟悉 Python",
            ),
            status="已投递",
        )
        self.session.add(application)
        self.session.flush()
        completed = PlannerSession(
            application_id=application.id,
            provider="openai",
            resume_snapshot="Python 项目经验",
            jd_snapshot="熟悉 Python",
            intel_snapshot=[],
            available_windows=[],
            draft_payload={"summary": "历史分析", "strengths": [], "gaps": [], "actions": []},
            status="已完成",
        )
        self.session.add(completed)
        self.session.commit()

        response = self.client.get("/api/planner-sessions")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["id"] for item in response.json()], [completed.id])

    def _create_planner_session(self, insight):
        application = Application(
            position=Position(
                company=Company(name="洞察测试公司"),
                title="Agent 工程师",
                jd_text="熟悉 Python 与工作流设计",
                intel_insight=insight,
            ),
            status="已投递",
        )
        self.session.add_all([application, ResumeProfile(id=1, resume_text="Python 项目经验")])
        self.session.flush()
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for index in range(4):
            self.session.add(
                InterviewIntel(
                    application_id=application.id,
                    title=f"面经 {index}",
                    payload={"marker": index},
                    created_at=base_time + timedelta(days=index),
                )
            )
        self.session.commit()

        with patch("app.planner_api.resolve_role_provider", return_value="openai"), \
                patch("app.planner_api.snapshot_for", return_value="provider-snapshot"), \
                patch("app.planner_api.enqueue", return_value=SimpleNamespace(id="queue-task")):
            response = self.client.post("/api/planner-sessions", json={"application_id": application.id})

        self.assertEqual(response.status_code, 201, response.text)
        return self.session.get(PlannerSession, response.json()["id"])

    def test_new_planner_session_includes_generated_position_insight_and_latest_three_materials(self):
        insight = {
            "status": "已生成",
            "high_frequency_directions": [{"title": "Agent 工作流", "source_ids": ["insight-source"]}],
            "core_questions": [{"question": "如何设计工作流？", "source_ids": ["insight-source"]}],
            "preparation_items": [{"title": "复盘项目", "source_ids": ["insight-source"]}],
        }
        session = self._create_planner_session(insight)

        materials = [item for item in session.intel_snapshot if item.get("kind") != "position_insight"]
        position_insight = next(
            item for item in session.intel_snapshot if item.get("kind") == "position_insight"
        )
        self.assertEqual(len(materials), 3)
        self.assertEqual([item["payload"]["marker"] for item in materials], [3, 2, 1])
        self.assertEqual(position_insight["preparation_items"], insight["preparation_items"])
        self.assertIn("insight-source", _allowed_source_ids(session.intel_snapshot))
        validated = _validate(
            json.dumps({"actions": [{"title": "复盘项目", "priority": 1, "source_ids": ["insight-source"]}]}),
            session.intel_snapshot,
        )
        self.assertEqual(validated.actions[0].source_ids, ["insight-source"])

    def test_new_planner_session_omits_unavailable_position_insight(self):
        session = self._create_planner_session({"status": "失败", "preparation_items": []})

        self.assertEqual(len(session.intel_snapshot), 3)
        self.assertFalse(any(item.get("kind") == "position_insight" for item in session.intel_snapshot))


if __name__ == "__main__":
    unittest.main()
