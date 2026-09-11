import os
import unittest

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.intel_api import discard_intel, list_intel
from app.models import Application, Company, IntelSession, InterviewIntel, Position
from scripts.init_db import initialize_database


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "需要配置 TEST_DATABASE_URL")
class IntelLibraryApiTestCase(unittest.TestCase):
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
            db.execute(delete(IntelSession))
            db.execute(delete(InterviewIntel))
            db.execute(delete(Application))
            db.execute(delete(Position))
            db.execute(delete(Company))
            ctrip = Application(position=Position(company=Company(name="携程"), title="Agent开发工程师"), status="已投递")
            byte = Application(position=Position(company=Company(name="字节跳动"), title="后端工程师"), status="已投递")
            db.add_all([ctrip, byte])
            db.flush()
            self.ctrip_id = ctrip.id
            db.add_all([
                InterviewIntel(application_id=ctrip.id, payload={}, sources=[]),
                InterviewIntel(application_id=ctrip.id, payload={}, sources=[]),
                InterviewIntel(application_id=byte.id, payload={}, sources=[]),
            ])

    def test_pending_session_can_be_discarded_without_writing_material(self):
        with self.sessions.begin() as db:
            session = IntelSession(application_id=self.ctrip_id, provider="qwen", status="待裁决")
            db.add(session)
            db.flush()
            session_id = session.id
        with self.sessions() as db:
            discarded = discard_intel(session_id, db)
        self.assertEqual(discarded.status, "已丢弃")
        with self.sessions() as db:
            self.assertEqual(db.query(InterviewIntel).count(), 3)

    def test_library_lists_all_records_and_filters_by_job(self):
        with self.sessions() as db:
            all_records = list_intel(db, page=1, page_size=100, q=None)
            ctrip_records = list_intel(db, page=1, page_size=100, q="携程")

        self.assertEqual(all_records.total, 3)
        self.assertEqual(ctrip_records.total, 2)
        self.assertEqual(
            {item.application.position.company.name for item in ctrip_records.items},
            {"携程"},
        )


if __name__ == "__main__":
    unittest.main()
