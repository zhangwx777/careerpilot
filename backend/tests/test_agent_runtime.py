import unittest
from unittest.mock import patch

from app.agent_runtime import AgentBudget, run_chat_agent
from app.agent_schemas import AgentToolResult
from app.agent_tools import AgentTool


class AgentRuntimeTestCase(unittest.TestCase):
    def setUp(self):
        self.tool = AgentTool(
            name="lookup",
            description="读取测试资料",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            category="personal",
            handler=lambda _arguments: AgentToolResult(ok=True, data={"value": "ready"}),
        )

    @patch("app.agent_runtime.chat_stream", return_value=iter(['{"answer":"完成","source_ids":[]}']))
    @patch(
        "app.agent_runtime.chat_with_tools",
        side_effect=[
            {"content": None, "tool_calls": [{"id": "call-1", "name": "lookup", "arguments": {}}]},
            {"content": None, "tool_calls": []},
        ],
    )
    def test_runtime_executes_tool_then_streams_final_answer(self, chat_with_tools, chat_stream):
        stages = []
        result = run_chat_agent(
            [{"role": "user", "content": "查资料"}],
            [self.tool.spec()],
            {"lookup": self.tool},
            "anthropic",
            {"api_key": "key", "model": "model"},
            on_stage=stages.append,
        )

        self.assertEqual(result.raw, '{"answer":"完成","source_ids":[]}')
        self.assertEqual(result.steps[0].tool_calls[0]["name"], "lookup")
        self.assertEqual(stages[-1], "正在整理回答")
        chat_stream.assert_called_once()

    @patch("app.agent_runtime.chat_stream", return_value=iter(['{"answer":"完成","source_ids":[]}']))
    @patch(
        "app.agent_runtime.chat_with_tools",
        return_value={"content": None, "tool_calls": [{"id": "call-1", "name": "lookup", "arguments": {}}]},
    )
    def test_runtime_stops_at_personal_read_budget(self, _chat_with_tools, _chat_stream):
        result = run_chat_agent(
            [{"role": "user", "content": "查资料"}],
            [self.tool.spec()],
            {"lookup": self.tool},
            "anthropic",
            {"api_key": "key", "model": "model"},
            budget=AgentBudget(max_steps=2, max_model_calls=3, max_personal_reads=1),
        )

        self.assertEqual(result.status, "budget_exceeded")
        self.assertEqual(len(result.steps), 2)
        self.assertEqual(result.steps[0].tool_calls[0]["status"], "completed")
        self.assertEqual(result.steps[1].tool_calls[0]["status"], "failed")

    @patch("app.agent_runtime.chat_stream", return_value=iter(['{"answer":"完成","source_ids":[]}']))
    @patch(
        "app.agent_runtime.chat_with_tools",
        return_value={"content": None, "tool_calls": [{"id": "call-1", "name": "lookup", "arguments": {"bad": True}}]},
    )
    def test_invalid_tool_arguments_are_recorded_as_failed(self, _chat_with_tools, _chat_stream):
        def invalid_handler(_arguments):
            raise ValueError("bad args")

        invalid_tool = AgentTool(
            name="lookup",
            description="读取测试资料",
            parameters={"type": "object"},
            category="personal",
            handler=invalid_handler,
        )
        result = run_chat_agent(
            [{"role": "user", "content": "查资料"}],
            [invalid_tool.spec()],
            {"lookup": invalid_tool},
            "anthropic",
            {"api_key": "key", "model": "model"},
        )
        self.assertEqual(result.steps[0].tool_calls[0]["status"], "failed")

    @patch("app.agent_runtime.chat_stream", return_value=iter(['{"answer":"依据岗位资料回答","source_ids":["jd-1"],"insufficient_data":false,"used_tools":["read_current_jd"],"answer_mode":"sourced","search_status":"not_used"}']))
    @patch("app.agent_runtime.chat_with_tools", return_value={"content": None, "tool_calls": []})
    def test_required_tools_are_read_before_model_can_finish(self, _chat_with_tools, _chat_stream):
        required = AgentTool(
            name="read_current_jd",
            description="读取当前岗位 JD",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            category="personal",
            handler=lambda _arguments: AgentToolResult(
                ok=True,
                data={"title": "后端工程师"},
                sources=[{"id": "jd-1", "title": "当前岗位 JD", "kind": "jd", "scope": "current_position"}],
            ),
        )
        result = run_chat_agent(
            [{"role": "user", "content": "这个岗位要求什么？"}],
            [required.spec()],
            {required.name: required},
            "anthropic",
            {"api_key": "key", "model": "model"},
            required_tools=[("read_current_jd", {})],
        )
        self.assertEqual(result.used_tools, ["read_current_jd"])
        self.assertEqual(result.sources[0].id, "jd-1")
        self.assertEqual(result.steps[0].tool_calls[0]["status"], "completed")
        self.assertGreaterEqual(result.steps[0].tool_elapsed_ms, 0)

    @patch("app.agent_runtime.chat_stream", return_value=iter(['{"answer":"通用解释","source_ids":[],"answer_mode":"general","insufficient_data":false,"search_status":"not_used"}']))
    @patch("app.agent_runtime.chat_with_tools", return_value={"content": None, "tool_calls": []})
    def test_general_question_without_sources_is_not_marked_insufficient(self, _chat_with_tools, _chat_stream):
        result = run_chat_agent(
            [{"role": "user", "content": "什么是幂等性？"}],
            [self.tool.spec()],
            {self.tool.name: self.tool},
            "anthropic",
            {"api_key": "key", "model": "model"},
        )

        self.assertFalse(result.insufficient_data)
        self.assertEqual(result.answer_mode, "general")


if __name__ == "__main__":
    unittest.main()
