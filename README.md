# 职航 CareerPilot

**把投递进度、招聘通知、岗位面经和面试准备，放进一个本地求职工作台。**

[![Verify](https://github.com/zhangwx777/careerpilot/actions/workflows/verify.yml/badge.svg?branch=main)](https://github.com/zhangwx777/careerpilot/actions/workflows/verify.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[下载 Windows 桌面版](https://github.com/zhangwx777/careerpilot/releases/latest) · [从源码启动](#从源码启动) · [反馈问题](https://github.com/zhangwx777/careerpilot/issues)

CareerPilot 面向秋招、春招等校园招聘场景，适合同时跟进多个公司与岗位的个人求职者。记录每次投递，核对通知中的面试与截止时间，把收集到的面经和岗位要求转成具体的准备行动，让你更容易知道今天该处理什么、下次面试前该练什么。

- **本地使用，无需注册**：求职资料保存在自己的电脑上，当前按单用户设计。
- **记录与准备关联**：围绕公司和岗位整理投递、时间线、JD、面经与简历，减少在多份表格和笔记间来回查找。
- **AI 辅助，自己确认**：模型帮助提取通知、整理面经和生成准备建议；通知解析结果经你核对后才会保存。
- **自选模型服务**：使用自己的 API Key，可配置兼容网关；公开网页检索单独配置。

> 本地存储不等于所有处理都在本机完成。使用 AI 或公开检索时，相关输入会发送到你配置的服务。详见[数据、隐私与安全](#数据隐私与安全)。

## 能帮你做什么

| 求职中遇到的问题 | CareerPilot 提供的功能 |
| --- | --- |
| 同时投了多家公司，记不清各自进度 | **投递管理**：按公司、岗位记录每次独立投递，跟踪招聘阶段；同一岗位的多次投递分别保留。 |
| 面试、测评和截止时间散落在各处 | **求职总览与时间线**：集中查看招聘节点、临期与逾期事项；**每日简报**汇总当天需要关注的节点。 |
| 收到通知后，要手动整理公司、岗位与时间 | **智能录入**：粘贴邮件、短信或通知，提取候选字段，核对后保存到投递与时间线。 |
| 收集了很多面经，却难以归纳准备方向 | **面经工作台**：整理文字与截图面经，按公司、岗位和轮次归纳考察方向，并保留资料来源。 |
| 想结合自己的资料了解一个岗位 | **岗位问答**：根据当前岗位的 JD、面经、简历和时间线回答问题，展示回答使用的资料来源。 |
| 面试临近，不知道该优先练什么 | **备战与练习**：上传 PDF/DOCX 简历，结合岗位资料生成匹配分析、差距和准备行动，逐项练习并获得评估反馈。 |

配置公开检索后，还可以查找相关面经来源，补充岗位准备资料。

## 下载与使用

### Windows 桌面版

前往 [最新 Release](https://github.com/zhangwx777/careerpilot/releases/latest)，选择 Windows x64 发行包：

| 文件 | 使用方式 |
| --- | --- |
| `CareerPilotSetup.exe` | 向导式安装，可创建桌面和开始菜单快捷方式。 |
| `CareerPilot-portable.zip` | 解压后运行 `CareerPilot.exe`，无需安装。 |

桌面版自带所需运行环境，**无需另装 Python、Node.js、PostgreSQL、Redis 或 Docker**。安装程序尚未进行代码签名，Windows 可能显示发布者提示。

### 配置 AI 功能

在应用的“模型设置”中添加模型服务和 API Key，选择默认模型。内置供应商包括 **OpenAI、Anthropic、DeepSeek 和 Qwen**，也可通过自定义 Base URL 使用兼容所选接口协议的网关。

面经、备战、简报和图片识别可以分别指定模型；识别截图需要所选模型支持图片输入。公开网页检索是可选服务，在同一页面单独配置。

模型与检索服务的费用由对应服务商收取，使用自己的 API Key；连接测试也会发送真实模型请求。

<details>
<summary>模型连接与自定义网关说明</summary>

供应商选择决定请求使用的接口协议。Base URL 留空时使用该供应商的默认地址；填写自定义地址时，应填写 API 根路径，不要填 `/chat/completions`。

连接测试会发送模型请求，并探测工具调用和流式能力。测试成功表示该地址可按所选协议调用，不代表 URL 域名属于所选供应商。

</details>

### 更新与本地数据

点击侧栏品牌旁的版本按钮检查更新，有新版本时点击更新提示下载并安装。更新器使用 Windows 系统代理，支持断点续传和安装包校验；发行版配置镜像后会优先从镜像下载，失败时回退到 GitHub。

桌面数据保存在当前 Windows 用户的 `%LOCALAPPDATA%\CareerPilot` 目录，覆盖安装和应用内更新会保留该目录。便携版也使用这个目录存储数据；迁移到其他电脑时，需要同时迁移数据，不能只复制程序文件。

## 使用前你可能想知道

**需要注册账号吗？** 无需注册，当前按本机单用户设计，不提供多用户账号或云端账户同步。

**支持哪些平台？** 当前提供 Windows x64 桌面发行包。也可以通过下方 Docker Compose 方式从源码启动。

**会自动投递简历吗？** 不会。CareerPilot 用于记录、整理和准备，不代替你向招聘平台提交申请，也不替你做求职决定。

**AI 结果能直接作为招聘信息吗？** 通知解析可能遗漏或误读字段，保存前需要核对原始通知，尤其是时间、地点和截止要求；面经洞察和准备建议也需要结合自己的情况判断。

## 从源码启动

源码环境使用 Docker Compose，适合本机开发或受信任环境中的个人使用。需要 Git 和 Docker Desktop（含 Docker Compose v2），宿主机无需另装 Python、Node.js、PostgreSQL 或 Redis。

在 PowerShell 中执行：

```powershell
git clone https://github.com/zhangwx777/careerpilot.git
cd careerpilot
docker compose up --build
```

启动完成后，打开 **<http://127.0.0.1:5173>**。

模型服务、API Key 和公开检索设置均在应用的“模型设置”页面保存，无需手动创建 `.env` 或密钥文件。

<details>
<summary>服务端口与日常开发命令</summary>

Compose 会启动前端、API、后台 worker、PostgreSQL 和 Redis：

| 服务 | 本机地址或端口 |
| --- | --- |
| 前端 | <http://127.0.0.1:5173> |
| API | <http://127.0.0.1:8000> |
| 健康检查 | <http://127.0.0.1:8000/health> |
| PostgreSQL | `5433` |
| Redis | `6379` |

前端使用 Vite，修改界面文件会自动刷新。修改后端代码后执行 `docker compose restart backend worker`；更改依赖或 Dockerfile 后执行 `docker compose up --build` 重新构建。

```powershell
docker compose ps
docker compose logs -f backend worker
docker compose down
```

`docker compose down` 停止并移除容器，保留 PostgreSQL、Redis 和模型配置密钥数据卷。删除数据卷会清除本机开发数据及已保存的模型配置。

Compose 端口仅绑定本机地址，内置数据库凭据只供本机开发使用。此配置运行 Vite 开发服务器，不提供公网生产部署所需的 TLS、反向代理或多用户隔离。

</details>

<details>
<summary>Compose 数据备份与模型密钥</summary>

Compose 会在首次保存模型 API Key 时自动生成加密根密钥，存入持久化的 `careerpilot-config` 数据卷。已有的 `.llm_config_secret` 和 `.llm_config_legacy_keys` 仅作为旧密钥迁移来源。

备份或迁移时，应同时保留数据库与配置密钥。丢失密钥后，已保存的 API Key 无法解密，需要重新填写。桌面版和 Compose 分别管理自己的运行环境与数据，启动源码环境不会自动读取桌面版记录。

</details>

<details>
<summary>运行自动化验证</summary>

CI 使用独立的 PostgreSQL、Redis 和临时构建卷，不读取日常 `.env` 或本机数据库。在仓库根目录执行：

```powershell
docker compose -f docker-compose.ci.yml build
docker compose -f docker-compose.ci.yml run --rm frontend
docker compose -f docker-compose.ci.yml run --rm backend
node --test docker-compose.test.mjs desktop/port-selection.test.mjs desktop/startup.test.mjs
docker compose -f docker-compose.ci.yml down --volumes --remove-orphans
```

前端步骤运行 `pnpm test` 和生产构建；后端步骤运行 pytest 与 PostgreSQL 集成验证。先运行前端，以生成后端桌面静态资源测试所需的临时构建产物。清理命令只针对名为 `careerpilot-ci` 的独立验证环境。

</details>

## 数据、隐私与安全

投递、简历和面经资料保存在本机。使用模型或公开检索时，相关输入会发送给你配置的模型服务商或检索服务；数据如何处理取决于对应服务的数据政策。模型 API Key 在本地数据库中加密保存，接口只显示掩码。

提交 Issue、日志或截图前，请删除 API Key、密码、简历、个人资料和真实求职记录。安全漏洞请通过 [GitHub 私密漏洞报告](https://github.com/zhangwx777/careerpilot/security/advisories/new) 提交。

## 反馈与参与

欢迎通过 [GitHub Issues](https://github.com/zhangwx777/careerpilot/issues) 反馈实际使用中遇到的问题或提出功能建议。报告问题时，请尽量附上应用版本、运行方式（桌面版或 Docker）、复现步骤，以及预期和实际结果。

也欢迎提交 Pull Request。开发约定见 [AGENTS.md](AGENTS.md)，项目运行边界和代码工作说明见 [CLAUDE.md](CLAUDE.md)。

如果 CareerPilot 对你有帮助，欢迎点一个 Star，或分享给正在准备求职的朋友。

## 技术栈与许可证

前端：React / Vite / TypeScript · 后端：FastAPI / SQLAlchemy / PostgreSQL · 后台任务：Celery / Redis · AI 流程：LangGraph / LiteLLM · 桌面：Electron。

CareerPilot 使用 [MIT 许可证](LICENSE)。桌面发行包中的第三方组件按各自许可证发布，详见[第三方组件许可说明](THIRD_PARTY_NOTICES.md)。
