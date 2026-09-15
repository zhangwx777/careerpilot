import unittest
import json
from unittest.mock import patch

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.agent_schemas import AgentToolResult
from app.agent_tools import AgentToolContext, build_chat_toolset
from app.db import Base
from app.models import AgentRun, Application, Company, IntelChatMessage, InterviewIntel, Position


class AgentToolsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        cls.sessions = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.sessions.begin() as db:
            for model in (AgentRun, IntelChatMessage, InterviewIntel, Application, Position, Company):
                db.execute(delete(model))
            current_company = Company(name="当前公司")
            current_position = Position(company=current_company, title="当前岗位", jd_text="需要 Python")
            current_application = Application(position=current_position, status="已投递")
            other_position = Position(company=current_company, title="相关岗位")
            other_application = Application(position=other_position, status="已投递")
            other_company = Company(name="其他公司")
            foreign_position = Position(company=other_company, title="外部岗位")
            foreign_application = Application(position=foreign_position, status="已投递")
            db.add_all([current_application, other_application, foreign_application])
            db.flush()
            db.add_all(
                [
                    InterviewIntel(
                        application_id=current_application.id,
                        payload={},
                        sources=[{"id": "manual", "title": "当前面经", "text": "一面问 Python"}],
                    ),
                    InterviewIntel(
                        application_id=other_application.id,
                        payload={},
                        sources=[{"id": "related", "title": "相关面经", "text": "二面问系统设计"}],
                    ),
                    InterviewIntel(
                        application_id=foreign_application.id,
                        payload={},
                        sources=[{"id": "foreign", "title": "外部面经", "text": "二面问系统设计"}],
                    ),
                ]
            )
            self.application_id = current_application.id
            self.position_id = current_position.id
            self.company_id = current_company.id

    def context(self, run_id: int = 7):
        return AgentToolContext(
            application_id=self.application_id,
            position_id=self.position_id,
            company_id=self.company_id,
            run_id=run_id,
            session_factory=self.sessions,
        )

    def test_toolset_exposes_only_read_tools(self):
        specs, registry = build_chat_toolset(self.context())
        self.assertEqual(
            {item["function"]["name"] for item in specs},
            set(registry),
        )
        self.assertNotIn("save_interview_intel", registry)
        self.assertNotIn("update_application_status", registry)

    def test_current_intel_is_limited_to_current_position(self):
        _, registry = build_chat_toolset(self.context())
        result = registry["search_current_intel"].handler({})
        self.assertEqual([source.id for source in result.sources], ["material-1:manual"])

    def test_related_intel_is_limited_to_same_company(self):
        _, registry = build_chat_toolset(self.context())
        result = registry["search_related_intel"].handler({})
        self.assertEqual([source.title for source in result.sources], ["相关岗位 · 相关面经"])
        self.assertEqual(result.sources[0].scope, "related_position")

    def test_chat_history_is_bounded(self):
        with self.sessions.begin() as db:
            for index in range(6):
                user = IntelChatMessage(
                    position_id=self.position_id,
                    role="user",
                    content=f"问题 {index} " + "q" * 3000,
                    status="已完成",
                    source_ids=[],
                )
                assistant = IntelChatMessage(
                    position_id=self.position_id,
                    role="assistant",
                    content="回答 " + "a" * 6000,
                    status="已完成",
                    source_ids=[],
                )
                db.add_all([user, assistant])
                db.flush()
                db.add(
                    AgentRun(
                        kind="chat",
                        assistant_message_id=assistant.id,
                        position_id=self.position_id,
                        application_id=self.application_id,
                        provider="anthropic",
                        status="completed",
                        sources=[],
                    )
                )
        _, registry = build_chat_toolset(self.context())
        result = registry["read_chat_history"].handler({})
        self.assertLessEqual(len(json.dumps(result.data["turns"], ensure_ascii=False)), 12_000)

    @patch("app.agent_tools.search", return_value=[{"title": "公开面经", "url": "https://example.test/a", "text": "一面"}])
    def test_public_sources_are_namespaced_to_agent_run(self, _search):
        _, registry = build_chat_toolset(self.context(run_id=9))
        result = registry["search_public_intel"].handler({"query": "当前岗位 面经"})
        self.assertEqual(result.sources[0].id, "agent-run-9:web-1")
        self.assertEqual(result.sources[0].scope, "public")
        second = registry["search_public_intel"].handler({"query": "当前岗位 技术栈"})
        self.assertEqual(second.sources[0].id, "agent-run-9:web-2")


if __name__ == "__main__":
    unittest.main()
