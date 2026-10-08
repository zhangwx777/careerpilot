import json
from pathlib import Path
import unittest

from app.agent_routing import required_tools_for_question
from app.intel_api import _parse_chat_answer


class FixedAgentEvalTests(unittest.TestCase):
    def test_fixed_offline_routing_corpus(self):
        cases = json.loads((Path(__file__).parent / "agent_eval_cases.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 30)
        self.assertEqual(len({item["id"] for item in cases}), len(cases))
        for item in cases:
            with self.subTest(sample=item["id"]):
                self.assertEqual([name for name, _ in required_tools_for_question(item["question"])], item["tools"])

    def test_fixed_offline_answer_grounding_contract_corpus(self):
        cases = json.loads(
            (Path(__file__).parent / "agent_answer_eval_cases.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertGreaterEqual(len(cases), 8)
        self.assertEqual(len({item["id"] for item in cases}), len(cases))
        for item in cases:
            with self.subTest(sample=item["id"]):
                content = json.dumps(item["response"], ensure_ascii=False)
                if item["accepted"]:
                    answer = _parse_chat_answer(content, set(item["available_source_ids"]))
                    self.assertEqual(answer.answer_mode, item["response"]["answer_mode"])
                else:
                    with self.assertRaises(ValueError):
                        _parse_chat_answer(content, set(item["available_source_ids"]))
