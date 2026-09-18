import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Application, Company, PlannerSession, Position


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
        for model in (PlannerSession, Application, Position, Company):
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


if __name__ == "__main__":
    unittest.main()
