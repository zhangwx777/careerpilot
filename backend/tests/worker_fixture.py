"""Explicitly loaded only by the real-worker integration test; models stay offline."""

import os
import time

from app import planner_api
from app.planner_schemas import PlannerDraft


def extract_plan(*args, **kwargs):
    time.sleep(float(os.environ.get("CAREERPILOT_TEST_WORK_SECONDS", "0.5")))
    return PlannerDraft(summary="真实 worker 完成离线测试")


planner_api.extract_plan = extract_plan
planner_api.config_from_snapshot = lambda *args, **kwargs: {}
