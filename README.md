# 秋招作战指挥中心（qiuzhao-agent）

面向个人的秋招求职辅助系统。不做自动投递，专注**信息聚合与决策辅助**：把分散在各平台的投递进度、时间线节点统一成一张作战地图，并针对目标岗位聚合结构化面经情报。

## 为什么做这个

秋招和海外 job hunting 结构完全不同，海外工具（海投、ATS 优化、Easy Apply）的核心假设在国内都不成立。真正的痛点是：

- **多平台进度分散**：网申官网 + 牛客 + 各公司小程序，状态更新不同步，全靠手动追。
- **时间线密集**：大厂 HC 8 月集中释放、10 月中旬基本关闭，窗口只有 6 周，错过节点 = 错过一年。
- **笔试/面试冲突**：多场笔试撞车、临期节点没人提醒。
- **面经碎片化**：牛客/小红书/微信群到处是，无法针对"我投的这家这个岗"聚合。

本项目针对这些空白点，做两件市面没做好的事。

## 核心功能

### A. 进度指挥中心
- 投递记录管理：公司 / 岗位 / 投递状态机（已投递 → 笔试 → 各轮面试 → offer/挂）。
- **半自动解析**：粘贴笔试通知邮件/短信，AI 抽取「公司 + 岗位 + 节点类型 + 时间」，人工确认后写入时间线。
- 作战地图：日历 + 列表视图，自动检测冲突（两场笔试撞车）和临期未处理节点。

### B. 定向面经情报
- 针对某条投递（公司 + 岗位），聚合公开面经，多源交叉验证后输出结构化情报：几轮面试、常考题型、考察重点、最新面经摘要，可溯源。
- 备战规划：结合简历 + JD + 面经情报，生成能力差距分析和分解到日的备战任务，自动写回时间线。

## 技术栈

| 层 | 选型 |
|---|---|
| 前端 | React + Vite + TypeScript |
| 后端 | Python 3.12 + FastAPI |
| 数据库 | PostgreSQL 18（情报用 JSONB 存储） |
| 多模型 | LiteLLM 统一 Claude / OpenAI / DeepSeek / Qwen，按任务选模型 |
| Agent 编排 | LangGraph（用于面经交叉验证、Reflection 自校正、半自动解析的人工介入 interrupt） |

## 目录结构

```
qiuzhao-agent/
├─ backend/
│  ├─ app/
│  │  ├─ main.py          # FastAPI 入口 + /health
│  │  ├─ config.py        # 读 .env
│  │  ├─ db.py            # SQLAlchemy engine/session
│  │  ├─ models.py        # 5 张表 ORM
│  │  └─ llm/             # 多模型 provider 层
│  └─ scripts/            # 建表、smoke test
├─ frontend/              # 第 2 期
└─ docs/工作计划.md
```

## 本地运行

### 前置
- PostgreSQL 18 已安装并运行（本地实例）
- Python 3.12、Node.js

### 后端
```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e .

# 配置：复制 .env.example 为 .env，填数据库连接串和模型 key
python -m scripts.init_db      # 建表
python -m scripts.smoke_llm    # 验证模型连通（需已填 key）
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

访问 `http://127.0.0.1:8000/health` 应返回 `{"status":"ok","db":true}`。

## 数据同步说明

**代码**通过 git 同步，**数据库数据不进 git**（在本地 PG 实例中）。换电脑时：
- 代码：`git clone` 即可。
- 配置：`.env` 不入库（含密码/key），需在新机重新创建。
- 数据：用 `pg_dump` / `psql` 手动导出导入，或后续改用云数据库（只需改 `.env` 连接串，代码无需改动）。

## 开发进度

见 [docs/工作计划.md](docs/工作计划.md)。当前：第 1 期已完成（骨架 + 数据模型 + 多模型 provider 层）。
