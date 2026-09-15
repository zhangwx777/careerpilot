import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.llm.provider import LlmCallError
from app.parsing import NoticeParseError, extract_notice


class NoticeParsingTestCase(unittest.TestCase):
    def setUp(self):
        self.requested_at = datetime(
            2026, 9, 8, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")
        )

    @patch("app.parsing.chat")
    def test_extracts_valid_json_with_explicit_qwen_provider(self, mock_chat):
        mock_chat.return_value = (
            '{"company_name":"示例科技","position_title":"后端工程师",'
            '"node_type":"笔试","scheduled_at":"2026-09-09T19:00:00+08:00",'
            '"ends_at":"2026-09-09T21:00:00+08:00","source":"邮件"}'
        )

        result = extract_notice("请于明晚参加笔试", self.requested_at, provider="qwen")

        self.assertEqual(result.company_name, "示例科技")
        self.assertEqual(result.node_type, "笔试")
        self.assertEqual(result.scheduled_at.hour, 19)
        _, kwargs = mock_chat.call_args
        self.assertEqual(kwargs["provider"], "qwen")
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        self.assertIn("2026-09-08T10:00:00+08:00", mock_chat.call_args.args[0][1]["content"])

    @patch("app.parsing.chat")
    def test_keeps_unknown_fields_null(self, mock_chat):
        mock_chat.return_value = (
            '{"company_name":null,"position_title":null,"node_type":null,'
            '"scheduled_at":null,"ends_at":null,"source":"短信"}'
        )

        result = extract_notice("请留意后续通知", self.requested_at, provider="qwen")

        self.assertIsNone(result.company_name)
        self.assertIsNone(result.scheduled_at)

    @patch("app.parsing.chat")
    def test_extracts_workday_deadline(self, mock_chat):
        mock_chat.return_value = (
            '{"company_name":"携程集团","position_title":"Agent开发工程师",'
            '"node_type":"笔试","time_mode":"截止窗口","deadline_workdays":3,'
            '"scheduled_at":null,"ends_at":null,"source":"邮件"}'
        )

        result = extract_notice("请在3个工作日内完成测评", self.requested_at, provider="qwen")

        self.assertEqual(result.time_mode, "截止窗口")
        self.assertEqual(result.deadline_workdays, 3)

    @patch("app.parsing.chat", side_effect=["not-json", "still-not-json"])
    def test_rejects_non_json_response(self, _mock_chat):
        with self.assertRaises(NoticeParseError):
            extract_notice("通知", self.requested_at, provider="qwen")

    @patch("app.parsing.chat", side_effect=RuntimeError("upstream failed"))
    def test_wraps_model_error_without_retry(self, mock_chat):
        with self.assertRaisesRegex(NoticeParseError, "模型调用失败"):
            extract_notice("通知", self.requested_at, provider="qwen")
        mock_chat.assert_called_once()

    @patch("app.parsing.chat", side_effect=LlmCallError("unavailable"))
    def test_preserves_safe_provider_error_category(self, _mock_chat):
        with self.assertRaisesRegex(NoticeParseError, "模型服务暂时不可用"):
            extract_notice("通知", self.requested_at, provider="qwen")

    @patch("app.parsing.chat")
    def test_rejects_naive_or_reversed_times(self, mock_chat):
        mock_chat.return_value = (
            '{"company_name":"示例科技","position_title":"后端工程师",'
            '"node_type":"一面","scheduled_at":"2026-09-09T20:00:00",'
            '"ends_at":"2026-09-09T19:00:00","source":"网页"}'
        )

        with self.assertRaises(NoticeParseError):
            extract_notice("通知", self.requested_at)


if __name__ == "__main__":
    unittest.main()
