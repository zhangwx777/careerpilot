import os
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.intel_graph import IntelGraphError, _merge, resume_intel_graph, start_intel_graph
from app.intel_schemas import Fact, IntelExtraction, SourceRecord
from app.models import Application, Company, IntelSession, InterviewIntel, Position
from scripts.init_db import initialize_database

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise RuntimeError("必须配置 TEST_DATABASE_URL，面经图测试不允许跳过")


class IntelGraphTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database(TEST_DATABASE_URL)
        cls.engine = create_engine(TEST_DATABASE_URL)
        cls.sessions = sessionmaker(bind=cls.engine, expire_on_commit=False)

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

    @patch("app.intel_graph.chat", return_value='{"approved": true, "feedback": ""}')
    @patch("app.intel_graph.extract_intel")
    @patch("app.intel_graph.search")
    def test_conflict_interrupt_resumes_once(self, mock_search, mock_extract, _mock_chat):
        mock_search.return_value = [{"title": "甲", "url": "https://a.test", "text": "甲"}, {"title": "乙", "url": "https://b.test", "text": "乙"}]
        def extraction(source, _provider, feedback=None):
            value = "困难" if source.id.endswith("-1") else "一般"
            return IntelExtraction(difficulty=Fact(value=value, source_ids=[source.id]))
        mock_extract.side_effect = extraction
        session_id, thread_id = self._session()
        result = start_intel_graph(session_id, thread_id, "qwen", "测试公司 后端", None, TEST_DATABASE_URL, self.sessions)
        self.assertIn("__interrupt__", result)
        with self.sessions() as db: self.assertEqual(db.get(IntelSession, session_id).status, "待裁决")
        resume_intel_graph(thread_id, {"difficulty": "困难"}, TEST_DATABASE_URL, self.sessions)
        with self.sessions() as db:
            item = db.get(IntelSession, session_id)
            self.assertEqual(item.status, "已完成")
            intel = db.scalars(select(InterviewIntel)).one()
            self.assertEqual(intel.payload["difficulty"]["value"], "困难")

    @patch("app.intel_graph.chat", side_effect=['{"approved": false, "feedback": "删除没有来源的结论"}', '{"approved": true, "feedback": ""}'])
    @patch("app.intel_graph.extract_intel", return_value=IntelExtraction(frequent_topics=[Fact(value="算法", source_ids=["anysearch-1-1"])]))
    @patch("app.intel_graph.search", return_value=[{"title": "甲", "url": "https://a.test", "text": "甲"}, {"title": "乙", "url": "https://b.test", "text": "乙"}])
    def test_critic_feedback_reextracts_sources(self, _mock_search, mock_extract, _mock_chat):
        session_id, thread_id = self._session()
        result = start_intel_graph(session_id, thread_id, "qwen", "测试公司 后端", None, TEST_DATABASE_URL, self.sessions)
        self.assertNotIn("__interrupt__", result)
        self.assertEqual(mock_extract.call_count, 4)
        self.assertEqual(mock_extract.call_args_list[2].kwargs["feedback"], "删除没有来源的结论")
        with self.sessions() as db:
            self.assertEqual(db.get(IntelSession, session_id).status, "已完成")

    @patch("app.intel_graph.chat", return_value="```json\n{}\n```")
    @patch("app.intel_graph.extract_intel", return_value=IntelExtraction())
    @patch("app.intel_graph.search", return_value=[{"title": "甲", "url": "https://a.test", "text": "甲"}])
    def test_invalid_critic_json_fails_explicitly(self, _mock_search, _mock_extract, _mock_chat):
        session_id, thread_id = self._session()
        with self.assertRaisesRegex(IntelGraphError, "反思模型返回的不是合法 JSON"):
            start_intel_graph(session_id, thread_id, "qwen", "测试公司 后端", None, TEST_DATABASE_URL, self.sessions)

    @patch("app.intel_graph.chat", return_value='{"approved": true, "feedback": ""}')
    @patch("app.intel_graph.search", side_effect=[[], [], []])
    def test_supplement_search_uses_different_queries(self, mock_search, _mock_chat):
        session_id, thread_id = self._session()
        start_intel_graph(session_id, thread_id, "qwen", "测试公司 后端", None, TEST_DATABASE_URL, self.sessions)
        self.assertEqual(
            [call.args[0] for call in mock_search.call_args_list],
            ["测试公司 后端 面经", "测试公司 后端 面经 技术面 算法 项目 八股", "测试公司 后端 面经 笔试 高频题"],
        )
