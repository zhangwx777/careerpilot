import unittest

from pydantic import ValidationError

from app.phase3_schemas import ParseConfirmation


class ParseConfirmationTestCase(unittest.TestCase):
    def test_deadline_window_only_requires_deadline(self):
        confirmation = ParseConfirmation.model_validate(
            {
                "application_id": 1,
                "node_type": "网申截止",
                "time_mode": "截止窗口",
                "ends_at": "2026-09-28T23:59:00+08:00",
            }
        )

        self.assertIsNone(confirmation.scheduled_at)

    def test_fixed_time_still_requires_scheduled_at(self):
        with self.assertRaises(ValidationError):
            ParseConfirmation.model_validate(
                {
                    "application_id": 1,
                    "node_type": "笔试",
                    "time_mode": "固定时间",
                }
            )


if __name__ == "__main__":
    unittest.main()
