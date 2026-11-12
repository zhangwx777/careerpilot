import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Application, Company, DailyBriefing, PlannerSession, Position, PreparationTask, TimelineNode


class StageHistoryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        with self.sessions.begin() as db:
            position = Position(company=Company(name="进度测试公司"), title="工程师")
            a = Application(position=position, status="已投递")
            other = Application(position=position, status="已投递")
            db.add_all([a, other])
            db.flush()
            node = TimelineNode(application_id=a.id, node_type="笔试", status="已完成", time_mode="固定时间", scheduled_at=datetime.now(timezone.utc))
            db.add(node)
            db.flush()
            self.application_id, self.other_id, self.node_id = a.id, other.id, node.id
        def override():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app)
        self.addCleanup(app.dependency_overrides.clear)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.client.close)

    def preview(self):
        response = self.client.get("/api/applications/progress-check")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["items"]

    def history(self):
        return self.client.get(f"/api/applications/{self.application_id}/stage-history").json()["items"]

    def test_preview_is_read_only_apply_is_scoped_and_idempotent(self):
        items = self.preview()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["suggested_status"], "笔试")
        self.assertEqual(items[0]["evidence"][0]["id"], self.node_id)
        self.assertEqual(self.history(), [])
        request = {"items": [{"application_id": self.application_id, "token": items[0]["token"]}]}
        for _ in range(2):
            response = self.client.post("/api/applications/progress-check/apply", json=request)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["applied_ids"], [self.application_id])
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.history()[0]["source"], "历史校正")
        with self.sessions() as db:
            self.assertEqual(db.get(Application, self.other_id).status, "已投递")

    def test_stale_node_or_stage_rejects_apply(self):
        for change in ("node", "application"):
            with self.subTest(change=change):
                item = self.preview()[0]
                with self.sessions.begin() as db:
                    if change == "node":
                        db.get(TimelineNode, self.node_id).status = "已取消"
                    else:
                        db.get(Application, self.application_id).status = "测评"
                response = self.client.post("/api/applications/progress-check/apply", json={"items": [{"application_id": self.application_id, "token": item["token"]}]})
                self.assertEqual(response.status_code, 409, response.text)
                with self.sessions.begin() as db:
                    db.get(TimelineNode, self.node_id).status = "已完成"
                    db.get(Application, self.application_id).status = "已投递"
        self.assertEqual(self.history(), [])

    def test_manual_update_and_timeline_changes_are_logged_without_duplicates(self):
        for endpoint in (f"/api/applications/{self.application_id}", f"/api/applications/{self.application_id}/status"):
            response = self.client.patch(endpoint, json={"status": "测评"})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.history()), 1)
        response = self.client.patch(f"/api/timeline/{self.node_id}/status", json={"status": "已完成"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.history()), 2)
        self.assertEqual(self.history()[0]["to_status"], "笔试")
        self.assertEqual(self.history()[0]["source"], "日程更新")

    def test_terminal_or_cancelled_nodes_are_not_candidates(self):
        for status in ("offer", "挂", "三面"):
            with self.sessions.begin() as db:
                db.get(Application, self.application_id).status = status
            self.assertEqual(self.preview(), [])
        with self.sessions.begin() as db:
            db.get(Application, self.application_id).status = "已投递"
            db.get(TimelineNode, self.node_id).status = "已取消"
        self.assertEqual(self.preview(), [])

    def test_manual_stage_change_back_to_original_still_invalidates_preview(self):
        item = self.preview()[0]
        for status in ("测评", "已投递"):
            self.client.patch(f"/api/applications/{self.application_id}/status", json={"status": status})
        response = self.client.post("/api/applications/progress-check/apply", json={"items": [{"application_id": self.application_id, "token": item["token"]}]})
        self.assertEqual(response.status_code, 409, response.text)

    def test_cancel_and_restore_node_without_stage_change_invalidates_preview(self):
        with self.sessions.begin() as db:
            db.get(Application, self.application_id).status = "测评"
            db.get(TimelineNode, self.node_id).node_type = "测评"
            db.add(TimelineNode(application_id=self.application_id, node_type="笔试", status="已完成", time_mode="固定时间", scheduled_at=datetime.now(timezone.utc)))
        item = self.preview()[0]
        before = self.history()
        for status in ("已取消", "已完成"):
            response = self.client.patch(f"/api/timeline/{self.node_id}/status", json={"status": status})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.history(), before)
        response = self.client.post("/api/applications/progress-check/apply", json={"items": [{"application_id": self.application_id, "token": item["token"]}]})
        self.assertEqual(response.status_code, 409, response.text)

    def test_batch_locks_all_applications_before_reading_nodes(self):
        with self.sessions.begin() as db:
            db.add(TimelineNode(application_id=self.other_id, node_type="笔试", status="待处理", time_mode="固定时间", scheduled_at=datetime.now(timezone.utc)))
        items = self.preview()
        queries = []
        def observe(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.startswith("SELECT"):
                queries.append(statement)
        event.listen(self.engine, "before_cursor_execute", observe)
        try:
            response = self.client.post("/api/applications/progress-check/apply", json={"items": [{"application_id": item["application_id"], "token": item["token"]} for item in reversed(items)]})
        finally:
            event.remove(self.engine, "before_cursor_execute", observe)
        self.assertEqual(response.status_code, 200, response.text)
        first_node_read = next(index for index, query in enumerate(queries) if "FROM timeline_node" in query)
        application_reads = [query for query in queries[:first_node_read] if "FROM application " in query]
        self.assertEqual(len(application_reads), 2)

    def test_timeline_waiting_on_task_lock_refreshes_the_latest_node(self):
        from app.timeline import update_timeline_node

        with self.sessions.begin() as db:
            db.get(Application, self.application_id).status = "笔试"
            db.get(TimelineNode, self.node_id).status = "待处理"
            planner = PlannerSession(application_id=self.application_id, provider="qwen", resume_snapshot="", jd_snapshot="", intel_snapshot=[], available_windows=[], status="已完成")
            db.add(planner)
            db.flush()
            task = PreparationTask(application_id=self.application_id, planner_session_id=planner.id, title="练习", status="待处理", timeline_node_id=self.node_id)
            db.add(task)
            db.flush()
            task_id = task.id
        scalar = Session.scalar
        interleaved = False

        def wait_for_task(session, statement, *args, **kwargs):
            nonlocal interleaved
            if not interleaved and getattr(statement, "_for_update_arg", None) is not None and any(description.get("entity") is PreparationTask for description in getattr(statement, "column_descriptions", [])):
                interleaved = True
                # A preparation update commits while this request waits for its task lock.
                with self.sessions.begin() as concurrent:
                    concurrent.get(PreparationTask, task_id).status = "已跳过"
                    update_timeline_node(concurrent.get(TimelineNode, self.node_id), status="已取消")
            return scalar(session, statement, *args, **kwargs)

        with patch.object(Session, "scalar", wait_for_task):
            response = self.client.patch(f"/api/timeline/{self.node_id}/status", json={"status": "待处理"})
        self.assertTrue(interleaved)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "待处理")
        with self.sessions() as db:
            node = db.get(TimelineNode, self.node_id)
            self.assertEqual((node.status, node.revision), ("待处理", 2))
            self.assertEqual(db.get(PreparationTask, task_id).status, "待处理")

    def test_briefing_current_states_do_not_modify_historical_payload(self):
        payload = {"alerts": [{"timeline_node_id": self.node_id}, {"timeline_node_id": 99999}], "today_tasks": [{"task_id": 99999}]}
        with self.sessions.begin() as db:
            item = DailyBriefing(briefing_date=date(2026, 11, 12), payload=payload)
            db.add(item)
            db.flush()
            briefing_id = item.id
        for url in (f"/api/daily-briefings/{briefing_id}", "/api/daily-briefings"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json() if url.endswith(str(briefing_id)) else response.json()["items"][0]
            self.assertEqual(data["current_states"]["timeline"][str(self.node_id)], {"exists": True, "status": "已完成"})
            self.assertEqual(data["current_states"]["timeline"]["99999"], {"exists": False, "status": None})
            self.assertEqual(data["current_states"]["preparation"]["99999"]["exists"], False)
        with self.sessions() as db:
            self.assertEqual(db.get(DailyBriefing, briefing_id).payload, payload)
