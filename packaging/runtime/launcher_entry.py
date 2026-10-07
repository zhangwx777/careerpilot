"""被 PyInstaller 冻结的瘦启动器。

它本身不含业务逻辑：
1. 依赖清单式 import —— 让 PyInstaller 静态分析收集到全部第三方依赖，
   冻结进 _internal，归入运行时层（几乎不变）。
2. 把应用层的 backend 源码目录加入 sys.path。
3. 以 __main__ 方式运行外部的 packaged_server.py（权威入口，明文可更新）。

改业务源码时只替换应用层 .py，无需重新 freeze 本启动器。
"""

# --- 1. 依赖清单：仅为让 PyInstaller 发现依赖，运行时的实际入口在 packaged_server ---
import fastapi  # noqa: F401
import fastapi.staticfiles  # noqa: F401
import uvicorn  # noqa: F401
import sqlalchemy  # noqa: F401
import sqlalchemy.dialects.postgresql  # noqa: F401
import psycopg  # noqa: F401
import pydantic  # noqa: F401
import pydantic_settings  # noqa: F401
import litellm  # noqa: F401
import langgraph  # noqa: F401
import langgraph.checkpoint.postgres  # noqa: F401
import langchain_mcp_adapters  # noqa: F401
import pypdf  # noqa: F401
import docx  # noqa: F401
import multipart  # noqa: F401
import cryptography  # noqa: F401
import tiktoken  # noqa: F401
import tiktoken_ext  # noqa: F401
import starlette  # noqa: F401
import anyio  # noqa: F401
import httpx  # noqa: F401
import celery  # noqa: F401
import redis  # noqa: F401

# --- 2 & 3. 定位应用层源码并运行外部入口 ---
import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    app_root = os.environ.get("CAREERPILOT_APP_ROOT")
    if not app_root and getattr(sys, "frozen", False):
        install_root = Path(sys.executable).resolve().parents[2]
        packaged_root = install_root / "app"
        if (packaged_root / "backend" / "packaged_server.py").is_file():
            app_root = str(packaged_root)
    if not app_root:
        raise SystemExit("未设置 CAREERPILOT_APP_ROOT，无法定位后端源码。")
    os.environ.setdefault("CAREERPILOT_APP_ROOT", app_root)
    backend_src = Path(app_root) / "backend"
    if not (backend_src / "packaged_server.py").is_file():
        raise SystemExit(f"未找到后端源码：{backend_src}")
    sys.path.insert(0, str(backend_src))
    if sys.argv[1:2] and sys.argv[1] in {"backup", "restore"}:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data and not os.environ.get("CAREERPILOT_DATA_DIR"):
            os.environ["CAREERPILOT_DATA_DIR"] = str(
                Path(local_app_data) / "CareerPilot"
            )
        runpy.run_module("scripts.backup_database", run_name="__main__")
        return
    if os.environ.get("CAREERPILOT_WORKER") == "1":
        from app.task_queue import celery_app

        celery_app.worker_main(["worker", "--loglevel=INFO", "--pool=solo"])
        return
    runpy.run_module("packaged_server", run_name="__main__")


if __name__ == "__main__":
    main()
