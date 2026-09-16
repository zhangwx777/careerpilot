import os

import uvicorn

from app.config import settings
from app.main import app
from scripts.init_db import initialize_database


if __name__ == "__main__":
    initialize_database(settings.database_url)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("CAREERPILOT_BACKEND_PORT", "8000")),
    )
