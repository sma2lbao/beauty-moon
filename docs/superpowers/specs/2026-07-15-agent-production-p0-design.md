# Agent 生产化 P0（阻断级）设计

> 状态：设计已确认，待用户 review
> 日期：2026-07-15
> 范围：将 `apps/luna-corpus` 的 agent 从"能演示的原型"升级为"可上生产的可用 agent"

## 结论摘要

现有 `app/agent/` 有 4 个模式骨架（direct / react / plan / langgraph），但均为半成品：

- `langgraph` 的 complex 分支只执行一步就收尾，谈不上多步自主。
- 工具调用靠 `TOOL_CALL: {...}` 文本协议 + 正则解析，脆弱。
- agent 路由未接入已建好的治理设施（成本计量 / 配额 / 审计 / 会话记忆 / 租户隔离），是"孤岛"。
- 无执行安全边界（步数/超时/递归/成本熔断）。
- 无可观测轨迹（每步 reasoning/tool-call/结果不落库，无法回放排障）。

本设计定义 **P0 阻断级** 的 5 条改动，不补齐则不算"可用的 agent"：

| # | P0 条目 | 落点 |
| --- | --- | --- |
| 1 | 真正的多步 agent 循环（跑到收敛，替换"只走一步"） | `core/llm_loop.py` |
| 2 | 原生 function-calling 工具协议（替换 `TOOL_CALL:` 正则） | `core/llm_loop.py` |
| 3 | agent 接入现有基础设施（成本/配额/审计/会话记忆/租户隔离） | `core/context.py` + 管线 |
| 4 | 工具执行安全边界（步数/超时/递归/成本熔断） | `core/governance.py` |
| 5 | 可观测的 agent 轨迹（每步落库、可回放） | `core/trace.py` + 两张表 |

### 已确认的关键决策

1. **模式收敛**：保留 4 个模式，全部升级到生产级 —— 通过抽取共享"生产内核"，模式只保留编排策略差异，避免 ×4 工作量。
2. **会话记忆**：agent 支持多轮会话，复用现有 conversation/message 表与 `app/services/memory.py`。
3. **轨迹存储**：专用轨迹表 `agent_runs` + `agent_steps`。
4. **成本熔断**：每步预检，超限即停；已跑步骤照常落库计费；配额服务不可用时 fail-open（与现有 cost 模块一致）。

### 技术底确认

- LLM provider 为 ARK（走 `langchain_openai.ChatOpenAI` → OpenAI 兼容接口），**原生支持 function-calling**；Ollama 亦支持。用 LangChain `bind_tools` 可一套代码覆盖两个 provider。
- `app/agent/tool.py` 的 `Tool` 已具备 `executor` 与 OpenAI 格式的 `get_schema()`，**工具层零改动**。
- `app/services/llm.py` 已有 `extract_usage` / `TokenUsage`，可直接接成本计量。
- `app/services/memory.py` 已有会话历史载入函数，可直接复用。
- `app/cost/enforcement.py`、`app/security/audit.py` 已存在，直接接入。

---

## 第 1 节：架构骨架（共享生产内核）

核心思路：4 个模式全要升级，不逐个改，而是抽一层所有模式共用的"生产内核"，模式只保留各自的编排策略差异。

```
apps/luna-corpus/app/agent/
├── core/                      ← 新增：共享生产内核
│   ├── llm_loop.py            # function-calling 循环引擎（bind_tools + 工具执行 + 收敛）
│   ├── governance.py          # 每步预检钩子：配额熔断 / 步数 / 超时 / 递归深度
│   ├── trace.py               # 轨迹记录器：写 agent_runs / agent_steps
│   └── context.py             # AgentRunContext：贯穿一次执行的 tenant/kb/conversation/user/run_id
├── modes/                     ← 改造：4 个模式都基于 core 重写
│   ├── direct.py              # 单轮 + 可选一次工具调用
│   ├── react.py               # 思考-行动循环（用原生 tool_calls，去掉正则）
│   ├── plan_execute.py        # 先规划再执行
│   └── langgraph.py           # 状态机（complex 分支真正多步）
├── base.py / factory.py / registry.py / tool.py   ← 微调
```

### 执行管线（包住所有模式）

```
agent_routes → AgentRunContext 构建（记忆载入 + 启动预检）
            → TraceRecorder.start_run()
            → mode.run(ctx)              # 每个模式内部循环时，每步都调 governance.check()
                                          #   每步都调 trace.record_step()
            → TraceRecorder.end_run()（挂成本、状态、latency）
            → 会话消息落库（复用 memory）+ 审计日志（复用 audit）
```

模式之间的**唯一差异**是"如何决定下一步"（direct 不循环 / react 边想边做 / plan 先列计划 / langgraph 走状态图）。**function-calling、治理预检、轨迹落库、记忆、成本计量这 5 样全模式共享，只写一遍。**

核心取舍：一个共享内核 + 薄模式层，而非 4 份独立实现。4 模式全升级的工作量为 ×1 内核 + 4 个薄壳。

---

## 第 2 节：数据模型（agent_runs + agent_steps）

设计原则与现有 cost/quality 表一致：零耦合、带全套隔离键、可聚合、可回放。全部走 Alembic 迁移，不碰 `create_all`。

### 表 1：`agent_runs`（一次 agent 执行 = 一行）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str PK | run_id，贯穿全链路 |
| `tenant_id` / `workspace_id` / `knowledge_base_id` | str, indexed | 隔离键（与现有表对齐） |
| `user_id` | str, indexed | 发起人 |
| `conversation_id` | str, nullable, indexed | 关联多轮会话（复用现有表） |
| `mode` | str | direct/react/plan/langgraph |
| `query` | text | 原始输入 |
| `final_answer` | text, nullable | 最终答复 |
| `status` | str | `running`/`completed`/`failed`/`halted_quota`/`halted_max_steps`/`halted_timeout` |
| `steps_count` | int | 实际步数 |
| `total_input_tokens` / `total_output_tokens` | int | 聚合用量 |
| `total_cost` | Numeric | 聚合成本（复用 cost 折算） |
| `latency_ms` | int | 总耗时 |
| `error_message` | text, nullable | 失败/熔断原因 |
| `created_at` / `finished_at` | datetime | 时间戳 |

### 表 2：`agent_steps`（一步 = 一行，属于某个 run）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str PK | |
| `run_id` | str FK→agent_runs, indexed | 所属 run |
| `step_index` | int | 第几步（从 0 起） |
| `step_type` | str | `reasoning`/`tool_call`/`tool_result`/`final` |
| `thought` | text, nullable | 该步推理内容 |
| `tool_name` | str, nullable | 调用的工具 |
| `tool_args` | JSON, nullable | 工具入参 |
| `tool_result` | text, nullable | 工具返回（截断存储，上限 8KB） |
| `tool_success` | bool, nullable | 工具是否成功 |
| `input_tokens` / `output_tokens` | int, nullable | 该步 LLM 用量 |
| `latency_ms` | int | 该步耗时 |
| `created_at` | datetime | 时间戳 |

### 关键设计点

1. **run 上聚合、step 上明细**：成本/配额熔断挂在 run 级累加，排障时按 `run_id` 拉出完整 step 序列即可回放。
2. **`tool_result` 截断落库**：上限 8KB，超长截断并标记，避免大检索结果撑爆表。
3. **`status` 区分熔断类型**：`halted_quota` / `halted_max_steps` / `halted_timeout` 三种"主动停"与 `failed`（异常）分开，运营能直接看出 agent 被谁掐停。
4. **回放 API**：
   - `GET /api/v1/agent/runs/{run_id}` 返回 run + 有序 steps，权限 `KNOWLEDGE_BASE_READ`。
   - `GET /api/v1/agent/runs` 列表，支持按 conversation/user/status 过滤。

---

## 第 3 节：执行管线与治理

### 3.1 `core/llm_loop.py` —— 原生 function-calling 循环引擎

替换掉所有 `TOOL_CALL:` / JSON 正则解析。核心循环：

```
messages = [system, ...memory_history, user_query]
bound = chat.bind_tools([t.get_schema() for t in registry])   # 原生 function-calling

for step_index in range(max_steps):
    governance.check(ctx, step_index)          # 每步预检（见 3.2），不过则抛 HaltSignal
    response = bound.invoke(messages)          # LLM 决定：回答 or 调工具
    usage = extract_usage(response, ...)       # 复用现有 token 提取
    trace.record_step(reasoning, usage, ...)   # 落 agent_steps
    accumulate_usage_to_run(usage)             # run 级累加，供下一步预检

    if not response.tool_calls:                # 没有工具调用 = 收敛，得到 final answer
        trace.record_step(type="final", ...)
        return response.content

    for call in response.tool_calls:           # 执行 LLM 请求的每个工具（P0 串行）
        tool = registry.get(call.name)
        result = await tool.execute(**call.args)   # 复用现有 Tool.execute
        trace.record_step(type="tool_call"/"tool_result", tool_name, args, result, ...)
        messages.append(tool_call_msg)
        messages.append(tool_result_msg)       # 原生 role=tool 消息回灌
# 循环用尽 max_steps 未收敛 → status=halted_max_steps，用已有信息强制生成一次 final answer
```

**关键点：**

- 用 LangChain 原生 `bind_tools` + `response.tool_calls`，ARK（OpenAI 兼容）和 Ollama 都支持，一套代码两个 provider。
- `Tool.get_schema()` 已是 OpenAI 格式，`Tool.execute()` 已存在——工具层零改动，循环改用原生协议驱动它。
- 4 个模式的差异收敛为"如何构造 messages / 是否循环"：`direct` 只跑一轮、`react` 全量循环、`plan` 先让 LLM 产出计划再循环执行、`langgraph` 在状态图节点里调这个 loop。引擎只写一遍。

### 3.2 `core/governance.py` —— 每步预检钩子

每步开始前按顺序检查，任一不过就抛 `HaltSignal(reason)`，被管线捕获后把 run 标记为对应 `halted_*` 状态并优雅收尾（已跑步骤照常落库、照常计成本）。

| 检查项 | 逻辑 | 触发状态 |
| --- | --- | --- |
| **配额熔断** | 复用现有 `cost/enforcement.py` 检查；**fail-open**（配额服务挂了不阻断） | `halted_quota` |
| **步数上限** | `step_index >= max_steps`（`settings.agent_max_steps`，默认 10） | `halted_max_steps` |
| **墙钟超时** | `now - run.start > settings.agent_timeout_s`（新增配置，默认 120s） | `halted_timeout` |
| **递归深度** | 工具触发子 agent 时的嵌套深度上限（防自我调用爆栈；P0 只设硬上限） | `halted_max_steps` |

**治理与成本的咬合**：每步 LLM 调用后，用量立即累加到 run 级 `total_*`，下一步预检时配额检查看到的是"已消耗到此刻"的真实值——熔断跟着实际花销走，不是启动时一次性估算。

### 3.3 管线串接（agent_routes 改造）

```
1. 构建 AgentRunContext（tenant/kb/user/conversation + run_id）
2. 载入会话记忆（复用 app/services/memory.py）
3. trace.start_run()  → 落 agent_runs(status=running)
4. try: answer = await mode.run(ctx)          # 内部走 3.1/3.2
   except HaltSignal as h: status = h.status
   except Exception: status = failed
5. trace.end_run(status, totals, latency)
6. 写会话消息（复用 memory）+ 审计日志（复用 security/audit）
7. 返回 AgentQueryResponse（新增 run_id 字段，便于前端拉轨迹）
```

**审计接入**：agent 执行作为一个可审计事件写 `audit_logs`（复用现有），补上 P0#3 里 agent"绕过治理"的最后一个缺口。

---

## 第 4 节：错误处理、流式、测试策略

### 4.1 错误处理（分层，绝不让 agent 把服务拖垮）

| 场景 | 处理 | 落库状态 |
| --- | --- | --- |
| 单个工具执行抛异常 | `Tool.execute` 已捕获返回 `ToolResult(success=False, error=...)`；把 error 作为 tool_result 回灌给 LLM，让它自行决定重试/换路/放弃 | step 记 `tool_success=false`，run 继续 |
| LLM 调用失败（网络/超时） | 循环内捕获，run 标 `failed` + `error_message`，返回已收集的部分轨迹 | `failed` |
| 治理熔断 | `HaltSignal` → 优雅收尾，已跑步骤照常落库计费 | `halted_*` |
| LLM 反复调工具不收敛 | 撞 `max_steps` 上限 → 用已有信息强制生成一次 final answer | `halted_max_steps` |
| 轨迹落库失败 | **fail-safe**：trace 写库异常不阻断主流程（与 cost/citation 一致），只记 warning | run 主流程不受影响 |

原则统一：**治理和可观测性是旁路，绝不阻断用户拿到答复；只有 LLM 本身挂了才算 failed。**

### 4.2 流式（run_stream 对齐新引擎）

统一 SSE 事件协议，4 模式一致：

```
event: run_start   { run_id }
event: step        { step_index, step_type, thought }
event: tool_call   { tool, args }
event: tool_result { result, success }
event: token       { delta }          # final answer 增量（复用现有 astream）
event: done        { answer, run_id, steps, status }
event: error       { message }
```

轨迹落库在流式下同步进行（每 yield 一个 step 事件的同时 record_step），保证流式与非流式落库行为一致。

### 4.3 测试策略

沿用现有 `tests/agent/` 结构，分三层：

1. **单元**：`llm_loop`（mock LLM 返回 tool_calls → 验证工具被调、收敛、max_steps 截断）；`governance`（每种 halt 触发点）；`trace`（run/step 落库字段正确、fail-safe 不抛）。
2. **集成**：`tests/agent/test_integration.py` 扩展——4 模式各跑一条 mock 全链路，验证 run+steps 落库、成本累加、记忆载入、审计写入。
3. **回归兜底**：配额耗尽 → `halted_quota` 且部分步骤已计费；工具抛异常 → run 不崩、error 回灌。

关键用例用 **mock LLM**（不打真实 provider），保证 CI 可跑、确定性。

### 4.4 明确不做（YAGNI，划归 P1）

- 工具**并行**调用（P0 串行执行 LLM 请求的多个 tool_calls 即可）。
- 子 agent / agent 编排 agent（递归深度 P0 只设防护上限，不做真正的多 agent）。
- 人工审批中断（human-in-the-loop）。
- 动态注册工具的**可执行体**（现在 `POST /tools` 只存 schema；P0 保持现状，不打通执行——在 spec 中标注为已知限制）。

---

## 部署/运维待办（实现完成后手动执行）

- 运行 Alembic 迁移创建 `agent_runs` / `agent_steps` 两表。
- 新增配置项：`AGENT_TIMEOUT_S`（默认 120）、递归深度上限；确认 `AGENT_MAX_STEPS` 已存在。

## 已知限制（P0 内不解决）

- 动态注册工具无可执行体，注册后不可调用。
- 无工具并行、无多 agent 编排、无人工审批中断。
