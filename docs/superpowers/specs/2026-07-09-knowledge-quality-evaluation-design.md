# 知识质量评测（Knowledge Quality Evaluation）设计

- 日期：2026-07-09
- 应用：`apps/luna-corpus`
- 阶段定位：企业级 RAG 差距分析「阶段 4 · 评测、反馈和观测闭环」的核心一环
- 关联记忆：P1 rerank module、P0-M8 observability、P0-M6 async indexing

## 1. 背景与目标

现有 `luna-corpus` 已具备 RAG 问答闭环（检索、生成、多轮会话），但**质量不可度量**：改动 chunk / embedding / prompt / rerank 后，无法判断线上问答质量是否变好或退化。

本设计交付**持续质量监控**能力：对线上真实问答持续采集质量信号，追踪质量趋势、发现退化。质量信号来自两条互补的线：

1. **用户反馈信号**（真实但稀疏）：👍/👎 + 错误类型标注。
2. **LLM 自动评分**（覆盖面广、实时）：faithfulness、answer relevance、citation accuracy。

两条线共享同一个地基——一张可回溯的 **QA 交互记录表**。

### 非目标（YAGNI 边界）

以下明确不在本 spec 范围内，留给后续独立迭代：

- 前端质量看板 UI（本 spec 只提供聚合查询 API）
- 离线 golden QA 数据集与 CI 回归门禁
- 多 judge 投票 / 交叉校验
- 反馈驱动的知识修复队列
- prompt 版本与评分的关联分析

## 2. 整体架构

```
                    ┌─────────────────────────────────────┐
   /qa/query ──────▶│ ① 交互记录 (interaction recorder)    │
   /qa/multi-turn   │   问答发生时同步落一条 QAInteraction  │
                    │   含 answer_id、问题、答案、检索快照   │
                    └───────────────┬─────────────────────┘
                                    │ answer_id
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
    ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
    │ ② 用户反馈       │  │ ③ LLM 自动评分    │  │ ④ 聚合与趋势查询  │
    │ POST feedback    │  │ judge 异步打分    │  │ 按 KB/时间窗聚合   │
    │ 👍/👎+错误类型   │  │ 采样触发          │  │ 反馈率+评分均值    │
    └──────────────────┘  └──────────────────┘  └──────────────────┘
```

**核心设计原则**：`QAInteraction`（交互记录）是唯一地基，②③④ 全部通过 `answer_id` 挂到它上面，彼此零耦合——反馈不知道评分存在，评分不知道反馈存在，聚合层只读三张表做汇总。

**关键取舍**：
- 交互记录**同步写**（问答链路内落库，保证不丢）。
- LLM 评分**异步跑**（复用现有 `BackgroundTasks` 模式，不阻塞问答响应）。
- 评分**按采样率**触发（控制 LLM 成本）；反馈**全量开放**。
- 评测是**旁路**：任何评测环节失败都绝不能拖垮问答主干。

### 代码落点

新增包 `apps/luna-corpus/app/quality/`：

| 文件 | 职责 |
|---|---|
| `recorder.py` | 记录交互：`record_interaction(db, ...) -> answer_id`；采样后触发评分任务 |
| `judge.py` | `QualityJudge` 抽象基类 + `LLMQualityJudge` 实现（参考 rerank 模块范式） |
| `tasks.py` | `_run_eval_task(evaluation_id)`：后台执行评分，独立 DB session |
| `feedback.py` | 反馈写入的服务函数 |
| `aggregation.py` | 只读聚合查询逻辑 |

三张新表加入 `app/db/models.py`，API 端点加入 `app/api/routes.py`（沿用现有 router）。

## 3. 数据模型

三张表遵循现有风格：`CHAR(36)` UUID 主键、`server_default=func.now()`、KB 维度隔离字段。

### 3.1 `QAInteraction`（交互记录 —— 地基）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | CHAR(36) | PK | 即 `answer_id` |
| `knowledge_base_id` | CHAR(36) | 索引, 非空 | KB 维度隔离/聚合 |
| `conversation_id` | CHAR(36) | 可空 | 多轮场景关联；单轮为 null |
| `question` | Text | 非空 | |
| `answer` | Text | 非空 | |
| `sources` | JSON | 非空 | 检索上下文快照：`[{document_id, chunk_content, relevance_score}]` |
| `retrieval_mode` | String(20) | 可空 | vector/hybrid/rerank，便于按模式对比 |
| `processing_time_ms` | Integer | 可空 | |
| `created_at` | DateTime | server_default | |

关键点：`sources` 存**当时的检索快照**（非外键引用），因为文档后续会被修改/删除，评测必须回溯到「回答那一刻」的上下文。这也是 faithfulness / citation 打分的输入。

### 3.2 `QAFeedback`（用户反馈）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | CHAR(36) | PK | |
| `interaction_id` | CHAR(36) | FK→qa_interactions, 非空, 索引 | |
| `rating` | Enum(UP/DOWN) | 非空 | |
| `error_type` | Enum | 可空 | 仅 DOWN 时：hallucination / irrelevant / incomplete / wrong_citation / other |
| `comment` | Text | 可空 | |
| `created_by_user_id` | CHAR(36) | 可空 | 谁反馈的 |
| `created_at` | DateTime | server_default | |

一条交互可有多条反馈（不同用户）。`error_type` 用枚举，对齐差距分析「错误类型」诉求，也是未来标注数据的分类基础。

### 3.3 `QAEvaluation`（LLM 自动评分）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | CHAR(36) | PK | |
| `interaction_id` | CHAR(36) | FK→qa_interactions, 非空, 索引 | |
| `faithfulness` | Float | 可空 | 0-1，答案是否忠于检索上下文（无幻觉） |
| `answer_relevance` | Float | 可空 | 0-1，答案是否切题 |
| `citation_accuracy` | Float | 可空 | 0-1，引用是否支撑答案 |
| `judge_model` | String(50) | 可空 | 记录用哪个模型评的，便于溯源 |
| `rationale` | Text | 可空 | judge 给的简短理由 |
| `status` | Enum | 非空 | pending / completed / failed |
| `created_at` | DateTime | server_default | |

三个分数对齐差距分析原文。分开存三列（而非一个 JSON）便于聚合层直接 `AVG()`。`status` 支持异步任务生命周期。

### 3.4 Migration

新增一个 alembic migration 建三张表及索引（`knowledge_base_id`、`interaction_id`）。遵循现有 alembic 目录约定。

## 4. 数据流与关键流程

### 流程 A · 记录交互（同步，问答链路内）

在 `/qa/query` 和 `/qa/multi-turn` 拿到 `result` 后、返回响应前，插入一条 `QAInteraction`，把 `answer_id`（即 `interaction.id`）放进响应体返回给前端——前端后续提交反馈要靠它。

- 落库封装在 `recorder.record_interaction(db, ...)`，问答端点只调一行。
- **失败降级**：记录失败绝不拖垮问答。try/except 包裹，失败只记 structlog warning，问答照常返回（此时响应 `answer_id` 可为 null）。
- `AnswerResponse` / `MultiTurnAnswerResponse` 新增 `answer_id: str | None` 字段。

### 流程 B · 提交反馈（同步，独立端点）

```
POST /qa/interactions/{answer_id}/feedback
body: { rating: "down", error_type: "hallucination", comment: "..." }
```

- 校验 `answer_id` 存在且属于当前 KB（复用 `require_permission` + KB scope 模式）。
- 写一条 `QAFeedback`，审计记录一次（沿用 `AuditService`，新增对应 `AuditAction`）。
- 权限：**新增 `PermissionSlug.QA_FEEDBACK`**。
- 跨 KB / 不存在的 answer_id → 404。

### 流程 C · LLM 自动评分（异步，实时采样触发）

```
record_interaction 落库后
      │
      ▼
按采样率决定是否评分 ──否──▶ 结束
      │是
      ▼
建 QAEvaluation(status=pending) + background_tasks.add_task(_run_eval_task)
      │
      ▼ (后台，独立 DB session，复用 _run_index_task 模式)
QualityJudge.evaluate(question, answer, sources)
      │  组装 judge prompt → 调 LLM → 解析出三个分数 + rationale
      ▼
更新 QAEvaluation(status=completed, 分数...) ；失败则 status=failed
```

- `QualityJudge` 是抽象基类，先落一个 `LLMQualityJudge`（复用现有 `generate_response`）。参考 rerank 模块「抽象 + 本地实现 + 可降级」范式。
- Judge 用**结构化输出**（要求模型返回 JSON），解析失败则 `status=failed`，不污染聚合。
- 采样率可配置（`app/core/config.py` 新增 `quality_eval_sample_rate`，默认 0.1）。率=0 不评、率=1 必评。
- 触发点在问答端点：`record_interaction` 返回 answer_id 后，端点根据采样决定是否 `background_tasks.add_task`。

### 流程 D · 聚合查询（只读）

```
GET /qa/quality/summary?days=7
→ {
    total_interactions, feedback_count, thumbs_up_rate,
    avg_faithfulness, avg_relevance, avg_citation_accuracy,
    error_type_breakdown: {hallucination: 3, ...},
    by_retrieval_mode: {...}
  }
```

- 纯 SQL 聚合（`AVG` / `COUNT` / `GROUP BY`），按 KB scope + 时间窗过滤。
- 无数据时返回 0 或 null（`avg_*` 无样本时为 null），不报错。
- 权限复用 `QA_QUERY` 或读权限（实现时对齐现有只读端点约定）。

## 5. 错误处理

核心原则：评测是旁路，绝不拖垮问答。

| 环节 | 失败时 | 处理 |
|---|---|---|
| 记录交互 | 落库异常 | try/except 吞掉，structlog warning，问答正常返回（answer_id 为 null） |
| 采样/建评分任务 | 建 pending 失败 | 同上吞掉，不影响问答 |
| Judge 后台执行 | LLM 调用失败 / JSON 解析失败 | `QAEvaluation.status=failed`，独立 DB session，不影响其他 |
| 提交反馈 | answer_id 不存在/跨 KB | 404，正常 HTTP 错误 |
| 聚合查询 | 无数据 | 返回 0 / null 而非报错 |

## 6. 可观测性

沿用 P0-M8 基建：

- **structlog**：记录交互写入、评分触发/完成/失败。
- **Prometheus `/metrics`**：新增 `qa_interactions_total`、`qa_feedback_total{rating}`、`qa_evaluations_total{status}`。参考现有 `INDEX_TASK_DURATION` 写法。

## 7. 测试策略

沿用现有 pytest 结构，通过 `nx` 运行。

- **单元**：
  - `QualityJudge` 用 fake LLM（返回固定 JSON）测分数解析。
  - Judge 解析失败路径 → status=failed。
  - 采样逻辑：率=0 不评、率=1 必评。
- **集成**：
  - `/qa/query` 返回 answer_id 且落了 `QAInteraction`。
  - 记录失败时问答仍成功（注入异常）。
  - 提交反馈 → 查得到；跨 KB 提交反馈 → 404。
  - 聚合端点数字正确（含无数据返回 0/null）。
- **异步**：`_run_eval_task` 独立 session，用 fake judge 验证 completed / failed 两条路径。
- 遵循现有习惯：不用 `sleep`，用显式时间戳 / 依赖注入。

## 8. 交付清单

- [ ] 三张表 `QAInteraction` / `QAFeedback` / `QAEvaluation` + 枚举 + alembic migration
- [ ] `app/quality/recorder.py` 记录钩子 + 采样触发
- [ ] `app/quality/judge.py` `QualityJudge` 抽象 + `LLMQualityJudge`
- [ ] `app/quality/tasks.py` 异步评分任务
- [ ] `app/quality/feedback.py` + `app/quality/aggregation.py`
- [ ] 问答端点接入记录钩子，响应体加 `answer_id`
- [ ] `POST /qa/interactions/{answer_id}/feedback` 端点 + `QA_FEEDBACK` 权限
- [ ] `GET /qa/quality/summary` 聚合端点
- [ ] 配置项 `quality_eval_sample_rate`
- [ ] Prometheus 指标 3 个
- [ ] 单元 / 集成 / 异步测试
