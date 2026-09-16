import unittest
from pathlib import Path


class PackagedServerInitTests(unittest.TestCase):
    """打包入口必须复用 init_db 的完整初始化，否则缺 checkpoint 表，
    解析图/面经图运行时崩溃。"""

    def _source(self) -> str:
        return Path(__file__).parents[1].joinpath("packaged_server.py").read_text(encoding="utf-8")

    def test_reuses_initialize_database(self):
        source = self._source()
        self.assertIn("initialize_database", source)

    def test_does_not_handroll_create_all_only(self):
        # 不允许只靠 Base.metadata.create_all 建表（会漏 checkpoint 表）
        source = self._source()
        self.assertNotIn("Base.metadata.create_all", source)


if __name__ == "__main__":
    unittest.main()
