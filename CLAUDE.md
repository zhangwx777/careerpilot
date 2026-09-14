# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

求职作战台（qiuzhao-agent）：面向国内秋招/春招的**个人自用**求职辅助系统。不做自动投递，只做信息聚合与决策辅助——两条主线：A 进度指挥中心（投递台账 + 半自动解析通知 + 时间线冲突/临期检测），B 面经工作台（按公司＋岗位持续保存多份材料，跨轮次生成岗位洞察、准备重点和问答）。

## 常用命令

后端（在 `backend/` 下，用 venv 里的 python，Windows 路径 `.venv/Scripts/python.exe`）：

```bash
cd backend
.venv/Scripts/python.exe -m pip install -e .           # 装依赖
.venv/Scripts/python.exe -m scripts.init_db            # 初始化开发库：业务表 + langgraph checkpoint 表
.venv/Scripts/python.exe -m scripts.init_db --test     # 初始化独立测试库 qiuzhao_test
.venv/Scripts/python.exe -m scripts.smoke_llm          # 测四家模型连通（需 .env 已填 key）
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

日常启动优先在仓库根目录双击或执行 `start.bat`。它会初始化数据库，为本次运行获取新的项目端口（优先后端 8000、前端 5173，被占用时顺延），并尝试打开浏览器。自动打开失败不会关闭服务；始终以后端/前端启动时打印的实际 URL 为准。停止时在启动终端按 `Ctrl+C`；脚本会清理本次启动的进程，并在 `taskkill` 被系统拒绝时回退到 `Stop-Process`。

前端（在 `frontend/` 下，包管理器是 pnpm via corepack）：

```bash
cd frontend
corepack pnpm install
corepack pnpm dev      # Vite dev，proxy /api 和 /health 到 127.0.0.1:8000
corepack pnpm test     # 前端草稿与工作日计算测试
corepack pnpm build    # tsc -b && vite build
```

## 测试（重要，别踩坑）

碰 PostgreSQL / LangGraph 状态的测试**必须**通过环境变量 `TEST_DATABASE_URL` 指向真实测试库 `qiuzhao_test` 才会真跑，否则会被 `@skipUnless` 跳过——**skip 不等于 pass**，跳过的测试等于没验证。用 pytest 跑，LLM/MCP 调用在测试里已 mock，图逻辑在真实测试库上跑：

```bash
cd backend
$env:TEST_DATABASE_URL=<开发库URL但把库名换成 qiuzhao_test>     # PowerShell；只换 path 段的库名，别动用户名
.venv/Scripts/python.exe -m pytest -p no:cacheprovider          # 全量，应 0 skipped
.venv/Scripts/python.exe -m pytest tests/test_intel_graph.py -v  # 单个文件
.venv/Scripts/python.exe -m pytest tests/test_intel_graph.py::IntelGraphTestCase::test_conflict_interrupt_resumes_once  # 单个用例
```

构造 `TEST_DATABASE_URL` 时用 urlsplit/urlunsplit 只替换 path 段的库名，不要用字符串 replace——曾经 `.replace('/qiuzhao','/qiuzhao_test')` 把用户名 `qiuzhao_app` 也改成 `qiuzhao_test_app` 导致认证失败，并把明文密码打进了日志。

## 架构要点（跨文件才能看清的部分）

**多模型 provider 层**（`app/llm/`）是全项目 LLM 调用的唯一入口，理解它是理解全局的前提：
- `registry.py` 提供四家 provider（openai/anthropic/deepseek/qwen）的 `.env` 兼容配置；`config_store.py` 读取数据库覆盖，数据库配置优先，删除后回退 `.env`。明确设置的全局默认优先级最高；未设置全局默认时，最近更新且有效的网页覆盖优先于 `.env`。model 名用 LiteLLM 的 `provider/model` 格式（网页设置页可从模型目录选择）。
- `provider.py` 的 `chat(messages, provider, response_format=None, config=None)` 是统一出口，**provider 由调用方显式传入**。改动时严禁把 provider 或 model 名写死在业务代码里；调用错误必须经过安全包装，不能把 LiteLLM 原始异常或 API Key 写入日志/响应。
- 前端“分析模型”下拉和设置页读 `GET /api/providers`，只展示脱敏状态；设置页通过 `POST /api/llm/providers/{provider}/models` 按 API Key 与 Base URL 读取模型目录，再由用户选择模型。任务创建时显式解析全局默认或任务级覆盖。网页保存前需要 `.env` 中的 `LLM_CONFIG_SECRET`，否则保持旧 `.env-only` 兼容模式。
- `.env` 优先于系统环境变量（config.py 定制了 settings 源顺序）。

**LangGraph 图**（只在控制流本身需要图编排处用，非装饰）：
- `parse_graph.py`（解析）：`START → extract → review_interrupt → persist → END`。`review_interrupt` 首个动作是 `interrupt()`，人工确认后 `Command(resume=...)` 恢复。
- `intel_graph.py`（面经聚合，项目含金量核心）：手动文本/截图来源先抽取 → 相关性过滤后的 AnySearch 公开面经补搜 → aggregate 汇聚 → critic 反思（反馈驱动**重抽取**）→ 冲突或反思未过时 interrupt 人工裁决 → persist；写入材料后由 `intel_insight.py` 跨轮次生成岗位级考察方向、核心问题和准备重点。
- `planner_graph.py` 仅保留历史备战任务的排期会话恢复；新的备战分析直接返回简历＋JD＋面经分析，不要求可用时间，也不创建新任务或时间线节点。
- 解析图与面经图共用 `PostgresSaver` checkpointer（`db.py` 的 `to_psycopg_connection_string` 把 SQLAlchemy URL 转成 psycopg 原生串），靠 `thread_id`（存在对应 session 表）实现进程重启后恢复。持久化节点用 `with_for_update()` 行锁 + 幂等（已完成状态重复恢复不重复写库）。

**会话与洞察表**：`parse_session`、`intel_session` 和 `planner_session` 保存可恢复会话；`interview_intel` 保存独立面经材料，`intel_chat_message` 保存岗位问答，`position.intel_insight` 保存岗位级洞察。数据模型主关系：company 1—n position 1—n application 1—n (timeline_node / interview_intel / *_session)；公司和岗位由创建投递时的直接输入自动归档，前端不要求预先建立岗位。枚举常量集中在 `models.py` 顶部。

**进度指挥中心的两条状态改法要分清**：`PATCH /api/applications/{id}/status`（`api.py`）是台账里的推进，只能向后或转「挂」；`PATCH /api/applications/{id}`（编辑投递）可把 status 直接改到任意阶段，是给「点错了阶段」的修正用，不走单向校验。前端落地页是作战总览（`/dashboard` → `GET /api/dashboard`，`phase3_api.py`），聚合各阶段投递计数与冲突/临期/逾期节点，复用 `timeline.py` 的 `alert_types`/`conflict_map`。

**不编造原则贯穿数据流**：所有情报/解析字段可空，抽取器 prompt 要求未知返回 null、每条事实带 source_id，critic 专门查编造/无来源/遗漏。改抽取或聚合逻辑时守住这条。

**面经聚合的冲突边界**：`_merge` 目前只对「难度」做冲突检测并进人工裁决；轮次、题型的多来源差异是合并展示、不进裁决。这是有意的当前边界（难度是主观互斥项）。

## 数据源

- AnySearch HTTP MCP（`anysearch.py`，endpoint `https://api.anysearch.com/mcp`，经 langchain-mcp-adapters 接入）是面经补充搜索源，检索词包含面经/面试经历/一面/二面/技术面/面试题等信号，招聘公告、岗位职责和秋招宣传页会被排除。
- 用户粘贴和每张截图识别结果优先作为独立来源；来源按材料和文件名保留，图片原文件不落盘。
- 当前配置下 OpenAI/Anthropic 的联网搜索端点不可实测，未保留无法验证的兼容分支；provider 仅用于单来源抽取与 critic 判定。

## 环境与约束

- 后端 Python 3.12 + FastAPI + SQLAlchemy 2.0；生产数据库 **PostgreSQL**，情报用 JSONB；ORM 测试使用可移植 JSON 类型以便 SQLite 单元测试收集。
- 本机另有 Docker 容器 `linker-local-db`（端口 5434）属于其他项目，**不要碰**。本项目开发库 `qiuzhao` / 测试库 `qiuzhao_test` 在本地 PG 5432，账号 `qiuzhao_app`。
- `.env` 含密码和 key，已 gitignore，不入库；换机需重建。数据库数据不进 git，用 pg_dump 手动迁移。
- 健康检查：`GET http://127.0.0.1:8000/health` 返回 `{"status":"ok","db":true}`。

模型目录排查：Base URL 应填写 API 根路径（例如 `https://gateway.example/v1`），不要填写用户名、密码、query、fragment 或完整 `/chat/completions`。后端会对自定义地址尝试规范化后的 `/models`，并在根路径未带 `/v1` 时回退到 `/v1/models`；如果两者均不可达，先检查 Python 进程的防火墙/代理权限，再检查网关是否实现模型目录接口。测试和解析都只返回脱敏错误，不把 LiteLLM 原始异常或 API Key 写入响应。

## 协作流程

本仓库由 codex 分期实现、在本会话审查验证后提交。审查要点：provider 不写死、循环有次数上限、测试真跑无 skip 冒充 pass、不留过程文件（findings/progress/task_plan 之类）在工作区。更细的分期进度见 `docs/工作计划.md`、`docs/开发文档.md`。
