# Agent 体系与 Claude 升级方案

> 评估对象：`pasted-text.txt` 中关于“LangGraph Workflow + 受约束 ReAct Agent”的方案
>
> 评估时间：2026-09-11
>
> 适用项目：职航 CareerPilot（个人自用、单用户、以面经和岗位资料为核心）

## 1. 结论

原方案可行，且与当前项目的真实形态基本吻合。推荐采用混合架构：

- `parse_graph`、`planner_graph`、每日巡检继续使用固定 Workflow。
- 面经问答先升级为“轻量、受限 ReAct Agent”。
- 面经研究在现有 `intel_graph` 中只替换“如何检索”的部分，保留聚合、Reflection、人工裁决和持久化。
- 暂不做全系统 Agent、Multi-Agent、向量数据库或 Agent 写库工具。

Claude 接入与 Agent 接入是两个不同问题。当前仓库已经通过 LiteLLM 具备 Anthropic provider：`config.py`、`llm/registry.py` 和 `llm/provider.py` 都支持 `anthropic`，前端 provider 列表也会读取已配置的模型。因此不需要再引入一套 Claude 专用 SDK；需要补的是工具调用运行时、权限边界、预算、追踪和评估。

## 2. 对原方案的可行性评估

### 2.1 已经具备的基础

当前实现已经提供了原方案所需的大部分“外层骨架”：

- LangGraph 已用于通知解析和面经聚合，`PostgresSaver` 通过 `thread_id` 支持进程重启后的恢复。
- `intel_graph` 已有搜索、抽取、汇聚、critic 反思、`interrupt()` 人工裁决和幂等写入。
- AnySearch 已通过 HTTP MCP 接入，`anysearch.py` 将搜索结果标准化为标题、URL、正文和发布时间。
- `InterviewIntel`、`IntelSession`、`IntelChatMessage`、`Position.intel_insight` 已覆盖材料、会话、问答和岗位洞察。
- 所有模型调用已收敛到 LiteLLM，调用方显式传入 provider，缺 key 或 model 时会失败而不是静默切换。

### 2.2 原方案需要修正的地方

1. **“加入 Claude”不能等同于“加入 Agent”。** Claude 只是一种模型 provider；是否是 Agent，取决于模型能否在受控循环中选择工具并返回工具调用结果。
2. **现有岗位问答还不是 Agent。** `intel_api.py` 的 `_chat_context()` 会读取整份岗位 dossier，`_chat_messages()` 再把所有来源正文一次性放入上下文；模型没有选择资料的机会。
3. **AnySearch 还不是通用 Agent 工具。** 它目前是面经图中的固定搜索节点。需要把它包装成有输入约束、调用计数和来源返回契约的只读工具。
4. **不能直接把 `create_react_agent` 当成完成方案。** 当前环境能导入 `langgraph.prebuilt.create_react_agent`，但该 API 已标记为迁移方向；实现前应以当前锁定依赖做一个最小工具调用 Spike，确认 LiteLLM 返回的 tool calls、结构化输出和 Claude 配置都能闭环。
5. **Agent 不应绕过现有写库流程。** `InterviewIntel`、`TimelineNode`、投递状态等写入仍须经过固定节点和人工确认；Agent 只读资料并生成草稿。

### 2.3 主要风险与控制方式

| 风险 | 具体表现 | 控制方式 |
| --- | --- | --- |
| 模型不支持工具调用 | Claude 配置或代理端点只支持普通文本 | 启动前检查 provider/model；用 mock 和一次真实 smoke test 验证 tool calls |
| Agent 无限循环 | 重复查询、费用和延迟失控 | 步骤数、个人资料读取次数、公开搜索次数、总耗时统一设上限 |
| 越权读资料 | 跨公司或跨岗位混入上下文 | 工具输入必须带 `application_id`/`position_id`，查询层强制限定范围 |
| 无来源回答 | 模型把通用知识说成岗位事实 | 输出强制 `source_ids`；服务端只接受实际返回的来源 ID |
| 结果不可复盘 | 无法区分模型判断、工具错误和空数据 | 每次 Agent 运行记录 run、步骤、工具参数摘要、耗时和错误 |
| 引入范围过大 | 全量重写已有图，回归风险高 | 先改问答，再改面经研究；固定 Workflow 和数据库写入不动 |

## 3. 目标架构

```text
API / session / 权限 / 人工确认 / 持久化
                    │
              LangGraph Workflow
          ┌─────────┴─────────┐
          │                   │
   固定业务节点        受限 ReAct Agent 子图
   聚合/校验/写库       选择只读工具并推理
          │                   │
          └─────────┬─────────┘
                    │
             Domain read tools
       JD / 简历 / 面经 / 时间线 / AnySearch
```

一次岗位问答的目标流程：

1. API 保存用户问题和“生成中”的 assistant 消息。
2. Workflow 建立岗位范围和 Agent 预算。
3. Agent 按需调用只读工具，工具返回带来源 ID 的结构化资料。
4. Agent 生成 `answer`、`source_ids` 和资料不足说明。
5. 服务端过滤不存在的来源 ID，保存答案和 Agent 运行摘要。

一次面经研究的目标流程：

```text
创建 intel_session
  → 固定节点读取岗位/已有状态
  → 受限 Agent 选择检索动作
  → 固定 aggregate 合并结构化结果
  → 固定 critic 做来源/编造检查
  → 必要时 interrupt 人工裁决
  → 固定 persist 写入 InterviewIntel
```

通知解析、状态推进和每日巡检不进入 Agent 循环。它们输入输出明确、需要幂等和可重试，现有 Workflow 更适合。

## 4. 工具契约

第一版只允许以下只读工具：

| 工具 | 输入 | 返回 | 说明 |
| --- | --- | --- | --- |
| `read_current_jd` | `application_id` | JD 文本、岗位/公司标识 | 只读当前投递对应岗位 |
| `search_current_intel` | `application_id`、可选 `round_type`、关键词 | 结构化面经摘要及来源 | 只查当前岗位的已保存材料 |
| `search_related_intel` | `company_id`、关键词、可选岗位过滤 | 相关岗位材料及来源 | 明确标记为跨岗位参考 |
| `read_resume` | 无或当前用户范围 | 简历文本及档案标识 | 当前单用户只读唯一简历档案 |
| `search_timeline` | `application_id` | 时间线节点 | 只读，不改变状态 |
| `search_public_intel` | 查询词 | AnySearch 结果及来源 | 联网工具；按公开搜索预算计数 |

每个工具必须有 Pydantic 输入/输出模型，并在契约中注明：只读、是否联网、最大返回条数、失败时的可展示错误。工具不得接收任意 SQL、表名或未校验的岗位范围。

Agent 不能调用以下操作：创建或删除面经、写入时间线、更新投递状态、删除材料、修改简历、发送外部通知。

## 5. 运行边界与输出契约

建议第一版固定为：

- 每次最多 5 个 Agent 步骤。
- 每次最多 3 次个人资料检索。
- 每次最多 2 次公开搜索。
- 沿用现有单次模型超时和重试配置，另加一个 Agent 总耗时上限。
- 达到上限时，基于已取得资料回答，并明确说明资料可能不完整。

内部输出模型建议包含：

```json
{
  "answer": "完整中文回答",
  "source_ids": ["material-12:session-3:web-1-2"],
  "insufficient_data": false,
  "used_tools": ["read_current_jd", "search_current_intel"]
}
```

对外继续使用现有问答 API 的 `answer` 和 `source_ids` 字段；`insufficient_data`、工具轨迹和预算信息用于内部记录或进度展示。服务端必须把 `source_ids` 与本次工具实际返回的来源集合做交集，不能信任模型自行编造的 ID。

## 6. Claude 接入方案

### 配置

Provider 的 API key、Base URL 和 model 只从网页“模型设置”保存到本地数据库，并以加密快照绑定到任务；`.env` 不再提供 provider 回退。数据库未配置时，任务应明确失败，不能静默切换其他 provider。

### 验证顺序

1. 先完成工作区基线清理、失败测试归因和 provider 下拉真实 API 验证。
2. 用最小工具验证 Claude 是否返回标准 tool call，并能接收工具结果后继续回答。
3. 再用至少一个当前实际配置的 Qwen/OpenAI/DeepSeek 模型完成同样闭环。
4. 验证来源 ID、中文回答、长度上限和“不支持工具调用”的明确失败；不增加另一套 provider 抽象。

若实际 Anthropic 代理端点不支持 tool calls，先保留 Claude 作为固定节点模型，不强行将其用于 Agent；Agent provider 需在真实能力验证后决定。

## 7. 分阶段开发计划

### 第 0 阶段：基线与 Tool-call Spike（1 个工作日）

**任务**

- 先记录当前工作区改动归属，解决已知测试失败并确认 provider 下拉运行正常。
- 固定 Agent 输入、工具 schema、输出 schema 和预算常量。
- 用 mock 模型跑通“模型请求 → 工具调用 → 工具结果 → 最终回答”。
- 用数据库中已配置的 Anthropic 模型和第二家真实 provider 各做一次非 CI smoke test。
- 确认当前 LangGraph 版本下使用的 Agent API，不在未验证前升级整套 LangChain 依赖。

**交付**：throwaway 工具调用样例、契约测试、依赖结论和基线报告；Spike 不写业务表。

**验收**：Fake 和至少两个真实 provider（含 Anthropic）完成两轮闭环；不支持工具调用时明确失败，不影响现有固定 Workflow。未满足则停止，不进入正式 Agent。

### 第 1 阶段：只读工具与 Agent Runtime（2—3 个工作日）

**任务**

- 新增 `backend/app/agent_schemas.py`：工具输入输出、Agent 结果和预算模型。
- 新增 `backend/app/agent_tools.py`：复用现有 dossier、`_position_intels`、简历和时间线查询逻辑；AnySearch 只作为联网工具封装。
- 新增 `backend/app/agent_runtime.py`：模型绑定工具、循环上限、工具调用计数、来源收集、错误和超预算处理。
- 在 `config.py` 增加必要的 Agent 预算配置，默认值与第 5 节一致。
- 运行轨迹先记录为结构化日志，并为每次运行保留 run_id、thread_id、步骤数、工具名、耗时、错误和最终状态。

**验收**

- 所有工具在越界 application/position 下返回空或明确错误。
- Agent 永远不能调用写库函数。
- 超过任一预算后能结束并返回已有资料，而不是继续循环。

### 第 2 阶段：岗位问答接入 Agent（2—3 个工作日）

**任务**

- 保留 `POST /api/intel/chat` 的创建、轮询和历史读取接口。
- 将 `_run_intel_chat` 的“全量 dossier 拼接”替换为 Agent Runtime；初始上下文只放岗位标识和用户问题。
- 保留现有 `IntelChatMessage` 状态机、增量预览和失败落库逻辑。
- 统一来源过滤：只保存工具实际返回的来源 ID。
- 增加问答 Agent 的运行摘要，便于页面或日志排查“为什么读了这些资料”。

**验收**

- “当前岗位二面最可能考什么”会先读当前 JD/面经，再按需搜索。
- 资料不足时明确说不足，不把通用知识伪装成个人资料。
- 旧有无面经 409、失败状态、历史问答和前端轮询测试继续通过。

### 第 3 阶段：面经研究嵌入 Agent（3—5 个工作日）

**任务**

- 在 `intel_graph.py` 中新增一个 Agent 检索节点，替换固定的搜索词序列；不改 `aggregate`、`critic`、`review`、`persist` 的业务职责。
- Agent 只能返回候选来源，来源相关性过滤、去重和 `SourceRecord` 校验仍由服务端执行。
- 继续使用现有 `IntelSession.thread_id` 和 `PostgresSaver`，Agent 步骤与外层图共享同一恢复边界。
- 保留现有最多 3 次补搜、反思重抽取和人工裁决语义；Agent 预算不能覆盖这些外层硬上限。

**验收**

- 手动文本/截图路径不受影响。
- 公开检索失败时仍能保留已有内容并完成可解释的失败状态。
- 冲突仍进入 `interrupt()`，Agent 不能直接写入 `InterviewIntel`。
- 现有面经图的循环、反思、恢复、幂等测试全部通过。

### 第 4 阶段：追踪、评估与上线（2—3 个工作日）

**任务**

- 建立一组真实但脱敏的问题集：岗位重点、JD/简历差距、历史项目深挖、跨岗位参考、资料不足。
- 测量答案是否引用正确来源、是否混淆岗位、是否误把通用知识当个人事实、是否调用了不必要工具。
- 记录每题的工具调用数、延迟、失败率和人工修改情况。
- 先在本地个人使用中运行一轮，再决定是否替换面经研究的固定检索节点。

**验收**：评估集达到可接受结果后再合并；未达到时只保留问答 Agent 或退回固定检索，不引入 Multi-Agent。

## 8. 预计改动文件

第一版实现预计触及以下文件，按阶段提交，避免一次性大改：

```text
新增  backend/app/agent_schemas.py
新增  backend/app/agent_tools.py
新增  backend/app/agent_runtime.py
新增  backend/app/models.py 中的 AgentRun 表
修改  backend/app/config.py
修改  backend/app/intel_api.py
修改  backend/app/intel_graph.py
修改  backend/tests/test_intel_features.py
新增  backend/tests/test_agent_runtime.py
新增  backend/tests/test_agent_tools.py
必要时修改 backend/app/models.py、backend/scripts/init_db.py
```

`AgentRun` 保存运行状态、预算、步骤摘要、来源快照和安全错误分类（如 `unsupported_tool_call`）；步骤不保存完整 prompt 或密钥。失败后台任务必须 `logger.exception`，数据库只保存安全错误。

## 9. 测试与验收清单

### 单元测试

- 工具只返回指定 `application_id`/`position_id` 的资料。
- 空 JD、无简历、无面经、无时间线时返回可处理的空结果。
- AnySearch 结果被正确转成带 URL 和来源 ID 的记录。
- 工具调用次数达到上限后停止。
- 模型返回未知来源 ID 时被服务端过滤。
- 模型返回非法 JSON、空回答或错误 tool arguments 时进入失败路径。

### 集成测试

- mock Claude/LiteLLM 完成多轮工具调用。
- Agent 运行与 `IntelChatMessage` 的“生成中 → 已完成/失败”状态一致。
- PostgreSQL `thread_id` 恢复后不会重复写库。
- 面经 Agent 触发冲突时仍暂停在 `interrupt()`，恢复后只写入一次。
- 原有 parse/intel/planner/briefing 测试无回归。

### 人工验收

- 使用当前岗位真实 JD 和至少一份面经提问，最终回答继续流式预览，工具轮次只显示阶段文字。
- 提问跨岗位参考问题，确认回答明确标注参考范围。
- 删除某份材料后再次提问，确认不会继续引用已删除来源。
- 临时关闭 AnySearch，确认本地资料问答仍可工作。
- 用 Anthropic provider 和第二个当前已配置的 Qwen/OpenAI/DeepSeek provider 各跑一轮；若第二家未配置，Spike 不算通过。

运行 PostgreSQL/LangGraph 集成测试前必须设置独立的 `TEST_DATABASE_URL`；未配置导致的 skip 不算通过。真实 Claude smoke test 不放入默认 CI，避免把 API 费用和外部网络作为提交门槛。

## 10. 明确暂不做的事项

- 不把通知解析、状态机、每日巡检改成 Agent。
- 不做简历 Agent、公司研究 Agent、汇总 Agent 的 Multi-Agent 拆分。
- 不给 Agent 开放任何写库、删除或状态推进工具。
- 不先引入向量数据库；当前结构化查询和已有 `IntelPayload` 足以支撑第一版。
- 不新增自动投递、邮件接入、外部推送或云端部署。
- 不因为接入 Claude 而复制一套 Anthropic 专用调用层。

## 11. 最终决策标准

满足以下条件才进入下一阶段：

1. 工作区形成可回退基线，已知失败测试已归因，provider 下拉真实 API 正常。
2. Fake、Anthropic 和第二家真实 provider 的 tool-call 闭环通过；不支持工具调用时明确失败。
3. 工具边界、来源过滤、预算、流式预览和问答状态测试通过。
4. 评估集显示 Agent 比当前“全量 dossier 注入”有可测量收益，才启动面经研究检索 Agent。
5. 现有面经图的人工裁决、恢复和幂等行为不回退。

如果第 4 条没有收益，停止在“Workflow + 固定问答”也成立；Agent 不是为了改变架构而改变架构。
