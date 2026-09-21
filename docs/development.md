# 开发手册

本文档面向贡献者。产品范围看 [`PRD.md`](PRD.md)，稳定架构看 [`architecture.md`](architecture.md)，部署和故障排查看 [`operations.md`](operations.md)。

## 运行时与依赖

| 层 | 版本/选型 |
|---|---|
| 后端 | Python 3.12、FastAPI、SQLAlchemy 2、Uvicorn |
| 前端 | React、Vite、TypeScript、Radix Themes |
| 数据库 | PostgreSQL 18 |
| 异步任务 | Celery + Redis |
| LLM/流程 | LiteLLM、LangGraph、AnySearch（可选） |
| 桌面 | Electron/Windows 打包脚本 |

## 目录职责

- `backend/app/main.py`：FastAPI 入口和路由装配。
- `backend/app/models.py`、`schemas.py`：持久化模型和 API 契约。
- `backend/app/api.py`、`phase3_api.py`、`intel_api.py`、`planner_api.py`、`briefing_api.py`：按领域提供接口。
- `backend/app/*_graph.py`：需要恢复、循环或人工中断的 LangGraph 流程。
- `backend/app/agent_*.py`：岗位问答和公开研究的只读 Agent。
- `backend/app/llm/`：Provider 注册、配置快照、提示词和结构化输出。
- `backend/scripts/`：数据库初始化和 smoke test。
- `frontend/src/`：页面、组件、API 客户端和前端类型。
- `packaging/`、`desktop/`：桌面打包和安装器。

## Docker 开发环境

开发机只需要 Git、Docker Desktop 和项目配置文件：

```powershell
Copy-Item .env.example .env
# 按需填写 ANYSEARCH_API_KEY
.\start.bat
```

根目录 `start.bat` 只负责调用 Docker Compose；Compose 统一启动 frontend、backend、worker、PostgreSQL 和 Redis。源码目录挂载到容器内，前端支持热更新，后端代码修改后重新执行 `docker compose up --build`。停止服务使用 `docker compose down`，数据卷默认保留。脚本在启动 Compose 前后台轮询前端就绪，`http://127.0.0.1:5173` 可访问后自动打开浏览器。

## 桌面包构建

构建机需要项目后端虚拟环境、PostgreSQL 18 和 Inno Setup 6。运行：

```powershell
.\packaging\build.ps1
```

脚本会下载固定版本的任务队列运行时和 .NET Runtime 并内置到桌面包，输出 `dist\CareerPilotSetup.exe` 和 `dist\CareerPilot-portable.zip`。这些运行时只属于桌面包，开发环境不使用它们；终端用户不需要安装 Python、Node.js、pnpm、PostgreSQL、Redis、Docker 或 .NET。

## 配置

`.env.example` 是运行配置的来源，当前包括：

- `DATABASE_URL`：开发数据库；
- `TEST_DATABASE_URL`：独立测试数据库；
- `ANYSEARCH_API_KEY`：可选公开检索；
- `CELERY_BROKER_URL`、`CELERY_RESULT_BACKEND`、任务超时和重试参数。

模型 Provider、API Key、Base URL 和默认模型只通过网页设置保存到数据库，不写入 `.env`。

## 测试与构建

```powershell
docker compose run --rm backend python -m scripts.init_db --test
docker compose run --rm backend pytest -p no:cacheprovider
docker compose run --rm frontend pnpm test
docker compose run --rm frontend pnpm build
```

没有 `TEST_DATABASE_URL` 时，依赖 PostgreSQL/LangGraph 的测试会跳过。跳过不等于通过；需要在独立测试库上运行并确认 0 skipped。默认测试应 mock LLM、MCP 和外网调用。

## API 开发约定

- 完整请求、响应和路由以运行中的 `/docs` 与 `/openapi.json` 为准；手写文档只保留领域入口和行为说明。
- 请求/响应 Pydantic 模型与领域模块相邻，新增接口必须补契约和测试。
- 长任务由 API 创建会话后提交 Celery；接口应返回可轮询的状态，而不是阻塞请求线程。
- API 错误使用安全、稳定的错误信息；不返回密钥、原始 Provider 异常或内部堆栈。
- 涉及人工确认的流程必须保持原 `thread_id` 恢复、互斥终态和幂等写入。

## 数据模型变更

更新 `models.py` 后同步检查 `scripts/init_db.py`、PostgreSQL 初始化、测试 fixture、API schema 和文档。需要新增索引、约束或兼容字段时，先在架构文档记录不变量，再补真实数据库测试。

## 前端开发

页面位于 `frontend/src/pages/`，共享布局和组件位于 `components/`。异步轮询必须支持取消和过期响应保护；加载、错误、空状态、键盘焦点和窄屏布局需与功能一起验证。

新增功能完成标准：受影响后端测试通过，前端 `pnpm test` 和 `pnpm build` 通过，运行时 OpenAPI 与 README/开发文档没有冲突。
