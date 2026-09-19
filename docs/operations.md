# 部署与运维

本文档面向运行、打包和迁移 CareerPilot 的人员。产品使用入口见 [`README.md`](../README.md)，内部架构见 [`architecture.md`](architecture.md)。

## Windows 桌面包

- `CareerPilot-portable.zip`：解压到有写入权限的目录后运行 `CareerPilot.exe`。
- `CareerPilotSetup.exe`：免管理员安装到当前用户目录，并创建快捷方式。

桌面包包含前端、后端、数据库运行时和 Electron 启动器；用户不需要另装 Python、Node.js、pnpm 或 PostgreSQL。桌面启动器仍会使用本机 `127.0.0.1:6379` 的 Redis，并启动 CareerPilot worker。

## 源码部署

源码运行需要 Python 3.12、Node.js/Corepack、PostgreSQL 18 和 Redis。复制 `.env.example` 为 `.env`，填写 `DATABASE_URL`，然后安装后端和前端依赖。根目录 `start.bat` 会：

1. 检查 Redis；
2. 初始化数据库；
3. 选择可用后端和前端端口；
4. 启动 API、Celery worker 和 Vite；
5. 打印实际 URL 并尝试打开浏览器。

端口被占用时脚本会顺延，不要手动结束同端口上的其他应用。按 `Ctrl+C` 停止本次启动的服务。

## 健康检查与队列

`GET /health` 返回数据库和队列状态。`db=false` 表示 PostgreSQL 不可用；`queue=false` 表示 Redis broker 或 worker 不可用。长任务依赖 Celery + Redis，队列不可用时应先恢复 Redis/worker，不能把任务当作已完成。

## 模型与密钥

Provider、API Key、Base URL 和默认模型只在“模型设置”页配置。API Key 使用 Fernet 加密写入本地数据库，接口只返回掩码；加密根密钥保存在 `.llm_config_secret`（桌面包位于用户数据目录）。

- `.env`、API Key、密码和 `.llm_config_secret` 不提交 Git。
- 迁移数据库时必须同时安全备份对应的 `.llm_config_secret`。
- 密钥丢失时设置页仍可打开，但已保存的 Provider 需要重新填写 API Key。
- Base URL 只允许 `http/https`，不要填写账号、密码、query、fragment 或完整 `/chat/completions` 路径。

## AnySearch

`ANYSEARCH_API_KEY` 是可选配置。没有 Key 时，本地 JD、简历、面经和历史问答仍可用；联网补充、岗位问答公开检索和每日简报公开来源会跳过或记录搜索失败，回答不能声称已完成公开搜索。

## 数据备份与迁移

代码用 Git 同步，数据库不进 Git。换机或迁移时：

使用 PostgreSQL 客户端工具导出和恢复数据库（将示例中的连接参数替换为实际主机、端口、数据库、用户和密码）：

```powershell
pg_dump --host 127.0.0.1 --port 5432 --username qiuzhao_app --format=custom --file careerpilot.dump qiuzhao
pg_restore --host 127.0.0.1 --port 5432 --username qiuzhao_app --dbname qiuzhao careerpilot.dump
```

在目标机器重新创建 `.env`，恢复数据库后再恢复同一数据目录中的 `.llm_config_secret`。不要把密钥写进仓库或聊天记录。

## 常见故障

- **PostgreSQL 连接失败**：检查服务、数据库名、账号和 `.env`；先运行 `python -m scripts.init_db`。
- **Redis 不可用**：确认 `127.0.0.1:6379` 监听，并重新启动 worker；`start.bat` 会直接提示而不会静默降级。
- **前端依赖不完整**：关闭占用 `frontend/node_modules` 的 Node 进程后运行 `corepack pnpm install --force`。
- **端口冲突**：使用脚本打印的实际端口；手动 Vite 端口变化时同步 `VITE_API_TARGET`。
- **模型目录或 Agent 能力验证失败**：检查 Base URL 是否为 API 根路径；普通文本/JSON 模型可用于固定 Workflow，但未验证工具能力的模型不能用于岗位问答 Agent。
- **集成测试被跳过**：设置独立 `TEST_DATABASE_URL` 并初始化测试库；skip 不算通过。

## 运行限制

当前版本按本机单用户设计，不应把后端端口直接暴露到公网。多用户、云数据库、云端部署和外部通知不属于当前运行契约。
