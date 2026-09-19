import unittest
from unittest.mock import patch

from app.agent_research import research_public_sources
from app.agent_schemas import AgentToolResult


class AgentResearchTestCase(unittest.TestCase):
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
