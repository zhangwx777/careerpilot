"""面经合并/读取的长度上限回归测试（纯函数，不依赖数据库）。

复现并锁定 bug：多份材料在同一轮次下合并 focus_topics 后超过 schema 上限 20，
写入不校验、读取 IntelPayload.model_validate 时抛 too_long -> dossier 接口 500。
"""

import unittest

from app.intel_schemas import Fact, IntelExtraction, InterviewRound, SourceRecord


class MergeTruncationTestCase(unittest.TestCase):
    def _round_with_topics(self, values, source_id):
        return InterviewRound(
            round_type="一面",
            focus_topics=[Fact(value=v, source_ids=[source_id]) for v in values],
            source_ids=[source_id],
        )

    def test_merge_truncates_focus_topics_to_schema_limit(self):
        from app.intel_graph import _merge

        first = [f"话题{i}" for i in range(15)]
        second = [f"话题{i}" for i in range(15, 23)]  # 去重后共 23 个不同值
        payload = _merge(
            [
                IntelExtraction(rounds=[self._round_with_topics(first, "src-a")]),
                IntelExtraction(rounds=[self._round_with_topics(second, "src-b")]),
            ],
            [
                SourceRecord(id="src-a", title="甲", text=""),
                SourceRecord(id="src-b", title="乙", text=""),
            ],
        )
        merged_round = next(r for r in payload.rounds if r.round_type == "一面")
        self.assertLessEqual(
            len(merged_round.focus_topics),
            20,
            "合并后 focus_topics 必须截断到 schema 上限 20，否则写入库后读取会 500",
        )

    def test_dossier_reads_material_with_over_limit_payload(self):
        from app.intel_api import _read_dossier_material

        payload = {
            "rounds": [
                {
                    "round_type": "一面",
                    "focus_topics": [
                        {"value": f"话题{i}", "source_ids": ["s1"]} for i in range(23)
                    ],
                    "source_ids": ["s1"],
                }
            ]
        }
        result = _read_dossier_material(payload)
        merged_round = next(r for r in result.rounds if r.round_type == "一面")
        self.assertLessEqual(
            len(merged_round.focus_topics),
            20,
            "读取侧必须能容错解析已存的超限老数据（截断到 20）",
        )


if __name__ == "__main__":
    unittest.main()
