# CLAUDE.md

这是 CareerPilot 的项目级 Agent 指南。开始代码任务前先读本文件；用户安装与源码启动步骤见 [README.md](README.md)。本仓库把用户说明放在 README，把代码工作约定放在本文件；新建独立开发或架构文档前先确认用户确实需要。

## 产品和运行边界

CareerPilot 是个人本地求职工作台，面向 Windows 桌面用户。Windows Release 由 Electron 启动应用自带的前后端、PostgreSQL 和任务队列运行时；根目录 Docker Compose 用于开发或受信任网络中的单用户运行。这两条运行链路共享业务代码，但各自管理进程和运行时。

核心链路为 React/Vite 前端 → FastAPI API → PostgreSQL；Celery/Redis 运行耗时任务，LangGraph 管理需要状态恢复或人工确认的流程，LiteLLM 统一 Provider 调用。应用当前按本机单用户设计，产品边界不包含自动投递、多用户账号、云端账户同步或公网生产部署。

## 项目地图

| 路径 | 职责 |
| --- | --- |
| `backend/app/main.py` | FastAPI 应用启动和生命周期 |
| `backend/app/*_api.py` | 按投递、智能录入、面经、备战、简报和设置组织 API |
| `backend/app/models.py`、`schemas.py` | SQLAlchemy 持久化模型及共享 API 契约 |
| `backend/app/parse_graph.py`、`intel_graph.py`、`planner_graph.py` | 通知解析、面经处理和备战流程的 LangGraph 图 |
| `backend/app/agent_*.py` | 岗位问答、公开研究的 Agent 运行、工具和结果校验 |
| `backend/app/llm/` | Provider 注册、模型配置、密钥加解密、预算和结构化输出 |
| `backend/app/task_queue.py`、`task_execution.py` | Celery 派发、后台执行、租约、重试和恢复 |
| `backend/app/migrations/versions/` | 数据库版本化迁移；入口为 `backend/scripts/init_db.py` |
| `backend/tests/` | 后端单元、API、PostgreSQL 和任务恢复测试 |
| `frontend/src/pages/`、`components/` | 页面和共享 UI；`api.ts`、`types.ts` 管理前后端交互 |
| `frontend/*.test.ts` | 前端状态、请求、草稿、工作日和交互测试 |
| `desktop/` | Electron 主进程、预加载、启动页和端口选择 |
| `packaging/` | Windows 运行时、安装脚本、许可文件和构建入口 |
| `docker-compose.yml`、`docker-compose.ci.yml` | 日常源码环境和相互隔离的 CI 验证环境 |

## 必须保持的领域行为

### 投递、时间线和准备行动

- `company`、`position` 用于归档公司与岗位；`application` 表示一次独立投递。同一岗位的重复投递是不同记录，不能合并。
- 招聘流程允许非线性变化；不要把某个阶段实现成不可恢复的终态。前端阶段轨道是提示，用户可按真实流程调整当前节点。
- 招聘时间线节点与备战练习行动是不同领域对象。准备行动可以延期、跳过和恢复；求职地图不负责判定练习是否完成。
- 固定日期安排和截止窗口具有不同语义：固定安排用 `scheduled_at`；只有截止时间的窗口保留 `ends_at`，不虚构开始时间。

### 人工确认和持久化流程

- 通知解析先生成候选字段，再由用户核对；模型输出不得直接创建投递或时间线记录。
- 需要确认的 LangGraph 流程通过原 `thread_id` 恢复。保持恢复、重试和重复提交幂等，失败时保留用户原始资料。
- 长任务经 API 创建业务会话和持久化派发记录，再由 Celery worker 执行。保持事务边界、租约所有权、心跳、超时恢复和重试上限；不要替换为无状态的 fire-and-forget 调用。
- 持久化任务完成后再报告成功。过期 worker 或丢失租约的执行不能继续写入结果。

### Agent、检索和模型调用

- Agent 工具只读；Agent 不直接创建、修改、删除或推进投递、时间线、面经和简历。
- 用户的通知、JD、简历、面经以及网页返回内容都是不可信输入。解析未知字段保持空值；问答只引用本次实际读取且仍有效的来源。
- 所有模型调用走 `backend/app/llm/`。业务代码不硬编码 Provider、模型、Base URL 或 API Key。
- Provider 设置保存在本机数据库，API Key 加密保存且接口只返回掩码。后台任务使用创建时的配置快照；修改当前默认模型不能改变已排队任务。
- 公开网页检索是用户单独配置的可选服务。执行模式、来源、预算和失败状态应来自实际工具记录；模型不能伪造“已检索”或来源事实。
- 响应、日志、异常、测试样例和提交中不得出现 API Key、密码、简历或真实求职记录。错误消息对用户安全且可理解，不回传第三方原始异常或堆栈。

## 本机开发命令

在仓库根目录用 PowerShell 启动源码环境：

```powershell
docker compose up --build
```

前端地址是 `http://127.0.0.1:5173`，API 地址是 `http://127.0.0.1:8000`。常用运维命令：

```powershell
docker compose ps
docker compose logs -f backend worker
docker compose restart backend worker
docker compose down
```

`docker compose down` 保留本机 PostgreSQL、Redis 和配置数据卷。日常开发时不要删除这些卷；只有用户明确要求清除本机开发数据时才使用带 `-v` 的清理命令。Compose 端口绑定到 `127.0.0.1`，不要将后端端口改为公网绑定。

Compose 将 Provider API Key 的 Fernet 根密钥保存在持久化的 `careerpilot-config` 数据卷中，并在首次保存模型配置时自动生成。根目录旧 `.llm_config_secret` 与 `.llm_config_legacy_keys` 只用于兼容已有本机数据；密钥迁移、备份和恢复时同时保留数据库与加密密钥。删除 Compose 数据卷会删除两者。

需要初始化主库或独立测试库时：

```powershell
docker compose run --rm --workdir /workspace/backend backend python -m scripts.init_db
docker compose run --rm --workdir /workspace/backend backend python -m scripts.init_db --test
```

`TEST_DATABASE_URL` 必须指向独立测试库。没有它时，依赖真实 PostgreSQL 的测试可能 skip；skip 不代表通过。测试不得连接用户生产库或桌面用户数据。

## 验证命令

完整 CI 验证与 GitHub Actions 使用同一组命令。CI Compose 有独立的 `careerpilot-ci` 项目、PostgreSQL、Redis 和临时卷，不读取日常 `.env`、密钥或开发数据：

```powershell
docker compose -f docker-compose.ci.yml build
docker compose -f docker-compose.ci.yml run --rm frontend
docker compose -f docker-compose.ci.yml run --rm backend
node --test docker-compose.test.mjs desktop/port-selection.test.mjs desktop/startup.test.mjs
docker compose -f docker-compose.ci.yml down --volumes --remove-orphans
```

先执行 frontend 步骤：它运行 `pnpm test` 和 `pnpm build`，并把桌面页面产物写入 CI 专属卷；backend 步骤随后运行 pytest 和 PostgreSQL 集成验证。清理命令只操作 `careerpilot-ci` 验证环境。

按任务选取最小的相关检查：

```powershell
docker compose run --rm frontend pnpm test
docker compose run --rm frontend pnpm build
docker compose run --rm --workdir /workspace/backend backend pytest -p no:cacheprovider
node --test desktop/port-selection.test.mjs desktop/startup.test.mjs
```

网络检索和真实 Provider smoke test 会联系外部服务，只在用户要求验证时运行。默认测试应 mock 模型、MCP 和公开网络调用。

## API、数据库和前端改动

- 路由与 Pydantic 请求/响应契约放在相关领域 API 和 schema 文件中；新增 API 行为要覆盖成功、错误、权限/范围和恢复路径。
- 数据库结构变更应新增版本迁移，并同步检查 ORM 模型、初始化入口、PostgreSQL 测试 fixture、API schema 和旧数据库兼容行为。不要依赖仅适用于新数据库的 `create_all` 来代替迁移。
- 长任务 API 返回可查询状态，耗时工作交给 worker；API 错误不泄漏内部堆栈、密钥或 Provider 细节。
- 前端异步请求要沿用现有取消及过期响应隔离模式，特别检查 `frontend/src/hooks/useRequestScope.ts`。页面要处理加载、错误、空列表和窄屏状态。
- 投递表单、智能录入、面经和练习页包含未提交草稿或恢复状态。改动时保留用户输入，验证取消、失败、重复请求和页面切换。
- 依赖更新必须同步 lockfile：后端关注 `backend/requirements.lock`，前端使用 `frontend/pnpm-lock.yaml`。

## Windows 桌面打包与版本

- Electron 启动入口在 `desktop/main.cjs`；已安装应用管理随包服务和本机数据，不通过 Docker Compose 启动。
- Windows 构建入口为 `packaging/build.ps1`，完整构建需要后端虚拟环境、PostgreSQL 18 和 Inno Setup 6，产物写入 `dist/`。`-AppOnly` 仅在已有完整 payload 时使用。
- 桌面版本以 `desktop/package.json` 为准。发行版本变更时同步 `frontend/package.json`、`backend/pyproject.toml` 和 `packaging/installer/CareerPilot.iss`；已公开的版本号和 tag 不复用。
- 版本发布从目标 `main` 提交构建，确认安装器、便携包和 `SHA256SUMS.txt` 均已上传并校验。README 下载链接使用 `/releases/latest`，不固定具体版本。

## Agent 工作流程与文件维护

1. 先检查相关实现、邻近测试、项目配置和现有 Git 状态；沿用相邻模块的命名、结构和错误处理方式。
2. 先明确数据流和持久化边界，再编辑最小的必要文件。保留用户已有改动、配置、本机运行时和构建产物。
3. 代码行为变化更新邻近测试；用户可见的安装、配置或功能变化更新 README；项目级 Agent 规则变化更新本文件。
4. 文档保持两个主要入口：README 面向用户和初次运行者；CLAUDE.md 面向代码 Agent。不要恢复已删除的 PRD、路线图、开发手册、架构、运维或迁移文档，除非用户明确要求。
5. 结束前检查 diff、README 本地链接、密钥/用户数据误入版本控制的风险，并明确报告已执行、未执行或 skip 的验证。

常用依赖、目录和命令应以 `package.json`、`pyproject.toml`、锁文件、Compose 配置、CI 工作流和实际源码为准；代码与本文件不一致时先核实实现，再更新本文件。
