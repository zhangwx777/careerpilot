from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from time import sleep
from unittest.mock import patch
import unittest

from app.agent_runtime import AgentBudget, run_chat_agent
from app.agent_schemas import AgentToolResult
from app.agent_tools import AgentTool
from app.llm.budget import BudgetExceeded, ExecutionBudget, execution_budget
from app.llm.provider import chat, chat_stream
from app.llm.structured import parse_structured

CONFIG = {"api_key": "offline-key", "model": "gpt-test"}


def response(content="{}"):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))], usage=SimpleNamespace(total_tokens=37))


class ExecutionBudgetTests(unittest.TestCase):
    def test_parameter_retry_consumes_actual_attempt_budget(self):
        error = RuntimeError("unsupported parameter response_format")
        with execution_budget(1, 10) as budget, patch("app.llm.provider.litellm.completion", side_effect=error) as completion:
            with self.assertRaises(BudgetExceeded):
                chat([], "openai", response_format={"type": "json_object"}, config=CONFIG)
        self.assertEqual(completion.call_count, 1)
        self.assertEqual(budget.calls, 1)

    def test_empty_stream_fallback_cannot_exceed_shared_budget(self):
        with execution_budget(2, 10), patch("app.llm.provider.litellm.completion", side_effect=[response(), RuntimeError("stream failed")]) as completion:
            with self.assertRaises(BudgetExceeded):
                run_chat_agent([], [], {}, "openai", CONFIG)
        self.assertEqual(completion.call_count, 2)

    def test_json_repair_uses_same_budget_as_initial_call(self):
        with execution_budget(1, 10), patch("app.llm.provider.litellm.completion", return_value=response("bad")) as completion:
            raw = chat([], "openai", config=CONFIG)
            with self.assertRaises(BudgetExceeded):
                parse_structured(raw, [], "openai", lambda text: __import__("json").loads(text), chat_fn=chat, config=CONFIG)
        self.assertEqual(completion.call_count, 1)

    def test_provider_receives_remaining_timeout_and_reports_usage(self):
        with execution_budget(2, 2) as budget, patch("app.llm.provider.litellm.completion", return_value=response()) as completion:
            chat([], "openai", config=CONFIG)
        self.assertLessEqual(completion.call_args.kwargs["timeout"], 2)
        self.assertEqual(completion.call_args.kwargs["num_retries"], 0)
        self.assertEqual(budget.snapshot()["reported_tokens"], 37)

    def test_stream_duration_includes_provider_iteration(self):
        chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))], usage=None)
        def stream():
            sleep(0.02)
            yield chunk
            sleep(0.02)
        with execution_budget(1, 2) as budget, patch("app.llm.provider.litellm.completion", return_value=stream()):
            self.assertEqual(list(chat_stream([], "openai", config=CONFIG)), ["ok"])
        self.assertGreaterEqual(budget.snapshot()["provider_ms"], 30)

    def test_stream_ending_after_deadline_is_rejected(self):
        now = [0.0]
        chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="{}"))], usage=None)
        def stream():
            yield chunk
            now[0] = 2.0
        with patch("app.llm.budget.monotonic", side_effect=lambda: now[0]), patch("app.llm.provider.monotonic", side_effect=lambda: now[0]):
            with execution_budget(1, 1) as budget:
                budget.started = 0.0
                with patch("app.llm.provider.litellm.completion", return_value=stream()):
                    with self.assertRaises(BudgetExceeded):
                        list(chat_stream([], "openai", config=CONFIG))

    def test_failed_stream_connection_contributes_provider_time(self):
        now = [0.0]
        def fail(**_kwargs):
            now[0] = 0.25
            raise RuntimeError("offline")
        with patch("app.llm.budget.monotonic", side_effect=lambda: now[0]), patch("app.llm.provider.monotonic", side_effect=lambda: now[0]):
            with execution_budget(1, 1) as budget, patch("app.llm.provider.litellm.completion", side_effect=fail):
                with self.assertRaises(RuntimeError):
                    list(chat_stream([], "openai", config=CONFIG))
        self.assertEqual(budget.snapshot()["provider_ms"], 250)

    def test_late_provider_result_is_rejected(self):
        with patch("app.llm.budget.monotonic", return_value=10):
            with execution_budget(2, 2) as budget:
                budget.started = 10
                def late(**kwargs):
                    budget.started = 0
                    return response()
                with patch("app.llm.provider.litellm.completion", side_effect=late):
                    with self.assertRaises(BudgetExceeded):
                        chat([], "openai", config=CONFIG)

    def test_baseline_reads_share_tool_and_deadline_limits(self):
        tool = AgentTool(name="lookup", description="测试", parameters={}, category="personal", handler=lambda _: AgentToolResult(ok=True))
        with patch("app.agent_runtime.chat_with_tools") as completion:
            with self.assertRaises(BudgetExceeded):
                run_chat_agent([], [], {"lookup": tool}, "openai", CONFIG, budget=AgentBudget(max_tool_calls=1), required_tools=[("lookup", {}), ("lookup", {})])
        completion.assert_not_called()

    def test_baseline_timeout_prevents_finalization(self):
        with execution_budget(2, 2) as budget:
            def slow(_):
                budget.started -= 10
                return AgentToolResult(ok=True)
            tool = AgentTool(name="lookup", description="测试", parameters={}, category="personal", handler=slow)
            with patch("app.agent_runtime.chat_stream") as stream, self.assertRaises(BudgetExceeded):
                run_chat_agent([], [], {"lookup": tool}, "openai", CONFIG, required_tools=[("lookup", {})])
            stream.assert_not_called()

    def test_parallel_graph_calls_cannot_overdraw_budget(self):
        budget = ExecutionBudget(2, 10)
        def claim(_):
            try:
                budget.claim_call()
                return True
            except BudgetExceeded:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(claim, range(8))), 2)
        self.assertIsNone(budget.snapshot()["reported_tokens"])
