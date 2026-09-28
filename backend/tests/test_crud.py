import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Application, Company, PlannerSession, Position, PreparationTask, TimelineNode

test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(
    test_engine,
    tables=[
        Company.__table__,
        Position.__table__,
        Application.__table__,
        PlannerSession.__table__,
        PreparationTask.__table__,
        TimelineNode.__table__,
    ],
)
with test_engine.connect() as connection:
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")


class CrudApiTestCase(unittest.TestCase):
    def setUp(self):
        self.session = Session(test_engine)

        def override_db():
            yield self.session

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.close()
        with test_engine.begin() as connection:
            connection.execute(delete(PreparationTask))
            connection.execute(delete(PlannerSession))
            connection.execute(delete(TimelineNode))
            connection.execute(delete(Application))
            connection.execute(delete(Position))
            connection.execute(delete(Company))

    def create_company(self, name="测试公司", industry="互联网"):
        response = self.client.post(
            "/api/companies", json={"name": name, "industry": industry}
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_position(self, company_id, title="后端工程师"):
        response = self.client.post(
            "/api/positions",
            json={"company_id": company_id, "title": title, "jd_text": "Python"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_application(self, status="已投递"):
        response = self.client.post(
            "/api/applications",
            json={
                "company_name": "测试公司",
                "position_title": "后端工程师",
                "status": status,
                "note": "重点跟进",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_company_crud_search_and_pagination(self):
        self.assertEqual(
            self.client.post("/api/companies", json={"name": " "}).status_code,
            422,
        )
        company = self.create_company()
        self.create_company("另一家公司")
        self.create_company("第三家公司")

        duplicate = self.client.post(
            "/api/companies", json={"name": company["name"]}
        )
        self.assertEqual(duplicate.status_code, 409)

        page = self.client.get("/api/companies", params={"page_size": 2}).json()
        self.assertEqual(page["total"], 3)
        self.assertEqual(len(page["items"]), 2)

        searched = self.client.get("/api/companies", params={"q": "测试"}).json()
        self.assertEqual([item["id"] for item in searched["items"]], [company["id"]])

        updated = self.client.patch(
            f"/api/companies/{company['id']}", json={"industry": "软件"}
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["industry"], "软件")

        deleted = self.client.delete(f"/api/companies/{company['id']}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(
            self.client.get(f"/api/companies/{company['id']}").status_code, 404
        )

    def test_position_crud_and_filters(self):
        company = self.create_company()
        missing_company = self.client.post(
            "/api/positions", json={"company_id": 999999, "title": "测试岗位"}
        )
        self.assertEqual(missing_company.status_code, 404)

        position = self.create_position(company["id"])
        filtered = self.client.get(
            "/api/positions", params={"company_id": company["id"], "q": "后端"}
        ).json()
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["company"]["name"], company["name"])

        updated = self.client.patch(
            f"/api/positions/{position['id']}", json={"title": "平台工程师"}
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["title"], "平台工程师")

        deleted = self.client.delete(f"/api/positions/{position['id']}")
        self.assertEqual(deleted.status_code, 204)

    def test_application_crud_filters_and_status_flow(self):
        company = self.create_company()
        position = self.create_position(company["id"])
        application = self.create_application(status="一面")

        filtered = self.client.get(
            "/api/applications",
            params={"q": "重点", "status": "一面", "company_id": company["id"]},
        ).json()
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["position"]["title"], position["title"])

        updated = self.client.patch(
            f"/api/applications/{application['id']}", json={"note": "等待结果"}
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["note"], "等待结果")

        skipped = self.client.patch(
            f"/api/applications/{application['id']}/status", json={"status": "三面"}
        )
        self.assertEqual(skipped.status_code, 200)
        self.assertEqual(skipped.json()["status"], "三面")

        backward = self.client.patch(
            f"/api/applications/{application['id']}/status", json={"status": "二面"}
        )
        self.assertEqual(backward.status_code, 200)

        offered = self.client.patch(
            f"/api/applications/{application['id']}/status", json={"status": "offer"}
        )
        self.assertEqual(offered.status_code, 200)
        terminal = self.client.patch(
            f"/api/applications/{application['id']}/status", json={"status": "挂"}
        )
        self.assertEqual(terminal.status_code, 200)

        restored = self.client.patch(
            f"/api/applications/{application['id']}/status", json={"status": "AI面"}
        )
        self.assertEqual(restored.status_code, 200)

        deleted = self.client.delete(f"/api/applications/{application['id']}")
        self.assertEqual(deleted.status_code, 204)

    def test_application_edit_can_correct_status_across_stages(self):
        self.create_company()
        self.create_position(
            self.client.get("/api/companies").json()["items"][0]["id"]
        )
        application = self.create_application(status="三面")

        # 台账的 /status 端点允许按实际流程调整到任意阶段
        backward = self.client.patch(
            f"/api/applications/{application['id']}/status", json={"status": "一面"}
        )
        self.assertEqual(backward.status_code, 200)
        self.assertEqual(backward.json()["status"], "一面")

        # 编辑接口允许把点错的阶段直接修正为更早的阶段
        corrected = self.client.patch(
            f"/api/applications/{application['id']}", json={"status": "一面"}
        )
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertEqual(corrected.json()["status"], "一面")

    def test_application_flow_supports_assessment_and_ai_interview(self):
        self.create_company()
        application = self.create_application()
        assessment = self.client.patch(
            f"/api/applications/{application['id']}/status", json={"status": "测评"}
        )
        self.assertEqual(assessment.status_code, 200, assessment.text)
        ai_interview = self.client.patch(
            f"/api/applications/{application['id']}/status", json={"status": "AI面"}
        )
        self.assertEqual(ai_interview.status_code, 200, ai_interview.text)

    def test_dashboard_counts_all_applications_as_applied(self):
        for application_status in ("已投递", "测评", "笔试", "一面", "挂"):
            self.create_application(status=application_status)

        response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 200, response.text)
        counts = {item["status"]: item["count"] for item in response.json()["pipeline"]}

        self.assertEqual(counts["已投递"], 5)
        self.assertEqual(counts["测评"], 1)
        self.assertEqual(counts["笔试"], 1)
        self.assertEqual(counts["一面"], 1)
        self.assertEqual(counts["挂"], 1)

    def test_application_create_materializes_job_and_keeps_reapplications(self):
        payload = {
            "company_name": "海投公司",
            "position_title": "Agent工程师",
            "jd_text": "负责 Agent 开发",
            "note": "官网投递",
        }
        first = self.client.post("/api/applications", json=payload)
        second = self.client.post("/api/applications", json=payload)

        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertNotEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(first.json()["position_id"], second.json()["position_id"])
        self.assertEqual(first.json()["position"]["company"]["name"], "海投公司")

    def test_company_delete_cascades(self):
        company = self.create_company()
        position = self.create_position(company["id"])
        application = self.create_application()

        self.assertEqual(
            self.client.delete(f"/api/companies/{company['id']}").status_code, 204
        )
        self.assertEqual(
            self.client.get(f"/api/positions/{position['id']}").status_code, 404
        )
        self.assertEqual(
            self.client.get(f"/api/applications/{application['id']}").status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()
