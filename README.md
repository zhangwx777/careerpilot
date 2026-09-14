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
GET  /api/providers                     四家模型的脱敏配置状态（网页覆盖优先于 .env）
PUT  /api/llm/providers/{provider}      保存网页模型配置（API Key 仅密文落库）
POST /api/llm/providers/{provider}/test 测试连接（可只提交临时覆盖字段；失败仍可保存，标记为待验证/失败）
POST /api/llm/providers/{provider}/models 读取当前 API Key/Base URL 可用模型（不落库）
DELETE /api/llm/providers/{provider}    删除网页覆盖并回退到 .env
PUT  /api/llm/default                   设置全局默认模型
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

请先启动本地 PostgreSQL，并将项目根目录的 `.env.example` 复制为 `.env`，填入数据库连接。模型可以继续写在 `.env`，也可以启动后打开“模型配置”页填写。

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

脚本会初始化数据库，并为本次运行获取新的项目端口（优先后端 8000、前端 5173；若被其他程序占用则顺延）。这样代码更新后不会误复用旧的项目进程。缺失前端依赖时会自动修复。浏览器自动打开受系统限制时，脚本会保留服务并打印可手动打开的地址；以后端和前端启动时打印的实际 URL 为准。

停止服务：在启动终端按 `Ctrl+C`，PowerShell 包装器会清理本次启动的前后端子进程。若终端被强制关闭，重新运行 `start.bat` 会清理可识别的旧项目进程；不要手动结束同端口上的其他应用。

### 手动启动

若需要在已有终端中启动，分别执行：

```powershell
# 终端一：后端
cd C:\qiuzhao-agent\backend
.\.venv\Scripts\python.exe -m scripts.init_db
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 终端二：前端（手动启动时使用 5173；端口被占用时请改用其他端口，并同步设置 VITE_API_TARGET）
cd C:\qiuzhao-agent\frontend
corepack pnpm exec vite --open --port 5173 --strictPort
```

如果 `start.bat` 提示缺少前端依赖，先关闭占用 `frontend\node_modules` 的 Node.js 进程，再运行 `corepack pnpm install --force`。

### 验证

```powershell
cd C:\qiuzhao-agent\backend
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
cd ..\frontend
corepack pnpm test
corepack pnpm build
```

未配置 `TEST_DATABASE_URL` 时，数据库集成测试不会执行；这不应视为集成测试通过。

### 模型配置与密钥

设置页支持 OpenAI、Anthropic、DeepSeek、Qwen。网页保存的配置优先于同名 `.env` 配置；删除网页覆盖后自动回退到 `.env`。API Key 使用 Fernet 加密写入 `llm_provider_config`，接口只返回掩码，不写入浏览器存储。

要启用网页保存，请在 `.env` 增加一个仅服务端使用的 `LLM_CONFIG_SECRET`（可使用随机长字符串），然后重启后端并运行一次 `scripts.init_db`。不设置该变量时仍保持旧的 `.env-only` 模式，适合已有电脑和旧启动方式；此模式下任务无法加密保存配置快照，会按旧行为读取 `.env`。

任务创建时会保存 provider、model、Base URL 和 prompt 版本的配置快照。修改默认模型不会影响已创建的解析、面经、备战或问答任务。Base URL 只接受 `http/https`，不得携带用户名、密码、query 或 fragment。当前版本按本机单用户设计，请勿将后端端口直接暴露到公网。

模型调用会根据具体模型和兼容网关自动移除不支持的可选参数（例如推理模型不接受的 `temperature`）；网页“测试连接”使用与实际结构化任务相同的参数策略，四家 provider 均适用。

## 数据同步说明

**代码**通过 git 同步，**数据库数据不进 git**（在本地 PG 实例中）。换电脑时：
- 代码：`git clone` 即可。
- 配置：`.env` 不入库（含密码/key），需在新机重新创建。
- 数据：用 `pg_dump` / `psql` 手动导出导入，或后续改用云数据库（只需改 `.env` 连接串，代码无需改动）。
- 如果使用了网页模型配置，数据库备份中的 API Key 是密文；必须把 `LLM_CONFIG_SECRET` 通过独立安全渠道备份，不能写进 git。删除网页覆盖前请确认 `.env` 中仍有可用回退配置；更换密钥前需要先完成数据迁移，避免旧快照无法解密。

## 开发进度

见 [docs/工作计划.md](docs/工作计划.md)。第 1 至 5 期及近期真实使用反馈迭代均已完成。
