import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Application, Company, Position

test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(
    test_engine,
    tables=[Company.__table__, Position.__table__, Application.__table__],
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

    def create_application(self, position_id, status="已投递"):
        response = self.client.post(
            "/api/applications",
            json={"position_id": position_id, "status": status, "note": "重点跟进"},
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
        application = self.create_application(position["id"], status="一面")

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
        self.assertEqual(backward.status_code, 409)

        offered = self.client.patch(
            f"/api/applications/{application['id']}/status", json={"status": "offer"}
        )
        self.assertEqual(offered.status_code, 200)
        terminal = self.client.patch(
            f"/api/applications/{application['id']}/status", json={"status": "挂"}
        )
        self.assertEqual(terminal.status_code, 409)

        deleted = self.client.delete(f"/api/applications/{application['id']}")
        self.assertEqual(deleted.status_code, 204)

    def test_company_delete_cascades(self):
        company = self.create_company()
        position = self.create_position(company["id"])
        application = self.create_application(position["id"])

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
