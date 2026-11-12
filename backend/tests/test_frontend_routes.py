import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_browser_refresh_serves_app_without_masking_missing_assets_or_api():
    from app.frontend_static import FrontendFiles
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, "index.html").write_text("<html>synthetic frontend</html>")
        app = FastAPI()
        app.mount("/", FrontendFiles(directory=directory, html=True))
        with TestClient(app) as client:
            assert client.get("/applications").text == "<html>synthetic frontend</html>"
            assert client.get("/practice/12").status_code == 200
            assert client.get("/api/missing").status_code == 404
            assert client.get("/assets/missing.js").status_code == 404
