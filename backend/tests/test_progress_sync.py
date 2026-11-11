import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Application, Company, ParseSession, Position, TimelineNode
from app.parse_graph import build_parse_graph
from app.parsing import NoticeExtraction


class ProgressSyncTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        with self.sessions.begin() as db:
            application = Application(
                position=Position(company=Company(name="同步测试公司"), title="工程师"),
                status="已投递",
            )
            db.add(application)
            db.flush()
            self.application_id = application.id

        def override_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        self.addCleanup(app.dependency_overrides.clear)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.client.close)

    def confirm_notice(self, node_type="笔试", create_application=False):
        with self.sessions.begin() as db:
            item = ParseSession(raw_text="测试通知", provider="qwen", status="解析中")
            db.add(item)
            db.flush()
            session_id = item.id
        graph = build_parse_graph(InMemorySaver(), self.sessions)
        config = {"configurable": {"thread_id": str(session_id)}}
        with patch("app.parse_graph.config_from_snapshot", return_value={}), patch(
            "app.parse_graph.extract_notice", return_value=NoticeExtraction(node_type=node_type)
        ):
            graph.invoke({
                "parse_session_id": session_id, "raw_text": "测试通知", "provider": "qwen",
                "requested_at": datetime.now(timezone.utc).isoformat(),
            }, config)
        if create_application:
            response = self.client.post(f"/api/parse-sessions/{session_id}/application", json={
                "company_name": "新通知公司", "position_title": "后端工程师",
            })
            self.assertEqual(response.status_code, 201, response.text)
            self.application_id = response.json()["id"]
        # 仅解析不应推进阶段，必须等用户确认。
        with self.sessions() as db:
            before = db.get(Application, self.application_id).status
        graph.invoke(Command(resume={
            "application_id": self.application_id, "node_type": node_type,
            "scheduled_at": "2026-10-26T10:00:00+08:00",
        }), config)
        return before

    def application_status(self):
        return self.client.get(f"/api/applications/{self.application_id}").json()["status"]

    def test_confirmed_notice_advances_application_and_dashboard(self):
        self.assertEqual(self.confirm_notice(), "已投递")
        self.assertEqual(self.application_status(), "笔试")
        pipeline = self.client.get("/api/dashboard").json()["pipeline"]
        self.assertEqual(next(item["count"] for item in pipeline if item["status"] == "笔试"), 1)

    def test_application_created_in_smart_entry_advances_only_after_confirmation(self):
        original_id = self.application_id
        self.assertEqual(self.confirm_notice(create_application=True), "已投递")
        self.assertEqual(self.application_status(), "笔试")
        self.assertEqual(self.client.get(f"/api/applications/{original_id}").json()["status"], "已投递")

    def test_each_recruitment_stage_is_synced_on_confirmation(self):
        for node_type in ("测评", "笔试", "AI面", "一面", "二面", "三面", "HR面"):
            with self.subTest(node_type=node_type):
                self.confirm_notice(node_type)
                self.assertEqual(self.application_status(), node_type)

    def test_late_notice_does_not_regress_later_or_manually_closed_application(self):
        for status in ("二面", "offer", "挂"):
            with self.subTest(status=status):
                with self.sessions.begin() as db:
                    db.get(Application, self.application_id).status = status
                self.confirm_notice()
                self.assertEqual(self.application_status(), status)

    def test_non_stage_notice_does_not_advance_application(self):
        self.confirm_notice("网申截止")
        self.assertEqual(self.application_status(), "已投递")

    def test_completing_existing_schedule_repairs_stage_and_updates_all_reads(self):
        with self.sessions.begin() as db:
            node = TimelineNode(
                application_id=self.application_id, node_type="笔试", status="待处理",
                scheduled_at=datetime(2026, 10, 26, 2, tzinfo=timezone.utc),
                time_mode="固定时间",
            )
            db.add(node)
            db.flush()
            node_id = node.id
        response = self.client.patch(f"/api/timeline/{node_id}/status", json={"status": "已完成"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "已完成")
        self.assertEqual(response.json()["application"]["status"], "笔试")
        self.assertEqual(self.application_status(), "笔试")
        calendar = self.client.get("/api/timeline", params={
            "start": "2026-10-01T00:00:00+08:00", "end": "2026-11-01T00:00:00+08:00",
        }).json()
        self.assertEqual(calendar["items"][0]["status"], "已完成")
        self.assertEqual(calendar["items"][0]["alert_types"], [])
        self.assertEqual(self.client.get("/api/dashboard").json()["feed"], [])
        # 恢复安排不应推进到下一轮，也不应丢掉当前阶段。
        self.client.patch(f"/api/timeline/{node_id}/status", json={"status": "待处理"})
        self.assertEqual(self.application_status(), "笔试")
        self.assertEqual(len(self.client.get("/api/dashboard").json()["feed"]), 1)


if __name__ == "__main__":
    unittest.main()
