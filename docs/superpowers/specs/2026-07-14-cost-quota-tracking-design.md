# 成本与配额统计（统计 + 硬限流）设计

- 日期：2026-07-14
- 应用：`apps/luna-corpus`（FastAPI + SQLAlchemy + Alembic）
- 状态：设计已确认，待写实现计划

## 1. 目标与范围

为多租户 RAG 系统提供 LLM 用量的**计量、成本折算、配额准入**能力：

1. **计量**：捕获每次问答生成的 token 用量，折算成本，落明细并按租户/工作区聚合。
2. **硬限流**：为租户/工作区设置日度配额阈值，超额请求直接拒绝（HTTP 429）。

### 已确认的决策

| 决策点 | 选择 |
|---|---|
| 目标程度 | 统计 + **硬限流**（超限拒绝，非软告警） |
| 计量口径 | **双口径**：token 数 + 折算成本金额 |
| 配额层级 | **租户 + 工作区**两层，任一层任一口径超限即拒 |
| 时间窗口 | **日度**（UTC 日界，日期分行实现重置） |
| 故障降级 | **fail-open**：计量/配额组件故障时放行请求 |
| 价格表 | **数据库表**，含生效时间，可通过 API 管理 |
| 计量范围 | **仅问答生成**（chat LLM 的 `/qa/query` 与 `/qa/stream`） |

### 非目标（YAGNI）

- embedding / 质量评估 judge / rerank 等内部调用的计量（本期不纳入）。
- 配额预扣（reserve）与精确不超线：采用事前检查语义（见 §6）。
- 跨副本共享的分布式计数（沿用现有进程内限流的部署假设；分布式为后续 scale follow-up）。
- 强制「工作区配额 ≤ 租户配额」的一致性校验（由配置方自负）。
- 价格变动回溯重算历史成本（成本按记录时刻快照）。

## 2. 现状与集成点

- **多租户层级**：`Tenant → Workspace → KnowledgeBase`，经请求头传入，由 `AuthenticatedRequestContext`（`app/api/auth.py`）承载，携带完整 `tenant/workspace/knowledge_base`。
- **LLM 层**（`app/services/llm.py`）：当前 `generate_response` / `generate_streaming_response` **不返回 token 用量**。Provider 为 Ark（`ChatOpenAI`，OpenAI 兼容，付费）、Ollama（本地，免费）、Doubao（embedding）。
- **QA 路径**：同步 `answer_question`（`app/graph/rag_graph.py`）与流式 `answer_question_stream`，路由在 `app/api/routes.py` 的 `/qa/query`、`/qa/stream`。
- **旁路记录范式**：`app/quality/recorder.py` 的 `record_interaction` —— 任何异常都 log + rollback + swallow，保证 QA 请求永远成功。本设计复刻该范式。
- **可观测性**：`app/observability/metrics.py` 已有 Prometheus Counter/Histogram 体系。
- **RBAC**：`app/auth/permissions.py` 的 `PermissionSlug` + `require_permission` 依赖；角色 `WORKSPACE_ADMIN` / `KB_EDITOR` / `KB_READER`。
- **迁移**：Alembic，最新版本 `20260713_0012_prompt_governance`。

## 3. 架构总览

采用**路由层准入守卫 + 独立用量明细表 + 日度累加计数器**（方案 A）。数据流：

```
请求 → require_permission(QA_QUERY) → enforce_quota (准入, O(1) 读计数器, fail-open)
     → 生成 (answer_question / answer_question_stream)
          → llm.py 返回 (text, TokenUsage)
     → record_interaction (既有)
     → cost.recorder.record_usage (旁路: 折算 → 写明细 → 原子累加计数器 → 打指标)
```

分层原则：LLM 层只负责**返回 usage 数据**，不感知租户/配额；租户折算与配额逻辑集中在新的 `app/cost/` 模块与路由层。

新增模块 `app/cost/`（对齐 `app/quality/` 结构）：

- `pricing.py` —— 价格解析与成本折算。
- `recorder.py` —— 旁路记录用量明细并累加计数器。
- `enforcement.py` —— 配额准入依赖 `enforce_quota`。
- `service.py` —— 配额配置与用量查询的业务逻辑（供 API 调用）。

## 4. 数据模型（4 张新表）

新增 Alembic 迁移 `20260714_0013_cost_quota.py`，SQLAlchemy 模型加入 `app/db/models.py`。

### 4.1 `model_prices` —— 价格表

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | CHAR(36) PK | uuid |
| `provider` | String(20) | `ark` / `ollama` / `doubao` |
| `model` | String(100) | 模型名 |
| `input_price_per_1k` | Numeric(18,6) | 每 1k input token 单价 |
| `output_price_per_1k` | Numeric(18,6) | 每 1k output token 单价 |
| `currency` | String(3) | `CNY` / `USD` |
| `effective_from` | DateTime | 生效时刻（UTC） |
| `created_at` | DateTime | server_default now |

- 索引：`(provider, model, effective_from)`。
- 查询语义：取 `(provider, model)` 下 `effective_from ≤ at` 的最新一条。
- Ollama 等本地模型单价填 0，仍入表，保证折算逻辑 provider 无关。

### 4.2 `usage_records` —— 用量明细（每次问答一条）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | CHAR(36) PK | |
| `tenant_id` | CHAR(36) | index |
| `workspace_id` | CHAR(36) | index |
| `knowledge_base_id` | CHAR(36) | index |
| `interaction_id` | CHAR(36) nullable | 软关联 `qa_interactions.id` |
| `provider` | String(20) | |
| `model` | String(100) | |
| `input_tokens` | Integer | |
| `output_tokens` | Integer | |
| `total_tokens` | Integer | |
| `cost_amount` | Numeric(18,6) | 折算快照（价格变动不回溯） |
| `currency` | String(3) | |
| `created_at` | DateTime | index，用于时间范围报表 |

### 4.3 `quota_limits` —— 配额阈值配置

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | CHAR(36) PK | |
| `scope_type` | String(10) | `tenant` / `workspace` |
| `scope_id` | CHAR(36) | tenant_id 或 workspace_id |
| `daily_token_limit` | BigInteger nullable | null = token 不限 |
| `daily_cost_limit` | Numeric(18,6) nullable | null = 成本不限 |
| `currency` | String(3) | 成本配额币种 |
| `created_at` / `updated_at` | DateTime | |

- 唯一约束：`(scope_type, scope_id)`。

### 4.4 `quota_counters` —— 日度累加计数器

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | CHAR(36) PK | |
| `scope_type` | String(10) | `tenant` / `workspace` |
| `scope_id` | CHAR(36) | |
| `usage_date` | Date | UTC 日界 |
| `token_used` | BigInteger | 当日累加，default 0 |
| `cost_used` | Numeric(18,6) | 当日累加，default 0 |
| `updated_at` | DateTime | |

- 唯一约束：`(scope_type, scope_id, usage_date)`。
- **日度重置** = 日期分行：每天首次写入自然产生新行，旧行留存为历史，无需定时清零任务。准入只读当天行。

## 5. 用量捕获（改造 LLM 层）

### 5.1 `TokenUsage` 数据类（`app/services/llm.py`）

```python
@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int
    model: str
    provider: str
```

### 5.2 同步路径

- 新增 `generate_response_with_usage(prompt, context) -> tuple[str, TokenUsage | None]`：从 LangChain 统一的 `response.usage_metadata`（`input_tokens` / `output_tokens`）提取。
- 保留 `generate_response`，内部委托新函数只取文本 —— **不破坏现有调用**。
- 提取兜底：`usage_metadata` 缺失时返回 `None`，绝不抛错。

### 5.3 流式路径

- 创建 `ChatOpenAI` 时设 `stream_usage=True`，流式末尾 chunk 携带 `usage_metadata`。
- 生成器无法既 yield 文本又 return 值给消费者，故用**可变累加器对象**回传：调用方传入一个 `usage_holder`，生成器在末尾 chunk 时填充其 usage 字段。
- 客户端中途断开导致 usage 缺失 → 记为 `None`（fail-safe，不阻断）。

### 5.4 向上透传

- `rag_graph.py` 的 LLM 调用点（约 `262` / `431` / `610` 行）改用带 usage 版本。
- `answer_question` 返回 dict 增加 `usage` 字段；`answer_question_stream` 通过累加器回传，流结束后可读。
- `routes.py` 拿到 usage 后传入 `record_usage`。

## 6. 折算与记录（`app/cost/`）

### 6.1 `pricing.py`

- `resolve_price(db, provider, model, at) -> ModelPrice | None`：取生效价。
- `compute_cost(usage, price) -> tuple[Decimal, str]`：
  `input_tokens/1000 * input_price + output_tokens/1000 * output_price`。
- 无匹配价格 → 返回成本 `Decimal(0)` + log warning，token 照常记录（**缺价不阻断计量**）。

### 6.2 `recorder.py`（复刻 quality/recorder fail-safe 风格）

`record_usage(db, *, context, interaction_id, usage) -> None`：

1. 折算成本。
2. 写一条 `usage_records` 明细。
3. **原子累加** `quota_counters`：对 `(tenant, today)` 与 `(workspace, today)` 两行分别用 `INSERT ... ON CONFLICT DO UPDATE`（数据库层原子自增，非「读-改-写」，避免并发丢失）累加 `token_used` / `cost_used`。
4. 打 Prometheus 指标。
5. 任何异常 → log warning + rollback + swallow，**绝不影响 QA 响应**。

`usage` 为 `None`（捕获失败）时：跳过折算与写库，仅 log，安静返回。

### 6.3 新增 Prometheus 指标（`app/observability/metrics.py`）

- `LLM_TOKENS_TOTAL`（Counter；labels `provider`, `model`, `direction=input|output`）
- `LLM_COST_TOTAL`（Counter；labels `provider`, `model`, `currency`）
- `QUOTA_REJECTED_TOTAL`（Counter；labels `scope_type`）

## 7. 配额准入（硬限流）

### 7.1 `enforce_quota` 依赖（`app/cost/enforcement.py`）

FastAPI 依赖，挂在 `/qa/query` 与 `/qa/stream`，执行顺序在 `require_permission(QA_QUERY)` 之后、生成之前：

1. 读 `quota_limits` 中该 `tenant` 与 `workspace` 的阈值；无配置 = 不限，放行。
2. 读 `quota_counters` 当天两行的 `token_used` / `cost_used`（按唯一键 O(1) 查）。
3. 对**任一层、任一口径**：已用 ≥ 阈值 → 拒绝。
4. 拒绝 → 抛 `HTTPException 429`，body 说明超限层级与口径（如 `tenant daily token quota exceeded`），打 `QUOTA_REJECTED_TOTAL` + 记审计日志。

### 7.2 关键语义

- **事前检查**：生成前按「截至当前已累计用量」判断。单次请求可能让当日用量略微冲高过阈值（本次消耗未知）。标准做法：拦住已超限的后续请求，放行刚好触线的这一次。不做预扣。
- **fail-open**：读 `quota_limits` / `quota_counters` 抛异常（DB 不可用等）→ log warning + 放行。仅「成功读到且确认超限」才拒绝。
- **边界口径**：`usage_date` 用 UTC 日界（与 `created_at` 一致）；租户与工作区阈值独立判断，任一超限即拒。

## 8. 管理 API（`app/api/cost_routes.py`）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| PUT | `/quota/limits` | `cost:manage` | upsert 某 scope 的日度阈值 |
| GET | `/quota/usage` | `cost:read` | 查当前租户/工作区当日用量与剩余额度 |
| GET | `/cost/records` | `cost:read` | 分页查 `usage_records` 明细报表 |

价格表管理（`PUT /cost/prices`）同样需 `cost:manage`，可作为管理端补充端点。

### RBAC 新增权限（`app/auth/permissions.py`）

- `cost:manage`（`COST_MANAGE`）：配置配额、维护价格表。
- `cost:read`（`COST_READ`）：查看用量与成本报表。

角色授权：`WORKSPACE_ADMIN` → 两者；`KB_EDITOR` → `cost:read`；`KB_READER` → 无。

## 9. 配置（`app/core/config.py` Settings）

- 无需新增开关即可运行（无 `quota_limits` 配置时全部放行，等价于纯统计模式）。
- 可选：`cost_enforcement_enabled: bool = True` 作为全局硬限流总开关，便于灰度（默认开；关时 `enforce_quota` 直接放行）。

## 10. 测试策略

- **单测**：
  - `pricing`：折算正确性、缺价返回 0、生效时间选取最新价。
  - `recorder`：counter 原子累加（两层）、usage=None 安静跳过、异常 swallow。
  - `enforce_quota`：未配置放行 / 未超放行 / token 超限拒 / cost 超限拒 / 工作区超限拒 / DB 故障 fail-open。
- **集成**：
  - QA 请求全链路 → `usage_records` 落库 + `quota_counters` 递增。
  - 超限请求返回 429，body 含超限层级。
  - 流式路径 usage 捕获（累加器回传）。
  - 管理 API 权限校验（`cost:manage` / `cost:read`）。
- 复用现有测试租户/工作区 fixture。

## 11. 交付边界与后续

- 迁移 `0013` 需手动执行 `alembic upgrade head`（与项目既有约定一致）。
- 初始价格数据通过管理 API 或 seed 脚本写入（Ark 模型单价 + Ollama 0 价）。
- 分布式计数器（Redis）、embedding/judge 计量、软告警通知渠道、成本报表前端 —— 均为后续 follow-up，不在本期。
