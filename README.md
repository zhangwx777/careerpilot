# 求职作战台（qiuzhao-agent）

面向秋招、春招等校园招聘场景的个人求职辅助系统。不做自动投递，专注**信息聚合与决策辅助**：把分散在各平台的投递进度、时间线节点统一成一张作战地图，并针对目标岗位聚合结构化面经情报。

## 为什么做这个

国内校园招聘和海外 job hunting 结构差异明显，海外工具（海投、ATS 优化、Easy Apply）的核心假设在国内并不完全成立。真正的痛点是：

- **多平台进度分散**：网申官网 + 牛客 + 各公司小程序，状态更新不同步，全靠手动追。
- **时间线密集**：大厂 HC 8 月集中释放、10 月中旬基本关闭，窗口只有 6 周，错过节点 = 错过一年。
- **笔试/面试冲突**：多场笔试撞车、临期节点没人提醒。
- **面经碎片化**：牛客/小红书/微信群到处是，无法针对"我投的这家这个岗"聚合。

本项目针对这些空白点，做两件市面没做好的事。

## 核心功能

### A. 进度指挥中心
- 作战总览：进入系统的落地页，一屏看需要马上处理的节点（冲突 / 临期 / 逾期）和各阶段投递分布。
- 投递记录管理：投递时直接录入公司和岗位，系统自动归档；台账按“公司 / 岗位”平铺，每条投递独立一行。同一岗位的多次投递会分别保留。统一阶段为已投递 → 测评 → 笔试 → AI面 → 各轮面试 → offer/挂，不适用的阶段可以直接跳过。台账列表会标出缺少 JD 的投递；编辑投递时可直接修正点错的当前阶段。
- **半自动解析**：粘贴笔试通知邮件/短信，AI 抽取「公司 + 岗位 + 节点类型 + 时间」，人工确认后可新建本次投递，或在确属同一次投递时关联已有记录。
- 录入不中断：新增投递和通知确认页会在当前浏览器保存未提交内容；通知未给出开始时间时默认当前时间，识别到“3 个工作日内”等期限时会随开始时间自动计算截止时间。
- 作战地图：日历 + 列表视图，自动检测冲突（两场笔试撞车）和临期未处理节点。

### B. 定向面经情报
- 面经工作台按「公司 + 岗位」建立持续资料库：手动粘贴内容优先分析，联网搜索只作补充，并过滤招聘公告、岗位职责和秋招宣传页等非面经来源。
- 支持上传 PNG/JPEG/WebP 面经截图，由当前选择的多模态模型提取文字，用户可编辑识别结果后再分析；图片不长期保存。
- 面经工作台分为“录入与进度 / 面试洞察 / 面经档案”：录入时手动选择测评、笔试、AI 面、一面、二面、三面、HR 面或多轮综合；岗位洞察跨轮次按考察方向聚合全部来源，只有多来源方向才标记为高频。
- 面经档案保留每份文字、每张截图的文件名与识别文字、以及联网来源，可按轮次筛选、展开查看和删除；岗位洞察不会混入单份材料的高频判断。
- 面经页提供岗位级持久问答。存在该岗位未来固定时间的一面、二面、三面或 HR 面时，Agent 自动在面试开始前 24 小时把高频考察方向中的核心问题和准备重点合并推送到时间线；没有确定面试则不创建提醒。
- 备战分析：上传 PDF/DOCX 简历，结合 JD + 面经情报生成匹配总结、优势、差距和准备行动清单；不自动排期或写入时间线。

进度指挥中心相关接口：

```text
GET  /api/dashboard                     作战总览：各阶段投递数 + 冲突/临期/逾期的待处理节点
GET  /api/providers                     当前 .env 里已配好 key 和模型名的厂商列表
PATCH /api/applications/{id}            编辑投递，可直接修正当前阶段（不受只能向后的限制）
PATCH /api/applications/{id}/status     台账里推进阶段，只能向后或标记为“挂”
```

面经相关接口：

```text
POST /api/intel                         新建面经分析会话（supplement_web 默认 false，主动开启才联网补充）
                                         必填 round_type；可传 image_texts 保存分图识别结果
POST /api/intel/images/extract          截图转可编辑文字
GET  /api/intel/dossier?application_id= 岗位级面试洞察、材料档案与提醒状态
POST /api/intel/dossier/rebuild         重新生成岗位级面试洞察
DELETE /api/intel/materials/{id}        删除一份面经材料并更新洞察
GET  /api/intel/chat?application_id=    读取岗位问答历史
POST /api/intel/chat                    创建后台增量问答，立即返回“生成中”消息
GET  /api/intel-sessions                找回最近运行中的面经聚合会话
POST /api/intel-sessions/{id}/discard   舍弃未写入面经档案的分析会话
POST /api/resume-profile/upload         上传 PDF/DOCX 并提取简历文字
POST /api/planner-sessions               创建岗位备战分析会话（不再提交可用时间）
GET  /api/planner-sessions              找回最近运行中的备战会话
```

`GET /api/intel` 仍保留为按投递读取历史材料的通用接口；面经工作台使用 dossier 接口按公司＋岗位聚合。岗位级高频只按不同材料来源统计考察方向，单份材料不会显示为高频。

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
│  │  ├─ models.py        # 业务表 ORM
│  │  └─ llm/             # 多模型 provider 层
│  └─ scripts/            # 建表、smoke test
├─ frontend/              # React + Vite + TypeScript 前端
└─ docs/                  # PRD、开发、交接与工作计划
```

## 启动服务

### 首次安装

请先启动本地 PostgreSQL，并将项目根目录的 `.env.example` 复制为 `.env`，填入数据库连接和模型 Key。

```bash
cd C:\qiuzhao-agent\backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

cd C:\qiuzhao-agent\frontend
corepack pnpm install
```

### 一键启动

双击项目根目录的 `start.bat`，或在 PowerShell 执行：

```powershell
cd C:\qiuzhao-agent
.\start.bat
```

脚本会初始化数据库、启动或复用健康的后端与前端服务；缺失前端依赖时会自动修复。前端就绪后会自动打开 `http://localhost:5173/`。前端进程会保持在启动终端中；后端健康检查地址为 `http://127.0.0.1:8000/health`。

若脚本提示 5173 端口已被不健康的旧服务占用，请先关闭对应的旧终端，再重新双击 `start.bat`。脚本不会为抢占端口改用其他前端地址，避免浏览器打开错误服务。

停止服务：在启动终端按 `Ctrl+C`，PowerShell 包装器会在前端退出后自动清理 5173 和 8000 端口的前后端子进程。若终端已经关闭或仍有旧进程，双击根目录的 `stop.bat`；它只处理本项目约定的 5173、8000 端口。

### 手动启动

若需要在已有终端中启动，分别执行：

```powershell
# 终端一：后端
cd C:\qiuzhao-agent\backend
.\.venv\Scripts\python.exe -m scripts.init_db
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 终端二：前端（启动后自动打开浏览器，并固定使用 5173 端口）
cd C:\qiuzhao-agent\frontend
corepack pnpm exec vite --open --port 5173 --strictPort
```

如果 `start.bat` 提示缺少前端依赖，先关闭占用 `frontend\node_modules` 的 Node.js 进程，再运行 `corepack pnpm install --force`。

### 验证

```powershell
cd C:\qiuzhao-agent\backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
cd ..\frontend
corepack pnpm test
corepack pnpm build
```

未配置 `TEST_DATABASE_URL` 时，数据库集成测试不会执行；这不应视为集成测试通过。

## 数据同步说明

**代码**通过 git 同步，**数据库数据不进 git**（在本地 PG 实例中）。换电脑时：
- 代码：`git clone` 即可。
- 配置：`.env` 不入库（含密码/key），需在新机重新创建。
- 数据：用 `pg_dump` / `psql` 手动导出导入，或后续改用云数据库（只需改 `.env` 连接串，代码无需改动）。

## 开发进度

见 [docs/工作计划.md](docs/工作计划.md)。第 1 至 5 期及近期真实使用反馈迭代均已完成。
