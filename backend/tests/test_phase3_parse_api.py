import os
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_db
from app.main import app
from app.models import Application, Company, ParseSession, Position, TimelineNode
from app.parsing import NoticeExtraction, NoticeParseError
from scripts.init_db import initialize_database


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "需要显式配置 TEST_DATABASE_URL，不允许回退到开发数据库",
)
class ParseSessionApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database(TEST_DATABASE_URL)
        cls.engine = create_engine(TEST_DATABASE_URL)
        cls.session_factory = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.session_factory.begin() as db:
            db.execute(delete(ParseSession))
            db.execute(delete(TimelineNode))
            db.execute(delete(Application))
            db.execute(delete(Position))
            db.execute(delete(Company))

            company = Company(name="示例科技", industry="互联网")
            position = Position(company=company, title="后端工程师")
            application = Application(position=position, status="已投递")
            db.add(application)
            db.flush()
            self.application_id = application.id

        def override_db():
            with self.session_factory() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        self.url_patch = patch(
            "app.phase3_api.settings.database_url", TEST_DATABASE_URL
        )
        self.factory_patch = patch(
            "app.phase3_api.SessionLocal", self.session_factory
        )
        self.url_patch.start()
        self.factory_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.factory_patch.stop()
        self.url_patch.stop()
        app.dependency_overrides.clear()

    def extraction(self):
        return NoticeExtraction.model_validate(
            {
                "company_name": "示例科技",
                "position_title": "后端工程师",
                "node_type": "笔试",
                "scheduled_at": "2026-09-09T19:00:00+08:00",
                "ends_at": "2026-09-09T21:00:00+08:00",
                "source": "邮件",
            }
        )

    def wait_for_status(self, parse_session_id: int, expected: set[str]) -> str:
        for _ in range(100):
            with self.session_factory() as db:
                item = db.get(ParseSession, parse_session_id)
                if item is not None and item.status in expected:
                    return item.status
            time.sleep(0.05)
        self.fail(f"解析会话未在限定时间内进入状态：{expected}")

    @patch("app.parse_graph.extract_notice")
    def test_interrupt_survives_new_checkpointer_and_confirm_is_idempotent(
        self, mock_extract
    ):
        mock_extract.return_value = self.extraction()
        created = self.client.post(
            "/api/parse-sessions", json={"raw_text": "笔试通知"}
        )
        self.assertEqual(created.status_code, 201, created.text)
        session_data = created.json()
        self.assertEqual(self.wait_for_status(session_data["id"], {"待确认"}), "待确认")
        self.assertEqual(len(session_data["recommended_applications"]), 1)
        parse_session_id = session_data["id"]

        pending = self.client.get(
            "/api/parse-sessions", params={"status": "待确认"}
        )
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["total"], 1)
        self.assertEqual(
            self.client.get(f"/api/parse-sessions/{parse_session_id}").status_code,
            200,
        )

        confirmation = {
            "application_id": self.application_id,
            "node_type": "笔试",
            "scheduled_at": "2026-09-09T19:30:00+08:00",
            "ends_at": "2026-09-09T21:00:00+08:00",
            "source": "邮件",
        }
        confirmed = self.client.post(
            f"/api/parse-sessions/{parse_session_id}/confirm", json=confirmation
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["status"], "已确认")
        timeline_node_id = confirmed.json()["timeline_node_id"]
        self.assertIsNotNone(timeline_node_id)

        repeated = self.client.post(
            f"/api/parse-sessions/{parse_session_id}/confirm", json=confirmation
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["timeline_node_id"], timeline_node_id)
        self.assertEqual(
            self.client.post(
                f"/api/parse-sessions/{parse_session_id}/discard"
            ).status_code,
            409,
        )

        with self.session_factory() as db:
            node_count = db.scalar(select(func.count()).select_from(TimelineNode))
            node = db.get(TimelineNode, timeline_node_id)
            self.assertEqual(node_count, 1)
            self.assertEqual(node.scheduled_at.minute, 30)

    @patch("app.parse_graph.extract_notice")
    def test_discard_is_idempotent_and_never_writes_timeline(self, mock_extract):
        mock_extract.return_value = self.extraction()
        created = self.client.post(
            "/api/parse-sessions", json={"raw_text": "面试通知"}
        ).json()
        self.assertEqual(self.wait_for_status(created["id"], {"待确认"}), "待确认")

        first = self.client.post(
            f"/api/parse-sessions/{created['id']}/discard"
        )
        second = self.client.post(
            f"/api/parse-sessions/{created['id']}/discard"
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], "已丢弃")
        self.assertEqual(
            self.client.post(
                f"/api/parse-sessions/{created['id']}/confirm",
                json={
                    "application_id": self.application_id,
                    "node_type": "一面",
                    "scheduled_at": "2026-09-10T10:00:00+08:00",
                },
            ).status_code,
            409,
        )
        with self.session_factory() as db:
            self.assertEqual(
                db.scalar(select(func.count()).select_from(TimelineNode)), 0
            )

    @patch(
        "app.parse_graph.extract_notice",
        side_effect=NoticeParseError("模型返回的抽取结果无效"),
    )
    def test_model_failure_marks_session_failed(self, _mock_extract):
        response = self.client.post(
            "/api/parse-sessions", json={"raw_text": "无法解析的通知"}
        )
        self.assertEqual(response.status_code, 201, response.text)
        with self.session_factory() as db:
            parse_session = db.scalar(
                select(ParseSession).order_by(ParseSession.id.desc())
            )
            parse_session_id = parse_session.id
        self.assertEqual(self.wait_for_status(parse_session_id, {"解析失败"}), "解析失败")
        with self.session_factory() as db:
            parse_session = db.get(ParseSession, parse_session_id)
            self.assertEqual(parse_session.status, "解析失败")
            self.assertIsNotNone(parse_session.error_message)

    @patch("app.parse_graph.extract_notice")
    def test_confirm_requires_existing_application(self, mock_extract):
        mock_extract.return_value = self.extraction()
        created = self.client.post(
            "/api/parse-sessions", json={"raw_text": "笔试通知"}
        ).json()
        self.assertEqual(self.wait_for_status(created["id"], {"待确认"}), "待确认")
        response = self.client.post(
            f"/api/parse-sessions/{created['id']}/confirm",
            json={
                "application_id": 999999,
                "node_type": "笔试",
                "scheduled_at": "2026-09-09T19:00:00+08:00",
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_create_application_from_pending_notice_keeps_reapplications(self):
        with self.session_factory.begin() as db:
            session = ParseSession(
                raw_text="投递回执",
                provider="qwen",
                status="待确认",
            )
            db.add(session)
            db.flush()
            session_id = session.id

        payload = {"company_name": "携程集团", "position_title": "Agent开发工程师"}
        created = self.client.post(
            f"/api/parse-sessions/{session_id}/application", json=payload
        )
        repeated = self.client.post(
            f"/api/parse-sessions/{session_id}/application", json=payload
        )

        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(repeated.status_code, 201, repeated.text)
        self.assertNotEqual(created.json()["id"], repeated.json()["id"])
        self.assertEqual(created.json()["status"], "已投递")
        with self.session_factory() as db:
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(Application).where(
                        Application.position.has(Position.title == "Agent开发工程师")
                    )
                ),
                2,
            )


if __name__ == "__main__":
    unittest.main()
