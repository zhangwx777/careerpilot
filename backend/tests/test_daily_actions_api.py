import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    Application,
    Company,
    PlannerSession,
    Position,
    PreparationTask,
    TimelineNode,
    TaskDispatch,
)
from app.planner_api import materialize_planner_actions
from app.planner_schemas import PreparationAnswer, PreparationFeedback


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)


class DailyActionsApiTestCase(unittest.TestCase):
    def setUp(self):
        self.session = Session(engine)
        application = Application(
            position=Position(
                company=Company(name="行动公司"),
                title="后端工程师",
                jd_text="熟悉 Python",
            ),
            status="已投递",
        )
        self.session.add(application)
        self.session.flush()
        self.application_id = application.id

        def override_db():
            yield self.session

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        self.dispatch_patch = patch("app.task_execution.publish_dispatch")
        self.dispatch_patch.start()
        self.sessions_patch = patch("app.task_execution.SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
        self.sessions_patch.start()

    def tearDown(self):
        self.dispatch_patch.stop()
        self.sessions_patch.stop()
        self.client.close()
        app.dependency_overrides.clear()
        self.session.rollback()
        for model in (TaskDispatch, TimelineNode, PreparationTask, PlannerSession, Application, Position, Company):
            self.session.execute(delete(model))
        self.session.commit()
        self.session.close()

    def _planner_session(self):
        session = PlannerSession(
            application_id=self.application_id,
            provider="openai",
            resume_snapshot="Python 项目经验",
            jd_snapshot="熟悉 Python",
            intel_snapshot=[],
            available_windows=[],
            draft_payload={
                "summary": "准备重点",
                "strengths": [],
                "gaps": [],
                "actions": [
                    {
                        "title": "准备项目深挖",
                        "detail": "整理项目中的故障排查案例",
                        "priority": 1,
                        "source_ids": ["manual-1"],
                    },
                    {
                        "title": "复习数据库",
                        "detail": "复习索引和事务",
                        "priority": 3,
                        "source_ids": [],
                    },
                ],
            },
            status="已完成",
        )
        self.session.add(session)
        self.session.flush()
        return session

    def drain_practice(self):
        from app.task_execution import execute_job
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with patch("app.planner_api.SessionLocal", factory):
            self.session.expire_all()
            for job in self.session.query(TaskDispatch).filter_by(status="pending").all():
                execute_job(job.id)
            self.session.expire_all()

    def test_completed_plan_materializes_actions_idempotently(self):
        planner_session = self._planner_session()

        self.assertEqual(materialize_planner_actions(self.session, planner_session), 2)
        self.session.flush()
        self.assertEqual(materialize_planner_actions(self.session, planner_session), 0)
        self.session.commit()

        tasks = self.session.query(PreparationTask).order_by(PreparationTask.action_index).all()
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0].priority, 1)
        self.assertEqual(tasks[0].category, "简历内容")
        self.assertEqual(tasks[1].category, "八股")
        self.assertIsNone(tasks[0].estimated_minutes)
        self.assertIsNone(tasks[0].scheduled_at)

    def test_materialize_actions_endpoint_is_a_safe_recovery_operation(self):
        planner_session = self._planner_session()
        self.session.commit()

        first = self.client.post(f"/api/planner-sessions/{planner_session.id}/materialize-actions", json={"action_indexes": [0, 1]})
        second = self.client.post(f"/api/planner-sessions/{planner_session.id}/materialize-actions", json={"action_indexes": [0, 1]})

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(self.session.query(PreparationTask).count(), 2)

    def test_materialize_actions_only_creates_selected_indexes(self):
        planner_session = self._planner_session()
        self.session.commit()

        response = self.client.post(
            f"/api/planner-sessions/{planner_session.id}/materialize-actions",
            json={"action_indexes": [1]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        tasks = self.session.query(PreparationTask).all()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].action_index, 1)

    def test_unanswered_task_can_be_removed_and_selected_again(self):
        planner_session = self._planner_session()
        materialize_planner_actions(self.session, planner_session, [0])
        self.session.commit()
        task_id = self.session.query(PreparationTask).first().id

        removed = self.client.delete(f"/api/preparation-tasks/{task_id}")
        self.assertEqual(removed.status_code, 204, removed.text)
        self.assertEqual(self.session.query(PreparationTask).count(), 0)

        restored = self.client.post(
            f"/api/planner-sessions/{planner_session.id}/materialize-actions",
            json={"action_indexes": [0]},
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(self.session.query(PreparationTask).count(), 1)

    def test_answer_and_review_are_saved_on_task(self):
        planner_session = self._planner_session()
        materialize_planner_actions(self.session, planner_session, [0])
        self.session.commit()
        task_id = self.session.query(PreparationTask).first().id
        answer = PreparationAnswer(
            question="如何排查线上故障？",
            core_answer="先确认影响范围，再定位指标和日志。",
            personalized_answer="结合你的项目经历说明排查过程。",
            follow_ups=["如何验证修复结果？"],
        )
        feedback = PreparationFeedback(
            strengths=["结构清晰"], gaps=["缺少结果"], rewrite="补充影响范围和结果。"
        )
        with patch("app.planner_api.config_from_snapshot", return_value={}), patch(
            "app.planner_api.generate_preparation_answer", return_value=answer
        ), patch("app.planner_api.run_review_preparation_answer", return_value=feedback):
            generated = self.client.post(f"/api/preparation-tasks/{task_id}/answer")
            self.assertEqual(generated.json()["practice_status"], "answer")
            self.drain_practice()
            generated = self.client.get(f"/api/preparation-tasks/{task_id}")
            reviewed = self.client.post(
                f"/api/preparation-tasks/{task_id}/review",
                json={"user_answer": "我会先看错误率和日志，再缩小范围。"},
            )

            self.assertEqual(reviewed.json()["practice_status"], "review")
            self.drain_practice()
            reviewed = self.client.get(f"/api/preparation-tasks/{task_id}")

        self.assertEqual(generated.status_code, 200, generated.text)
        self.assertEqual(generated.json()["answer_payload"]["question"], "如何排查线上故障？")
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["status"], "已完成")
        self.assertEqual(reviewed.json()["feedback_payload"]["rewrite"], "补充影响范围和结果。")

    def test_direct_completion_requires_review_and_task_detail_is_readable(self):
        planner_session = self._planner_session()
        materialize_planner_actions(self.session, planner_session, [0])
        self.session.commit()
        task_id = self.session.query(PreparationTask).first().id

        detail = self.client.get(f"/api/preparation-tasks/{task_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["id"], task_id)

        completed = self.client.patch(
            f"/api/preparation-tasks/{task_id}/status",
            json={"status": "已完成"},
        )
        self.assertEqual(completed.status_code, 409, completed.text)
        self.assertEqual(self.session.get(PreparationTask, task_id).status, "待处理")

    def test_dashboard_returns_pending_actions_and_status_update_removes_completed(self):
        planner_session = self._planner_session()
        materialize_planner_actions(self.session, planner_session)
        for task in self.session.query(PreparationTask).all():
            task.planned_date = date.today()
        self.session.commit()

        response = self.client.get("/api/dashboard")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["feed"]
        preparation_items = [item for item in payload if item["kind"] == "preparation"]
        self.assertEqual(len(preparation_items), 2)
        self.assertEqual(preparation_items[0]["title"], "准备项目深挖")
        task_id = preparation_items[0]["task_id"]
        self.session.get(PreparationTask, task_id).feedback_payload = {"rewrite": "已点评"}
        self.session.commit()

        updated = self.client.patch(
            f"/api/preparation-tasks/{task_id}/status",
            json={"status": "已完成"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["status"], "已完成")
        remaining = self.client.get("/api/dashboard").json()["feed"]
        self.assertEqual(len([item for item in remaining if item["kind"] == "preparation"]), 1)

    def test_dashboard_includes_all_pending_plan_actions(self):
        planner_session = self._planner_session()
        materialize_planner_actions(self.session, planner_session)
        self.session.commit()

        payload = self.client.get("/api/dashboard").json()["feed"]

        preparation_items = [item for item in payload if item["kind"] == "preparation"]
        self.assertEqual([item["title"] for item in preparation_items], ["准备项目深挖", "复习数据库"])

    def test_dashboard_does_not_truncate_pending_plan_actions(self):
        planner_session = self._planner_session()
        materialize_planner_actions(self.session, planner_session)
        for index in range(2, 10):
            self.session.add(
                PreparationTask(
                    planner_session_id=planner_session.id,
                    application_id=self.application_id,
                    title=f"准备行动 {index}",
                    detail="补充练习内容",
                    category="八股",
                    source_ids=[],
                    evidence=[],
                    priority=3,
                    action_index=index,
                    status="待处理",
                )
            )
        self.session.commit()

        payload = self.client.get("/api/dashboard").json()["feed"]

        preparation_items = [item for item in payload if item["kind"] == "preparation"]
        self.assertEqual(len(preparation_items), 10)

    def test_dashboard_remove_option_removes_pending_task(self):
        planner_session = self._planner_session()
        materialize_planner_actions(self.session, planner_session, [0])
        self.session.commit()
        task_id = self.session.query(PreparationTask).first().id

        removed = self.client.delete(f"/api/preparation-tasks/{task_id}")

        self.assertEqual(removed.status_code, 204, removed.text)
        self.assertNotIn(task_id, [item["task_id"] for item in self.client.get("/api/dashboard").json()["feed"]])

    def test_dashboard_feed_combines_preparation_and_timeline_items(self):
        planner_session = self._planner_session()
        materialize_planner_actions(self.session, planner_session, [0])
        self.session.add(
            TimelineNode(
                application_id=self.application_id,
                node_type="一面",
                scheduled_at=datetime.now() + timedelta(days=1),
                title="技术一面",
                status="待处理",
            )
        )
        self.session.commit()

        payload = self.client.get("/api/dashboard").json()

        self.assertNotIn("today_actions", payload)
        self.assertEqual({item["kind"] for item in payload["feed"]}, {"preparation", "timeline"})

    def test_deferred_action_is_hidden_until_due_unless_explicitly_included(self):
        planner_session = self._planner_session()
        materialize_planner_actions(self.session, planner_session)
        for task in self.session.query(PreparationTask).all():
            task.planned_date = date.today()
        self.session.commit()
        task_id = self.session.query(PreparationTask).first().id
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

        response = self.client.patch(
            f"/api/preparation-tasks/{task_id}/status",
            json={"status": "待处理", "deferred_until": future},
        )
        self.assertEqual(response.status_code, 200, response.text)
        visible = self.client.get("/api/preparation-tasks?status=待处理").json()
        self.assertEqual(visible["total"], 1)
        all_tasks = self.client.get("/api/preparation-tasks?status=待处理&include_deferred=true").json()
        self.assertEqual(all_tasks["total"], 2)

    def test_session_filter_does_not_drop_tasks_behind_another_plan(self):
        first = self._planner_session()
        second = self._planner_session()
        materialize_planner_actions(self.session, first)
        materialize_planner_actions(self.session, second, [0])
        self.session.commit()
        result = self.client.get(f"/api/preparation-tasks?planner_session_id={second.id}&include_deferred=true").json()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["planner_session_id"], second.id)

    def test_timeline_cannot_bypass_review_and_skip_synchronizes_task(self):
        planner = self._planner_session()
        node = TimelineNode(application_id=self.application_id, node_type="其他", status="待处理")
        self.session.add(node)
        self.session.flush()
        task = PreparationTask(planner_session_id=planner.id, application_id=self.application_id, title="练习", timeline_node_id=node.id)
        self.session.add(task)
        self.session.commit()
        self.assertEqual(self.client.patch(f"/api/timeline/{node.id}/status", json={"status": "已完成"}).status_code, 409)
        skipped = self.client.patch(f"/api/timeline/{node.id}/status", json={"status": "已取消"})
        self.assertEqual(skipped.status_code, 200, skipped.text)
        self.assertEqual(self.client.get(f"/api/preparation-tasks/{task.id}").json()["status"], "已跳过")

    def test_practice_failure_keeps_answer_and_allows_durable_retry(self):
        planner = self._planner_session()
        materialize_planner_actions(self.session, planner, [0])
        self.session.commit()
        task_id = self.session.query(PreparationTask).first().id
        queued = self.client.post(f"/api/preparation-tasks/{task_id}/answer")
        self.assertEqual(queued.json()["practice_status"], "answer")
        self.assertEqual(self.client.post(f"/api/preparation-tasks/{task_id}/answer").status_code, 409)
        with patch("app.planner_api.config_from_snapshot", side_effect=RuntimeError("sk-secret-do-not-save")):
            self.drain_practice()
        failed = self.client.get(f"/api/preparation-tasks/{task_id}").json()
        self.assertEqual(failed["practice_status"], "failed")
        self.assertNotIn("sk-secret", failed["practice_error"])
        self.assertEqual(self.client.post(f"/api/preparation-tasks/{task_id}/answer").status_code, 200)


if __name__ == "__main__":
    unittest.main()
