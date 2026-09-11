import os
import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.daily_briefing import run_daily_briefing
from app.models import Application, Company, DailyBriefing, PlannerSession, Position, PreparationTask, ReportedSource, TimelineNode
from scripts.init_db import initialize_database

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

@unittest.skipUnless(TEST_DATABASE_URL, "需要配置 TEST_DATABASE_URL，每日巡检测试不允许跳过")
class DailyBriefingTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database(TEST_DATABASE_URL)
        cls.engine = create_engine(TEST_DATABASE_URL)
        cls.sessions = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.sessions.begin() as db:
            db.execute(delete(ReportedSource))
            db.execute(delete(DailyBriefing))
            db.execute(delete(PreparationTask))
            db.execute(delete(PlannerSession))
            db.execute(delete(TimelineNode))
            db.execute(delete(Application))
            db.execute(delete(Position))
            db.execute(delete(Company))
            application = Application(position=Position(company=Company(name="测试公司"), title="后端"), status="一面")
            db.add(application)
            db.flush()
            self.application_id = application.id

    def test_same_day_is_idempotent_and_urls_are_reported_once(self):
        calls = []

        def search_fn(query):
            calls.append(query)
            return [{"title": "后端面经", "url": "https://example.test/interview"}]

        now = datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc)
        with self.sessions() as db:
            first = run_daily_briefing(db, now, search_fn)
            second = run_daily_briefing(db, now, search_fn)
            self.assertEqual(first.id, second.id)
            self.assertEqual(len(first.payload["new_sources"]), 1)
            self.assertEqual(len(calls), 1)
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(ReportedSource)).all()), 1)

    def test_previous_day_url_is_not_reported_again(self):
        def search_fn(_query):
            return [{"title": "后端面经", "url": "https://example.test/interview"}]

        with self.sessions() as db:
            first = run_daily_briefing(db, datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc), search_fn)
            second = run_daily_briefing(db, datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc), search_fn)
            self.assertEqual(len(first.payload["new_sources"]), 1)
            self.assertEqual(second.payload["new_sources"], [])
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(ReportedSource)).all()), 1)
