# 部署与运维

本文档面向运行、打包和迁移 CareerPilot 的人员。产品使用入口见 [`README.md`](../README.md)，内部架构见 [`architecture.md`](architecture.md)。

## Windows 桌面包

- `CareerPilotSetup.exe`：标准向导式安装器，免管理员安装到当前用户目录，创建桌面/开始菜单快捷方式并提供卸载入口。
- `CareerPilot-portable.zip`：绿色版，解压到有写入权限的目录后运行 `CareerPilot.exe`。

桌面包包含前端、后端、PostgreSQL、随包任务队列运行时、.NET Runtime 和 Electron 启动器；用户不需要另装 Python、Node.js、pnpm、PostgreSQL、Redis、Docker 或 .NET。桌面启动器只管理安装包自己的 PostgreSQL、任务队列、API 和 worker，不读取开发机服务，也不调用开发环境的 Docker Compose。

### 构建与客户端更新

首次构建或修改桌面运行时依赖时，运行完整构建：

```powershell
.\packaging\build.ps1
```

前端、后端或 Electron 代码更新时，在已有完整构建 payload 的机器上运行快速构建：

```powershell
.\packaging\build.ps1 -AppOnly
```

快速构建会重新生成前端、后端应用层和 Electron 壳，再生成 `dist\CareerPilotSetup.exe` 与 `dist\CareerPilot-portable.zip`；PostgreSQL、Garnet、.NET 和冻结的 Python 运行时沿用已有 payload。没有完整 payload 时先运行一次完整构建。修改上述运行时、桌面依赖或安装器配置后应运行完整构建。

桌面版本号取自 `desktop/package.json`。发布时使用对应的 `v<版本号>` GitHub Release 标签，并将安装器以精确文件名 `CareerPilotSetup.exe` 上传。客户端“模型设置 → 软件更新”会检查最新 Release；发现更高版本后可下载并启动该安装器。用户数据位于 `%LOCALAPPDATA%\CareerPilot`，由安装器更新时保留。

## Docker 本地开发与私有自托管

当前 Docker Compose 配置用于本地开发或受信任网络中的单用户自托管，需要 Docker Desktop 或 Docker Engine。它使用 Vite 开发服务器并挂载源码，不提供公网生产所需的反向代理、TLS 和多用户隔离。复制 `.env.example` 为 `.env` 后运行：

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Compose 固定提供以下服务：

1. `postgres`：持久化业务数据库；
2. `redis`：Celery broker 和 result backend；
3. `backend`：FastAPI API；
4. `worker`：Celery worker；
5. `frontend`：Vite 开发服务器。

前端地址为 `http://127.0.0.1:5173`，API 地址为 `http://127.0.0.1:8000`，Compose PostgreSQL 映射到宿主机 `127.0.0.1:5433`（容器内仍为 5432）。使用 `docker compose down` 停止容器；不带 `-v` 时保留 PostgreSQL 和 Redis 数据卷。

## 健康检查与队列

`GET /health` 返回数据库和队列状态。`db=false` 表示 PostgreSQL 不可用；`queue=false` 表示 Redis broker 或 worker 不可用。长任务依赖 Celery + Redis，队列不可用时应先恢复 Redis/worker，不能把任务当作已完成。

## 模型与密钥

Provider、API Key、Base URL 和默认模型只在“模型设置”页配置。API Key 使用 Fernet 加密写入本地数据库，接口只返回掩码；加密根密钥保存在 `.llm_config_secret`（桌面包位于用户数据目录）。

- `.env`、API Key、密码、`.llm_config_secret` 和 `.llm_config_legacy_keys/` 不提交 Git；仓库忽略规则覆盖这些本地密钥。
- 迁移数据库必须使用应用备份命令，以同时保存数据库、当前密钥和旧版 Fernet 密钥；不要只手工复制主密钥。
- 密钥丢失时设置页仍可打开，但已保存的 Provider 需要重新填写 API Key。
- Base URL 只允许 `http/https`，不要填写账号、密码、query、fragment 或完整 `/chat/completions` 路径。

## 公开检索联网工具

联网工具地址和工具名需要在“模型设置 → 公开检索”中配置。使用 AnySearch 时 API Key 可留空以使用匿名额度；配置的 Key 使用 Fernet 密文保存并只返回掩码。自定义 MCP 服务的认证要求由服务端决定。配置后面经分析和每日简报自动补充公开资料；未配置检索地址时进入明确的本地资料模式。当前适配器调用配置地址提供的 MCP 工具，并要求工具返回可解析的搜索结果。

## 数据备份与迁移

代码用 Git 同步，数据库不进 Git。换机或迁移请按[数据库迁移与备份操作说明](database-migrations-backups.md)运行应用备份命令。该命令同时备份数据库、当前密钥和历史密钥环；Docker 后端镜像内置与 PostgreSQL 18 兼容的客户端工具，桌面版使用安装包携带的 PostgreSQL 客户端。

不要只手动恢复 `database.dump` 并复制 `.llm_config_secret`：这会遗漏历史加密快照使用的旧密钥。备份目录包含明文密钥，应存放在私有且受保护的位置，不要提交 Git 或发到聊天记录。

## 常见故障

- **PostgreSQL 连接失败**：检查服务、数据库名、账号和 `.env`；先运行 `python -m scripts.init_db`。
- **Redis 不可用**：执行 `docker compose ps` 和 `docker compose logs redis worker`；不要在宿主机另起一套 Redis。
- **容器构建失败**：执行 `docker compose build --no-cache`，确认 Docker Desktop 有足够磁盘空间。
- **端口冲突**：释放宿主机的 5173、8000、5433 或 6379 后重新启动；Compose 不再顺延端口。
- **模型目录或 Agent 能力验证失败**：检查 Base URL 是否为 API 根路径；普通文本/JSON 模型可用于固定 Workflow，但未验证工具能力的模型不能用于岗位问答 Agent。
- **集成测试被跳过**：设置独立 `TEST_DATABASE_URL` 并初始化测试库；skip 不算通过。

## 运行限制

当前版本按本机单用户设计，不应把后端端口直接暴露到公网。多用户、云数据库、云端部署和外部通知不属于当前运行契约。
