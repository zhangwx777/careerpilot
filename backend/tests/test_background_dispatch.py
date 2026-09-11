import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi import BackgroundTasks

from app.models import ParseSession
from app.phase3_api import create_parse_session
from app.phase3_schemas import ParseSessionCreate


class FakeParseDb:
    def __init__(self):
        self.item = None

    def add(self, item):
        self.item = item
        item.id = 1
        item.thread_id = uuid4()
        item.created_at = datetime.now(timezone.utc)

    def commit(self):
        pass

    def refresh(self, _item):
        pass

    def expire_all(self):
        pass

    def get(self, model, _id):
        return self.item if model is ParseSession else None

    def scalars(self, _statement):
        return type("Rows", (), {"all": lambda _self: []})()


class BackgroundDispatchTestCase(unittest.TestCase):
    @patch("app.phase3_api.start_parse_graph")
    def test_parse_create_queues_work_and_returns_pending_status(self, start_graph):
        tasks = BackgroundTasks()

        created = create_parse_session(
            ParseSessionCreate(raw_text="请参加笔试"), tasks, FakeParseDb()
        )

        self.assertEqual(created.status, "解析中")
        start_graph.assert_not_called()
        self.assertEqual(len(tasks.tasks), 1)


if __name__ == "__main__":
    unittest.main()
