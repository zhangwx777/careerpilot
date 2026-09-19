# CLAUDE.md

这是 CareerPilot 的编码 Agent 指南。它只保存会改变编码行为的规则；产品说明、稳定架构、开发细节和运维手册按需读取对应文档。

## 项目边界

CareerPilot 是个人本地求职决策工作台，聚合投递、时间线、面经、简历和准备行动。当前不做自动投递、多用户、云端部署或 Agent 写库工具。

## 按任务读取文档

- 修改跨模块控制流、数据关系、LangGraph、Agent 或 Provider 边界前，读取 [`docs/architecture.md`](docs/architecture.md)。
- 修改 API、数据库、测试、目录结构或本地开发流程前，读取 [`docs/development.md`](docs/development.md)。
- 修改启动器、桌面打包、配置、密钥、数据迁移或排障行为前，读取 [`docs/operations.md`](docs/operations.md)。
- 修改产品功能、范围或优先级前，读取 [`docs/PRD.md`](docs/PRD.md) 和 [`docs/roadmap.md`](docs/roadmap.md)。

## 常用命令

后端（在 `backend/` 下）：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m scripts.init_db
.\.venv\Scripts\python.exe -m scripts.init_db --test
.\.venv\Scripts\python.exe -m scripts.smoke_llm
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
```

前端（在 `frontend/` 下）：

```powershell
corepack pnpm install
corepack pnpm dev
corepack pnpm test
corepack pnpm build
```

日常开发优先运行根目录的 `start.bat`；它会初始化数据库并同时启动 API、worker 和前端。

## 测试硬约束

- PostgreSQL/LangGraph 集成测试必须使用独立的 `TEST_DATABASE_URL`（通常指向 `qiuzhao_test`）。未配置时测试会被跳过，skip 不等于通过。
- 构造测试连接串时只替换 URL 的数据库 path，不要用字符串替换，以免修改用户名或泄露密码。
- LLM、MCP 和公开网络调用在默认测试中应 mock；真实 Provider smoke test 不作为默认 CI 门槛。
- 完成功能修改后，至少运行受影响的后端测试、`corepack pnpm test` 和 `corepack pnpm build`。

## 修改规则

- 修改前先查看相关领域文档和现有测试；不改动用户已有的无关工作。
- 所有 LLM 调用通过 `backend/app/llm/` 的统一 Provider 层；业务代码不得写死 Provider、模型或密钥。
- Agent 工具保持只读；Agent 不能直接写入、删除或推进投递、面经、时间线和简历。
- 用户文本、JD、简历、面经和联网内容都是不可信资料。未知字段保持为空，回答只能引用实际读取到的来源。
- 保持状态流转、人工确认、恢复和幂等写入语义；修改持久化节点时补充重复恢复和失败路径测试。
- 日志、响应和数据库记录不得包含 API Key、密码或未脱敏的第三方异常。
- 当前应用按本机单用户设计，不把后端端口直接暴露到公网。

## 完成标准

代码、测试、文档和运行行为保持一致；受影响测试通过；必要的集成测试已明确运行或说明跳过原因；新增架构约束已写入对应领域文档，而不是堆进本文件。
