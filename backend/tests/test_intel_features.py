import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.intel_api import IntelChatCreate, IntelImage, IntelImageExtractCreate, _chat_messages, _partial_chat_answer, create_intel_chat, extract_intel_images
from app.intel_graph import _apply_round_selection, _decide_review, _is_relevant_source, _merge
from app.intel_insight import _parse
from app.intel_parsing import SYSTEM_PROMPT, extract_intel
from app.intel_reminders import reminder_start
from app.intel_schemas import Fact, IntelExtraction, IntelPayload, IntelQuestion, PreparationItem, SourceRecord


class IntelFeatureTestCase(unittest.TestCase):
    def test_image_extract_maps_result_by_order_when_model_changes_filename(self):
        payload = IntelImageExtractCreate(
            provider="qwen",
            images=[IntelImage(name="面经截图.png", mime_type="image/png", data_url="data:image/png;base64," + "A" * 32)],
        )
        with patch("app.intel_api.chat", return_value='{"images":[{"name":"image-1","text":"一面问了项目复盘"}]}'):
            result = extract_intel_images(payload)
        self.assertEqual(result.combined_text, "一面问了项目复盘")

    def test_image_extract_does_not_silently_return_empty_text(self):
        payload = IntelImageExtractCreate(
            provider="qwen",
            images=[IntelImage(name="空白.png", mime_type="image/png", data_url="data:image/png;base64," + "A" * 32)],
        )
        with patch("app.intel_api.chat", return_value='{"images":[{"name":"空白.png","text":""}]}'):
            with self.assertRaisesRegex(HTTPException, "未识别出可编辑文字"):
                extract_intel_images(payload)

    def test_rejected_without_actionable_conflicts_does_not_wait_forever(self):
        self.assertEqual(
            _decide_review({"critic_rejected": True, "reflection_count": 2, "needs_review": False}),
            "persist",
        )
        self.assertEqual(
            _decide_review({"critic_rejected": True, "reflection_count": 2, "needs_review": True}),
            "review",
        )

    def test_jd_prompt_does_not_invent_interview_questions_or_internal_names(self):
        self.assertIn("这是一份岗位描述，未包含真实面试过程", SYSTEM_PROMPT)
        self.assertIn("不得凭空补写", SYSTEM_PROMPT)
        self.assertIn("不要出现 schema 字段名", SYSTEM_PROMPT)

    def test_chat_prompt_requires_a_generated_answer_for_question_only_material(self):
        source = SourceRecord(id="manual", title="用户粘贴", text="只记录了问题")
        application = SimpleNamespace(
            position_id=7,
            position=SimpleNamespace(company=SimpleNamespace(name="测试公司"), title="Agent工程师")
        )

        class FakeDb:
            def __init__(self):
                self.added = []

            def add(self, item):
                self.added.append(item)

            def commit(self):
                return None

            def refresh(self, item):
                item.id = 1
                item.created_at = datetime.now(timezone.utc)

        class FakeTasks:
            def __init__(self):
                self.calls = []

            def add_task(self, function, *args, **kwargs):
                self.calls.append((function, args, kwargs))

        db = FakeDb()
        tasks = FakeTasks()
        with patch("app.intel_api._chat_context", return_value=(application, IntelPayload(), [source])):
            result = create_intel_chat(
                IntelChatCreate(application_id=1, provider="qwen", question="如何设计 Agent workflow？"),
                tasks,
                db,
            )

        self.assertEqual(result.message.status, "生成中")
        self.assertEqual(result.message.content, "")
        self.assertEqual(len(tasks.calls), 1)
        prompt = _chat_messages(application, IntelPayload(), [source], "如何设计 Agent workflow？")
        self.assertIn("直接回答用户的问题", prompt[0]["content"])
        self.assertNotIn("只根据提供的岗位面经回答", prompt[0]["content"])

    def test_partial_chat_answer_is_visible_before_json_is_complete(self):
        self.assertEqual(_partial_chat_answer('{"answer":"先从项目边界'), "先从项目边界")

    def test_relevance_filter_rejects_recruitment_page_without_interview_content(self):
        self.assertFalse(
            _is_relevant_source(
                "携程集团2027届秋招启动公告",
                "校园招聘岗位职责、投递入口和招聘流程。",
            )
        )
        self.assertTrue(
            _is_relevant_source(
                "携程 Agent 开发工程师面经",
                "一面主要问了 workflow、项目复盘和 Agent 架构。",
            )
        )

    def test_merge_keeps_questions_and_preparation_items_by_source(self):
        payload = _merge(
            [
                IntelExtraction(
                    questions=[
                        IntelQuestion(
                            question="如何设计 Agent workflow？",
                            category="项目",
                            round_type="技术面",
                            answer_outline="结合项目说明状态流转和失败重试。",
                            source_ids=["manual"],
                        )
                    ],
                    preparation_items=[
                        PreparationItem(
                            title="复习 workflow 设计",
                            detail="准备状态流转和重试策略。",
                            priority=1,
                            source_ids=["manual"],
                        )
                    ],
                ),
                IntelExtraction(
                    questions=[
                        IntelQuestion(
                            question="如何设计 Agent workflow？",
                            category="项目",
                            round_type="技术面",
                            answer_outline="补充监控和人工兜底。",
                            source_ids=["web-1"],
                        )
                    ]
                ),
            ],
            [
                SourceRecord(id="manual", title="用户粘贴", text=""),
                SourceRecord(id="web-1", title="公开面经", text=""),
            ],
        )
        self.assertEqual(len(payload.questions), 1)
        self.assertEqual(payload.questions[0].source_ids, ["manual", "web-1"])
        self.assertEqual(len(payload.preparation_items), 1)

    def test_merge_does_not_join_same_question_across_rounds(self):
        payload = _merge(
            [
                IntelExtraction(questions=[IntelQuestion(question="介绍项目", category="项目", round_type="一面", answer_outline="说明背景", source_ids=["a"])]),
                IntelExtraction(questions=[IntelQuestion(question="介绍项目", category="项目", round_type="二面", answer_outline="说明取舍", source_ids=["b"])]),
            ],
            [SourceRecord(id="a", title="一面", text=""), SourceRecord(id="b", title="二面", text="")],
        )
        self.assertEqual({item.round_type for item in payload.questions}, {"一面", "二面"})

    def test_round_selection_overrides_model_round_for_single_round_material(self):
        payload = IntelPayload(
            questions=[IntelQuestion(question="项目复盘", category="项目", round_type="技术面", answer_outline="说明取舍", source_ids=["a"])],
        )
        self.assertEqual(_apply_round_selection(payload, "二面").questions[0].round_type, "二面")

    def test_insight_discards_single_source_directions(self):
        insight = _parse(
            '{"status":"未生成","high_frequency_directions":[{"title":"RAG检索质量","source_ids":["a","a"],"round_types":["一面"],"representative_questions":["如何优化召回"]},{"title":"项目复盘","source_ids":["a"],"round_types":["一面"],"representative_questions":["介绍项目"]}],"core_questions":[],"preparation_items":[],"error_message":null}',
            {"a", "b"},
        )
        self.assertEqual(insight.high_frequency_directions, [])

    def test_insight_keeps_direction_from_two_independent_sources(self):
        insight = _parse(
            '{"status":"未生成","high_frequency_directions":[{"title":"RAG检索质量","source_ids":["a","b"],"round_types":["一面","二面"],"representative_questions":["如何优化召回","如何排查检索质量"]}],"core_questions":[],"preparation_items":[],"error_message":null}',
            {"a", "b"},
        )
        self.assertEqual(insight.high_frequency_directions[0].source_ids, ["a", "b"])

    def test_reminder_is_exactly_one_day_before_interview(self):
        interview = datetime(2026, 9, 15, 10, 30, tzinfo=timezone.utc)
        self.assertEqual(reminder_start(interview, interview - timedelta(days=2)), interview - timedelta(days=1))

    def test_late_interview_reminder_starts_now(self):
        now = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)
        interview = now + timedelta(hours=6)
        self.assertEqual(reminder_start(interview, now), now)

    @patch(
        "app.intel_parsing.chat",
        side_effect=[
            '{"rounds":[{"round_type":"技术面","questions":[{"question":"错误字段"}]}]}',
            '{"rounds":[],"questions":[{"question":"如何设计 workflow？","category":"项目","round_type":"技术面","answer_outline":"结合项目说明。","source_ids":["user-paste"]}],"frequent_topics":[],"difficulty":null,"preparation_items":[],"summary":null}',
        ],
    )
    def test_invalid_extraction_is_repaired_once(self, mock_chat):
        result = extract_intel(SourceRecord(id="user-paste", title="用户粘贴", text="如何设计 workflow？"), "qwen")
        self.assertEqual(result.questions[0].source_ids, ["user-paste"])
        self.assertEqual(mock_chat.call_count, 2)


if __name__ == "__main__":
    unittest.main()
