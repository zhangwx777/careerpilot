import unittest
from unittest.mock import patch

from app.agent_research import research_public_sources
from app.agent_schemas import AgentToolResult


class AgentResearchTestCase(unittest.TestCase):
    def test_prior_query_is_not_repeated_and_feedback_reaches_model(self):
        turn = {"content": None, "tool_calls": [{"id": "c", "name": "search_public_intel", "arguments": {"query": "  ACME  后端 "}}]}
        with patch("app.agent_research.chat_with_tools", return_value=turn) as model, patch("app.agent_research.search") as search:
            result = research_public_sources(session_id=1, query="ACME", provider="qwen", config={}, prior_queries=["acme 后端"], critic_feedback="缺少二面资料")
        search.assert_not_called()
        self.assertEqual(result.queries, [])
        self.assertIn("缺少二面资料", model.call_args.args[0][1]["content"])

    def test_known_url_is_skipped_before_candidate_extraction(self):
        turn = {"content": None, "tool_calls": [{"id": "c", "name": "search_public_intel", "arguments": {"query": "新词"}}]}
        with patch("app.agent_research.chat_with_tools", return_value=turn):
            result = research_public_sources(session_id=1, query="ACME", provider="qwen", config={}, max_rounds=1, existing_urls=["https://example.com/a"], search_fn=lambda *a, **k: [{"url": "https://example.com/a/#section", "title": "旧来源"}, {"url": "https://example.com/b", "title": "新来源"}])
        self.assertEqual([item["url"] for item in result.sources], ["https://example.com/b"])
    @patch(
        "app.agent_research.chat_with_tools",
        return_value={
            "content": None,
            "tool_calls": [
                {"id": "call-1", "name": "search_public_intel", "arguments": {"query": "示例公司 后端 一面 面经"}}
            ],
        },
    )
    def test_agent_can_only_emit_validated_public_candidates(self, _chat):
        def search_fn(query, timeout_seconds):
            self.assertEqual(timeout_seconds, 30)
            return [{"title": "示例公司后端一面面经", "url": "https://example.com/a", "text": "一面问了项目"}]

        result = research_public_sources(
            session_id=7,
            query="示例公司 后端",
            provider="qwen",
            config={"api_key": "key", "model": "model"},
            max_rounds=1,
            search_fn=search_fn,
        )
        self.assertEqual(result.queries, ["示例公司 后端 一面 面经"])
        self.assertEqual(result.sources[0]["scope"], "public")
        self.assertEqual(result.sources[0]["id"], "session-7:research-1")

    @patch("app.agent_research.chat_with_tools", return_value={"content": "没有合适来源", "tool_calls": []})
    def test_no_tool_call_is_empty_and_does_not_create_sources(self, _chat):
        result = research_public_sources(
            session_id=8,
            query="未知公司岗位",
            provider="qwen",
            config={"api_key": "key", "model": "model"},
            max_rounds=1,
            search_fn=lambda _query, timeout_seconds: [],
        )
        self.assertEqual(result.sources, [])
        self.assertIsNone(result.error)


if __name__ == "__main__":
    unittest.main()
