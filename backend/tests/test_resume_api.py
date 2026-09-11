import io
import unittest

from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import ResumeProfile

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine, tables=[ResumeProfile.__table__])


class ResumeApiTestCase(unittest.TestCase):
    def setUp(self):
        self.session = Session(engine)

        def override_db():
            yield self.session

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.close()
        with engine.begin() as connection:
            connection.execute(delete(ResumeProfile))

    def test_upload_extracts_and_persists_filename(self):
        document = Document()
        document.add_paragraph("数据分析实习生")
        output = io.BytesIO()
        document.save(output)
        response = self.client.post(
            "/api/resume-profile/upload",
            files={"file": ("resume.docx", output.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["file_name"], "resume.docx")
        self.assertIn("数据分析实习生", response.json()["resume_text"])


if __name__ == "__main__":
    unittest.main()
