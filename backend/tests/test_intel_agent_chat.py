import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_schemas import AgentRunResult, AgentSource
from app.db import Base
from app.intel_api import _run_intel_chat
from app.models import AgentRun, Application, Company, IntelChatMessage, InterviewIntel, Position


class IntelAgentChatIntegrationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.sessions = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.sessions.begin() as db:
            for model in (AgentRun, IntelChatMessage, InterviewIntel, Application, Position, Company):
                db.execute(delete(model))
            company = Company(name="测试公司")
            position = Position(company=company, title="Agent 工程师")
            application = Application(position=position, status="已投递")
            db.add(application)
            db.flush()
            db.add(
                InterviewIntel(
                    application_id=application.id,
                    payload={},
                    sources=[{"id": "manual", "title": "用户面经", "text": "一面问了 Agent"}],
                )
            )
            user = IntelChatMessage(
                position_id=position.id,
                role="user",
                content="重点准备什么？",
                status="已完成",
                source_ids=[],
            )
            assistant = IntelChatMessage(
                position_id=position.id,
                role="assistant",
                content="",
                status="生成中",
                provider="anthropic",
                llm_snapshot="snapshot",
                source_ids=[],
            )
            db.add_all([user, assistant])
            db.flush()
            run = AgentRun(
                kind="chat",
                assistant_message_id=assistant.id,
                position_id=position.id,
                application_id=application.id,
                provider="anthropic",
                status="running",
                stage="准备中",
            )
            db.add(run)
            db.flush()
            self.message_id = assistant.id
            self.application_id = application.id
            self.run_id = run.id

    @patch("app.intel_api.config_from_snapshot", return_value={"api_key": "key", "model": "model"})
    @patch(
        "app.intel_api.run_chat_agent",
        return_value=AgentRunResult(
            raw='{"answer":"准备项目复盘","source_ids":["material-1:manual"]}',
            sources=[
                AgentSource(
                    id="material-1:manual",
                    title="用户面经",
                    text="一面问了 Agent",
                    kind="manual",
                )
            ],
        ),
    )
    def test_background_chat_persists_answer_and_trace(self, _run_agent, _config):
        with patch("app.intel_api.SessionLocal", self.sessions):
            _run_intel_chat(self.message_id, self.application_id, "anthropic", "重点准备什么？")

        with self.sessions() as db:
            assistant = db.get(IntelChatMessage, self.message_id)
            run = db.get(AgentRun, self.run_id)
            self.assertEqual(assistant.status, "已完成")
            self.assertEqual(assistant.content, "准备项目复盘")
            self.assertEqual(assistant.source_ids, ["material-1:manual"])
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.sources[0]["id"], "material-1:manual")


if __name__ == "__main__":
    unittest.main()
