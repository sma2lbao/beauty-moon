# 知识质量评测（Knowledge Quality Evaluation）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 luna-corpus 交付持续质量监控：持久化每次问答交互，采集用户反馈信号与 LLM 自动评分，并提供聚合查询 API。

**Architecture:** 新增 `app/quality/` 包。三张新表以 `QAInteraction`（交互记录）为地基，`QAFeedback`（用户反馈）与 `QAEvaluation`（LLM 评分）通过 `interaction_id` 挂接。交互记录在问答链路内**同步写**（失败降级不拖垮问答），LLM 评分复用 `BackgroundTasks` **异步采样**执行，聚合层只读三表做 SQL 汇总。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy（DeclarativeBase / Mapped）、Alembic、Pydantic v2、pytest、structlog、prometheus_client。

## Global Constraints

- 包管理器统一 `npm`；测试通过 `npm exec nx test luna-corpus`（或 `cd apps/luna-corpus && python -m pytest`）运行。
- 数据库主键统一 `CHAR(36)` UUID，`default=lambda: str(uuid.uuid4())`。
- 时间戳统一 `DateTime` + `server_default=func.now()`。
- 枚举统一继承 `(str, enum.Enum)`。
- KB 维度隔离：所有面向用户的查询按 `knowledge_base_id` + `require_permission` scope 过滤。
- **评测是旁路**：记录/采样/评分任何环节失败都不得让问答主干报错。
- 测试不用 `sleep`，用显式时间戳或依赖注入。
- 遵循现有 rerank 模块「抽象基类 + 工厂 + 可降级」范式。

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `app/db/models.py`（改） | 新增 `FeedbackRating` / `FeedbackErrorType` / `EvaluationStatus` 枚举与 `QAInteraction` / `QAFeedback` / `QAEvaluation` 三张表 |
| `alembic/versions/20260709_0009_quality_evaluation.py`（新） | 建三张表及索引 |
| `app/core/config.py`（改） | 新增 `quality_eval_sample_rate` 配置 |
| `app/auth/permissions.py`（改） | 新增 `QA_FEEDBACK` 权限并加入默认角色 |
| `app/security/audit.py`（改） | 新增 `QA_FEEDBACK` AuditAction |
| `app/observability/metrics.py`（改） | 新增 3 个计数器 |
| `app/quality/__init__.py`（新） | 包导出 |
| `app/quality/recorder.py`（新） | `record_interaction()` + 采样判定 `should_evaluate()` |
| `app/quality/judge.py`（新） | `QualityJudge` 抽象 + `LLMQualityJudge` + `get_judge()` + `evaluate_interaction()` |
| `app/quality/tasks.py`（新） | `_run_eval_task()` 异步评分任务 |
| `app/quality/feedback.py`（新） | `create_feedback()` 服务函数 |
| `app/quality/aggregation.py`（新） | `summarize_quality()` 聚合查询 |
| `app/api/routes.py`（改） | 问答端点接入记录；新增反馈端点 + 聚合端点；响应加 `answer_id` |
| `app/graph/rag_graph.py`（改） | `answer_question` 返回值加 `retrieval_mode` |
| `tests/quality/`（新） | 单元 + 异步测试 |
| `tests/api/test_quality_api.py`（新） | 集成测试 |

任务顺序：数据模型 → 配置/权限/指标 → judge → recorder → tasks → feedback → aggregation → API 接线 → 集成。每个任务结束都能独立测试。

---

### Task 1: 数据模型与枚举

**Files:**
- Modify: `apps/luna-corpus/app/db/models.py`（在 `AuditLog` 类之后、`from app.metadata.models import` 之前插入）
- Test: `apps/luna-corpus/tests/quality/test_quality_models.py`（新建，需先建 `tests/quality/__init__.py`）

**Interfaces:**
- Produces:
  - `QAInteraction(id, knowledge_base_id, conversation_id, question, answer, sources, retrieval_mode, processing_time_ms, created_at)`
  - `QAFeedback(id, interaction_id, rating, error_type, comment, created_by_user_id, created_at)`
  - `QAEvaluation(id, interaction_id, faithfulness, answer_relevance, citation_accuracy, judge_model, rationale, status, created_at)`
  - 枚举 `FeedbackRating.{UP,DOWN}`、`FeedbackErrorType.{HALLUCINATION,IRRELEVANT,INCOMPLETE,WRONG_CITATION,OTHER}`、`EvaluationStatus.{PENDING,COMPLETED,FAILED}`

- [ ] **Step 1: 建测试包目录**

```bash
touch apps/luna-corpus/tests/quality/__init__.py
```

- [ ] **Step 2: 写失败测试**

创建 `apps/luna-corpus/tests/quality/test_quality_models.py`：

```python
"""Unit tests for quality evaluation models."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    EvaluationStatus,
    FeedbackErrorType,
    FeedbackRating,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_interaction_persists_sources_json():
    session = _session()
    interaction = QAInteraction(
        knowledge_base_id="kb-1",
        question="Q?",
        answer="A.",
        sources=[{"document_id": "d1", "chunk_content": "c", "relevance_score": 0.9}],
        retrieval_mode="hybrid",
        processing_time_ms=120,
    )
    session.add(interaction)
    session.commit()
    row = session.query(QAInteraction).one()
    assert row.id
    assert row.sources[0]["document_id"] == "d1"
    assert row.created_at is not None


def test_feedback_and_evaluation_link_to_interaction():
    session = _session()
    interaction = QAInteraction(
        knowledge_base_id="kb-1", question="Q", answer="A", sources=[]
    )
    session.add(interaction)
    session.commit()

    feedback = QAFeedback(
        interaction_id=interaction.id,
        rating=FeedbackRating.DOWN,
        error_type=FeedbackErrorType.HALLUCINATION,
        comment="wrong",
    )
    evaluation = QAEvaluation(
        interaction_id=interaction.id,
        status=EvaluationStatus.PENDING,
    )
    session.add_all([feedback, evaluation])
    session.commit()

    assert session.query(QAFeedback).one().rating == FeedbackRating.DOWN
    assert session.query(QAEvaluation).one().status == EvaluationStatus.PENDING
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_quality_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'QAInteraction'`

- [ ] **Step 4: 实现模型**

在 `apps/luna-corpus/app/db/models.py` 的 `AuditLog` 类之后、`from app.metadata.models import MetadataFieldDefinition` 之前插入：

```python
class FeedbackRating(str, enum.Enum):
    """User thumbs rating on an answer."""

    UP = "up"
    DOWN = "down"


class FeedbackErrorType(str, enum.Enum):
    """Category of problem reported in a DOWN rating."""

    HALLUCINATION = "hallucination"
    IRRELEVANT = "irrelevant"
    INCOMPLETE = "incomplete"
    WRONG_CITATION = "wrong_citation"
    OTHER = "other"


class EvaluationStatus(str, enum.Enum):
    """Lifecycle of an async LLM evaluation."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class QAInteraction(Base):
    """Retrievable record of one Q&A exchange — the base for quality signals."""

    __tablename__ = "qa_interactions"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36), nullable=False, index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    retrieval_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class QAFeedback(Base):
    """Human feedback on a Q&A interaction."""

    __tablename__ = "qa_feedback"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    interaction_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("qa_interactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating: Mapped[FeedbackRating] = mapped_column(
        Enum(FeedbackRating), nullable=False
    )
    error_type: Mapped[FeedbackErrorType | None] = mapped_column(
        Enum(FeedbackErrorType), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class QAEvaluation(Base):
    """LLM-as-judge scores for a Q&A interaction."""

    __tablename__ = "qa_evaluations"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    interaction_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("qa_interactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_relevance: Mapped[float | None] = mapped_column(Float, nullable=True)
    citation_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    judge_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[EvaluationStatus] = mapped_column(
        Enum(EvaluationStatus), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

在文件顶部 `from sqlalchemy import (...)` 导入块中，`Enum,` 之后加入 `Float,`（保持字母序，紧跟 `Enum` 之后即可）。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_quality_models.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: 提交**

```bash
git add apps/luna-corpus/app/db/models.py apps/luna-corpus/tests/quality/
git commit -m "feat(quality): add QAInteraction/QAFeedback/QAEvaluation models"
```

---

### Task 2: Alembic 迁移

**Files:**
- Create: `apps/luna-corpus/alembic/versions/20260709_0009_quality_evaluation.py`

**Interfaces:**
- Consumes: Task 1 的表定义（表名 `qa_interactions` / `qa_feedback` / `qa_evaluations`）
- Produces: 数据库中三张表 + 索引 `ix_qa_interactions_kb` / `ix_qa_feedback_interaction` / `ix_qa_evaluations_interaction`

- [ ] **Step 1: 编写迁移文件**

创建 `apps/luna-corpus/alembic/versions/20260709_0009_quality_evaluation.py`：

```python
"""quality evaluation: qa_interactions, qa_feedback, qa_evaluations

Revision ID: 20260709_0009
Revises: 20260708_0008
Create Date: 2026-07-09

"""
import sqlalchemy as sa
from alembic import op

revision = "20260709_0009"
down_revision = "20260708_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qa_interactions",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("knowledge_base_id", sa.CHAR(36), nullable=False),
        sa.Column("conversation_id", sa.CHAR(36), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("retrieval_mode", sa.String(20), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_qa_interactions_kb", "qa_interactions", ["knowledge_base_id"]
    )

    op.create_table(
        "qa_feedback",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("interaction_id", sa.CHAR(36), nullable=False),
        sa.Column(
            "rating", sa.Enum("up", "down", name="feedbackrating"), nullable=False
        ),
        sa.Column(
            "error_type",
            sa.Enum(
                "hallucination",
                "irrelevant",
                "incomplete",
                "wrong_citation",
                "other",
                name="feedbackerrortype",
            ),
            nullable=True,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.CHAR(36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["qa_interactions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_qa_feedback_interaction", "qa_feedback", ["interaction_id"]
    )

    op.create_table(
        "qa_evaluations",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("interaction_id", sa.CHAR(36), nullable=False),
        sa.Column("faithfulness", sa.Float(), nullable=True),
        sa.Column("answer_relevance", sa.Float(), nullable=True),
        sa.Column("citation_accuracy", sa.Float(), nullable=True),
        sa.Column("judge_model", sa.String(50), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "completed", "failed", name="evaluationstatus"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["qa_interactions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_qa_evaluations_interaction", "qa_evaluations", ["interaction_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_qa_evaluations_interaction", table_name="qa_evaluations")
    op.drop_table("qa_evaluations")
    op.drop_index("ix_qa_feedback_interaction", table_name="qa_feedback")
    op.drop_table("qa_feedback")
    op.drop_index("ix_qa_interactions_kb", table_name="qa_interactions")
    op.drop_table("qa_interactions")
```

- [ ] **Step 2: 验证迁移可加载（离线检查 head 链）**

Run: `cd apps/luna-corpus && python -m alembic heads`
Expected: 输出包含 `20260709_0009 (head)`，无 "multiple heads" 报错。

- [ ] **Step 3: 提交**

```bash
git add apps/luna-corpus/alembic/versions/20260709_0009_quality_evaluation.py
git commit -m "feat(quality): add migration for quality evaluation tables"
```

---

### Task 3: 配置、权限与审计动作

**Files:**
- Modify: `apps/luna-corpus/app/core/config.py`
- Modify: `apps/luna-corpus/app/auth/permissions.py`
- Modify: `apps/luna-corpus/app/security/audit.py`
- Test: `apps/luna-corpus/tests/quality/test_quality_config.py`（新建）

**Interfaces:**
- Produces:
  - `settings.quality_eval_sample_rate: float`（默认 0.1）
  - `PermissionSlug.QA_FEEDBACK = "qa:feedback"`（加入 WORKSPACE_ADMIN / KB_EDITOR / KB_READER 三角色）
  - `AuditAction.QA_FEEDBACK = "qa.feedback"`

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/quality/test_quality_config.py`：

```python
"""Config / permission / audit wiring for quality evaluation."""
from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS, PermissionSlug, RoleSlug
from app.core.config import get_settings
from app.security.audit import AuditAction


def test_sample_rate_default():
    assert get_settings().quality_eval_sample_rate == 0.1


def test_qa_feedback_permission_seeded():
    assert PermissionSlug.QA_FEEDBACK == "qa:feedback"
    for role in (RoleSlug.WORKSPACE_ADMIN, RoleSlug.KB_EDITOR, RoleSlug.KB_READER):
        assert PermissionSlug.QA_FEEDBACK in DEFAULT_ROLE_PERMISSIONS[role]


def test_qa_feedback_audit_action():
    assert AuditAction.QA_FEEDBACK.value == "qa.feedback"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_quality_config.py -v`
Expected: FAIL（`AttributeError: quality_eval_sample_rate` / `QA_FEEDBACK`）

- [ ] **Step 3: 加配置项**

在 `apps/luna-corpus/app/core/config.py` 的 Rerank 配置块（`rerank_batch_size` 定义）之后插入：

```python
    # Quality Evaluation
    quality_eval_sample_rate: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="对问答交互触发 LLM 自动评分的采样率（0=从不，1=全部）",
    )
```

- [ ] **Step 4: 加权限**

在 `apps/luna-corpus/app/auth/permissions.py` 的 `PermissionSlug` 类中，`QA_QUERY` 之后加：

```python
    QA_FEEDBACK = "qa:feedback"
```

在 `DEFAULT_ROLE_PERMISSIONS` 的三个角色元组里，各自 `PermissionSlug.QA_QUERY` 之后加一行：

```python
        PermissionSlug.QA_FEEDBACK,
```

（WORKSPACE_ADMIN、KB_EDITOR、KB_READER 三处都要加。）

- [ ] **Step 5: 加审计动作**

在 `apps/luna-corpus/app/security/audit.py` 的 `AuditAction` 枚举中，`QA_QUERY` 之后加：

```python
    QA_FEEDBACK = "qa.feedback"
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_quality_config.py -v`
Expected: PASS（3 passed）

- [ ] **Step 7: 提交**

```bash
git add apps/luna-corpus/app/core/config.py apps/luna-corpus/app/auth/permissions.py apps/luna-corpus/app/security/audit.py apps/luna-corpus/tests/quality/test_quality_config.py
git commit -m "feat(quality): add sample-rate config, QA_FEEDBACK permission and audit action"
```

---

### Task 4: Prometheus 指标

**Files:**
- Modify: `apps/luna-corpus/app/observability/metrics.py`
- Test: `apps/luna-corpus/tests/quality/test_quality_metrics.py`（新建）

**Interfaces:**
- Produces:
  - `QA_INTERACTIONS_TOTAL`（Counter，无 label）
  - `QA_FEEDBACK_TOTAL`（Counter，label `rating`）
  - `QA_EVALUATIONS_TOTAL`（Counter，label `status`）

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/quality/test_quality_metrics.py`：

```python
"""Quality metrics counters exist and increment."""
from app.observability.metrics import (
    QA_EVALUATIONS_TOTAL,
    QA_FEEDBACK_TOTAL,
    QA_INTERACTIONS_TOTAL,
)


def test_counters_increment():
    QA_INTERACTIONS_TOTAL.inc()
    QA_FEEDBACK_TOTAL.labels(rating="up").inc()
    QA_EVALUATIONS_TOTAL.labels(status="completed").inc()
    # _value.get() 反映累计值；只要 >0 即证明可用
    assert QA_INTERACTIONS_TOTAL._value.get() > 0
    assert QA_FEEDBACK_TOTAL.labels(rating="up")._value.get() > 0
    assert QA_EVALUATIONS_TOTAL.labels(status="completed")._value.get() > 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_quality_metrics.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 加指标**

在 `apps/luna-corpus/app/observability/metrics.py` 的 `INDEX_TASK_DURATION` 定义之后加：

```python
QA_INTERACTIONS_TOTAL = Counter(
    "qa_interactions_total",
    "Total recorded Q&A interactions",
)
QA_FEEDBACK_TOTAL = Counter(
    "qa_feedback_total",
    "Total user feedback submissions",
    ["rating"],
)
QA_EVALUATIONS_TOTAL = Counter(
    "qa_evaluations_total",
    "Total LLM quality evaluations by terminal status",
    ["status"],
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_quality_metrics.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/observability/metrics.py apps/luna-corpus/tests/quality/test_quality_metrics.py
git commit -m "feat(quality): add prometheus counters for interactions/feedback/evaluations"
```

---

### Task 5: QualityJudge 抽象与 LLM 实现

**Files:**
- Create: `apps/luna-corpus/app/quality/__init__.py`
- Create: `apps/luna-corpus/app/quality/judge.py`
- Test: `apps/luna-corpus/tests/quality/test_judge.py`（新建）

**Interfaces:**
- Consumes: `app.services.llm.generate_response(prompt, context=None) -> str`
- Produces:
  - `class QualityJudge(ABC)`，方法 `evaluate(question: str, answer: str, sources: list[dict]) -> QualityScores`
  - `@dataclass QualityScores(faithfulness: float|None, answer_relevance: float|None, citation_accuracy: float|None, rationale: str|None, model: str|None)`
  - `class LLMQualityJudge(QualityJudge)`
  - `get_judge() -> QualityJudge`（单例）、`reset_judge_cache()`
  - `parse_judge_response(raw: str) -> QualityScores`（解析失败抛 `ValueError`）

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/quality/test_judge.py`：

```python
"""Unit tests for the LLM quality judge."""
import pytest

from app.quality.judge import (
    LLMQualityJudge,
    QualityScores,
    parse_judge_response,
)


def test_parse_valid_json():
    raw = (
        '{"faithfulness": 0.9, "answer_relevance": 0.8, '
        '"citation_accuracy": 0.7, "rationale": "ok"}'
    )
    scores = parse_judge_response(raw)
    assert scores.faithfulness == 0.9
    assert scores.answer_relevance == 0.8
    assert scores.citation_accuracy == 0.7
    assert scores.rationale == "ok"


def test_parse_json_embedded_in_text():
    raw = 'Here is my judgement:\n{"faithfulness": 1.0, "answer_relevance": 1.0, "citation_accuracy": 1.0}'
    scores = parse_judge_response(raw)
    assert scores.faithfulness == 1.0


def test_parse_invalid_raises():
    with pytest.raises(ValueError):
        parse_judge_response("no json here")


def test_judge_uses_injected_generate(monkeypatch):
    def fake_generate(prompt, context=None):
        assert "Q?" in prompt
        return '{"faithfulness": 0.5, "answer_relevance": 0.5, "citation_accuracy": 0.5, "rationale": "r"}'

    judge = LLMQualityJudge(generate=fake_generate, model="fake-model")
    scores = judge.evaluate(
        "Q?", "A.", [{"document_id": "d1", "chunk_content": "c", "relevance_score": 0.9}]
    )
    assert isinstance(scores, QualityScores)
    assert scores.faithfulness == 0.5
    assert scores.model == "fake-model"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_judge.py -v`
Expected: FAIL（`ModuleNotFoundError: app.quality`）

- [ ] **Step 3: 建包 __init__**

创建 `apps/luna-corpus/app/quality/__init__.py`：

```python
"""Knowledge quality evaluation: interaction recording, feedback, LLM judging."""
```

- [ ] **Step 4: 实现 judge**

创建 `apps/luna-corpus/app/quality/judge.py`：

```python
"""Quality judge abstraction and LLM-based implementation."""
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

from app.core.config import get_settings

settings = get_settings()

_JUDGE_PROMPT = """你是 RAG 回答质量评审。仅依据【检索上下文】判断【回答】的质量，输出 JSON。

【问题】
{question}

【检索上下文】
{context}

【回答】
{answer}

请对三项打 0 到 1 的分数：
- faithfulness：回答是否完全由检索上下文支撑（无幻觉）。
- answer_relevance：回答是否切合问题。
- citation_accuracy：回答引用/使用的内容是否确实来自检索上下文。

只输出如下 JSON，不要多余文字：
{{"faithfulness": <float>, "answer_relevance": <float>, "citation_accuracy": <float>, "rationale": "<一句话理由>"}}
"""


@dataclass
class QualityScores:
    """Structured judge output."""

    faithfulness: float | None
    answer_relevance: float | None
    citation_accuracy: float | None
    rationale: str | None = None
    model: str | None = None


def _format_context(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "（无检索上下文）"
    return "\n\n".join(
        f"[来源 {i + 1}] {s.get('chunk_content', '')}"
        for i, s in enumerate(sources)
    )


def parse_judge_response(raw: str) -> QualityScores:
    """Extract the JSON object from the model output. Raises ValueError on failure."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in judge response")
    data = json.loads(match.group(0))
    return QualityScores(
        faithfulness=float(data["faithfulness"]),
        answer_relevance=float(data["answer_relevance"]),
        citation_accuracy=float(data["citation_accuracy"]),
        rationale=data.get("rationale"),
    )


class QualityJudge(ABC):
    """Scores a Q&A interaction for faithfulness/relevance/citation accuracy."""

    @abstractmethod
    def evaluate(
        self, question: str, answer: str, sources: list[dict[str, Any]]
    ) -> QualityScores:
        """Return structured quality scores. Raises on unrecoverable failure."""


class LLMQualityJudge(QualityJudge):
    """LLM-as-judge implementation using the configured chat model."""

    def __init__(
        self,
        generate: Callable[..., str] | None = None,
        model: str | None = None,
    ) -> None:
        if generate is None:
            from app.services.llm import generate_response

            generate = generate_response
        self._generate = generate
        self._model = model or settings.llm_provider.value

    def evaluate(
        self, question: str, answer: str, sources: list[dict[str, Any]]
    ) -> QualityScores:
        prompt = _JUDGE_PROMPT.format(
            question=question,
            context=_format_context(sources),
            answer=answer,
        )
        raw = self._generate(prompt=prompt, context=None)
        scores = parse_judge_response(raw)
        scores.model = self._model
        return scores


_instance: QualityJudge | None = None


def get_judge() -> QualityJudge:
    """Return the cached judge singleton, building it on first use."""
    global _instance
    if _instance is None:
        _instance = LLMQualityJudge()
    return _instance


def reset_judge_cache() -> None:
    """Drop the cached judge (test helper)."""
    global _instance
    _instance = None
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_judge.py -v`
Expected: PASS（4 passed）

- [ ] **Step 6: 提交**

```bash
git add apps/luna-corpus/app/quality/__init__.py apps/luna-corpus/app/quality/judge.py apps/luna-corpus/tests/quality/test_judge.py
git commit -m "feat(quality): add QualityJudge abstraction and LLM judge"
```

---

### Task 6: 交互记录器与采样判定

**Files:**
- Create: `apps/luna-corpus/app/quality/recorder.py`
- Test: `apps/luna-corpus/tests/quality/test_recorder.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `QAInteraction`；`app.observability.metrics.QA_INTERACTIONS_TOTAL`
- Produces:
  - `record_interaction(db, *, knowledge_base_id, question, answer, sources, retrieval_mode=None, processing_time_ms=None, conversation_id=None) -> str | None`（返回 interaction id；失败返回 None，绝不抛）
  - `should_evaluate(rand: float | None = None) -> bool`（按 `settings.quality_eval_sample_rate` 判定；`rand` 可注入以便测试）

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/quality/test_recorder.py`：

```python
"""Unit tests for interaction recorder and sampling."""
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, QAInteraction
from app.quality.recorder import record_interaction, should_evaluate


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_record_interaction_persists_and_returns_id():
    session = _session()
    interaction_id = record_interaction(
        session,
        knowledge_base_id="kb-1",
        question="Q?",
        answer="A.",
        sources=[{"document_id": "d1", "chunk_content": "c", "relevance_score": 0.9}],
        retrieval_mode="hybrid",
        processing_time_ms=100,
    )
    assert interaction_id is not None
    assert session.query(QAInteraction).count() == 1


def test_record_interaction_swallows_errors():
    broken = MagicMock()
    broken.add.side_effect = RuntimeError("db down")
    # 不应抛出，返回 None
    assert record_interaction(
        broken, knowledge_base_id="kb", question="Q", answer="A", sources=[]
    ) is None


def test_should_evaluate_bounds(monkeypatch):
    from app.quality import recorder

    monkeypatch.setattr(recorder.settings, "quality_eval_sample_rate", 0.0)
    assert should_evaluate(rand=0.0) is False
    monkeypatch.setattr(recorder.settings, "quality_eval_sample_rate", 1.0)
    assert should_evaluate(rand=0.999) is True
    monkeypatch.setattr(recorder.settings, "quality_eval_sample_rate", 0.5)
    assert should_evaluate(rand=0.4) is True
    assert should_evaluate(rand=0.6) is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_recorder.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 recorder**

创建 `apps/luna-corpus/app/quality/recorder.py`：

```python
"""Synchronous interaction recording and evaluation sampling.

Recording is a side channel: any failure is logged and swallowed so the
Q&A request always succeeds.
"""
import random
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import QAInteraction
from app.observability.logging import get_logger
from app.observability.metrics import QA_INTERACTIONS_TOTAL

settings = get_settings()
logger = get_logger("luna.quality.recorder")


def record_interaction(
    db: Session,
    *,
    knowledge_base_id: str,
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
    retrieval_mode: str | None = None,
    processing_time_ms: int | None = None,
    conversation_id: str | None = None,
) -> str | None:
    """Persist one Q&A interaction, returning its id (None on failure)."""
    try:
        interaction = QAInteraction(
            knowledge_base_id=knowledge_base_id,
            conversation_id=conversation_id,
            question=question,
            answer=answer,
            sources=sources,
            retrieval_mode=retrieval_mode,
            processing_time_ms=processing_time_ms,
        )
        db.add(interaction)
        db.flush()
        interaction_id = interaction.id
        db.commit()
        QA_INTERACTIONS_TOTAL.inc()
        return interaction_id
    except Exception:
        logger.warning(
            "record_interaction_failed",
            knowledge_base_id=knowledge_base_id,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return None


def should_evaluate(rand: float | None = None) -> bool:
    """Decide whether to trigger LLM evaluation for this interaction."""
    rate = settings.quality_eval_sample_rate
    if rate <= 0.0:
        return False
    if rate >= 1.0:
        return True
    draw = rand if rand is not None else random.random()
    return draw < rate
```

> 说明：`get_logger` 在 rerank 模块与本文件中均以关键字参数记录（structlog 风格），与现有 `app/observability/logging.py` 一致。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_recorder.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/quality/recorder.py apps/luna-corpus/tests/quality/test_recorder.py
git commit -m "feat(quality): add interaction recorder with fail-safe recording and sampling"
```

---

### Task 7: 异步评分任务

**Files:**
- Create: `apps/luna-corpus/app/quality/tasks.py`
- Test: `apps/luna-corpus/tests/quality/test_eval_task.py`（新建）

**Interfaces:**
- Consumes: `QAInteraction` / `QAEvaluation` / `EvaluationStatus`；`get_judge()`；`QualityScores`；`QA_EVALUATIONS_TOTAL`
- Produces:
  - `create_pending_evaluation(db, interaction_id: str) -> str | None`（建 pending 行，返回 evaluation id）
  - `_run_eval_task(evaluation_id: str, judge=None) -> None`（后台任务：独立 session，评分并落 completed/failed）

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/quality/test_eval_task.py`：

```python
"""Async evaluation task: completed and failed paths."""
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    EvaluationStatus,
    QAEvaluation,
    QAInteraction,
)
from app.quality import tasks as tasks_module
from app.quality.judge import QualityJudge, QualityScores


class _FakeJudge(QualityJudge):
    def __init__(self, scores=None, error=None):
        self._scores = scores
        self._error = error

    def evaluate(self, question, answer, sources):
        if self._error:
            raise self._error
        return self._scores


def _setup(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    # 让任务内部的 SessionLocal() 复用本引擎
    monkeypatch.setattr(tasks_module, "SessionLocal", Session)
    return Session


def _interaction(session):
    inter = QAInteraction(
        knowledge_base_id="kb", question="Q", answer="A", sources=[]
    )
    session.add(inter)
    session.commit()
    return inter.id


def test_eval_task_completed(monkeypatch):
    Session = _setup(monkeypatch)
    session = Session()
    interaction_id = _interaction(session)
    eval_id = tasks_module.create_pending_evaluation(session, interaction_id)

    judge = _FakeJudge(
        scores=QualityScores(0.9, 0.8, 0.7, rationale="ok", model="fake")
    )
    tasks_module._run_eval_task(eval_id, judge=judge)

    row = session.get(QAEvaluation, eval_id)
    session.refresh(row)
    assert row.status == EvaluationStatus.COMPLETED
    assert row.faithfulness == 0.9
    assert row.judge_model == "fake"


def test_eval_task_failed(monkeypatch):
    Session = _setup(monkeypatch)
    session = Session()
    interaction_id = _interaction(session)
    eval_id = tasks_module.create_pending_evaluation(session, interaction_id)

    judge = _FakeJudge(error=RuntimeError("llm down"))
    tasks_module._run_eval_task(eval_id, judge=judge)

    row = session.get(QAEvaluation, eval_id)
    session.refresh(row)
    assert row.status == EvaluationStatus.FAILED
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_eval_task.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 tasks**

创建 `apps/luna-corpus/app/quality/tasks.py`：

```python
"""Background LLM evaluation task.

Mirrors the ingestion index-task pattern: runs in its own DB session and
never raises into the caller; failures land as EvaluationStatus.FAILED.
"""
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import EvaluationStatus, QAEvaluation, QAInteraction
from app.observability.logging import get_logger
from app.observability.metrics import QA_EVALUATIONS_TOTAL
from app.quality.judge import QualityJudge, get_judge

logger = get_logger("luna.quality.tasks")


def create_pending_evaluation(db: Session, interaction_id: str) -> str | None:
    """Create a pending QAEvaluation row, returning its id (None on failure)."""
    try:
        evaluation = QAEvaluation(
            interaction_id=interaction_id,
            status=EvaluationStatus.PENDING,
        )
        db.add(evaluation)
        db.flush()
        eval_id = evaluation.id
        db.commit()
        return eval_id
    except Exception:
        logger.warning(
            "create_pending_evaluation_failed",
            interaction_id=interaction_id,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _run_eval_task(evaluation_id: str, judge: QualityJudge | None = None) -> None:
    """Background task: score an interaction and persist terminal status."""
    judge = judge or get_judge()
    db = SessionLocal()
    try:
        evaluation = db.get(QAEvaluation, evaluation_id)
        if evaluation is None:
            logger.warning("evaluation_missing", evaluation_id=evaluation_id)
            return
        interaction = db.get(QAInteraction, evaluation.interaction_id)
        if interaction is None:
            logger.warning(
                "interaction_missing", evaluation_id=evaluation_id
            )
            evaluation.status = EvaluationStatus.FAILED
            db.commit()
            QA_EVALUATIONS_TOTAL.labels(status="failed").inc()
            return

        try:
            scores = judge.evaluate(
                interaction.question, interaction.answer, interaction.sources
            )
            evaluation.faithfulness = scores.faithfulness
            evaluation.answer_relevance = scores.answer_relevance
            evaluation.citation_accuracy = scores.citation_accuracy
            evaluation.judge_model = scores.model
            evaluation.rationale = scores.rationale
            evaluation.status = EvaluationStatus.COMPLETED
            db.commit()
            QA_EVALUATIONS_TOTAL.labels(status="completed").inc()
        except Exception:
            logger.warning(
                "evaluation_failed", evaluation_id=evaluation_id, exc_info=True
            )
            evaluation.status = EvaluationStatus.FAILED
            db.commit()
            QA_EVALUATIONS_TOTAL.labels(status="failed").inc()
    finally:
        db.close()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_eval_task.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/quality/tasks.py apps/luna-corpus/tests/quality/test_eval_task.py
git commit -m "feat(quality): add async LLM evaluation task with completed/failed paths"
```

---

### Task 8: 反馈服务

**Files:**
- Create: `apps/luna-corpus/app/quality/feedback.py`
- Test: `apps/luna-corpus/tests/quality/test_feedback_service.py`（新建）

**Interfaces:**
- Consumes: `QAInteraction` / `QAFeedback` / `FeedbackRating` / `FeedbackErrorType`；`QA_FEEDBACK_TOTAL`
- Produces:
  - `get_interaction(db, interaction_id, knowledge_base_id) -> QAInteraction | None`（KB scope 校验）
  - `create_feedback(db, *, interaction_id, rating, error_type=None, comment=None, created_by_user_id=None) -> QAFeedback`

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/quality/test_feedback_service.py`：

```python
"""Unit tests for feedback service."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, FeedbackErrorType, FeedbackRating, QAInteraction
from app.quality.feedback import create_feedback, get_interaction


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _interaction(session, kb="kb-1"):
    inter = QAInteraction(
        knowledge_base_id=kb, question="Q", answer="A", sources=[]
    )
    session.add(inter)
    session.commit()
    return inter.id


def test_get_interaction_scoped_by_kb():
    session = _session()
    iid = _interaction(session, kb="kb-1")
    assert get_interaction(session, iid, "kb-1") is not None
    assert get_interaction(session, iid, "kb-other") is None


def test_create_feedback_persists():
    session = _session()
    iid = _interaction(session)
    fb = create_feedback(
        session,
        interaction_id=iid,
        rating=FeedbackRating.DOWN,
        error_type=FeedbackErrorType.HALLUCINATION,
        comment="bad",
        created_by_user_id="u1",
    )
    assert fb.id is not None
    assert fb.rating == FeedbackRating.DOWN
    assert fb.error_type == FeedbackErrorType.HALLUCINATION
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_feedback_service.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 feedback 服务**

创建 `apps/luna-corpus/app/quality/feedback.py`：

```python
"""Feedback service: KB-scoped lookup and feedback creation."""
from sqlalchemy.orm import Session

from app.db.models import (
    FeedbackErrorType,
    FeedbackRating,
    QAFeedback,
    QAInteraction,
)
from app.observability.metrics import QA_FEEDBACK_TOTAL


def get_interaction(
    db: Session, interaction_id: str, knowledge_base_id: str
) -> QAInteraction | None:
    """Return the interaction only if it belongs to the given knowledge base."""
    return (
        db.query(QAInteraction)
        .filter(
            QAInteraction.id == interaction_id,
            QAInteraction.knowledge_base_id == knowledge_base_id,
        )
        .first()
    )


def create_feedback(
    db: Session,
    *,
    interaction_id: str,
    rating: FeedbackRating,
    error_type: FeedbackErrorType | None = None,
    comment: str | None = None,
    created_by_user_id: str | None = None,
) -> QAFeedback:
    """Persist a feedback row (caller commits)."""
    feedback = QAFeedback(
        interaction_id=interaction_id,
        rating=rating,
        error_type=error_type,
        comment=comment,
        created_by_user_id=created_by_user_id,
    )
    db.add(feedback)
    db.flush()
    QA_FEEDBACK_TOTAL.labels(rating=rating.value).inc()
    return feedback
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_feedback_service.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/quality/feedback.py apps/luna-corpus/tests/quality/test_feedback_service.py
git commit -m "feat(quality): add feedback service with KB-scoped lookup"
```

---

### Task 9: 聚合查询

**Files:**
- Create: `apps/luna-corpus/app/quality/aggregation.py`
- Test: `apps/luna-corpus/tests/quality/test_aggregation.py`（新建）

**Interfaces:**
- Consumes: `QAInteraction` / `QAFeedback` / `QAEvaluation` / `FeedbackRating` / `EvaluationStatus`
- Produces:
  - `summarize_quality(db, knowledge_base_id: str, days: int = 7) -> dict`，键：`total_interactions, feedback_count, thumbs_up_rate, avg_faithfulness, avg_relevance, avg_citation_accuracy, error_type_breakdown, by_retrieval_mode`

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/quality/test_aggregation.py`：

```python
"""Unit tests for quality aggregation."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    EvaluationStatus,
    FeedbackErrorType,
    FeedbackRating,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
)
from app.quality.aggregation import summarize_quality


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_summary_empty_returns_zeros():
    session = _session()
    summary = summarize_quality(session, "kb-1")
    assert summary["total_interactions"] == 0
    assert summary["feedback_count"] == 0
    assert summary["thumbs_up_rate"] is None
    assert summary["avg_faithfulness"] is None
    assert summary["error_type_breakdown"] == {}


def test_summary_aggregates():
    session = _session()
    inter = QAInteraction(
        knowledge_base_id="kb-1",
        question="Q",
        answer="A",
        sources=[],
        retrieval_mode="hybrid",
    )
    session.add(inter)
    session.commit()

    session.add_all([
        QAFeedback(interaction_id=inter.id, rating=FeedbackRating.UP),
        QAFeedback(
            interaction_id=inter.id,
            rating=FeedbackRating.DOWN,
            error_type=FeedbackErrorType.HALLUCINATION,
        ),
        QAEvaluation(
            interaction_id=inter.id,
            faithfulness=0.8,
            answer_relevance=0.6,
            citation_accuracy=1.0,
            status=EvaluationStatus.COMPLETED,
        ),
    ])
    session.commit()

    summary = summarize_quality(session, "kb-1")
    assert summary["total_interactions"] == 1
    assert summary["feedback_count"] == 2
    assert summary["thumbs_up_rate"] == 0.5
    assert summary["avg_faithfulness"] == 0.8
    assert summary["error_type_breakdown"]["hallucination"] == 1
    assert summary["by_retrieval_mode"]["hybrid"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_aggregation.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现聚合**

创建 `apps/luna-corpus/app/quality/aggregation.py`：

```python
"""Read-only quality aggregation for the monitoring summary endpoint."""
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    EvaluationStatus,
    FeedbackRating,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
)


def summarize_quality(
    db: Session, knowledge_base_id: str, days: int = 7
) -> dict:
    """Aggregate interactions, feedback and evaluations for a KB / time window."""
    since = datetime.utcnow() - timedelta(days=days)

    base = db.query(QAInteraction).filter(
        QAInteraction.knowledge_base_id == knowledge_base_id,
        QAInteraction.created_at >= since,
    )
    total_interactions = base.count()

    # by_retrieval_mode
    mode_rows = (
        db.query(QAInteraction.retrieval_mode, func.count(QAInteraction.id))
        .filter(
            QAInteraction.knowledge_base_id == knowledge_base_id,
            QAInteraction.created_at >= since,
        )
        .group_by(QAInteraction.retrieval_mode)
        .all()
    )
    by_retrieval_mode = {mode: count for mode, count in mode_rows if mode}

    # feedback joined to in-scope interactions
    feedback_q = (
        db.query(QAFeedback)
        .join(QAInteraction, QAFeedback.interaction_id == QAInteraction.id)
        .filter(
            QAInteraction.knowledge_base_id == knowledge_base_id,
            QAInteraction.created_at >= since,
        )
    )
    feedback_count = feedback_q.count()
    up_count = feedback_q.filter(QAFeedback.rating == FeedbackRating.UP).count()
    thumbs_up_rate = (up_count / feedback_count) if feedback_count else None

    error_rows = (
        db.query(QAFeedback.error_type, func.count(QAFeedback.id))
        .join(QAInteraction, QAFeedback.interaction_id == QAInteraction.id)
        .filter(
            QAInteraction.knowledge_base_id == knowledge_base_id,
            QAInteraction.created_at >= since,
            QAFeedback.error_type.isnot(None),
        )
        .group_by(QAFeedback.error_type)
        .all()
    )
    error_type_breakdown = {
        et.value: count for et, count in error_rows if et is not None
    }

    # evaluation averages over completed rows
    avg_row = (
        db.query(
            func.avg(QAEvaluation.faithfulness),
            func.avg(QAEvaluation.answer_relevance),
            func.avg(QAEvaluation.citation_accuracy),
        )
        .join(QAInteraction, QAEvaluation.interaction_id == QAInteraction.id)
        .filter(
            QAInteraction.knowledge_base_id == knowledge_base_id,
            QAInteraction.created_at >= since,
            QAEvaluation.status == EvaluationStatus.COMPLETED,
        )
        .one()
    )

    def _round(v):
        return round(float(v), 4) if v is not None else None

    return {
        "total_interactions": total_interactions,
        "feedback_count": feedback_count,
        "thumbs_up_rate": _round(thumbs_up_rate),
        "avg_faithfulness": _round(avg_row[0]),
        "avg_relevance": _round(avg_row[1]),
        "avg_citation_accuracy": _round(avg_row[2]),
        "error_type_breakdown": error_type_breakdown,
        "by_retrieval_mode": by_retrieval_mode,
    }
```

> 注：`thumbs_up_rate` 期望 `0.5` 与 `_round(0.5)==0.5` 一致；`avg_faithfulness` 期望 `0.8` 与 `_round(0.8)==0.8` 一致。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_aggregation.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/quality/aggregation.py apps/luna-corpus/tests/quality/test_aggregation.py
git commit -m "feat(quality): add read-only quality aggregation"
```

---

### Task 10: rag_graph 返回 retrieval_mode

**Files:**
- Modify: `apps/luna-corpus/app/graph/rag_graph.py:295-299`（`answer_question` 返回 dict）
- Test: `apps/luna-corpus/tests/quality/test_rag_graph_mode.py`（新建）

**Interfaces:**
- Produces: `answer_question(...)` 返回 dict 增加键 `retrieval_mode`（值取 `settings.retrieval_mode.value`）

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/quality/test_rag_graph_mode.py`：

```python
"""answer_question exposes retrieval_mode for interaction recording."""
from unittest.mock import patch

from app.graph import rag_graph


def test_answer_question_returns_retrieval_mode():
    fake_graph = type("G", (), {})()
    fake_graph.invoke = lambda state: {"answer": "A", "sources": []}
    with patch.object(rag_graph, "get_rag_graph", return_value=fake_graph):
        result = rag_graph.answer_question("Q", knowledge_base_id="kb-1")
    assert "retrieval_mode" in result
    assert result["retrieval_mode"] == rag_graph.settings.retrieval_mode.value
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_rag_graph_mode.py -v`
Expected: FAIL（`KeyError`/`assert 'retrieval_mode' in result`）

- [ ] **Step 3: 修改返回值**

将 `apps/luna-corpus/app/graph/rag_graph.py` 中 `answer_question` 的返回改为：

```python
    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "processing_time_ms": processing_time_ms,
        "retrieval_mode": settings.retrieval_mode.value,
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/quality/test_rag_graph_mode.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/graph/rag_graph.py apps/luna-corpus/tests/quality/test_rag_graph_mode.py
git commit -m "feat(quality): expose retrieval_mode from answer_question"
```

---

### Task 11: API 接线 —— 记录钩子、反馈端点、聚合端点

**Files:**
- Modify: `apps/luna-corpus/app/api/routes.py`
- Test: `apps/luna-corpus/tests/api/test_quality_api.py`（新建）

**Interfaces:**
- Consumes: `record_interaction`、`should_evaluate`、`create_pending_evaluation`、`_run_eval_task`、`create_feedback`、`get_interaction`、`summarize_quality`；`PermissionSlug.QA_FEEDBACK`；`AuditAction.QA_FEEDBACK`；`FeedbackRating` / `FeedbackErrorType`
- Produces:
  - `AnswerResponse` / `MultiTurnAnswerResponse` 新增字段 `answer_id: str | None = None`
  - `POST /api/v1/qa/interactions/{answer_id}/feedback`
  - `GET /api/v1/qa/quality/summary?days=7`

- [ ] **Step 1: 写失败集成测试**

创建 `apps/luna-corpus/tests/api/test_quality_api.py`：

```python
"""Integration tests for quality endpoints."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.permissions import PermissionSlug
from app.db.database import get_db
from app.db.models import (
    Base,
    KnowledgeBase,
    Permission,
    Role,
    Tenant,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.main import create_app


@pytest.fixture
def app_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="Research", slug="research", tenant=tenant)
    kb = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    kb2 = KnowledgeBase(name="Other", slug="other", workspace=workspace)
    session.add_all([kb, kb2])
    session.commit()
    context = {
        "tenant_id": tenant.id,
        "workspace_id": workspace.id,
        "kb_one_id": kb.id,
        "kb_two_id": kb2.id,
    }
    session.close()
    yield engine, Session, context
    engine.dispose()


@pytest.fixture
def client(app_db):
    engine, Session, _ = app_db

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _user(Session, workspace_id, slugs):
    session = Session()
    try:
        user = User(email="u@example.com", display_name="u")
        perms = []
        for slug in slugs:
            p = session.query(Permission).filter(Permission.slug == slug).first()
            if not p:
                p = Permission(name=slug, slug=slug, description=slug)
            perms.append(p)
        role = Role(name="r", slug="r", is_system=True, permissions=perms)
        session.add(
            WorkspaceMembership(user=user, workspace_id=workspace_id, roles=[role])
        )
        session.commit()
        return user.id
    finally:
        session.close()


def _headers(context, user_id, kb_key="kb_one_id"):
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": context[kb_key],
    }


@patch("app.api.routes.answer_question")
def test_query_records_interaction_and_returns_answer_id(mock_answer, client, app_db):
    _, Session, context = app_db
    mock_answer.return_value = {
        "answer": "A.",
        "sources": [{"document_id": "d1", "chunk_content": "c", "relevance_score": 0.9}],
        "processing_time_ms": 42,
        "retrieval_mode": "vector",
    }
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_QUERY])
    resp = client.post(
        "/api/v1/qa/query",
        headers=_headers(context, uid),
        json={"question": "Q?"},
    )
    assert resp.status_code == 200
    assert resp.json()["answer_id"] is not None


@patch("app.api.routes.answer_question")
def test_feedback_roundtrip_and_cross_kb_404(mock_answer, client, app_db):
    _, Session, context = app_db
    mock_answer.return_value = {
        "answer": "A.",
        "sources": [],
        "processing_time_ms": 10,
        "retrieval_mode": "vector",
    }
    uid = _user(
        Session,
        context["workspace_id"],
        [PermissionSlug.QA_QUERY, PermissionSlug.QA_FEEDBACK],
    )
    q = client.post(
        "/api/v1/qa/query", headers=_headers(context, uid), json={"question": "Q?"}
    )
    answer_id = q.json()["answer_id"]

    ok = client.post(
        f"/api/v1/qa/interactions/{answer_id}/feedback",
        headers=_headers(context, uid),
        json={"rating": "down", "error_type": "hallucination", "comment": "bad"},
    )
    assert ok.status_code == 201

    cross = client.post(
        f"/api/v1/qa/interactions/{answer_id}/feedback",
        headers=_headers(context, uid, kb_key="kb_two_id"),
        json={"rating": "up"},
    )
    assert cross.status_code == 404


def test_quality_summary_empty(client, app_db):
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_QUERY])
    resp = client.get(
        "/api/v1/qa/quality/summary?days=7", headers=_headers(context, uid)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_interactions"] == 0
    assert body["thumbs_up_rate"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/api/test_quality_api.py -v`
Expected: FAIL（`answer_id` KeyError / 404 endpoint 未定义 → 405/404）

- [ ] **Step 3: 加导入与请求/响应模型**

在 `apps/luna-corpus/app/api/routes.py` 顶部导入区加入（放在现有 `from app.services...` 附近）：

```python
from app.db.models import FeedbackErrorType, FeedbackRating
from app.quality.aggregation import summarize_quality
from app.quality.feedback import create_feedback, get_interaction
from app.quality.recorder import record_interaction, should_evaluate
from app.quality.tasks import _run_eval_task, create_pending_evaluation
```

在 `AnswerResponse` 类中加字段：

```python
    answer_id: str | None = None
```

在 `MultiTurnAnswerResponse` 类中加字段：

```python
    answer_id: str | None = None
```

在 `AnswerResponse` 定义之后新增请求/响应模型：

```python
class FeedbackRequest(BaseModel):
    """User feedback on an answer."""

    rating: FeedbackRating
    error_type: FeedbackErrorType | None = None
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    """Feedback creation response."""

    id: str
    interaction_id: str
    rating: str


class QualitySummaryResponse(BaseModel):
    """Aggregated quality metrics for a knowledge base / time window."""

    total_interactions: int
    feedback_count: int
    thumbs_up_rate: float | None
    avg_faithfulness: float | None
    avg_relevance: float | None
    avg_citation_accuracy: float | None
    error_type_breakdown: dict[str, int]
    by_retrieval_mode: dict[str, int]
```

- [ ] **Step 4: 在 `/qa/query` 接入记录钩子**

在 `query` 端点中，`db.commit()`（QA_QUERY 审计后）之后、`return AnswerResponse(...)` 之前，加入记录逻辑，并把 `answer_id` 带入响应。将原来的 `return AnswerResponse(...)` 替换为：

```python
    answer_id = record_interaction(
        db,
        knowledge_base_id=context.knowledge_base.id,
        question=question_req.question,
        answer=result["answer"],
        sources=result["sources"],
        retrieval_mode=result.get("retrieval_mode"),
        processing_time_ms=result["processing_time_ms"],
    )

    if answer_id and should_evaluate():
        eval_id = create_pending_evaluation(db, answer_id)
        if eval_id:
            background_tasks.add_task(_run_eval_task, eval_id)

    return AnswerResponse(
        answer=result["answer"],
        sources=enriched_sources,
        processing_time_ms=result["processing_time_ms"],
        answer_id=answer_id,
    )
```

同时给 `query` 端点函数签名加入 `background_tasks: BackgroundTasks` 参数（放在 `question_req` 之后、`db` 之前）：

```python
async def query(
    question_req: QuestionRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_QUERY)),
    ],
) -> AnswerResponse:
```

- [ ] **Step 5: 在 `/qa/multi-turn` 接入记录钩子**

在 `multi_turn_query` 端点中，`add_message_to_conversation`（assistant 消息）之后、构造响应之前加入记录，并在返回体带上 `answer_id`。给函数签名加 `background_tasks: BackgroundTasks`（`req` 之后、`db` 之前）。将 `return MultiTurnAnswerResponse(...)` 替换为：

```python
    answer_id = record_interaction(
        db,
        knowledge_base_id=context.knowledge_base.id,
        question=req.question,
        answer=result["answer"],
        sources=result["sources"],
        retrieval_mode=result.get("retrieval_mode"),
        processing_time_ms=result["processing_time_ms"],
        conversation_id=conversation_id,
    )

    if answer_id and should_evaluate():
        eval_id = create_pending_evaluation(db, answer_id)
        if eval_id:
            background_tasks.add_task(_run_eval_task, eval_id)

    return MultiTurnAnswerResponse(
        answer=result["answer"],
        conversation_id=conversation_id,
        sources=enriched_sources,
        processing_time_ms=result["processing_time_ms"],
        answer_id=answer_id,
    )
```

> 注：`answer_question_multi_turn` 当前返回 dict 未含 `retrieval_mode`，`result.get("retrieval_mode")` 返回 None，可接受（字段可空）。

- [ ] **Step 6: 新增反馈端点**

在文档管理端点区之前（`# Document Management` 注释附近的合适位置）加入：

```python
@router.post(
    "/qa/interactions/{answer_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    answer_id: str,
    feedback_req: FeedbackRequest,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_FEEDBACK)),
    ],
) -> FeedbackResponse:
    """Submit thumbs up/down feedback on a recorded Q&A interaction."""
    interaction = get_interaction(db, answer_id, context.knowledge_base.id)
    if interaction is None:
        raise HTTPException(status_code=404, detail="Interaction not found")

    feedback = create_feedback(
        db,
        interaction_id=answer_id,
        rating=feedback_req.rating,
        error_type=feedback_req.error_type,
        comment=feedback_req.comment,
        created_by_user_id=context.user.id,
    )
    AuditService().record(
        db,
        action=AuditAction.QA_FEEDBACK,
        resource_type="qa_interaction",
        resource_id=answer_id,
        result=AuditResult.SUCCESS,
        context=context,
    )
    db.commit()
    db.refresh(feedback)

    return FeedbackResponse(
        id=feedback.id,
        interaction_id=feedback.interaction_id,
        rating=feedback.rating.value,
    )
```

- [ ] **Step 7: 新增聚合端点**

在反馈端点之后加入：

```python
@router.get("/qa/quality/summary", response_model=QualitySummaryResponse)
async def quality_summary(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_QUERY)),
    ],
    days: int = Query(default=7, ge=1, le=365),
) -> QualitySummaryResponse:
    """Aggregated quality metrics for the current knowledge base."""
    summary = summarize_quality(db, context.knowledge_base.id, days=days)
    return QualitySummaryResponse(**summary)
```

- [ ] **Step 8: 运行集成测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/api/test_quality_api.py -v`
Expected: PASS（3 passed）

- [ ] **Step 9: 提交**

```bash
git add apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/api/test_quality_api.py
git commit -m "feat(quality): wire recording into QA endpoints, add feedback and summary endpoints"
```

---

### Task 12: 全量回归与文档

**Files:**
- Modify: `apps/luna-corpus/tests/api/conftest.py`（如需，确保 quality 测试的 fixture 可用——本计划的 quality API 测试自带 fixture，通常无需改动）

- [ ] **Step 1: 跑 quality 全套单元/异步测试**

Run: `cd apps/luna-corpus && python -m pytest tests/quality -v`
Expected: 全部 PASS

- [ ] **Step 2: 跑 API 集成测试**

Run: `cd apps/luna-corpus && python -m pytest tests/api/test_quality_api.py -v`
Expected: 全部 PASS

- [ ] **Step 3: 跑全量测试确认无回归**

Run: `npm exec nx test luna-corpus`
（或 `cd apps/luna-corpus && python -m pytest`）
Expected: 全部 PASS（无既有测试因新增字段/权限而失败）

- [ ] **Step 4: 若既有问答测试因 `background_tasks` 签名变动失败**

检查失败项：`/qa/query`、`/qa/multi-turn` 现在多了 `background_tasks: BackgroundTasks` 参数。FastAPI 会自动注入，TestClient 调用无需改动。若有测试直接调用端点函数（非通过 client），需传入一个 `BackgroundTasks()` 实例。逐个修正。

- [ ] **Step 5: 最终提交**

```bash
git add -A
git commit -m "test(quality): full regression pass for quality evaluation"
```

---

## Self-Review 记录

**Spec 覆盖检查**：
- 三张表 + migration → Task 1、2 ✓
- 记录钩子 + 采样 → Task 6、11 ✓
- QualityJudge 抽象 + LLM 实现 → Task 5 ✓
- 异步评分任务 → Task 7 ✓
- feedback / aggregation → Task 8、9 ✓
- answer_id 响应 + 反馈端点 + QA_FEEDBACK 权限 → Task 3、11 ✓
- 聚合端点 → Task 11 ✓
- 配置 `quality_eval_sample_rate` → Task 3 ✓
- 3 个 Prometheus 指标 → Task 4 ✓
- 单元/集成/异步测试 → 每个 Task 均含 ✓
- 失败降级（记录不拖垮问答）→ Task 6 recorder + Task 11 集成测试注入 mock ✓

**类型一致性**：`QualityScores` 字段、`record_interaction` 签名、`summarize_quality` 返回键在 producer/consumer 间一致；`QualitySummaryResponse` 字段与 `summarize_quality` 返回键逐一对应。

**留意点**：`retrieval_mode` 仅单轮 `answer_question` 提供（Task 10）；多轮暂为 None，字段可空，已在 Task 11 Step 5 注明。
