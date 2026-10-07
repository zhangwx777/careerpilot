import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_schemas import AgentRunResult, AgentSource
from app.db import Base
from app.llm.structured import StructuredOutputError
from app.intel_api import (
    _run_intel_chat,
    clear_intel_chat_history,
    delete_intel_chat_turn,
    _chat_message_read,
    router,
)
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
                status="queued",
                stage="准备中",
            )
            db.add(run)
            db.flush()
            self.position_id = position.id
            self.user_message_id = user.id
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

    @patch("app.intel_api.config_from_snapshot", return_value={"api_key": "key", "model": "model"})
    @patch("app.intel_api.run_chat_agent")
    @patch("app.intel_api.parse_structured", side_effect=StructuredOutputError("格式错误"))
    def test_structured_failure_keeps_streamed_plain_text(self, _parse, run_agent, _config):
        def emit_partial_answer(*args, **kwargs):
            kwargs["on_chunk"]('{"answer":"已生成的可读回答片段')
            return AgentRunResult(raw="invalid structured output", sources=[])

        run_agent.side_effect = emit_partial_answer
        with patch("app.intel_api.SessionLocal", self.sessions), patch("app.intel_api.time.monotonic", return_value=10.0):
            _run_intel_chat(self.message_id, self.application_id, "anthropic", "重点准备什么？")

        with self.sessions() as db:
            assistant = db.get(IntelChatMessage, self.message_id)
            run = db.get(AgentRun, self.run_id)
            self.assertEqual(assistant.status, "失败")
            self.assertEqual(assistant.content, "已生成的可读回答片段")
            self.assertEqual(run.error_kind, "structured_output")
            self.assertEqual(_chat_message_read(assistant, run).error_message, "模型返回格式不符合要求，请稍后重试")

    def test_chat_history_has_single_turn_and_clear_delete_routes(self):
        delete_routes = {
            route.path
            for route in router.routes
            if "DELETE" in getattr(route, "methods", set())
        }
        self.assertIn("/api/intel/chat", delete_routes)
        self.assertIn("/api/intel/chat/{assistant_message_id}", delete_routes)

    def test_delete_turn_removes_both_messages_and_its_run(self):
        with self.sessions() as db:
            user = IntelChatMessage(
                position_id=self.position_id, role="user", content="第二个问题", status="已完成", source_ids=[]
            )
            assistant = IntelChatMessage(
                position_id=self.position_id, role="assistant", content="第二个回答", status="已完成", source_ids=[]
            )
            db.add_all([user, assistant])
            db.flush()
            run = AgentRun(
                kind="chat", assistant_message_id=assistant.id, position_id=self.position_id,
                application_id=self.application_id, provider="anthropic", status="completed", stage="完成",
            )
            db.add(run)
            db.flush()
            user_id, assistant_id, run_id = user.id, assistant.id, run.id

            result = delete_intel_chat_turn(assistant_id, self.application_id, user_id, db)

            self.assertEqual(result["deleted"], [user_id, assistant_id])
            self.assertIsNone(db.get(IntelChatMessage, user_id))
            self.assertIsNone(db.get(IntelChatMessage, assistant_id))
            self.assertIsNone(db.get(AgentRun, run_id))
            self.assertIsNotNone(db.get(IntelChatMessage, self.message_id))

    def test_clear_history_is_scoped_to_current_position(self):
        with self.sessions() as db:
            current_assistant = db.get(IntelChatMessage, self.message_id)
            current_assistant.status = "失败"
            db.get(AgentRun, self.run_id).status = "failed"
            other_company = Company(name="另一家公司")
            other_position = Position(company=other_company, title="另一岗位")
            other_application = Application(position=other_position, status="已投递")
            other_user = IntelChatMessage(
                position=other_position, role="user", content="保留的问题", status="已完成", source_ids=[]
            )
            db.add_all([other_application, other_user])
            db.flush()
            other_position_id, other_user_id = other_position.id, other_user.id

            result = clear_intel_chat_history(self.application_id, db)

            self.assertEqual(result["deleted_count"], 2)
            self.assertEqual(
                db.scalars(select(IntelChatMessage).where(IntelChatMessage.position_id == self.position_id)).all(),
                [],
            )
            self.assertEqual(db.get(IntelChatMessage, other_user_id).position_id, other_position_id)
            self.assertIsNone(db.get(AgentRun, self.run_id))

    def test_generating_turn_cannot_be_deleted_or_cleared(self):
        with self.sessions() as db:
            with self.assertRaises(HTTPException) as turn_error:
                delete_intel_chat_turn(self.message_id, self.application_id, self.user_message_id, db)
            self.assertEqual(turn_error.exception.status_code, 409)
            with self.assertRaises(HTTPException) as clear_error:
                clear_intel_chat_history(self.application_id, db)
            self.assertEqual(clear_error.exception.status_code, 409)

    def test_running_chat_cannot_be_claimed_again(self):
        with self.sessions.begin() as db:
            db.get(AgentRun, self.run_id).status = "running"
        with patch("app.intel_api.SessionLocal", self.sessions), patch("app.intel_api.run_chat_agent") as work:
            _run_intel_chat(self.message_id, self.application_id, "anthropic", "问题")
        work.assert_not_called()

    def test_removed_material_is_rejected_before_answer_commit(self):
        def remove_then_answer(*args, **kwargs):
            with self.sessions.begin() as db:
                db.execute(delete(InterviewIntel))
            return AgentRunResult(raw='{"answer":"旧材料结论","source_ids":["material-1:manual"]}', sources=[AgentSource(id="material-1:manual", title="旧资料")])
        with patch("app.intel_api.SessionLocal", self.sessions), patch("app.intel_api.config_from_snapshot", return_value={}), patch("app.intel_api.run_chat_agent", side_effect=remove_then_answer):
            _run_intel_chat(self.message_id, self.application_id, "anthropic", "问题")
        with self.sessions() as db:
            answer = db.get(IntelChatMessage, self.message_id)
            self.assertEqual(answer.status, "失败")
            self.assertEqual(answer.source_ids, [])
            self.assertIn("资料已变更", answer.content)
            self.assertEqual(db.get(AgentRun, self.run_id).error_kind, "source_invalidated")

    def test_model_cannot_override_runtime_tool_and_search_facts(self):
        result = AgentRunResult(raw='{"answer":"已有材料结论","source_ids":["material-1:manual"],"used_tools":["invented"],"search_status":"success"}', sources=[AgentSource(id="material-1:manual", title="用户面经")], used_tools=["search_current_intel"], search_status="failed")
        with patch("app.intel_api.SessionLocal", self.sessions), patch("app.intel_api.config_from_snapshot", return_value={}), patch("app.intel_api.run_chat_agent", return_value=result):
            _run_intel_chat(self.message_id, self.application_id, "anthropic", "问题")
        with self.sessions() as db:
            run = db.get(AgentRun, self.run_id)
            self.assertEqual(run.used_tools, ["search_current_intel"])
            self.assertEqual(run.search_status, "failed")
            self.assertIn("公开检索失败", db.get(IntelChatMessage, self.message_id).content)

    def test_history_marks_invalid_references_without_presenting_them_as_valid(self):
        with self.sessions() as db:
            answer = db.get(IntelChatMessage, self.message_id)
            answer.source_ids = ["material-1:manual"]
            read = _chat_message_read(answer, db.get(AgentRun, self.run_id), set())
            self.assertEqual(read.source_ids, [])
            self.assertEqual(read.invalid_source_ids, ["material-1:manual"])
            self.assertTrue(read.insufficient_data)


if __name__ == "__main__":
    unittest.main()
