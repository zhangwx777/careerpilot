# 开发手册

本文档面向贡献者。产品范围看 [`PRD.md`](PRD.md)，稳定架构看 [`architecture.md`](architecture.md)，部署和故障排查看 [`operations.md`](operations.md)。

## 运行时与依赖

| 层 | 版本/选型 |
|---|---|
| 后端 | Python 3.12、FastAPI、SQLAlchemy 2、Uvicorn |
| 前端 | React、Vite、TypeScript、Radix Themes |
| 数据库 | PostgreSQL 18 |
| 异步任务 | Celery + Redis |
| LLM/流程 | LiteLLM、LangGraph、可配置联网工具（可选） |
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

## 启动环境

项目有三个运行场景，依赖边界如下：

| 场景 | 入口 | 需要安装的环境 | 数据与用途 |
|---|---|---|---|
| Windows 用户使用 | `CareerPilotSetup.exe` 或便携包 | 无需安装开发工具 | 桌面包管理自己的数据库和任务队列，数据保存在 `%LOCALAPPDATA%\CareerPilot` |
| 本地开发或私有自托管 | 根目录 `docker-compose.yml` | Git、Docker Desktop（或 Docker Engine 与 Compose 插件）、`.env` | 启动前端、API、worker、PostgreSQL 和 Redis；数据库与 Redis 使用持久化卷 |
| 自动化验证 | `docker-compose.ci.yml` | Docker 与 Compose 插件 | 使用独立数据库、Redis、临时前端构建卷和无宿主机端口的测试网络 |

当前 Compose 是单用户源码环境：前端运行 Vite 开发服务器，后端和前端挂载工作区源码，服务端口只绑定到本机回环地址。它适合本机开发或受信任网络中的个人使用，不提供公网生产所需的反向代理、TLS 和多用户隔离。

本地开发只需 Git、Docker Desktop 和项目配置文件：

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Compose 统一启动 frontend、backend、worker、PostgreSQL 和 Redis。启动完成后访问 `http://127.0.0.1:5173`。backend 和 worker 共同挂载根目录 `.llm_config_secret`，确保数据库中的模型配置可以被后台任务解密。

`docker compose build` 只构建镜像，不会启动服务；日常开发用 `docker compose up --build` 一步完成构建和启动。需要后台运行时加 `-d`，查看日志用 `docker compose logs -f`。`docker compose down` 保留 PostgreSQL 和 Redis 数据卷；不要对日常开发环境执行 `down --volumes`，除非确实要删除本地数据库和队列数据。

## 桌面包构建

构建机需要项目后端虚拟环境、PostgreSQL 18 和 Inno Setup 6。首次准备后端虚拟环境时，在 `backend` 目录安装桌面打包依赖：

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m pip install -e ".[desktop-build]"
Pop-Location
```

然后运行：

```powershell
.\packaging\build.ps1
```

脚本会下载固定版本的任务队列运行时和 .NET Runtime 并内置到桌面包，输出 `dist\CareerPilotSetup.exe` 和 `dist\CareerPilot-portable.zip`。这些运行时只属于桌面包，开发环境不使用它们；终端用户不需要安装 Python、Node.js、pnpm、PostgreSQL、Redis、Docker 或 .NET。

## 版本与发布

桌面发行版本以 `desktop/package.json` 的 `version` 为准，`packaging/build.ps1` 会将该值传给 Inno Setup。修改发行版本时，同步更新 `frontend/package.json`、`backend/pyproject.toml` 和 `packaging/installer/CareerPilot.iss` 的默认版本。Git tag 和 GitHub Release 使用 `v<version>` 格式（例如 `v0.1.4`）。发布后确认 Release 已公开，并且 `CareerPilotSetup.exe` 与 `CareerPilot-portable.zip` 两个附件均已上传。README 下载入口应指向 GitHub 的 `/releases/latest`，避免把版本号写死。

## 配置

`.env.example` 是运行配置的来源，当前包括：

- `DATABASE_URL`：开发数据库；
- `TEST_DATABASE_URL`：独立测试数据库；
- 联网工具地址、工具名和 Key：通过“模型设置 → 公开检索”保存，不写入 `.env`；
- `CELERY_BROKER_URL`、`CELERY_RESULT_BACKEND`、任务超时和重试参数。

模型 Provider、API Key、Base URL 和默认模型只通过网页设置保存到数据库，不写入 `.env`。

## 自动化验证

完整验证使用 `docker-compose.ci.yml`，不读取开发 `.env`、密钥或数据卷，不对宿主机开放端口，并使用新建的测试数据库和 Redis：

```powershell
docker compose -f docker-compose.ci.yml build
docker compose -f docker-compose.ci.yml run --rm frontend
docker compose -f docker-compose.ci.yml run --rm backend
node --test docker-compose.test.mjs desktop/port-selection.test.mjs desktop/startup.test.mjs
docker compose -f docker-compose.ci.yml down --volumes --remove-orphans
```

先运行前端以便将真实构建产物写入测试专用卷；后端随后只读挂载该卷，验证桌面包静态页面。完整后端验证会检查 JUnit 结果，存在 skipped 或未收集到测试时返回失败。GitHub Actions 使用相同入口。

验证 Compose 与日常 Compose 共用 `careerpilot-backend:local` 和 `careerpilot-frontend:local` 两个镜像标签及同一组 Dockerfile；测试配置只改变命令、环境变量、网络和卷，不会另建测试专用镜像。清理命令会删除测试容器和临时卷，并保留这两个可供日常开发复用的应用镜像。请勿把该清理命令改为删除日常开发 Compose 的数据卷。

容器后端通过 `requirements.lock` 锁定 Python 3.12/Linux 的运行与测试依赖；桌面构建仍使用 Windows 环境。更新依赖时，在 Python 3.12 容器中用 `pip-tools==7.6.2` 执行 `pip-compile --extra=test --strip-extras --no-header --no-emit-index-url --output-file=requirements.lock pyproject.toml`，再完成完整验证。不要仅修改版本下限而遗漏锁文件。

前端使用 pnpm 12 的多文档锁文件：第一段记录包管理器，第二段记录应用依赖，必须保留完整文件。安装继续使用 `pnpm install --frozen-lockfile`。

## API 开发约定

- 完整请求、响应和路由以运行中的 `/docs` 与 `/openapi.json` 为准；手写文档只保留领域入口和行为说明。
- 请求/响应 Pydantic 模型与领域模块相邻，新增接口必须补契约和测试。
- 长任务由 API 创建会话后提交 Celery；接口应返回可轮询的状态，而不是阻塞请求线程。
- API 错误使用安全、稳定的错误信息；不返回密钥、原始 Provider 异常或内部堆栈。
- 涉及人工确认的流程必须保持原 `thread_id` 恢复、互斥终态和幂等写入。
- 投递状态接口允许按实际招聘流程在任意 `ApplicationStatus` 之间调整；“offer”和“挂”不再作为不可恢复的终态，前端阶段轨道只做流程参考，当前状态由推进控件负责展示。

## 数据模型变更

更新 `models.py` 后同步检查 `scripts/init_db.py`、PostgreSQL 初始化、测试 fixture、API schema 和文档。需要新增索引、约束或兼容字段时，先在架构文档记录不变量，再补真实数据库测试。

## 前端开发

页面位于 `frontend/src/pages/`，共享布局和组件位于 `components/`。异步轮询必须支持取消和过期响应保护；加载、错误、空状态、键盘焦点和窄屏布局需与功能一起验证。

求职总览采用紧凑 Dashboard：顶部为半栏投递分布和关注指标，下方为统一的“接下来”时间流。学习行动与时间线节点使用不同标记，完整日程仍由求职地图负责；首页不展示学习行动的长文本详情。

新增功能完成标准：受影响后端测试通过，前端 `pnpm test` 和 `pnpm build` 通过，运行时 OpenAPI 与 README/开发文档没有冲突。
