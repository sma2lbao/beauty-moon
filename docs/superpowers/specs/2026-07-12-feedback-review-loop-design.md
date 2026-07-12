# 用户反馈闭环：运营复审工单流 —— 设计文档

- 日期：2026-07-12
- 模块：`apps/luna-corpus`（企业级 RAG 服务 Luna Corpus）
- 定位：P1 质量评估模块（[[p1_quality_evaluation]]）之后的「闭环」补齐

## 背景与问题

现有质量模块（`app/quality/`）已经把**信号采集**做得很完整：

- `recorder` 记录每次问答（`qa_interactions`）
- `judge` / `tasks` 异步 LLM 打分（`qa_evaluations`：faithfulness / answer_relevance / citation_accuracy）
- `feedback` 收集用户 👍/👎 + 错误类型 + 评论（`qa_feedback`）
- `aggregation` 提供只读 summary

但这些信号目前是**死数据**——只能被 summary 聚合看一眼，没有任何东西「回流」去改善系统。这是一个**开环**。

本设计补齐缺失的一环：把低分 / 差评的问答变成**可执行的运营复审工单流**（human-in-the-loop）。运营 / 知识管理员能看到待复审项、标注根因、记录处置，从而真正驱动知识库改善。

## 方案选型

在四个候选方向（A 运营复审闭环 / B 检索质量自动优化 / C 用户侧即时闭环 / D 其他）中选定 **A 运营复审闭环**：

- 是现有架构最自然的下一步——不改采集层，只在其上加一层「消费」。
- 尊重核心原则「评测是旁路信号，绝不中断问答主流程」——复审是纯后台异步的运营通道。
- 风险可控、人在环中——是将来 B（检索自动优化）的数据地基：先有结构化根因标注，才谈得上自动调参。

交付边界：**纯后端 REST API**，审阅界面留给未来 / 外部运营系统消费（与 luna-corpus 纯后端 FastAPI 服务现状一致）。

## 核心设计原则

- **零耦合、不改采集层**：不建物化队列表，待复审队列是**运行时派生查询**；只新增一张 `qa_reviews` 处置记录表。延续 [[p1_quality_evaluation]] 的三表零耦合范式。
- **KB 作用域**：所有操作先校验 interaction 属于当前知识库，不匹配即 404，杜绝跨租户越权。
- **复审端点正常报错**（区别于旁路的 recorder 的 fail-safe）：复审是显式管理操作，失败就应让运营知道。

---

## 1. 数据模型与入队规则

### 新增表 `qa_reviews`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | CHAR(36) PK | uuid |
| `interaction_id` | CHAR(36) FK→`qa_interactions`, ondelete=CASCADE, **unique** | 一条 interaction 最多一条 review |
| `status` | Enum(ReviewStatus), 默认 OPEN, not null | 状态机 |
| `root_cause` | Enum(ReviewRootCause), nullable | 处置时填写 |
| `resolution_note` | Text, nullable | 处置说明 |
| `assignee_user_id` | CHAR(36), nullable | 认领人（字段预留，本版不通过 API 写入） |
| `resolved_by_user_id` | CHAR(36), nullable | 处置人 |
| `created_at` | DateTime, server_default now | |
| `updated_at` | DateTime, onupdate now | |

### 新枚举

- `ReviewStatus`：`OPEN` / `RESOLVED` / `DISMISSED`（轻量三态，无独立「认领中」态）
- `ReviewRootCause`：`KNOWLEDGE_GAP`（知识缺失）/ `CHUNK_ERROR`（切分或检索错误）/ `HALLUCINATION`（幻觉）/ `OUTDATED`（信息过时）/ `OTHER`

> **为何新建 `ReviewRootCause` 而非复用 `FeedbackErrorType`**：二者是不同视角——`root_cause` 是**运营复审归因**（造成问题的系统根因），`FeedbackErrorType` 是**用户报错分类**（用户主观感受）。语义不同，独立枚举更清晰。

### 入队规则（派生查询）

一条 interaction 进入「待复审队列」，当且仅当满足**任一信号**：

1. 存在 `rating=DOWN` 的 feedback；**或**
2. 存在 `status=COMPLETED` 的 evaluation，且 `faithfulness < 阈值` **或** `answer_relevance < 阈值`

阈值走配置 `quality_review_score_threshold`，默认 **0.6**（严格小于，即 `=0.6` 不入队）。

**且**该 interaction 不存在状态为 `RESOLVED` / `DISMISSED` 的 review（已处理的移出队列）。若已有 `OPEN` review，则带上其 review 信息一起返回。

实现方式：`interaction LEFT JOIN feedback LEFT JOIN evaluation LEFT JOIN qa_reviews`，按上述规则过滤。运营处置只写 / 改 `qa_reviews` 行，采集层完全不动。

---

## 2. API 端点

新增权限 `QA_REVIEW = "qa:review"`：

- 授予 `WORKSPACE_ADMIN`、`KB_EDITOR`
- **不授予** `KB_READER`（读者能提反馈，但不能复审处置）

端点前缀沿用 `/api/v1`，全部 KB 作用域（从 `context.knowledge_base.id` 取）：

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| `GET` | `/qa/reviews` | QA_REVIEW | 待复审队列（派生查询）。支持 `status` 过滤（默认返回队列中待处理项）、分页 `limit`/`offset`。每项含 interaction 摘要 + 触发信号 + 已有 review 状态 |
| `GET` | `/qa/reviews/{interaction_id}` | QA_REVIEW | 单条复审详情：完整 question/answer/sources + feedback[] + evaluation + review |
| `POST` | `/qa/reviews/{interaction_id}/resolve` | QA_REVIEW | 处置：body 含 `root_cause`、`resolution_note`。upsert review 为 `RESOLVED`。记审计 |
| `POST` | `/qa/reviews/{interaction_id}/dismiss` | QA_REVIEW | 忽略（误报 / 无需处理）：body 含可选 `resolution_note`。置为 `DISMISSED`。记审计 |

设计取舍：

- **不做独立「认领」端点**（轻量三态无 IN_REVIEW）。`assignee_user_id` 保留但暂不通过 API 写入。
- **resolve/dismiss 用 POST 动作端点**而非 PATCH：状态机流转语义更清晰，且各自记不同审计动作。
- **幂等**：对已有 review 的 interaction 再次 resolve/dismiss，视为**更新**（覆盖 status/root_cause/note），运营可改判。
- **审计**：新增审计动作 `QA_REVIEW_RESOLVE` / `QA_REVIEW_DISMISS`，沿用现有 `AuditAction` + `record_audit` 范式。

---

## 3. 模块结构、数据流与错误处理

### 新模块 `app/quality/review.py`

沿用 feedback/aggregation 的服务函数风格（纯函数 + 传入 Session，路由层负责 commit）：

```
list_reviews(db, kb_id, *, status_filter, limit, offset) -> list[dict]
    # 派生查询：interaction LEFT JOIN feedback/evaluation/review
    # 按入队规则过滤，附带触发信号与 review 状态

get_review_detail(db, kb_id, interaction_id) -> dict | None
    # KB 作用域校验（复用 feedback.get_interaction 模式）
    # 返回 interaction 全文 + feedback[] + evaluation + review

resolve_review(db, kb_id, interaction_id, *, root_cause, note, user_id) -> QAReview | None
dismiss_review(db, kb_id, interaction_id, *, note, user_id) -> QAReview | None
    # upsert：查已有 review 则更新，否则新建；置对应状态
    # KB 作用域不匹配返回 None（路由层转 404）
```

入队阈值读 `settings.quality_review_score_threshold`（默认 0.6），加进 `app/core/config.py`。

### 数据流

```
运营 GET /qa/reviews
  → list_reviews 派生查询（实时 JOIN + 过滤）→ 返回待复审项 + 触发信号

运营 GET /qa/reviews/{id}  → 看全文 / 信号 / 已有处置

运营 POST .../resolve | .../dismiss
  → 服务层 upsert qa_reviews 行 → db.commit()
  → record_audit(QA_REVIEW_RESOLVE / DISMISS)
  → 返回更新后的 review
  → 下次 list_reviews 该项自动移出队列（因已 RESOLVED / DISMISSED）
```

### 错误处理与边界

- **KB 作用域**：所有操作先校验 interaction 属当前 KB，不匹配 → 404（复用 `get_interaction` 模式）。
- **与旁路原则的关系**：复审是独立运营读写通道，不触碰问答主链路，天然不影响 QA。此处**不吞异常**——失败正常报错（与 feedback 端点一致）。
- **并发处置**：轻量三态下 upsert 幂等，两运营同时处置同一项 → 后写覆盖（可接受，无认领态本就假设原子处置）。`interaction_id` unique 约束防重复 review 行。
- **派生查询性能**：现有 `knowledge_base_id`、`interaction_id` 索引已够；列表带分页避免全表返回。

---

## 4. 测试策略

沿用现有 `tests/quality/` 与 `tests/api/` 的分层与风格。

### 单元测试 `tests/quality/test_review_service.py`

- **入队规则**：构造「仅点踩」「仅低分（<0.6）」「双信号」「低分恰好 =0.6 / >0.6」「无信号」等，断言 `list_reviews` 精确纳入 / 排除。
- **已处置移出队列**：已 RESOLVED / DISMISSED 的 review 不再出现在默认队列。
- **upsert 语义**：无 review → 新建；已有 OPEN review 再 resolve/dismiss → 更新同一行（不新增），状态 / root_cause / note 正确覆盖。
- **KB 作用域**：跨 KB 的 interaction_id → `get_review_detail` / `resolve` 返回 None。
- **阈值可配**：改 `quality_review_score_threshold`，断言入队边界随之变化。

### 模型 & 迁移 `tests/quality/test_review_models.py`

- 新枚举值、`qa_reviews` 字段、`interaction_id` unique 约束、CASCADE 删除（删 interaction 连带删 review）。

### API 测试 `tests/api/test_review_api.py`

- **权限**：`KB_READER` 访问 `/qa/reviews*` → 403；`KB_EDITOR` / `WORKSPACE_ADMIN` → 200。
- **队列端点**：双信号数据，`GET /qa/reviews` 返回该项及触发信号；分页 `limit`/`offset` 生效。
- **详情端点**：返回全文 + feedback + evaluation + review。
- **resolve/dismiss**：动作成功、状态流转、幂等再处置、审计日志写入（断言 `QA_REVIEW_RESOLVE`/`DISMISS` 落库）。
- **404**：不存在或跨 KB 的 interaction_id。

### 配置 & 权限种子

- `tests/quality/test_quality_config.py` 补 `quality_review_score_threshold` 默认值断言。
- 权限种子测试补 `QA_REVIEW` 授予关系（admin/editor 有、reader 无）。

---

## 交付清单（供实现计划参考）

1. `app/db/models.py`：新增 `ReviewStatus`、`ReviewRootCause` 枚举与 `QAReview` 模型。
2. Alembic 迁移：新建 `qa_reviews` 表（down 指向当前最新 revision）。
3. `app/core/config.py`：新增 `quality_review_score_threshold` 默认 0.6。
4. `app/auth/permissions.py`：新增 `QA_REVIEW`，授予 admin/editor。
5. `app/security/audit.py`（或对应枚举）：新增 `QA_REVIEW_RESOLVE`/`QA_REVIEW_DISMISS` 审计动作。
6. `app/quality/review.py`：`list_reviews` / `get_review_detail` / `resolve_review` / `dismiss_review`。
7. `app/api/routes.py`：4 个端点 + 请求 / 响应 Pydantic 模型。
8. 测试：`test_review_service.py`、`test_review_models.py`、`test_review_api.py` + 配置 / 权限种子补充。
