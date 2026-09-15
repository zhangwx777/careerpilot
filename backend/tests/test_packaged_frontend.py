import unittest

from fastapi.testclient import TestClient

from app.main import app


class PackagedFrontendTest(unittest.TestCase):
    def test_root_serves_built_frontend(self):
        with TestClient(app) as client:
            response = client.get("/")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("<div id=\"root\"></div>", response.text)


if __name__ == "__main__":
    unittest.main()
