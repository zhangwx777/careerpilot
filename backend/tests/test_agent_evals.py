import json
from pathlib import Path
import unittest

from app.agent_routing import required_tools_for_question


class FixedAgentEvalTests(unittest.TestCase):
    def test_fixed_offline_routing_corpus(self):
        cases = json.loads((Path(__file__).parent / "agent_eval_cases.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 30)
        self.assertEqual(len({item["id"] for item in cases}), len(cases))
        for item in cases:
            with self.subTest(sample=item["id"]):
                self.assertEqual([name for name, _ in required_tools_for_question(item["question"])], item["tools"])
