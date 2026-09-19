import unittest
from unittest.mock import Mock, patch

from app.task_queue import TaskQueueUnavailable, enqueue


class TaskQueueTestCase(unittest.TestCase):
    def test_broker_errors_are_safe_and_actionable(self):
        task = Mock()
        task.apply_async.side_effect = OSError("connection refused")

        with patch("app.task_queue.settings.celery_task_always_eager", False):
            with self.assertRaisesRegex(TaskQueueUnavailable, "启动 Redis"):
                enqueue(task, 1)

    def test_eager_task_errors_are_not_misclassified_as_broker_errors(self):
        task = Mock()
        task.apply_async.side_effect = ValueError("task body failed")

        with patch("app.task_queue.settings.celery_task_always_eager", True):
            with self.assertRaisesRegex(ValueError, "task body failed"):
                enqueue(task, 1)


if __name__ == "__main__":
    unittest.main()
