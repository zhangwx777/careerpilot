import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.agent_schemas import AgentSource
from app.agent_research import ResearchResult
from app.intel_graph import IntelGraphError, _merge, build_intel_graph, resume_intel_graph, start_intel_graph
from app.intel_schemas import Fact, IntelExtraction, SourceRecord
from app.llm.config_store import save_provider
from app.models import Application, Company, IntelSession, InterviewIntel, Position
from scripts.init_db import initialize_database

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


class IntelGraphSearchCallbackTestCase(unittest.TestCase):
    def test_search_callback_accepts_and_forwards_timeout(self):
        item = SimpleNamespace(progress_payload={}, status="聚合中")
        db = MagicMock()
        db.__enter__.return_value = db
        db.get.return_value = item
        search_mock = Mock(return_value=[])

        def research_with_timeout(**kwargs):
            kwargs["search_fn"]("测试关键词", timeout_seconds=17)
            return ResearchResult()

        with (
            patch("app.intel_graph.search", search_mock),
            patch("app.intel_graph._ORIGINAL_SEARCH", search_mock),
            patch("app.intel_graph.research_public_sources", side_effect=research_with_timeout),
            patch(
                "app.intel_graph.get_search_config",
                return_value={"api_key": "test", "endpoint": "https://api.anysearch.com/mcp", "tool_name": "search"},
            ),
            patch("app.intel_graph._session_llm_config", return_value={}),
        ):
            graph = build_intel_graph(InMemorySaver(), lambda: db)
            graph.invoke(
                {
                    "intel_session_id": 1,
                    "provider": "qwen",
                    "query": "测试公司 后端",
                    "user_paste": None,
                    "round_type": "一面",
                    "image_texts": [],
                    "supplement_web": True,
                    "sources": [],
                    "extractions": {},
                },
                {"configurable": {"thread_id": "intel-search-callback-test"}},
            )

        self.assertGreater(search_mock.call_count, 0)
        self.assertTrue(all(call.kwargs["timeout_seconds"] == 17 for call in search_mock.call_args_list))

    def test_public_research_source_scope_is_not_passed_to_intel_record(self):
        item = SimpleNamespace(
            id=1,
            status="聚合中",
            progress_payload={},
            application_id=1,
            application=SimpleNamespace(position_id=1),
            intel_revision=0,
            llm_snapshot=None,
        )
        db = MagicMock()
        db.__enter__.return_value = db
        db.get.return_value = item
        db.scalar.return_value = item
        source = AgentSource(
            id="research-1",
            title="测试公司面经",
            url="https://example.com/interview",
            text="一面问了算法和项目",
            kind="web",
            scope="public",
        ).model_dump(mode="json")

        def extraction(record, _provider, **_kwargs):
            return IntelExtraction(summary=Fact(value="测试摘要", source_ids=[record.id]))

        with (
            patch("app.intel_graph.get_search_config", return_value={"api_key": "test", "endpoint": "https://api.anysearch.com/mcp", "tool_name": "search"}),
            patch("app.intel_graph.research_public_sources", return_value=ResearchResult(sources=[source])),
            patch("app.intel_graph._session_llm_config", return_value={}),
            patch("app.intel_graph.extract_intel", side_effect=extraction),
            patch("app.intel_graph._decide_after_aggregate", return_value="persist"),
            patch("app.intel_graph.publish_dispatch"),
            patch("app.intel_reminders.sync_intel_reminder"),
        ):
            graph = build_intel_graph(InMemorySaver(), lambda: db)
            result = graph.invoke(
                {
                    "intel_session_id": 1,
                    "provider": "qwen",
                    "query": "测试公司 后端",
                    "user_paste": None,
                    "round_type": "一面",
                    "image_texts": [],
                    "supplement_web": True,
                    "sources": [],
                    "extractions": {},
                },
                {"configurable": {"thread_id": "intel-public-source-scope-test"}},
            )

        self.assertEqual(item.status, "已完成")
        self.assertNotIn("scope", result["sources"][0])
        self.assertEqual(result["sources"][0]["kind"], "web")


@unittest.skipUnless(TEST_DATABASE_URL, "需要配置 TEST_DATABASE_URL，面经图测试不允许跳过")
class IntelGraphTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database(TEST_DATABASE_URL)
        cls.engine = create_engine(TEST_DATABASE_URL)
        cls.sessions = sessionmaker(bind=cls.engine, expire_on_commit=False)
        # 图节点会解析模型配置；LLM 调用已 mock，这里只需库里有一条可用配置。
        with cls.sessions() as db:
            save_provider(db, "qwen", api_key="test-key", model="qwen/qwen-max", base_url=None)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.sessions.begin() as db:
            db.execute(delete(IntelSession)); db.execute(delete(InterviewIntel)); db.execute(delete(Application)); db.execute(delete(Position)); db.execute(delete(Company))
            app = Application(position=Position(company=Company(name="测试公司"), title="后端"), status="已投递")
            db.add(app); db.flush(); self.application_id = app.id

    def _session(self):
        with self.sessions.begin() as db:
            item = IntelSession(application_id=self.application_id, provider="qwen", status="聚合中")
            db.add(item); db.flush(); return item.id, str(item.thread_id)

    def test_newer_source_breaks_equal_difficulty_tie(self):
        payload = _merge(
            [
                IntelExtraction(difficulty=Fact(value="一般", source_ids=["old"])),
                IntelExtraction(difficulty=Fact(value="困难", source_ids=["new"])),
            ],
            [
                SourceRecord(id="old", title="旧", text="", published_at="2025-01-01T00:00:00Z"),
                SourceRecord(id="new", title="新", text="", published_at="2025-02-01T00:00:00Z"),
            ],
        )
        self.assertEqual(payload.difficulty.value, "困难")
        self.assertEqual(payload.conflicts, [])

    @patch("app.intel_graph.rebuild_position_insight")
    @patch("app.intel_graph.chat", return_value='{"approved": true, "feedback": ""}')
    @patch("app.intel_graph.extract_intel")
    @patch("app.intel_graph.search")
    def test_conflict_interrupt_resumes_once(self, mock_search, mock_extract, _mock_chat, _mock_insight):
        mock_search.return_value = [{"title": "甲面经", "url": "https://a.test", "text": "一面问了算法"}, {"title": "乙面经", "url": "https://b.test", "text": "二面问了项目"}]
        def extraction(source, _provider, feedback=None):
            value = "困难" if source.id.endswith("-1") else "一般"
            return IntelExtraction(difficulty=Fact(value=value, source_ids=[source.id]))
        mock_extract.side_effect = extraction
        session_id, thread_id = self._session()
        result = start_intel_graph(session_id, thread_id, "qwen", "测试公司 后端", None, TEST_DATABASE_URL, self.sessions, supplement_web=True)
        self.assertIn("__interrupt__", result)
        with self.sessions() as db: self.assertEqual(db.get(IntelSession, session_id).status, "待裁决")
        resume_intel_graph(thread_id, {"difficulty": "困难"}, TEST_DATABASE_URL, self.sessions)
        with self.sessions() as db:
            item = db.get(IntelSession, session_id)
            self.assertEqual(item.status, "已完成")
            intel = db.scalars(select(InterviewIntel)).one()
            self.assertEqual(intel.payload["difficulty"]["value"], "困难")

    @patch("app.intel_graph.rebuild_position_insight")
    @patch("app.intel_graph.chat", side_effect=['{"approved": false, "feedback": "删除没有来源的结论"}', '{"approved": true, "feedback": ""}'])
    @patch("app.intel_graph.extract_intel", return_value=IntelExtraction(frequent_topics=[Fact(value="算法", source_ids=["anysearch-1-1"])]))
    @patch("app.intel_graph.search", return_value=[{"title": "甲面经", "url": "https://a.test", "text": "一面问了算法"}, {"title": "乙面经", "url": "https://b.test", "text": "二面问了项目"}])
    def test_critic_feedback_reextracts_sources(self, _mock_search, mock_extract, _mock_chat, _mock_insight):
        session_id, thread_id = self._session()
        result = start_intel_graph(session_id, thread_id, "qwen", "测试公司 后端", None, TEST_DATABASE_URL, self.sessions, supplement_web=True)
        self.assertNotIn("__interrupt__", result)
        self.assertEqual(mock_extract.call_count, 4)
        self.assertEqual(mock_extract.call_args_list[2].kwargs["feedback"], "删除没有来源的结论")
        with self.sessions() as db:
            item = db.get(IntelSession, session_id)
            self.assertEqual(item.status, "已完成")
            self.assertEqual(item.progress_payload["stage"], "已完成")
            self.assertEqual(
                [source["title"] for source in item.progress_payload["sources"]],
                ["甲面经", "乙面经"],
            )

    @patch("app.intel_graph._decide_after_aggregate", new=lambda _state: "critic")
    @patch("app.intel_graph.chat", side_effect=["```json\n{}\n```", "```json\n{}\n```"])
    @patch("app.intel_graph.extract_intel", return_value=IntelExtraction())
    @patch("app.intel_graph.search", return_value=[{"title": "甲面经", "url": "https://a.test", "text": "一面问了算法"}])
    def test_invalid_critic_json_fails_explicitly(self, _mock_search, _mock_extract, _mock_chat):
        session_id, thread_id = self._session()
        with patch("app.intel_graph._decide_after_aggregate", return_value="critic"):
            with self.assertRaisesRegex(IntelGraphError, "反思模型返回格式无效"):
                start_intel_graph(session_id, thread_id, "qwen", "测试公司 后端", None, TEST_DATABASE_URL, self.sessions)

    @patch("app.intel_graph.rebuild_position_insight")
    @patch("app.intel_graph.chat", return_value='{"approved": true, "feedback": ""}')
    @patch("app.intel_graph.search", side_effect=[[], [], []])
    def test_supplement_search_uses_different_queries(self, mock_search, _mock_chat, _mock_insight):
        session_id, thread_id = self._session()
        start_intel_graph(session_id, thread_id, "qwen", "测试公司 后端", None, TEST_DATABASE_URL, self.sessions, supplement_web=True)
        self.assertEqual(
            [call.args[0] for call in mock_search.call_args_list],
            ["测试公司 后端 面经", "测试公司 后端 面经 技术面 算法 项目 八股", "测试公司 后端 面经 笔试 高频题"],
        )
