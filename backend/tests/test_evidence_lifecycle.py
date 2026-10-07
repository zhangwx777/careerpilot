import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.evidence import valid_source_ids
from app.intel_insight import rebuild_position_insight
from app.intel_schemas import IntelInsight
from app.models import Application, Company, InterviewIntel, Position, TaskDispatch
from app.llm.config_store import LlmConfigError
from fastapi import BackgroundTasks


class EvidenceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions.begin() as db:
            company = Company(name="来源测试")
            application = Application(position=Position(company=company, title="后端"), status="已投递")
            related = Application(position=Position(company=company, title="算法"), status="已投递")
            db.add_all([application, related])
            db.flush()
            current_material = InterviewIntel(application_id=application.id, sources=[{"id": "manual", "title": "资料", "text": "项目经验"}], payload={})
            related_material = InterviewIntel(application_id=related.id, sources=[{"id": "manual", "title": "关联资料", "text": "算法经验"}], payload={})
            db.add_all([current_material, related_material])
            db.flush()
            self.position_id = application.position_id
            self.material_id = current_material.id
            self.current_source = f"material-{current_material.id}:manual"
            self.related_source = f"material-{related_material.id}:manual"

    def tearDown(self):
        self.engine.dispose()

    def test_validity_uses_material_liveness_instead_of_current_position(self):
        with self.sessions() as db:
            self.assertEqual(valid_source_ids(db, [self.current_source, self.related_source, "material-999:missing"]), {self.current_source, self.related_source})
            db.delete(db.get(InterviewIntel, self.material_id))
            db.commit()
            self.assertEqual(valid_source_ids(db, [self.current_source, self.related_source]), {self.related_source})

    def test_deleted_material_cannot_be_restored_by_an_old_insight_result(self):
        def delete_material(*args, **kwargs):
            with self.sessions.begin() as db:
                db.delete(db.get(InterviewIntel, self.material_id))
                position = db.get(Position, self.position_id)
                position.intel_revision += 1
                position.intel_insight = {"status": "暂无资料"}
            return IntelInsight(status="已生成")
        with patch("app.intel_insight._generate", side_effect=delete_material):
            rebuild_position_insight(self.position_id, "qwen", self.sessions, llm_config={})
        with self.sessions() as db:
            self.assertEqual(db.get(Position, self.position_id).intel_insight["status"], "暂无资料")

    def test_old_generation_failure_does_not_overwrite_a_newer_result(self):
        def newer_result_then_fail(*args, **kwargs):
            with self.sessions.begin() as db:
                position = db.get(Position, self.position_id)
                position.intel_revision += 1
                position.intel_insight = {"status": "已生成"}
            raise RuntimeError("old generation failed")
        with patch("app.intel_insight._generate", side_effect=newer_result_then_fail):
            rebuild_position_insight(self.position_id, "qwen", self.sessions, llm_config={})
        with self.sessions() as db:
            self.assertEqual(db.get(Position, self.position_id).intel_insight["status"], "已生成")

    def test_superseded_dispatch_does_not_call_the_model(self):
        with self.sessions.begin() as db:
            db.get(Position, self.position_id).intel_revision = 2
        with patch("app.intel_insight._generate") as generate:
            rebuild_position_insight(self.position_id, "qwen", self.sessions, llm_config={}, expected_revision=1)
        generate.assert_not_called()

    def test_delete_without_model_configuration_keeps_material_deletion_and_no_unfrozen_job(self):
        from app.intel_api import delete_intel_material
        with self.sessions.begin() as db:
            old = db.get(InterviewIntel, self.material_id)
            db.add(InterviewIntel(application_id=old.application_id, provider="qwen", payload={}, sources=[]))
        with self.sessions() as db, patch("app.intel_api.snapshot_for", side_effect=LlmConfigError("模型未配置")):
            delete_intel_material(self.material_id, BackgroundTasks(), db)
        with self.sessions() as db:
            self.assertIsNone(db.get(InterviewIntel, self.material_id))
            self.assertEqual(db.get(Position, self.position_id).intel_insight["status"], "失败")
            self.assertEqual(db.scalars(select(TaskDispatch)).all(), [])
