import unittest

from app.agent_routing import required_tools_for_question


class AgentRoutingTestCase(unittest.TestCase):
    def test_position_fact_question_requires_current_jd_and_intel(self):
        names = [name for name, _ in required_tools_for_question("这个岗位一面主要考什么？")]
        self.assertEqual(names, ["read_current_jd", "search_current_intel"])

    def test_resume_question_requires_resume_and_jd(self):
        names = [name for name, _ in required_tools_for_question("我的简历和岗位匹配吗？")]
        self.assertEqual(names, ["read_resume", "read_current_jd"])

    def test_general_definition_can_skip_private_reads(self):
        self.assertEqual(required_tools_for_question("什么是向量数据库？"), [])


if __name__ == "__main__":
    unittest.main()
