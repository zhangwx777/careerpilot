# 职航 CareerPilot

[![Verify](https://github.com/zhangwx777/careerpilot/actions/workflows/verify.yml/badge.svg?branch=main)](https://github.com/zhangwx777/careerpilot/actions/workflows/verify.yml)

职航 CareerPilot 是面向秋招、春招等校园招聘场景的个人求职工作台。它把投递记录、招聘节点、岗位面经和备战练习放在一个本地应用中，帮助你决定现在该处理什么、面试前该练什么。

CareerPilot 不自动投递，也不替用户做求职决定。通知解析、面经洞察和 AI 建议均由用户确认后再使用。求职数据保存在本机；模型服务和公开网页检索由用户自行配置。

## 主要功能

- **求职总览与时间线**：查看投递阶段、待练行动、临期和逾期节点，以及面试、笔试、测评和截止日期。
- **投递管理**：按公司和岗位记录每次独立投递，跟踪招聘阶段及后续节点。
- **智能录入**：粘贴邮件、短信或通知，让模型提取公司、岗位、考试/面试安排和时间；核对后再保存。
- **面经工作台**：按公司与岗位整理文字和截图面经，跨轮次归纳考察方向，保留资料来源。
- **岗位问答**：根据当前岗位的 JD、面经、简历和时间线进行只读问答，并展示回答所用的资料来源。
- **备战与练习**：上传 PDF/DOCX 简历，结合岗位资料生成匹配分析、差距和准备行动；可以逐项练习并获得自我评估反馈。
- **每日简报**：汇总当天需要处理的求职节点；配置公开检索后，可发现新的相关面经来源。

## Windows 桌面版

从 [最新 Release](https://github.com/zhangwx777/careerpilot/releases/latest) 下载 Windows x64 安装包或便携包：

- **CareerPilotSetup.exe**：向导式安装，可创建桌面和开始菜单快捷方式。
- **CareerPilot-portable.zip**：解压后运行 CareerPilot.exe，无需安装。

桌面版自带前端、后端、PostgreSQL、任务队列运行时和 Electron 启动器。使用它不需要另行安装 Python、Node.js、pnpm、PostgreSQL、Redis、Docker 或 .NET。安装程序未进行代码签名，Windows 可能显示发布者提示。

首次启动后，打开“模型设置”，配置模型服务、API Key、Base URL 和默认模型。内置 Provider 包括 OpenAI、Anthropic、DeepSeek 和 Qwen；面经、备战、简报和图片识别也可以分别指定模型。公开检索在“模型设置”中单独配置。

供应商选择决定请求使用的接口协议；Base URL 留空时使用该供应商的默认地址，也可填入兼容该协议的自定义网关。连接测试会实际发送模型请求，并探测工具调用和流式能力；测试成功表示该地址可按所选协议调用，不代表 URL 域名属于所选供应商。

桌面版可在“模型设置 → 软件更新”中检查并获取最新发行版。新版更新器使用 Windows 系统代理，支持断点续传与安装包校验；发行版配置镜像后会优先从镜像下载，失败时回退到 GitHub。
桌面数据保存在当前 Windows 用户的 %LOCALAPPDATA%\CareerPilot 目录。覆盖安装和应用内更新会保留该目录。

## 从源码启动

源码环境使用 Docker Compose，适合本机开发或受信任网络中的个人使用。需要 Git 和 Docker Desktop（含 Docker Compose v2），宿主机不需要安装 Python、Node.js、PostgreSQL 或 Redis。

在 PowerShell 中执行：

```powershell
git clone https://github.com/zhangwx777/careerpilot.git
cd careerpilot
docker compose up --build
```

启动后访问：

- 前端：<http://127.0.0.1:5173>
- API 与健康检查：<http://127.0.0.1:8000>、<http://127.0.0.1:8000/health>
- PostgreSQL：本机端口 5433；Redis：本机端口 6379。

Compose 会启动 frontend、backend、worker、PostgreSQL 和 Redis。前端使用 Vite，修改界面文件会自动刷新；修改后端代码后执行 `docker compose restart backend worker`。更改依赖或 Dockerfile 后用 `docker compose up --build` 重新构建。

常用操作：

```powershell
docker compose ps
docker compose logs -f backend worker
docker compose down
```

`docker compose down` 会停止并移除容器，但保留 PostgreSQL、Redis 和模型配置密钥数据卷。删除数据卷会清除本机开发数据及已保存的模型配置。Compose 端口仅绑定本机地址；此配置运行 Vite 开发服务器，不提供公网生产部署所需的 TLS、反向代理或多用户隔离。

模型 Provider、API Key 和公开检索设置在应用“模型设置”页面保存，不写入 `.env`。Compose 内置的数据库凭据只供本机开发使用，不可用于公网或生产服务。

Compose 会在首次保存模型 API Key 时自动生成加密根密钥，并保存在 `careerpilot-config` 数据卷中；无需手动创建密钥文件或 `.env`。已有的 `.llm_config_secret` 和 `.llm_config_legacy_keys` 会作为旧密钥迁移来源。备份或迁移数据时一并保留配置密钥；丢失密钥后，已保存的 API Key 无法解密，需要重新填写。

## 自动化验证

CI 使用独立的 PostgreSQL、Redis 和临时构建卷，不读取日常 `.env` 或本机数据库。需要在本地运行同一套验证时，在仓库根目录执行：

```powershell
docker compose -f docker-compose.ci.yml build
docker compose -f docker-compose.ci.yml run --rm frontend
docker compose -f docker-compose.ci.yml run --rm backend
node --test docker-compose.test.mjs desktop/port-selection.test.mjs desktop/startup.test.mjs
docker compose -f docker-compose.ci.yml down --volumes --remove-orphans
```

前端步骤会运行 `pnpm test` 和生产构建；后端步骤会运行 pytest 与 PostgreSQL 集成验证。先运行前端，以便生成后端桌面静态资源测试所需的临时构建产物。清理命令只针对名为 `careerpilot-ci` 的独立验证环境。

## 数据、隐私与安全

投递、简历和面经资料保存在本机。使用模型或公开检索时，相关输入会发送给你配置的 Provider 或检索服务；请先查阅对应服务的数据政策。模型 API Key 在本地数据库中加密保存，接口只显示掩码。

报告一般问题可使用 [GitHub Issues](https://github.com/zhangwx777/careerpilot/issues)。提交前请删除日志和截图中的 API Key、密码、简历、个人资料及真实求职记录。安全漏洞请通过 [GitHub 私密漏洞报告](https://github.com/zhangwx777/careerpilot/security/advisories/new) 提交，不要在公开 Issue 中披露利用细节。

## 技术与许可证

前端使用 React、Vite 和 TypeScript；后端使用 FastAPI、SQLAlchemy 和 PostgreSQL；后台任务使用 Celery 与 Redis；LangGraph 管理可恢复流程，LiteLLM 统一模型调用；Windows 桌面壳使用 Electron。

CareerPilot 使用 MIT 许可证，详见 [LICENSE](LICENSE)。桌面发行包中的第三方组件仍按各自许可证发布，详见[第三方组件许可说明](THIRD_PARTY_NOTICES.md)。
