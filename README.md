# 职航 CareerPilot

职航 CareerPilot 是面向秋招、春招等校园招聘场景的个人求职决策工作台。它把投递记录、招聘节点和岗位面经集中到一个本地应用中，帮助你决定“现在该处理什么、下一步准备什么”。

CareerPilot 不自动投递，也不代替用户做求职决策；它优先使用用户保存的 JD、简历和面经，公开网页检索只是可选补充。

## 能做什么

- **求职总览**：维护公司、岗位和投递台账，查看阶段分布、临期节点、逾期节点和时间冲突。
- **智能录入**：粘贴邮件、短信或通知文本，让模型提取公司、岗位、笔试/面试节点和时间；确认后再写入投递和时间线。
- **面经工作台**：按公司与岗位保存文字和截图面经，跨轮次生成考察方向、核心问题和准备重点。
- **岗位问答**：基于当前岗位的 JD、面经、简历、时间线和历史问答进行有来源的只读检索与回答。
- **备战分析**：上传 PDF/DOCX 简历，结合岗位资料生成匹配总结、差距和准备行动。
- **每日简报**：汇总当天需要处理的求职节点，并在配置公开检索后发现新的相关面经来源。

模型由用户在“模型设置”页配置，支持 OpenAI、Anthropic、DeepSeek 和 Qwen 等 Provider。AnySearch 是可选的公开检索服务；没有它时，本地资料相关功能仍可使用。

## 运行方式

### Windows 桌面包

普通使用者优先从 [Releases 页面](https://github.com/zhangwx777/careerpilot/releases/latest) 下载 `CareerPilot-portable.zip`：解压后双击 `CareerPilot.exe`。也可以运行 `CareerPilotSetup.exe` 安装到当前用户目录。桌面包内置前端、后端、数据库运行时和启动器；使用前仍需在本机启动 Redis（`127.0.0.1:6379`）。首次进入后，在“模型设置”页填写 API Key、Base URL 和默认模型。

桌面包数据保存在当前 Windows 用户目录。不要把用户数据目录或 `.env` 提交到 Git。

### 从源码运行

开发机需要：

- Windows、Git
- Python 3.12
- Node.js（含 Corepack）和 pnpm
- PostgreSQL 18
- Redis（默认 `127.0.0.1:6379`）

```powershell
git clone https://github.com/zhangwx777/careerpilot.git
cd careerpilot

Copy-Item .env.example .env
# 编辑 .env，填写 PostgreSQL 连接和可选 ANYSEARCH_API_KEY

cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

cd ..\frontend
corepack pnpm install
```

在项目根目录运行一键启动脚本：

```powershell
cd C:\careerpilot
.\start.bat
```

脚本会检查 Redis、初始化数据库、启动 API、Celery worker 和 Vite，并在端口被占用时选择相邻可用端口。终端会打印实际访问地址；按 `Ctrl+C` 停止本次启动的服务。

需要分别启动服务时，参见 [开发文档](docs/development.md)。部署、数据迁移和故障排查参见 [运维文档](docs/operations.md)。

## 验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider

cd ..\frontend
corepack pnpm test
corepack pnpm build
```

连接 PostgreSQL 的集成测试需要设置独立的 `TEST_DATABASE_URL`；未设置时相关测试会跳过，跳过不代表通过。

## 文档入口

- [产品需求与范围](docs/PRD.md)
- [系统架构](docs/architecture.md)
- [开发手册](docs/development.md)
- [部署与运维](docs/operations.md)
- [当前路线图](docs/roadmap.md)

编码 Agent 的工作规则位于 [CLAUDE.md](CLAUDE.md)。历史计划、交接记录和早期 Agent 设计讨论位于 [docs/archive](docs/archive/)；归档内容不作为当前实现规范。

## 技术栈概览

React、Vite、TypeScript、FastAPI、Python 3.12、SQLAlchemy、PostgreSQL、Redis、Celery、LangGraph、LiteLLM 和 Electron。稳定架构与组件边界见 [系统架构](docs/architecture.md)。
