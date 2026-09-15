import os

import uvicorn

from app.db import Base, engine
import app.models
from app.main import app


if __name__ == "__main__":
    Base.metadata.create_all(engine)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("QIUZHAO_BACKEND_PORT", "8000")),
    )
