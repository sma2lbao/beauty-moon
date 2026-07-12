# 用户反馈闭环：运营复审工单流 —— 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有质量模块上补齐「运营复审工单流」——把差评/低分的问答派生成待复审队列，运营可标注根因并处置，形成反馈闭环。

**Architecture:** 零耦合、不改采集层。不建物化队列表，队列是运行时派生查询（interaction LEFT JOIN feedback/evaluation/review）；只新增一张 `qa_reviews` 处置记录表。新增服务模块 `app/quality/review.py` 与 4 个 KB 作用域 REST 端点，复审是独立运营通道，正常报错（区别于旁路 recorder 的 fail-safe）。

**Tech Stack:** Python 3.14、FastAPI、SQLAlchemy 2.x（Mapped/mapped_column）、Alembic、Pydantic v2、pytest、SQLite（测试）。

## Global Constraints

- 交流与文档一律中文；工作区包管理器统一 `npm`（`npm exec nx ...`）。
- 测试命令统一走 nx：`npm exec nx test luna-corpus -- <pytest-args>`。
- 服务函数纯函数风格：传入 `Session`，服务层 `flush`，路由层负责 `commit`（沿用 `app/quality/feedback.py`）。
- 所有复审操作 KB 作用域校验：interaction 不属当前 KB → 服务层返回 `None`，路由层转 404（复用 `get_interaction` 模式）。
- 入队低分阈值走配置 `quality_review_score_threshold`，默认 `0.6`，判定为**严格小于**（`=0.6` 不入队）。
- 新枚举命名遵循现有小写风格：`sa.Enum(..., name="reviewstatus")` / `"reviewrootcause"`。

---

### Task 1: 数据模型、枚举与迁移

**Files:**
- Modify: `apps/luna-corpus/app/db/models.py`（在第 608 行 `QAEvaluation` 之后、第 611 行 metadata 注册之前插入）
- Create: `apps/luna-corpus/alembic/versions/20260712_0010_qa_reviews.py`
- Test: `apps/luna-corpus/tests/quality/test_review_models.py`

**Interfaces:**
- Produces:
  - `ReviewStatus(str, enum.Enum)`：`OPEN="open"` / `RESOLVED="resolved"` / `DISMISSED="dismissed"`
  - `ReviewRootCause(str, enum.Enum)`：`KNOWLEDGE_GAP="knowledge_gap"` / `CHUNK_ERROR="chunk_error"` / `HALLUCINATION="hallucination"` / `OUTDATED="outdated"` / `OTHER="other"`
  - `QAReview(Base)` 表 `qa_reviews`，字段：`id: str`、`interaction_id: str`(FK→qa_interactions, CASCADE, unique)、`status: ReviewStatus`(默认 OPEN, not null)、`root_cause: ReviewRootCause | None`、`resolution_note: str | None`、`assignee_user_id: str | None`、`resolved_by_user_id: str | None`、`created_at: datetime`、`updated_at: datetime`
- Consumes: `Base`、`QAInteraction`（已存在于 models.py）

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/quality/test_review_models.py`：

```python
"""Unit tests for the qa_reviews model."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    QAInteraction,
    QAReview,
    ReviewRootCause,
    ReviewStatus,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _interaction(session):
    interaction = QAInteraction(
        knowledge_base_id="kb-1", question="Q", answer="A", sources=[]
    )
    session.add(interaction)
    session.commit()
    return interaction


def test_review_defaults_to_open():
    session = _session()
    interaction = _interaction(session)
    review = QAReview(interaction_id=interaction.id)
    session.add(review)
    session.commit()
    row = session.query(QAReview).one()
    assert row.id
    assert row.status == ReviewStatus.OPEN
    assert row.root_cause is None
    assert row.created_at is not None


def test_review_stores_resolution_fields():
    session = _session()
    interaction = _interaction(session)
    review = QAReview(
        interaction_id=interaction.id,
        status=ReviewStatus.RESOLVED,
        root_cause=ReviewRootCause.KNOWLEDGE_GAP,
        resolution_note="补充了缺失文档",
        resolved_by_user_id="user-9",
    )
    session.add(review)
    session.commit()
    row = session.query(QAReview).one()
    assert row.status == ReviewStatus.RESOLVED
    assert row.root_cause == ReviewRootCause.KNOWLEDGE_GAP
    assert row.resolution_note == "补充了缺失文档"


def test_one_review_per_interaction():
    session = _session()
    interaction = _interaction(session)
    session.add(QAReview(interaction_id=interaction.id))
    session.commit()
    session.add(QAReview(interaction_id=interaction.id))
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm exec nx test luna-corpus -- tests/quality/test_review_models.py -v`
Expected: FAIL —— `ImportError: cannot import name 'QAReview'`

- [ ] **Step 3: 在 models.py 中新增枚举与模型**

在 `apps/luna-corpus/app/db/models.py` 第 608 行（`QAEvaluation` 类结束）之后、`# 注册元数据字段定义表...`（第 611 行）之前插入：

```python
class ReviewStatus(str, enum.Enum):
    """Lifecycle of an operational review ticket."""

    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ReviewRootCause(str, enum.Enum):
    """Operator-assigned root cause for a reviewed interaction."""

    KNOWLEDGE_GAP = "knowledge_gap"
    CHUNK_ERROR = "chunk_error"
    HALLUCINATION = "hallucination"
    OUTDATED = "outdated"
    OTHER = "other"


class QAReview(Base):
    """Operational triage record for a low-quality Q&A interaction."""

    __tablename__ = "qa_reviews"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    interaction_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("qa_interactions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), nullable=False, default=ReviewStatus.OPEN
    )
    root_cause: Mapped[ReviewRootCause | None] = mapped_column(
        Enum(ReviewRootCause), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_user_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    resolved_by_user_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npm exec nx test luna-corpus -- tests/quality/test_review_models.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 创建 Alembic 迁移**

创建 `apps/luna-corpus/alembic/versions/20260712_0010_qa_reviews.py`：

```python
"""feedback review loop: qa_reviews

Revision ID: 20260712_0010
Revises: 20260709_0009
Create Date: 2026-07-12

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import CHAR

revision = "20260712_0010"
down_revision = "20260709_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qa_reviews",
        sa.Column("id", CHAR(36), primary_key=True),
        sa.Column("interaction_id", CHAR(36), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "resolved", "dismissed", name="reviewstatus"),
            nullable=False,
        ),
        sa.Column(
            "root_cause",
            sa.Enum(
                "knowledge_gap",
                "chunk_error",
                "hallucination",
                "outdated",
                "other",
                name="reviewrootcause",
            ),
            nullable=True,
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("assignee_user_id", CHAR(36), nullable=True),
        sa.Column("resolved_by_user_id", CHAR(36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["qa_interactions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("interaction_id", name="uq_qa_reviews_interaction"),
    )
    op.create_index(
        "ix_qa_reviews_interaction", "qa_reviews", ["interaction_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_qa_reviews_interaction", table_name="qa_reviews")
    op.drop_table("qa_reviews")
```

- [ ] **Step 6: 提交**

```bash
git add apps/luna-corpus/app/db/models.py \
  apps/luna-corpus/alembic/versions/20260712_0010_qa_reviews.py \
  apps/luna-corpus/tests/quality/test_review_models.py
git commit -m "feat(quality): add QAReview model and migration for review loop"
```

---

### Task 2: 配置阈值、权限与审计动作

**Files:**
- Modify: `apps/luna-corpus/app/core/config.py`（第 219 行 `quality_eval_sample_rate` Field 定义之后）
- Modify: `apps/luna-corpus/app/auth/permissions.py`（第 16 行 `QA_FEEDBACK` 之后 + admin/editor 授予块）
- Modify: `apps/luna-corpus/app/security/audit.py`（第 22 行 `QA_FEEDBACK` 之后）
- Test: `apps/luna-corpus/tests/quality/test_review_config.py`

**Interfaces:**
- Produces:
  - `settings.quality_review_score_threshold: float`（默认 `0.6`）
  - `PermissionSlug.QA_REVIEW = "qa:review"`（授予 `WORKSPACE_ADMIN`、`KB_EDITOR`，不授予 `KB_READER`）
  - `AuditAction.QA_REVIEW_RESOLVE = "qa.review_resolve"`、`AuditAction.QA_REVIEW_DISMISS = "qa.review_dismiss"`

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/quality/test_review_config.py`：

```python
"""Config / permission / audit wiring for the review loop."""
from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS, PermissionSlug, RoleSlug
from app.core.config import get_settings
from app.security.audit import AuditAction


def test_review_score_threshold_default():
    assert get_settings().quality_review_score_threshold == 0.6


def test_qa_review_permission_seeded():
    assert PermissionSlug.QA_REVIEW == "qa:review"
    for role in (RoleSlug.WORKSPACE_ADMIN, RoleSlug.KB_EDITOR):
        assert PermissionSlug.QA_REVIEW in DEFAULT_ROLE_PERMISSIONS[role]
    assert PermissionSlug.QA_REVIEW not in DEFAULT_ROLE_PERMISSIONS[RoleSlug.KB_READER]


def test_qa_review_audit_actions():
    assert AuditAction.QA_REVIEW_RESOLVE.value == "qa.review_resolve"
    assert AuditAction.QA_REVIEW_DISMISS.value == "qa.review_dismiss"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm exec nx test luna-corpus -- tests/quality/test_review_config.py -v`
Expected: FAIL —— `AttributeError`（`quality_review_score_threshold` / `QA_REVIEW` 不存在）

- [ ] **Step 3: 新增配置项**

在 `apps/luna-corpus/app/core/config.py` 第 219 行 `quality_eval_sample_rate` 的 Field 定义（`)` 结束）之后插入：

```python
    quality_review_score_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="低于该阈值的 LLM 评分（faithfulness/relevance）将该问答纳入待复审队列",
    )
```

- [ ] **Step 4: 新增权限**

在 `apps/luna-corpus/app/auth/permissions.py` 第 16 行 `QA_FEEDBACK = "qa:feedback"` 之后插入：

```python
    QA_REVIEW = "qa:review"
```

在 `RoleSlug.WORKSPACE_ADMIN` 的权限元组内（第 38 行 `PermissionSlug.QA_FEEDBACK,` 之后）插入：

```python
        PermissionSlug.QA_REVIEW,
```

在 `RoleSlug.KB_EDITOR` 的权限元组内（第 50 行 `PermissionSlug.QA_FEEDBACK,` 之后）插入：

```python
        PermissionSlug.QA_REVIEW,
```

（`KB_READER` 块不加。）

- [ ] **Step 5: 新增审计动作**

在 `apps/luna-corpus/app/security/audit.py` 第 22 行 `QA_FEEDBACK = "qa.feedback"` 之后插入：

```python
    QA_REVIEW_RESOLVE = "qa.review_resolve"
    QA_REVIEW_DISMISS = "qa.review_dismiss"
```

- [ ] **Step 6: 运行测试确认通过**

Run: `npm exec nx test luna-corpus -- tests/quality/test_review_config.py -v`
Expected: PASS（3 passed）

- [ ] **Step 7: 提交**

```bash
git add apps/luna-corpus/app/core/config.py \
  apps/luna-corpus/app/auth/permissions.py \
  apps/luna-corpus/app/security/audit.py \
  apps/luna-corpus/tests/quality/test_review_config.py
git commit -m "feat(quality): add review threshold config, QA_REVIEW permission and audit actions"
```

---

### Task 3: 复审服务层 `app/quality/review.py`

**Files:**
- Create: `apps/luna-corpus/app/quality/review.py`
- Test: `apps/luna-corpus/tests/quality/test_review_service.py`

**Interfaces:**
- Consumes: `QAInteraction`、`QAFeedback`、`QAEvaluation`、`QAReview`、`FeedbackRating`、`EvaluationStatus`、`ReviewStatus`、`ReviewRootCause`（models.py）；`get_settings`（config）
- Produces（供 Task 4 路由调用）：
  - `list_reviews(db, kb_id, *, status_filter="queue", limit=50, offset=0) -> list[dict]`
    - `status_filter="queue"`（默认）：仅返回满足入队规则且无终态 review 的项；`"resolved"`/`"dismissed"`：返回该终态的 review 项。每个 dict：`{"interaction_id", "question", "answer", "retrieval_mode", "created_at", "signals": {"thumbs_down": bool, "low_score": bool}, "review_status": str | None}`
  - `get_review_detail(db, kb_id, interaction_id) -> dict | None`
    - 返回 `{"interaction": {...全字段...}, "feedback": [...], "evaluation": {...} | None, "review": {...} | None}`；KB 不匹配返回 `None`
  - `resolve_review(db, kb_id, interaction_id, *, root_cause, note, user_id) -> QAReview | None`
  - `dismiss_review(db, kb_id, interaction_id, *, note, user_id) -> QAReview | None`
    - upsert：已有 review 则更新、否则新建；KB 不匹配返回 `None`（调用方 commit）

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/quality/test_review_service.py`：

```python
"""Unit tests for the review derivation and upsert service."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    EvaluationStatus,
    FeedbackRating,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
    QAReview,
    ReviewRootCause,
    ReviewStatus,
)
from app.quality.review import (
    dismiss_review,
    get_review_detail,
    list_reviews,
    resolve_review,
)

KB = "kb-1"


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _interaction(session, kb_id=KB):
    i = QAInteraction(
        knowledge_base_id=kb_id, question="Q", answer="A", sources=[]
    )
    session.add(i)
    session.commit()
    return i


def _add_feedback(session, iid, rating):
    session.add(QAFeedback(interaction_id=iid, rating=rating))
    session.commit()


def _add_eval(session, iid, faith, rel, status=EvaluationStatus.COMPLETED):
    session.add(
        QAEvaluation(
            interaction_id=iid,
            faithfulness=faith,
            answer_relevance=rel,
            status=status,
        )
    )
    session.commit()


def test_thumbs_down_enters_queue():
    session = _session()
    i = _interaction(session)
    _add_feedback(session, i.id, FeedbackRating.DOWN)
    rows = list_reviews(session, KB)
    assert len(rows) == 1
    assert rows[0]["interaction_id"] == i.id
    assert rows[0]["signals"]["thumbs_down"] is True
    assert rows[0]["signals"]["low_score"] is False


def test_low_score_enters_queue():
    session = _session()
    i = _interaction(session)
    _add_eval(session, i.id, faith=0.5, rel=0.9)
    rows = list_reviews(session, KB)
    assert len(rows) == 1
    assert rows[0]["signals"]["low_score"] is True


def test_threshold_is_strict_less_than():
    session = _session()
    i = _interaction(session)
    _add_eval(session, i.id, faith=0.6, rel=0.6)  # == 0.6, not < 0.6
    assert list_reviews(session, KB) == []


def test_thumbs_up_and_good_score_not_in_queue():
    session = _session()
    i = _interaction(session)
    _add_feedback(session, i.id, FeedbackRating.UP)
    _add_eval(session, i.id, faith=0.9, rel=0.9)
    assert list_reviews(session, KB) == []


def test_pending_eval_does_not_trigger():
    session = _session()
    i = _interaction(session)
    _add_eval(session, i.id, faith=0.1, rel=0.1, status=EvaluationStatus.PENDING)
    assert list_reviews(session, KB) == []


def test_resolved_review_leaves_queue():
    session = _session()
    i = _interaction(session)
    _add_feedback(session, i.id, FeedbackRating.DOWN)
    resolve_review(
        session, KB, i.id,
        root_cause=ReviewRootCause.KNOWLEDGE_GAP, note="fixed", user_id="u1",
    )
    session.commit()
    assert list_reviews(session, KB) == []
    resolved = list_reviews(session, KB, status_filter="resolved")
    assert len(resolved) == 1
    assert resolved[0]["review_status"] == "resolved"


def test_resolve_is_upsert_not_duplicate():
    session = _session()
    i = _interaction(session)
    _add_feedback(session, i.id, FeedbackRating.DOWN)
    resolve_review(
        session, KB, i.id,
        root_cause=ReviewRootCause.OTHER, note="first", user_id="u1",
    )
    session.commit()
    dismiss_review(session, KB, i.id, note="changed my mind", user_id="u2")
    session.commit()
    reviews = session.query(QAReview).filter(QAReview.interaction_id == i.id).all()
    assert len(reviews) == 1
    assert reviews[0].status == ReviewStatus.DISMISSED
    assert reviews[0].resolution_note == "changed my mind"


def test_cross_kb_returns_none():
    session = _session()
    i = _interaction(session, kb_id="other-kb")
    assert get_review_detail(session, KB, i.id) is None
    assert resolve_review(
        session, KB, i.id,
        root_cause=ReviewRootCause.OTHER, note="x", user_id="u1",
    ) is None


def test_detail_returns_signals_and_review():
    session = _session()
    i = _interaction(session)
    _add_feedback(session, i.id, FeedbackRating.DOWN)
    _add_eval(session, i.id, faith=0.4, rel=0.5)
    detail = get_review_detail(session, KB, i.id)
    assert detail["interaction"]["id"] == i.id
    assert len(detail["feedback"]) == 1
    assert detail["evaluation"]["faithfulness"] == 0.4
    assert detail["review"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm exec nx test luna-corpus -- tests/quality/test_review_service.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.quality.review'`

- [ ] **Step 3: 实现服务模块**

创建 `apps/luna-corpus/app/quality/review.py`：

```python
"""Review derivation and triage service for the feedback loop.

The review queue is DERIVED at query time (no materialized queue table):
an interaction is queued when it has a thumbs-down feedback OR a completed
low-score evaluation, and has no terminal (resolved/dismissed) review.
Triage state lives in the qa_reviews table, upserted one row per interaction.
"""
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    EvaluationStatus,
    FeedbackRating,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
    QAReview,
    ReviewRootCause,
    ReviewStatus,
)

settings = get_settings()

_TERMINAL = (ReviewStatus.RESOLVED, ReviewStatus.DISMISSED)


def _has_thumbs_down(db: Session, interaction_id: str) -> bool:
    return (
        db.query(QAFeedback)
        .filter(
            QAFeedback.interaction_id == interaction_id,
            QAFeedback.rating == FeedbackRating.DOWN,
        )
        .first()
        is not None
    )


def _has_low_score(db: Session, interaction_id: str) -> bool:
    threshold = settings.quality_review_score_threshold
    return (
        db.query(QAEvaluation)
        .filter(
            QAEvaluation.interaction_id == interaction_id,
            QAEvaluation.status == EvaluationStatus.COMPLETED,
            (QAEvaluation.faithfulness < threshold)
            | (QAEvaluation.answer_relevance < threshold),
        )
        .first()
        is not None
    )


def _get_scoped_interaction(
    db: Session, kb_id: str, interaction_id: str
) -> QAInteraction | None:
    return (
        db.query(QAInteraction)
        .filter(
            QAInteraction.id == interaction_id,
            QAInteraction.knowledge_base_id == kb_id,
        )
        .first()
    )


def _get_review(db: Session, interaction_id: str) -> QAReview | None:
    return (
        db.query(QAReview)
        .filter(QAReview.interaction_id == interaction_id)
        .first()
    )


def list_reviews(
    db: Session,
    kb_id: str,
    *,
    status_filter: str = "queue",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Derive the review list for a KB.

    status_filter="queue": interactions triggering a signal with no terminal
    review. "resolved"/"dismissed": interactions whose review is in that state.
    """
    interactions = (
        db.query(QAInteraction)
        .filter(QAInteraction.knowledge_base_id == kb_id)
        .order_by(QAInteraction.created_at.desc())
        .all()
    )
    rows: list[dict] = []
    for it in interactions:
        review = _get_review(db, it.id)
        thumbs_down = _has_thumbs_down(db, it.id)
        low_score = _has_low_score(db, it.id)
        triggered = thumbs_down or low_score

        if status_filter == "queue":
            in_terminal = review is not None and review.status in _TERMINAL
            if not triggered or in_terminal:
                continue
        else:  # "resolved" / "dismissed"
            if review is None or review.status.value != status_filter:
                continue

        rows.append(
            {
                "interaction_id": it.id,
                "question": it.question,
                "answer": it.answer,
                "retrieval_mode": it.retrieval_mode,
                "created_at": it.created_at.isoformat() if it.created_at else None,
                "signals": {"thumbs_down": thumbs_down, "low_score": low_score},
                "review_status": review.status.value if review else None,
            }
        )
    return rows[offset : offset + limit]


def _feedback_dicts(db: Session, interaction_id: str) -> list[dict]:
    items = (
        db.query(QAFeedback)
        .filter(QAFeedback.interaction_id == interaction_id)
        .all()
    )
    return [
        {
            "id": f.id,
            "rating": f.rating.value,
            "error_type": f.error_type.value if f.error_type else None,
            "comment": f.comment,
        }
        for f in items
    ]


def _evaluation_dict(db: Session, interaction_id: str) -> dict | None:
    ev = (
        db.query(QAEvaluation)
        .filter(QAEvaluation.interaction_id == interaction_id)
        .order_by(QAEvaluation.created_at.desc())
        .first()
    )
    if ev is None:
        return None
    return {
        "faithfulness": ev.faithfulness,
        "answer_relevance": ev.answer_relevance,
        "citation_accuracy": ev.citation_accuracy,
        "status": ev.status.value,
        "rationale": ev.rationale,
    }


def _review_dict(review: QAReview | None) -> dict | None:
    if review is None:
        return None
    return {
        "id": review.id,
        "status": review.status.value,
        "root_cause": review.root_cause.value if review.root_cause else None,
        "resolution_note": review.resolution_note,
        "resolved_by_user_id": review.resolved_by_user_id,
    }


def get_review_detail(
    db: Session, kb_id: str, interaction_id: str
) -> dict | None:
    """Full triage detail for one interaction; None if not in this KB."""
    it = _get_scoped_interaction(db, kb_id, interaction_id)
    if it is None:
        return None
    return {
        "interaction": {
            "id": it.id,
            "question": it.question,
            "answer": it.answer,
            "sources": it.sources,
            "retrieval_mode": it.retrieval_mode,
            "created_at": it.created_at.isoformat() if it.created_at else None,
        },
        "feedback": _feedback_dicts(db, interaction_id),
        "evaluation": _evaluation_dict(db, interaction_id),
        "review": _review_dict(_get_review(db, interaction_id)),
    }


def _upsert(
    db: Session,
    kb_id: str,
    interaction_id: str,
    *,
    status: ReviewStatus,
    root_cause: ReviewRootCause | None,
    note: str | None,
    user_id: str | None,
) -> QAReview | None:
    if _get_scoped_interaction(db, kb_id, interaction_id) is None:
        return None
    review = _get_review(db, interaction_id)
    if review is None:
        review = QAReview(interaction_id=interaction_id)
        db.add(review)
    review.status = status
    review.root_cause = root_cause
    review.resolution_note = note
    review.resolved_by_user_id = user_id
    db.flush()
    return review


def resolve_review(
    db: Session,
    kb_id: str,
    interaction_id: str,
    *,
    root_cause: ReviewRootCause,
    note: str | None,
    user_id: str | None,
) -> QAReview | None:
    """Mark an interaction resolved with a root cause (upsert)."""
    return _upsert(
        db, kb_id, interaction_id,
        status=ReviewStatus.RESOLVED,
        root_cause=root_cause, note=note, user_id=user_id,
    )


def dismiss_review(
    db: Session,
    kb_id: str,
    interaction_id: str,
    *,
    note: str | None,
    user_id: str | None,
) -> QAReview | None:
    """Dismiss an interaction as not actionable (upsert)."""
    return _upsert(
        db, kb_id, interaction_id,
        status=ReviewStatus.DISMISSED,
        root_cause=None, note=note, user_id=user_id,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npm exec nx test luna-corpus -- tests/quality/test_review_service.py -v`
Expected: PASS（9 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/quality/review.py \
  apps/luna-corpus/tests/quality/test_review_service.py
git commit -m "feat(quality): add review derivation and triage service"
```

---

### Task 4: REST 端点与集成测试

**Files:**
- Modify: `apps/luna-corpus/app/api/routes.py`（Pydantic 模型加在第 136 行 `QualitySummaryResponse` 之后；端点加在第 559 行 `quality_summary` 之后、第 562 行 `# Document Management` 之前）
- Test: `apps/luna-corpus/tests/api/test_review_api.py`

**Interfaces:**
- Consumes: `list_reviews`、`get_review_detail`、`resolve_review`、`dismiss_review`（Task 3）；`PermissionSlug.QA_REVIEW`、`AuditAction.QA_REVIEW_RESOLVE/DISMISS`（Task 2）；`ReviewRootCause`（Task 1）；`require_permission`、`AuditService`、`AuditResult`、`get_db`（已有）
- Produces: 端点 `GET /api/v1/qa/reviews`、`GET /api/v1/qa/reviews/{interaction_id}`、`POST /api/v1/qa/reviews/{interaction_id}/resolve`、`POST /api/v1/qa/reviews/{interaction_id}/dismiss`

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/api/test_review_api.py`。复用 `tests/api/test_quality_api.py` 的 fixture 模式（本文件自带一份，便于独立运行）：

```python
"""Integration tests for review-loop endpoints."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.permissions import PermissionSlug
from app.db.database import get_db
from app.db.models import (
    Base,
    EvaluationStatus,
    FeedbackRating,
    KnowledgeBase,
    Permission,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
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


def _user(Session, workspace_id, slugs, email="u@example.com"):
    session = Session()
    try:
        user = User(email=email, display_name="u")
        perms = []
        for slug in slugs:
            p = session.query(Permission).filter(Permission.slug == slug).first()
            if not p:
                p = Permission(name=slug, slug=slug, description=slug)
            perms.append(p)
        role = Role(name="r", slug="r-" + email, is_system=True, permissions=perms)
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


def _seed_down_interaction(Session, kb_id):
    session = Session()
    try:
        it = QAInteraction(
            knowledge_base_id=kb_id, question="Q?", answer="A.", sources=[]
        )
        session.add(it)
        session.commit()
        session.add(QAFeedback(interaction_id=it.id, rating=FeedbackRating.DOWN))
        session.add(
            QAEvaluation(
                interaction_id=it.id,
                faithfulness=0.3,
                answer_relevance=0.4,
                status=EvaluationStatus.COMPLETED,
            )
        )
        session.commit()
        return it.id
    finally:
        session.close()


def test_reader_forbidden(client, app_db):
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_FEEDBACK])
    resp = client.get("/api/v1/qa/reviews", headers=_headers(context, uid))
    assert resp.status_code == 403


def test_queue_lists_triggered_interaction(client, app_db):
    _, Session, context = app_db
    iid = _seed_down_interaction(Session, context["kb_one_id"])
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_REVIEW])
    resp = client.get("/api/v1/qa/reviews", headers=_headers(context, uid))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["reviews"][0]["interaction_id"] == iid
    assert body["reviews"][0]["signals"]["thumbs_down"] is True


def test_detail_and_cross_kb_404(client, app_db):
    _, Session, context = app_db
    iid = _seed_down_interaction(Session, context["kb_one_id"])
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_REVIEW])
    ok = client.get(
        f"/api/v1/qa/reviews/{iid}", headers=_headers(context, uid)
    )
    assert ok.status_code == 200
    assert ok.json()["interaction"]["id"] == iid

    cross = client.get(
        f"/api/v1/qa/reviews/{iid}",
        headers=_headers(context, uid, kb_key="kb_two_id"),
    )
    assert cross.status_code == 404


def test_resolve_then_leaves_queue(client, app_db):
    _, Session, context = app_db
    iid = _seed_down_interaction(Session, context["kb_one_id"])
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_REVIEW])
    r = client.post(
        f"/api/v1/qa/reviews/{iid}/resolve",
        headers=_headers(context, uid),
        json={"root_cause": "knowledge_gap", "resolution_note": "补充文档"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"

    queue = client.get("/api/v1/qa/reviews", headers=_headers(context, uid))
    assert queue.json()["total"] == 0

    resolved = client.get(
        "/api/v1/qa/reviews?status=resolved", headers=_headers(context, uid)
    )
    assert resolved.json()["total"] == 1


def test_dismiss_leaves_queue(client, app_db):
    _, Session, context = app_db
    iid = _seed_down_interaction(Session, context["kb_one_id"])
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_REVIEW])
    r = client.post(
        f"/api/v1/qa/reviews/{iid}/dismiss",
        headers=_headers(context, uid),
        json={"resolution_note": "误报"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "dismissed"
    queue = client.get("/api/v1/qa/reviews", headers=_headers(context, uid))
    assert queue.json()["total"] == 0


def test_resolve_cross_kb_404(client, app_db):
    _, Session, context = app_db
    iid = _seed_down_interaction(Session, context["kb_one_id"])
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_REVIEW])
    r = client.post(
        f"/api/v1/qa/reviews/{iid}/resolve",
        headers=_headers(context, uid, kb_key="kb_two_id"),
        json={"root_cause": "other", "resolution_note": "x"},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm exec nx test luna-corpus -- tests/api/test_review_api.py -v`
Expected: FAIL —— 端点未定义（404，断言失败）

- [ ] **Step 3: 新增 Pydantic 模型**

在 `apps/luna-corpus/app/api/routes.py` 第 136 行 `QualitySummaryResponse` 类结束之后插入：

```python
class ReviewSignals(BaseModel):
    """Which signal(s) queued this interaction for review."""

    thumbs_down: bool
    low_score: bool


class ReviewListItem(BaseModel):
    """One row in the review queue."""

    interaction_id: str
    question: str
    answer: str
    retrieval_mode: str | None = None
    created_at: str | None = None
    signals: ReviewSignals
    review_status: str | None = None


class ReviewListResponse(BaseModel):
    """Paginated review queue."""

    reviews: list[ReviewListItem]
    total: int


class ReviewResolveRequest(BaseModel):
    """Resolve a review with a root cause."""

    root_cause: ReviewRootCause
    resolution_note: str | None = Field(default=None, max_length=2000)


class ReviewDismissRequest(BaseModel):
    """Dismiss a review as not actionable."""

    resolution_note: str | None = Field(default=None, max_length=2000)


class ReviewActionResponse(BaseModel):
    """Result of a resolve/dismiss action."""

    interaction_id: str
    status: str
    root_cause: str | None = None
```

- [ ] **Step 4: 新增导入**

在 `apps/luna-corpus/app/api/routes.py` 顶部导入区，把 `ReviewRootCause` 加入从 `app.db.models` 的导入（与现有 `FeedbackRating` 等同组）；在第 51 行 `from app.quality.feedback import ...` 之后新增：

```python
from app.quality.review import (
    dismiss_review,
    get_review_detail,
    list_reviews,
    resolve_review,
)
```

- [ ] **Step 5: 新增端点**

在 `apps/luna-corpus/app/api/routes.py` 第 559 行 `quality_summary` 函数结束之后、第 562 行 `# Document Management` 之前插入：

```python
@router.get("/qa/reviews", response_model=ReviewListResponse)
async def list_review_queue(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_REVIEW)),
    ],
    status: str = Query(default="queue", pattern="^(queue|resolved|dismissed)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ReviewListResponse:
    """Derived review queue for the current knowledge base."""
    rows = list_reviews(
        db,
        context.knowledge_base.id,
        status_filter=status,
        limit=limit,
        offset=offset,
    )
    return ReviewListResponse(
        reviews=[ReviewListItem(**r) for r in rows], total=len(rows)
    )


@router.get("/qa/reviews/{interaction_id}")
async def review_detail(
    interaction_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_REVIEW)),
    ],
) -> dict:
    """Full triage detail for one interaction."""
    detail = get_review_detail(db, context.knowledge_base.id, interaction_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return detail


@router.post(
    "/qa/reviews/{interaction_id}/resolve",
    response_model=ReviewActionResponse,
)
async def resolve_review_endpoint(
    interaction_id: str,
    review_req: ReviewResolveRequest,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_REVIEW)),
    ],
) -> ReviewActionResponse:
    """Resolve a queued interaction with a root cause."""
    review = resolve_review(
        db,
        context.knowledge_base.id,
        interaction_id,
        root_cause=review_req.root_cause,
        note=review_req.resolution_note,
        user_id=context.user.id,
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Interaction not found")
    AuditService().record(
        db,
        action=AuditAction.QA_REVIEW_RESOLVE,
        resource_type="qa_interaction",
        resource_id=interaction_id,
        result=AuditResult.SUCCESS,
        context=context,
    )
    db.commit()
    return ReviewActionResponse(
        interaction_id=interaction_id,
        status=review.status.value,
        root_cause=review.root_cause.value if review.root_cause else None,
    )


@router.post(
    "/qa/reviews/{interaction_id}/dismiss",
    response_model=ReviewActionResponse,
)
async def dismiss_review_endpoint(
    interaction_id: str,
    review_req: ReviewDismissRequest,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_REVIEW)),
    ],
) -> ReviewActionResponse:
    """Dismiss a queued interaction as not actionable."""
    review = dismiss_review(
        db,
        context.knowledge_base.id,
        interaction_id,
        note=review_req.resolution_note,
        user_id=context.user.id,
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Interaction not found")
    AuditService().record(
        db,
        action=AuditAction.QA_REVIEW_DISMISS,
        resource_type="qa_interaction",
        resource_id=interaction_id,
        result=AuditResult.SUCCESS,
        context=context,
    )
    db.commit()
    return ReviewActionResponse(
        interaction_id=interaction_id,
        status=review.status.value,
        root_cause=None,
    )
```

- [ ] **Step 6: 运行测试确认通过**

Run: `npm exec nx test luna-corpus -- tests/api/test_review_api.py -v`
Expected: PASS（6 passed）

- [ ] **Step 7: 运行全量质量测试回归**

Run: `npm exec nx test luna-corpus -- tests/quality/ tests/api/test_review_api.py tests/api/test_quality_api.py -v`
Expected: 全部 PASS（确认未破坏既有质量/反馈测试）

- [ ] **Step 8: 提交**

```bash
git add apps/luna-corpus/app/api/routes.py \
  apps/luna-corpus/tests/api/test_review_api.py
git commit -m "feat(quality): add review queue REST endpoints with audit"
```

---

## 自查

**1. Spec 覆盖：**
- 数据模型（qa_reviews + 两枚举）→ Task 1 ✅
- 入队规则（双信号 / 派生 / 严格 <0.6 / 已处置移出）→ Task 3（`list_reviews` + 测试）✅
- 配置阈值 0.6 → Task 2 ✅
- 权限 QA_REVIEW（admin/editor 有、reader 无）→ Task 2 ✅
- 审计动作 QA_REVIEW_RESOLVE/DISMISS → Task 2 + Task 4 ✅
- 4 个端点（队列/详情/resolve/dismiss）→ Task 4 ✅
- KB 作用域 404 → Task 3（服务返回 None）+ Task 4（转 404）✅
- upsert 幂等 → Task 3（`_upsert` + 测试）✅
- 复审端点正常报错（不吞异常）→ Task 4（`raise HTTPException`）✅
- 测试三文件 + 配置/权限种子 → Task 1/2/3/4 全覆盖 ✅

**2. 占位符扫描：** 无 TBD/TODO；每个代码步骤均含完整代码。✅

**3. 类型一致性：**
- 服务签名 `resolve_review(db, kb_id, interaction_id, *, root_cause, note, user_id)` 在 Task 3 定义、Task 4 调用一致 ✅
- `list_reviews(..., status_filter, limit, offset)` 定义与路由调用一致 ✅
- dict 键（`interaction_id`/`question`/`answer`/`retrieval_mode`/`created_at`/`signals`/`review_status`）在服务返回、`ReviewListItem` 字段、API 测试断言三处一致 ✅
- 枚举值字符串（`"knowledge_gap"` 等）在 models、migration、API 测试 json 一致 ✅
- 审计动作值 `"qa.review_resolve"`/`"qa.review_dismiss"` 在 audit.py 与 config 测试一致 ✅
