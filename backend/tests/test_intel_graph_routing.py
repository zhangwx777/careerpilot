import unittest

from app.intel_graph import _decide_after_aggregate


class IntelGraphRoutingTestCase(unittest.TestCase):
    def test_local_sources_without_conflicts_persist_without_critic(self):
        self.assertEqual(
            _decide_after_aggregate(
                {"supplement_web": False, "sources": [{"id": "a"}], "confidence": 0.55, "search_attempt": 0, "payload": {"conflicts": []}}
            ),
            "persist",
        )

    def test_local_conflicts_still_require_critic(self):
        self.assertEqual(
            _decide_after_aggregate(
                {"supplement_web": False, "confidence": 0.55, "search_attempt": 0, "payload": {"conflicts": [{"field": "difficulty"}]}}
            ),
            "critic",
        )

    def test_multiple_local_sources_still_require_critic(self):
        self.assertEqual(
            _decide_after_aggregate(
                {"supplement_web": False, "sources": [{"id": "a"}, {"id": "b"}], "confidence": 0.85, "search_attempt": 0, "payload": {"conflicts": []}}
            ),
            "critic",
        )

    def test_web_search_stops_at_the_bound(self):
        self.assertEqual(
            _decide_after_aggregate(
                {"supplement_web": True, "confidence": 0.55, "search_attempt": 3, "payload": {"conflicts": []}}
            ),
            "critic",
        )

    def test_empty_extraction_is_never_persisted(self):
        self.assertEqual(
            _decide_after_aggregate(
                {
                    "supplement_web": False,
                    "sources": [{"id": "manual"}],
                    "extractions": {},
                    "confidence": 0.0,
                    "search_attempt": 0,
                    "payload": {"conflicts": []},
                }
            ),
            "fail",
        )


if __name__ == "__main__":
    unittest.main()
