# 职航 CareerPilot

职航 CareerPilot 是面向秋招、春招等校园招聘场景的个人求职决策工作台。它把投递记录、招聘节点、岗位面经和备战练习集中到一个本地应用中，回答同一个问题：现在该处理什么，面试前该练什么。

CareerPilot 不自动投递，也不代替用户做求职决策；它优先使用用户保存的 JD、简历和面经，公开网页检索只是可选补充。数据保存在本机，模型使用你自己配置的 API Key。

## 能做什么

- **求职总览**：用投递分布、关注指标和“接下来”时间流，快速查看阶段进度、待练习行动、临期节点、逾期节点和时间冲突。
- **投递推进**：投递台账保留完整阶段节点，当前节点在“推进”下拉框中展示；不同公司的非线性流程可以自由调整到任意阶段。
- **智能录入**：粘贴邮件、短信或通知文本，让模型提取公司、岗位、笔试/面试节点和时间；确认后再写入投递和时间线。
- **面经工作台**：按公司与岗位保存文字和截图面经，跨轮次生成考察方向、核心问题和准备重点。
- **岗位问答**：基于当前岗位的 JD、面经、简历、时间线和历史问答进行有来源的只读检索与回答。
- **备战分析**：上传 PDF/DOCX 简历，结合岗位资料生成匹配总结、差距和准备行动；选中的行动进入独立练习页生成答案并提交自答点评。
- **求职地图**：按月查看完整的面试、笔试、测评和截止日期等求职节点，不承载学习行动完成逻辑。
- **每日简报**：汇总当天需要处理的求职节点，并在配置联网工具后发现新的相关面经来源。

模型由用户在“模型设置”页配置，支持 OpenAI、Anthropic、DeepSeek 和 Qwen 等 Provider；面经、备战、简报和图片识别可以分别指定模型，未指定的角色回退到全局默认。联网工具在“模型设置”中单独配置；没有它时，本地资料相关功能仍可使用。

## 运行方式

### Windows 桌面包

普通使用者从 [Releases 页面](https://github.com/zhangwx777/careerpilot/releases/latest) 下载 `CareerPilotSetup.exe`，按向导安装即可；安装器会创建桌面和开始菜单快捷方式，也可以在安装完成页直接启动。桌面包内置前端、后端、PostgreSQL、任务队列和所需运行时，不需要另外安装 Python、Node.js、pnpm、PostgreSQL、Redis 或 .NET。首次进入后，在“模型设置”页填写 API Key、Base URL 和默认模型。

如果不想安装，可下载 `CareerPilot-portable.zip`，解压后双击 `CareerPilot.exe`。模型调用和公开检索仍需要网络以及用户自己的 API Key。

桌面包数据保存在当前 Windows 用户目录。不要把用户数据目录或 `.env` 提交到 Git。

### Docker 开发/服务器环境

开发和服务器运行统一由 Docker Compose 管理，不再要求宿主机安装 Python、Node.js、PostgreSQL 或 Redis：

```powershell
git clone https://github.com/zhangwx777/careerpilot.git
cd careerpilot
Copy-Item .env.example .env
# 编辑 .env（如有需要）
docker compose up --build
```

启动后访问 `http://127.0.0.1:5173`。Compose 会固定管理 frontend、backend、worker、PostgreSQL 和 Redis；按 `Ctrl+C` 停止前台服务，使用 `docker compose down` 关闭服务。完整说明见 [开发文档](docs/development.md) 和 [运维文档](docs/operations.md)。

## 验证

```powershell
docker compose run --rm backend pytest -p no:cacheprovider

docker compose run --rm frontend pnpm test
docker compose run --rm frontend pnpm build
```

连接 PostgreSQL 的集成测试需要设置独立的 `TEST_DATABASE_URL`；未设置时相关测试会跳过，跳过不代表通过。

## 文档入口

- [产品需求与范围](docs/PRD.md)
- [系统架构](docs/architecture.md)
- [开发手册](docs/development.md)
- [部署与运维](docs/operations.md)
- [当前路线图](docs/roadmap.md)

编码 Agent 的工作规则位于 [CLAUDE.md](CLAUDE.md)。

## 技术栈概览

React、Vite、TypeScript、FastAPI、Python 3.12、SQLAlchemy、PostgreSQL、Redis、Celery、LangGraph、LiteLLM 和 Electron。稳定架构与组件边界见 [系统架构](docs/architecture.md)。
