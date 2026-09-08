# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

求职作战台（qiuzhao-agent）：面向国内秋招/春招的**个人自用**求职辅助系统。不做自动投递，只做信息聚合与决策辅助——两条主线：A 进度指挥中心（投递台账 + 半自动解析通知 + 时间线冲突/临期检测），B 定向面经情报（针对某条投递多源聚合、交叉验证、产出可溯源的结构化面经）。

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

前端（在 `frontend/` 下，包管理器是 pnpm via corepack）：

```bash
cd frontend
corepack pnpm install
corepack pnpm dev      # Vite dev，proxy /api 和 /health 到 127.0.0.1:8000
corepack pnpm build    # tsc -b && vite build
```

## 测试（重要，别踩坑）

碰 PostgreSQL / LangGraph 状态的测试**必须**通过环境变量 `TEST_DATABASE_URL` 指向真实测试库 `qiuzhao_test` 才会真跑，否则会被 `@skipUnless` 跳过——**skip 不等于 pass**，跳过的测试等于没验证。用 pytest 跑，LLM/MCP 调用在测试里已 mock，图逻辑在真实测试库上跑：

```bash
cd backend
export TEST_DATABASE_URL=<开发库URL但把库名换成 qiuzhao_test>   # 只换 path 段的库名，别动用户名
.venv/Scripts/python.exe -m pytest -p no:cacheprovider          # 全量，应 0 skipped
.venv/Scripts/python.exe -m pytest tests/test_intel_graph.py -v  # 单个文件
.venv/Scripts/python.exe -m pytest tests/test_intel_graph.py::IntelGraphTestCase::test_conflict_interrupt_resumes_once  # 单个用例
```

构造 `TEST_DATABASE_URL` 时用 urlsplit/urlunsplit 只替换 path 段的库名，不要用字符串 replace——曾经 `.replace('/qiuzhao','/qiuzhao_test')` 把用户名 `qiuzhao_app` 也改成 `qiuzhao_test_app` 导致认证失败，并把明文密码打进了日志。

## 架构要点（跨文件才能看清的部分）

**多模型 provider 层**（`app/llm/`）是全项目 LLM 调用的唯一入口，理解它是理解全局的前提：
- `registry.py` 把 4 家 provider（anthropic/openai/deepseek/qwen）映射到 `{api_key, api_base, model}`，三件套**全部来自 `.env`，代码不预设任何默认值**，model 名用 LiteLLM 的 `provider/model` 格式。
- `provider.py` 的 `chat(messages, provider, response_format=None)` 是统一出口，**provider 由调用方显式传入**。改动时严禁把 provider 或 model 名写死在业务代码里（parsing.py 曾有 `provider="qwen"` 硬编码遗留，已改成参数）。
- `.env` 优先于系统环境变量（config.py 定制了 settings 源顺序）。

**两条 LangGraph 图**（只在控制流本身需要图编排处用，非装饰）：
- `parse_graph.py`（解析）：`START → extract → review_interrupt → persist → END`。`review_interrupt` 首个动作是 `interrupt()`，人工确认后 `Command(resume=...)` 恢复。
- `intel_graph.py`（面经聚合，项目含金量核心）：planner → 并行 fan-out（AnySearch 搜索 / 用户粘贴）→ aggregate 汇聚 → 置信度条件补搜（每轮换检索意图，最多 3 轮）→ critic 反思（反馈驱动**重抽取**，最多 2 轮）→ 冲突或反思未过时 interrupt 人工裁决 → persist。
- 两图共用 `PostgresSaver` checkpointer（`db.py` 的 `to_psycopg_connection_string` 把 SQLAlchemy URL 转成 psycopg 原生串），靠 `thread_id`（存在对应 session 表）实现进程重启后恢复。持久化节点用 `with_for_update()` 行锁 + 幂等（已完成状态重复恢复不重复写库）。

**HITL 会话表**：`parse_session` 对应解析图、`intel_session` 对应面经图，各自保存 thread_id、草稿、冲突、状态、最终关联 id。只有人工裁决完成（或无冲突）才写入终表（`timeline_node` / `interview_intel`）。数据模型主关系：company 1—n position 1—n application 1—n (timeline_node / interview_intel / *_session)。枚举常量集中在 `models.py` 顶部。

**不编造原则贯穿数据流**：所有情报/解析字段可空，抽取器 prompt 要求未知返回 null、每条事实带 source_id，critic 专门查编造/无来源/遗漏。改抽取或聚合逻辑时守住这条。

**面经聚合的冲突边界**：`_merge` 目前只对「难度」做冲突检测并进人工裁决；轮次、题型的多来源差异是合并展示、不进裁决。这是有意的当前边界（难度是主观互斥项）。

## 数据源

- AnySearch HTTP MCP（`anysearch.py`，endpoint `https://api.anysearch.com/mcp`，经 langchain-mcp-adapters 接入）是面经主搜索源，返回 Markdown 需正则抽取，最多 5 条。
- 用户粘贴作为独立保底来源。
- 当前配置下 OpenAI/Anthropic 的联网搜索端点不可实测，未保留无法验证的兼容分支；provider 仅用于单来源抽取与 critic 判定。

## 环境与约束

- 后端 Python 3.12 + FastAPI + SQLAlchemy 2.0；数据库 **PostgreSQL（明确不用 SQLite）**，情报用 JSONB。
- 本机另有 Docker 容器 `linker-local-db`（端口 5434）属于其他项目，**不要碰**。本项目开发库 `qiuzhao` / 测试库 `qiuzhao_test` 在本地 PG 5432，账号 `qiuzhao_app`。
- `.env` 含密码和 key，已 gitignore，不入库；换机需重建。数据库数据不进 git，用 pg_dump 手动迁移。
- 健康检查：`GET http://127.0.0.1:8000/health` 返回 `{"status":"ok","db":true}`。

## 协作流程

本仓库由 codex 分期实现、在本会话审查验证后提交。审查要点：provider 不写死、循环有次数上限、测试真跑无 skip 冒充 pass、不留过程文件（findings/progress/task_plan 之类）在工作区。更细的分期进度见 `docs/工作计划.md`、`docs/开发文档.md`。
