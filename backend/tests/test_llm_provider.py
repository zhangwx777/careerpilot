import unittest
from types import SimpleNamespace
from unittest.mock import patch

from litellm.exceptions import UnsupportedParamsError

from app.llm.provider import _request_kwargs, chat, chat_stream, chat_with_tools


def _response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _tool_response(name: str = "lookup_status", arguments: str = '{"item":"alpha"}'):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(name=name, arguments=arguments),
                        )
                    ],
                )
            )
        ]
    )


def _chunk(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


class LlmProviderParametersTestCase(unittest.TestCase):
    def setUp(self):
        self.config = {
            "api_key": "test-key",
            "api_base": "https://api.example.test/v1",
            "model": "test-model",
        }

    def test_request_passes_explicit_provider_to_litellm(self):
        for provider in ("openai", "anthropic", "deepseek", "qwen"):
            with self.subTest(provider=provider):
                kwargs = _request_kwargs(
                    [{"role": "user", "content": "{}"}],
                    provider,
                    {"type": "json_object"},
                    self.config,
                    generation="structured",
                )
                self.assertEqual(kwargs["custom_llm_provider"], provider)

    def test_all_providers_allow_litellm_to_drop_unsupported_parameters(self):
        for provider in ("openai", "anthropic", "deepseek", "qwen"):
            with self.subTest(provider=provider):
                kwargs = _request_kwargs(
                    [{"role": "user", "content": "{}"}],
                    provider,
                    {"type": "json_object"},
                    self.config,
                    generation="structured",
                )
                self.assertTrue(kwargs["drop_params"])
                self.assertEqual(kwargs["temperature"], 0)
                self.assertEqual(
                    kwargs["extra_headers"],
                    {
                        "Accept": "application/json",
                        "User-Agent": "qiuzhao-agent/0.1",
                    },
                )

    @patch("app.llm.provider.litellm.completion")
    def test_chat_retries_when_gateway_rejects_temperature(self, completion):
        completion.side_effect = [
            UnsupportedParamsError("temperature is not supported"),
            _response('{"ok":true}'),
        ]

        result = chat(
            [{"role": "user", "content": "{}"}],
            "openai",
            response_format={"type": "json_object"},
            config=self.config,
            generation="structured",
        )

        self.assertEqual(result, '{"ok":true}')
        self.assertEqual(completion.call_count, 2)
        first_kwargs = completion.call_args_list[0].kwargs
        retry_kwargs = completion.call_args_list[1].kwargs
        self.assertEqual(first_kwargs["temperature"], 0)
        self.assertNotIn("temperature", retry_kwargs)
        self.assertTrue(retry_kwargs["drop_params"])

    @patch("app.llm.provider.litellm.completion")
    def test_chat_retries_without_response_format_when_gateway_rejects_json_mode(
        self, completion
    ):
        completion.side_effect = [
            UnsupportedParamsError("response_format is not supported"),
            _response('{"ok":true}'),
        ]

        result = chat(
            [{"role": "user", "content": "{}"}],
            "anthropic",
            response_format={"type": "json_object"},
            config=self.config,
            generation="chat",
        )

        self.assertEqual(result, '{"ok":true}')
        self.assertEqual(completion.call_count, 2)
        self.assertNotIn("response_format", completion.call_args_list[1].kwargs)

    @patch("app.llm.provider.litellm.completion")
    def test_stream_retries_before_any_chunk_when_parameter_is_rejected(self, completion):
        def reject_before_streaming():
            raise UnsupportedParamsError("temperature is not supported")
            yield  # pragma: no cover - keeps this a generator function

        def stream_successfully():
            yield _chunk("ok")

        completion.side_effect = [reject_before_streaming(), stream_successfully()]

        result = list(
            chat_stream(
                [{"role": "user", "content": "{}"}],
                "openai",
                response_format={"type": "json_object"},
                config=self.config,
                generation="structured",
            )
        )

        self.assertEqual(result, ["ok"])
        self.assertEqual(completion.call_count, 2)
        self.assertNotIn("temperature", completion.call_args_list[1].kwargs)

    @patch("app.llm.provider.litellm.completion")
    def test_stream_does_not_replay_partial_response(self, completion):
        def partial_then_rejects():
            yield _chunk("partial")
            raise UnsupportedParamsError("temperature is not supported")

        completion.return_value = partial_then_rejects()

        with self.assertRaisesRegex(RuntimeError, "模型返回异常"):
            list(
                chat_stream(
                    [{"role": "user", "content": "{}"}],
                    "openai",
                    config=self.config,
                    generation="structured",
                )
            )

        completion.assert_called_once()

    @patch("app.llm.provider.litellm.completion")
    def test_chat_with_tools_normalizes_tool_call(self, completion):
        completion.return_value = _tool_response()

        result = chat_with_tools(
            [{"role": "user", "content": "查一下 alpha"}],
            [{"type": "function", "function": {"name": "lookup_status"}}],
            "anthropic",
            config=self.config,
        )

        self.assertEqual(result["content"], None)
        self.assertEqual(
            result["tool_calls"],
            [{"id": "call-1", "name": "lookup_status", "arguments": {"item": "alpha"}}],
        )
        self.assertEqual(completion.call_args.kwargs["tool_choice"], "auto")
        self.assertNotIn("response_format", completion.call_args.kwargs)

    @patch("app.llm.provider.litellm.completion")
    def test_chat_with_tools_rejects_invalid_arguments(self, completion):
        completion.return_value = _tool_response(arguments="[]")

        with self.assertRaisesRegex(RuntimeError, "模型返回异常"):
            chat_with_tools(
                [{"role": "user", "content": "查一下 alpha"}],
                [{"type": "function", "function": {"name": "lookup_status"}}],
                "anthropic",
                config=self.config,
            )

    @patch("app.llm.provider.litellm.completion")
    def test_chat_with_tools_reports_unsupported_models_without_fallback(self, completion):
        completion.side_effect = RuntimeError("This model does not support tool calls")

        with self.assertRaisesRegex(RuntimeError, "当前模型不支持工具调用"):
            chat_with_tools(
                [{"role": "user", "content": "查一下 alpha"}],
                [{"type": "function", "function": {"name": "lookup_status"}}],
                "qwen",
                config=self.config,
            )
        completion.assert_called_once()


if __name__ == "__main__":
    unittest.main()
