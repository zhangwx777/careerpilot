# 系统架构

本文档记录 CareerPilot 当前稳定的系统边界、数据关系和设计约束。它不记录阶段进度；进度以 [`roadmap.md`](roadmap.md) 为准。

## 系统边界

CareerPilot 是本地单用户应用，分为两条明确的运行链路：Docker Compose 负责开发/服务器环境，Electron 安装包负责 Windows 桌面环境。两条链路共享应用代码和数据契约，但不共享启动脚本。React/Vite 前端通过 FastAPI 后端访问 PostgreSQL；Celery 执行耗时任务；LangGraph 管理需要恢复和人工确认的固定流程；LiteLLM 统一模型调用。

```text
Docker Compose（开发/服务器）
  frontend ── HTTP ── backend ── SQLAlchemy ── postgres
                           │
                           ├── LiteLLM / provider layer
                           ├── LangGraph + Postgres checkpoint
                           └── worker ── Redis

Electron 安装包（Windows 桌面）
  Electron ── HTTP ── backend ── PostgreSQL（随包）
                       └── worker ── 随包任务队列运行时
```

公开检索是独立配置的联网工具适配器，不是模型本身的联网能力。

## 领域关系

- `company` 归档公司，`position` 归档岗位，`application` 表示一次独立投递；同一岗位的多次投递不合并。
- `application` 可拥有多个 `timeline_node`、`interview_intel` 和会话记录。
- `parse_session` 保存通知解析的可恢复状态；`intel_session` 保存面经聚合状态。
- `intel_chat_message` 保存岗位问答；`agent_run` 保存对应的只读 Agent 运行轨迹。
- `resume_profile` 保存当前简历文字；`planner_session` 保存备战分析快照；`preparation_task` 保存准备行动。

## 主要控制流

### 通知解析

文本输入 → 任务快照选择 Provider → 结构化抽取 → `interrupt()` 等待人工确认 → 以原 `thread_id` 恢复 → 幂等写入投递/时间线。

### 面经聚合

用户文字或截图抽取 → 可选联网工具补充 → 相关性过滤 → 汇聚 → critic 反思与有限重抽取 → 仍有冲突时人工裁决 → 写入材料 → 生成岗位级洞察。

### 岗位问答

问题分类和确定性基础取证 → 有界 Agent 按需调用只读工具 → 服务端校验来源 ID、边界和预算 → 返回带来源范围与资料完整性标记的回答。

LangGraph 负责固定控制流、循环和人工中断；有界 Agent 负责动态检索。Agent 不替代图的持久化、人工裁决或最终写库职责。

## LLM 与 Provider 边界

- 所有模型调用经过 `backend/app/llm/` 的统一入口，业务模块不写死 Provider 或模型。
- Provider、模型、Base URL 和加密 Key 来自设置页或任务创建时的配置快照。
- 任务使用快照，修改默认模型不改变已创建任务。
- 原始第三方异常和密钥不得进入响应、日志或持久化记录。

## 数据真实性与安全边界

- 模型无法确定的字段保持 `null` 或空值，不用常识补造。
- 回答只能引用本次工具实际返回且仍有效的来源 ID。
- 删除材料后，其来源快照不得继续作为有效引用。
- Agent 工具只读，不能直接写入、删除或推进投递、面经、时间线和简历。
- 用户原文、JD、简历、面经和联网结果均按不可信输入处理。

## 后台任务与恢复

API 负责创建会话/运行记录并提交 Celery；worker 执行长任务。Docker 环境的 Redis 由 Compose 管理，桌面环境的任务队列运行时由安装包管理。两种环境都不允许静默降级或切换到未声明的服务。

## 启动与发行边界

- Docker Compose 只属于开发/服务器入口，负责启动 frontend、backend、worker、PostgreSQL 和 Redis。
- `desktop/main.cjs` 只属于已安装桌面应用，负责启动随包 PostgreSQL、任务队列、API 和 worker。
- Inno Setup 只负责安装桌面运行时和创建快捷方式，不调用开发启动脚本。
- 桌面包不依赖宿主机的 Python、Node.js、pnpm、PostgreSQL、Redis 或 Docker。
- Docker Compose 不参与桌面安装包运行，也不会被打进安装包。

需要人工确认或进程重启恢复的图使用 PostgreSQL checkpoint 和业务 session 的 `thread_id`。持久化节点必须使用事务、必要的行锁和幂等检查，重复恢复不能重复写库。

## 当前明确不属于架构的事项

- 自动投递、邮件接入和外部推送；
- 多用户、权限系统和公网部署；
- 向量数据库；
- Agent 写库、删除或状态推进工具；
- 为单个模型 Provider 复制专用业务调用层。
