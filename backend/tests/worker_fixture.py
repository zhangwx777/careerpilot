"""Explicitly loaded only by the real-worker integration test; models stay offline."""

import os
import time

from app import planner_api
from app.planner_schemas import PlannerDraft, PreparationAnswer


def extract_plan(*args, **kwargs):
    time.sleep(float(os.environ.get("CAREERPILOT_TEST_WORK_SECONDS", "0.5")))
    return PlannerDraft(summary="真实 worker 完成离线测试")


planner_api.extract_plan = extract_plan
planner_api.config_from_snapshot = lambda *args, **kwargs: {}


def practice_answer(*args, **kwargs):
    time.sleep(float(os.environ.get("CAREERPILOT_TEST_WORK_SECONDS", "0.5")))
    return PreparationAnswer(question="测试题", core_answer="测试答案", personalized_answer="测试定制回答")


planner_api.generate_preparation_answer = practice_answer
