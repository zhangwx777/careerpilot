import os
import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.main import app
from app.models import Application, Company, ParseSession, Position, TimelineNode
from app.timeline import alert_types, nodes_conflict
from scripts.init_db import initialize_database


def node(
    node_id: int,
    start: datetime,
    end: datetime | None = None,
    node_type: str = "笔试",
    status: str = "待处理",
) -> TimelineNode:
    return TimelineNode(
        id=node_id,
        application_id=1,
        node_type=node_type,
        scheduled_at=start,
        ends_at=end,
        status=status,
    )


class TimelineRulesTestCase(unittest.TestCase):
    def setUp(self):
        self.base = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)

    def test_complete_intervals_overlap_but_touching_endpoints_do_not(self):
        left = node(1, self.base, self.base + timedelta(hours=2))
        overlap = node(
            2, self.base + timedelta(hours=1), self.base + timedelta(hours=3)
        )
        touching = node(
            3, self.base + timedelta(hours=2), self.base + timedelta(hours=3)
        )
        self.assertTrue(nodes_conflict(left, overlap))
        self.assertFalse(nodes_conflict(left, touching))

    def test_point_conflicts_inside_interval_but_not_at_interval_end(self):
        interval = node(1, self.base, self.base + timedelta(hours=2))
        at_start = node(2, self.base)
        inside = node(3, self.base + timedelta(hours=1))
        at_end = node(4, self.base + timedelta(hours=2))
        self.assertTrue(nodes_conflict(interval, at_start))
        self.assertTrue(nodes_conflict(interval, inside))
        self.assertFalse(nodes_conflict(interval, at_end))

    def test_two_points_only_conflict_at_same_time(self):
        self.assertTrue(nodes_conflict(node(1, self.base), node(2, self.base)))
        self.assertFalse(
            nodes_conflict(node(1, self.base), node(2, self.base + timedelta(minutes=1)))
        )

    def test_non_pending_or_non_collision_types_do_not_conflict(self):
        active = node(1, self.base, self.base + timedelta(hours=1))
        completed = node(
            2,
            self.base,
            self.base + timedelta(hours=1),
            status="已完成",
        )
        deadline = node(
            3,
            self.base,
            self.base + timedelta(hours=1),
            node_type="网申截止",
        )
        self.assertFalse(nodes_conflict(active, completed))
        self.assertFalse(nodes_conflict(active, deadline))

    def test_upcoming_overdue_and_completed_alert_boundaries(self):
        now = self.base
        self.assertEqual(
            alert_types(node(1, now + timedelta(hours=24)), [], now), ["临期"]
        )
        self.assertEqual(
            alert_types(node(2, now - timedelta(seconds=1)), [], now), ["逾期"]
        )
        self.assertEqual(
            alert_types(node(3, now + timedelta(hours=25)), [], now), []
        )
        self.assertEqual(
            alert_types(node(4, now - timedelta(hours=1), status="已完成"), [], now),
            [],
        )
        self.assertEqual(
            alert_types(
                node(5, now + timedelta(hours=25)), [9], now
            ),
            ["冲突"],
        )


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "需要显式配置 TEST_DATABASE_URL，不允许回退到开发数据库",
)
class TimelineApiTestCase(unittest.TestCase):
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
            application = Application(
                position=Position(
                    company=Company(name="时间线公司"), title="测试工程师"
                ),
                status="一面",
            )
            db.add(application)
            db.flush()
            self.application_id = application.id
            first = TimelineNode(
                application_id=application.id,
                node_type="一面",
                scheduled_at=datetime(2026, 9, 10, 10, tzinfo=timezone.utc),
                ends_at=datetime(2026, 9, 10, 12, tzinfo=timezone.utc),
                status="待处理",
                source="邮件",
            )
            second = TimelineNode(
                application_id=application.id,
                node_type="笔试",
                scheduled_at=datetime(2026, 9, 10, 11, tzinfo=timezone.utc),
                ends_at=datetime(2026, 9, 10, 13, tzinfo=timezone.utc),
                status="待处理",
                source="短信",
            )
            boundary = TimelineNode(
                application_id=application.id,
                node_type="网申截止",
                scheduled_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                status="待处理",
            )
            db.add_all([first, second, boundary])
            db.flush()
            self.first_id = first.id
            self.second_id = second.id

        def override_db():
            with self.session_factory() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()

    def test_range_is_left_closed_right_open_and_conflicts_are_returned(self):
        response = self.client.get(
            "/api/timeline",
            params={
                "start": "2026-09-10T10:00:00+00:00",
                "end": "2026-10-01T00:00:00+00:00",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual([item["id"] for item in data["items"]], [self.first_id, self.second_id])
        self.assertEqual(data["items"][0]["conflict_node_ids"], [self.second_id])
        self.assertIn("冲突", data["items"][0]["alert_types"])

    def test_status_update_removes_conflict_from_both_views(self):
        updated = self.client.patch(
            f"/api/timeline/{self.first_id}/status", json={"status": "已完成"}
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["alert_types"], [])

        remaining = self.client.get(
            "/api/timeline", params={"status": "待处理"}
        ).json()
        second = next(item for item in remaining["items"] if item["id"] == self.second_id)
        self.assertNotIn("冲突", second["alert_types"])
        self.assertEqual(second["conflict_node_ids"], [])

    def test_rejects_invalid_or_naive_range(self):
        self.assertEqual(
            self.client.get(
                "/api/timeline",
                params={
                    "start": "2026-09-11T00:00:00+00:00",
                    "end": "2026-09-10T00:00:00+00:00",
                },
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.get(
                "/api/timeline", params={"start": "2026-09-10T00:00:00"}
            ).status_code,
            422,
        )


if __name__ == "__main__":
    unittest.main()
