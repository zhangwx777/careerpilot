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
- `agent_run.user_message_id` 明确记录所属问题，避免并发问答按相邻消息猜测配对。
- `task_dispatch` 保存待派发记录、执行租约、次数和恢复状态；任务参数中的模型配置只能使用加密快照。
- `resume_profile` 保存当前简历文字；`planner_session` 保存备战分析快照；`preparation_task` 保存准备行动。
- `preparation_task` 同时保存该行动的参考答案载荷、用户自答和答案模式；练习内容归属单条行动，不跨行动复用。

## 主要控制流

### 通知解析

单条通知文本 → 任务快照选择 Provider → 结构化抽取候选字段 → `interrupt()` 等待人工核对并关联/创建投递 → 以原 `thread_id` 恢复 → 幂等写入一条时间线节点。

智能录入负责通知原文暂存、解析会话恢复、字段核对和单条节点确认；模型抽取只是候选值，不能直接落库。固定时间节点使用 `scheduled_at`；截止窗口节点只要求 `ends_at`，相对工作日截止从解析会话创建时间推算。它不负责投递进度管理或批量事件拆分；一条通知包含多个独立安排时，当前由用户分别确认录入。

### 面经聚合

用户文字或截图抽取 → 可选联网工具补充 → 相关性过滤 → 汇聚 → critic 反思与有限重抽取 → 仍有冲突时人工裁决 → 写入材料 → 生成岗位级洞察。

### 岗位问答

问题分类和确定性基础取证 → 有界 Agent 按需调用只读工具 → 服务端校验来源 ID、边界和预算 → 返回带来源范围与资料完整性标记的回答。

### 备战行动练习

备战分析产出准备行动 → 用户选中行动进入独立练习页 → `planner_coach` 按行动分类、关联差距和会话中的简历/JD/面经快照生成结构化参考答案 → 用户录入自答 → 返回针对该行动的结构化点评。练习状态由练习页闭环，求职地图不承载学习行动的完成逻辑。

LangGraph 负责固定控制流、循环和人工中断；有界 Agent 负责动态检索。Agent 不替代图的持久化、人工裁决或最终写库职责。

## LLM 与 Provider 边界

- 所有模型调用经过 `backend/app/llm/` 的统一入口，业务模块不写死 Provider 或模型。
- Provider、模型、Base URL 和加密 Key 来自设置页或任务创建时的配置快照。
- 面经、备战、简报和图片识别四个角色各有独立的 Provider 映射，由统一入口按角色解析；角色未配置时回退全局默认，业务页面不在运行时临时选择模型。
- 任务使用快照，修改默认模型不改变已创建任务；历史会话继续使用保存时的 Provider 快照。
- 原始第三方异常和密钥不得进入响应、日志或持久化记录。

## 数据真实性与安全边界

- 模型无法确定的字段保持 `null` 或空值，不用常识补造。
- 回答只能引用本次工具实际返回且仍有效的来源 ID。
- 删除材料后，其来源快照不得继续作为有效引用。
- Agent 工具只读，不能直接写入、删除或推进投递、面经、时间线和简历。
- 用户原文、JD、简历、面经和联网结果均按不可信输入处理。

## 后台任务与恢复

API 负责创建会话/运行记录并提交 Celery；worker 执行长任务。Docker 环境的 Redis 由 Compose 管理，桌面环境的任务队列运行时由安装包管理。两种环境都不允许静默降级或切换到未声明的服务。

业务会话与 `task_dispatch` 在同一事务提交，再派发到 Celery。队列不可用时保留 pending 并自动重新派发，不把任务误报为完成。通知解析也使用此协议；仅测试用轻量 fake 保留进程内派发入口。

worker 只能认领 pending/dispatched 记录，认领后生成 lease token，每 10 秒续心跳。API 每 10 秒巡检并恢复超过 60 秒无心跳的执行；预览、状态和最终写入必须在事务内锁定并验证同一 token。已完成的业务结果在恢复时直接认定完成，避免模型重复调用；恢复超过重试次数后进入可解释的失败状态。旧版本没有派发记录的失联会话转为可重试失败，不盲目重新写库。

岗位洞察由 `position.intel_revision` 标识当前材料与重建请求。材料新增、删除和用户重建在事务内更新版本，洞察仅能回写对应版本。问答提交前重新检查所引用材料的存活状态；历史回答可保留阅读，但失效引用单独标记，并禁止再次作为有效对话证据。关联岗位材料的有效性按材料本身检查。

工具列表、搜索状态和资料模式来自实际执行记录；模型不决定执行事实。实际搜索失败必须向用户说明，材料失效时清除旧预览并要求重试。

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
