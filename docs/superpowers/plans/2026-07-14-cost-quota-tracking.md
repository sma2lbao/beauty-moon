# 成本与配额统计（统计 + 硬限流）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为多租户 RAG 系统实现 LLM 问答用量的计量、成本折算与日度配额硬限流。

**Architecture:** 路由层准入守卫（`enforce_quota`，fail-open）+ 独立用量明细表（`usage_records`）+ 日度累加计数器（`quota_counters`，O(1) 准入读取）。LLM 层只返回 usage 数据，租户折算与配额逻辑集中在新的 `app/cost/` 模块。用量记录复刻 `app/quality/recorder.py` 的旁路容错范式。

**Tech Stack:** FastAPI + SQLAlchemy 2.0（Mapped/mapped_column）+ Alembic + LangChain（`usage_metadata`）+ Prometheus client + pytest。

## Global Constraints

- 应用根目录：`apps/luna-corpus`；所有命令在该目录下执行。包管理与运行统一用 `uv` 环境（`.venv` 已存在），测试命令：`.venv/bin/pytest`。
- 数据库：生产 MySQL、测试 SQLite 内存库。**禁止使用方言特定 upsert**（`ON CONFLICT` / `ON DUPLICATE KEY`）——计数器累加用可移植的「UPDATE→0行则INSERT→IntegrityError重试UPDATE」模式。
- SQLAlchemy 模型统一用 `Mapped` + `mapped_column`；主键为 `CHAR(36)` uuid，`default=lambda: str(uuid.uuid4())`；金额列用 `Numeric(18, 6)`。
- 时间口径：配额日界统一用 **UTC**（`datetime.now(timezone.utc).date()`）。
- 旁路容错：任何用量记录失败必须 log warning + rollback + swallow，**绝不影响 QA 响应**。
- 配额准入 **fail-open**：读取配额数据异常时放行请求，仅「成功读到且确认超限」才拒绝。
- 中文注释/文档；错误信息（HTTPException detail）用英文，与现有代码一致。
- 迁移文件命名遵循 `20260714_0013_cost_quota.py`，`down_revision = "20260713_0012"`。

---

## 文件结构

**新建：**
- `app/cost/__init__.py` —— 模块标识。
- `app/cost/pricing.py` —— 价格解析与成本折算。
- `app/cost/recorder.py` —— 旁路记录用量明细并累加计数器。
- `app/cost/enforcement.py` —— 配额准入依赖 `enforce_quota` 与 `QuotaExceeded`。
- `app/cost/service.py` —— 配额配置 upsert、用量查询、价格 upsert 业务逻辑。
- `app/api/cost_routes.py` —— 管理 API 路由。
- 迁移 `alembic/versions/20260714_0013_cost_quota.py`。
- 测试：`tests/cost/__init__.py`、`tests/cost/test_pricing.py`、`tests/cost/test_recorder.py`、`tests/cost/test_enforcement.py`、`tests/cost/test_cost_config.py`、`tests/cost/test_cost_metrics.py`、`tests/cost/test_llm_usage.py`、`tests/api/test_cost_api.py`。

**修改：**
- `app/auth/permissions.py` —— 新增 `COST_MANAGE` / `COST_READ` 权限与角色授权。
- `app/db/models.py` —— 新增 4 个模型。
- `app/observability/metrics.py` —— 新增 3 个 Counter。
- `app/core/config.py` —— 新增 `cost_enforcement_enabled` 开关。
- `app/services/llm.py` —— 新增 `TokenUsage`、`generate_response_with_usage`、流式 usage 累加器。
- `app/graph/rag_graph.py` —— 透传 usage。
- `app/api/routes.py` —— `/qa/query`、`/qa/stream` 挂 `enforce_quota` + 调 `record_usage`。
- `app/main.py` —— 注册 `cost_router`。

---

## Task 1: RBAC 权限与配置开关

**Files:**
- Modify: `app/auth/permissions.py`
- Modify: `app/core/config.py`
- Test: `tests/cost/test_cost_config.py`, `tests/cost/__init__.py`

**Interfaces:**
- Produces: `PermissionSlug.COST_MANAGE = "cost:manage"`、`PermissionSlug.COST_READ = "cost:read"`；`Settings.cost_enforcement_enabled: bool`（default True）。

- [ ] **Step 1: 创建测试包并写失败测试**

创建 `tests/cost/__init__.py`（空文件）。

创建 `tests/cost/test_cost_config.py`：

```python
"""成本模块 RBAC 权限与配置开关。"""
from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS, PermissionSlug, RoleSlug
from app.core.config import get_settings


def test_cost_permission_slugs_defined():
    assert PermissionSlug.COST_MANAGE == "cost:manage"
    assert PermissionSlug.COST_READ == "cost:read"


def test_workspace_admin_has_both_cost_permissions():
    perms = DEFAULT_ROLE_PERMISSIONS[RoleSlug.WORKSPACE_ADMIN]
    assert PermissionSlug.COST_MANAGE in perms
    assert PermissionSlug.COST_READ in perms


def test_kb_editor_has_read_only():
    perms = DEFAULT_ROLE_PERMISSIONS[RoleSlug.KB_EDITOR]
    assert PermissionSlug.COST_READ in perms
    assert PermissionSlug.COST_MANAGE not in perms


def test_kb_reader_has_no_cost_permissions():
    perms = DEFAULT_ROLE_PERMISSIONS[RoleSlug.KB_READER]
    assert PermissionSlug.COST_READ not in perms
    assert PermissionSlug.COST_MANAGE not in perms


def test_cost_enforcement_enabled_defaults_true():
    assert get_settings().cost_enforcement_enabled is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/cost/test_cost_config.py -v`
Expected: FAIL（`AttributeError: COST_MANAGE` / `cost_enforcement_enabled`）

- [ ] **Step 3: 在 `app/auth/permissions.py` 添加权限**

在 `PermissionSlug` 类末尾（`PROMPT_MANAGE` 行后）添加：

```python
    COST_MANAGE = "cost:manage"
    COST_READ = "cost:read"
```

在 `DEFAULT_ROLE_PERMISSIONS` 中，`WORKSPACE_ADMIN` 元组末尾（`PROMPT_MANAGE` 后）添加：

```python
        PermissionSlug.COST_MANAGE,
        PermissionSlug.COST_READ,
```

在 `KB_EDITOR` 元组末尾（`PROMPT_MANAGE` 后）添加：

```python
        PermissionSlug.COST_READ,
```

`KB_READER` 不改。

- [ ] **Step 4: 在 `app/core/config.py` 添加开关**

在 `Settings` 类中 `quality_eval_sample_rate` 字段附近添加：

```python
    cost_enforcement_enabled: bool = Field(
        default=True,
        description="配额硬限流总开关；关闭时 enforce_quota 直接放行",
    )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/bin/pytest tests/cost/test_cost_config.py -v`
Expected: PASS（5 passed）

- [ ] **Step 6: 提交**

```bash
git add app/auth/permissions.py app/core/config.py tests/cost/__init__.py tests/cost/test_cost_config.py
git commit -m "feat(cost): add cost RBAC permissions and enforcement toggle"
```

---

## Task 2: 数据模型与迁移（4 张表）

**Files:**
- Modify: `app/db/models.py`
- Create: `alembic/versions/20260714_0013_cost_quota.py`
- Test: `tests/cost/test_models.py`

**Interfaces:**
- Produces: 模型 `ModelPrice`（表 `model_prices`）、`UsageRecord`（表 `usage_records`）、`QuotaLimit`（表 `quota_limits`）、`QuotaCounter`（表 `quota_counters`），均在 `app.db.models` 导出。字段见 §4。

- [ ] **Step 1: 写失败测试**

创建 `tests/cost/test_models.py`：

```python
"""成本与配额数据模型。"""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    ModelPrice,
    QuotaCounter,
    QuotaLimit,
    UsageRecord,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_model_price_persists():
    s = _session()
    p = ModelPrice(
        provider="ark",
        model="deepseek-v4-pro-260425",
        input_price_per_1k=Decimal("0.002000"),
        output_price_per_1k=Decimal("0.008000"),
        currency="CNY",
        effective_from=datetime.now(timezone.utc),
    )
    s.add(p)
    s.commit()
    assert s.query(ModelPrice).count() == 1


def test_usage_record_persists():
    s = _session()
    r = UsageRecord(
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="kb1",
        interaction_id="i1",
        provider="ark",
        model="m",
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        cost_amount=Decimal("0.001000"),
        currency="CNY",
    )
    s.add(r)
    s.commit()
    assert s.query(UsageRecord).one().total_tokens == 30


def test_quota_limit_unique_scope():
    s = _session()
    s.add(QuotaLimit(scope_type="tenant", scope_id="t1", daily_token_limit=1000, currency="CNY"))
    s.commit()
    assert s.query(QuotaLimit).one().daily_token_limit == 1000


def test_quota_counter_persists():
    s = _session()
    c = QuotaCounter(
        scope_type="workspace",
        scope_id="w1",
        usage_date=date(2026, 7, 14),
        token_used=100,
        cost_used=Decimal("0.050000"),
    )
    s.add(c)
    s.commit()
    assert s.query(QuotaCounter).one().token_used == 100
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/cost/test_models.py -v`
Expected: FAIL（`ImportError: cannot import name 'ModelPrice'`）

- [ ] **Step 3: 在 `app/db/models.py` 添加模型**

先确认 `from datetime import date` 已导入（当前仅 `datetime`）——在文件顶部 `from datetime import datetime` 改为 `from datetime import date, datetime`。在 `sqlalchemy` 导入块中补充 `BigInteger`、`Date`、`Numeric`（追加到已有导入列表）。

在文件末尾追加：

```python
class ModelPrice(Base):
    """provider/model 的单价，按 effective_from 取生效价。"""

    __tablename__ = "model_prices"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_price_per_1k: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    output_price_per_1k: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    effective_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_model_prices_lookup", "provider", "model", "effective_from"),
    )


class UsageRecord(Base):
    """每次问答生成的 token/成本明细。"""

    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(CHAR(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(CHAR(36), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(CHAR(36), nullable=False, index=True)
    interaction_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )


class QuotaLimit(Base):
    """租户/工作区的日度配额阈值。"""

    __tablename__ = "quota_limits"
    __table_args__ = (UniqueConstraint("scope_type", "scope_id"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scope_type: Mapped[str] = mapped_column(String(10), nullable=False)
    scope_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    daily_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    daily_cost_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class QuotaCounter(Base):
    """按 (scope, 日期) 分行的日度累加计数器。"""

    __tablename__ = "quota_counters"
    __table_args__ = (
        UniqueConstraint("scope_type", "scope_id", "usage_date"),
    )

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scope_type: Mapped[str] = mapped_column(String(10), nullable=False)
    scope_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    token_used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_used: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

同时在文件顶部 import 区加入 `from decimal import Decimal`，并在 sqlalchemy 导入块加入 `Index`。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/cost/test_models.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 编写 Alembic 迁移**

创建 `alembic/versions/20260714_0013_cost_quota.py`：

```python
"""cost & quota: model_prices, usage_records, quota_limits, quota_counters

Revision ID: 20260714_0013
Revises: 20260713_0012
Create Date: 2026-07-14

"""
import sqlalchemy as sa
from alembic import op

revision = "20260714_0013"
down_revision = "20260713_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_prices",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_price_per_1k", sa.Numeric(18, 6), nullable=False),
        sa.Column("output_price_per_1k", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_model_prices_lookup", "model_prices", ["provider", "model", "effective_from"]
    )

    op.create_table(
        "usage_records",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("workspace_id", sa.CHAR(36), nullable=False),
        sa.Column("knowledge_base_id", sa.CHAR(36), nullable=False),
        sa.Column("interaction_id", sa.CHAR(36), nullable=True),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_usage_records_tenant_id", "usage_records", ["tenant_id"])
    op.create_index("ix_usage_records_workspace_id", "usage_records", ["workspace_id"])
    op.create_index(
        "ix_usage_records_knowledge_base_id", "usage_records", ["knowledge_base_id"]
    )
    op.create_index("ix_usage_records_created_at", "usage_records", ["created_at"])

    op.create_table(
        "quota_limits",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("scope_type", sa.String(length=10), nullable=False),
        sa.Column("scope_id", sa.CHAR(36), nullable=False),
        sa.Column("daily_token_limit", sa.BigInteger(), nullable=True),
        sa.Column("daily_cost_limit", sa.Numeric(18, 6), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("scope_type", "scope_id", name="uq_quota_limits_scope"),
    )

    op.create_table(
        "quota_counters",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("scope_type", sa.String(length=10), nullable=False),
        sa.Column("scope_id", sa.CHAR(36), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("token_used", sa.BigInteger(), nullable=False),
        sa.Column("cost_used", sa.Numeric(18, 6), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "scope_type", "scope_id", "usage_date", name="uq_quota_counters_scope_date"
        ),
    )


def downgrade() -> None:
    op.drop_table("quota_counters")
    op.drop_table("quota_limits")
    op.drop_index("ix_usage_records_created_at", table_name="usage_records")
    op.drop_index("ix_usage_records_knowledge_base_id", table_name="usage_records")
    op.drop_index("ix_usage_records_workspace_id", table_name="usage_records")
    op.drop_index("ix_usage_records_tenant_id", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_index("ix_model_prices_lookup", table_name="model_prices")
    op.drop_table("model_prices")
```

- [ ] **Step 6: 校验迁移可导入（离线检查）**

Run: `.venv/bin/python -c "import importlib.util, pathlib; spec = importlib.util.spec_from_file_location('m', 'alembic/versions/20260714_0013_cost_quota.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(m.revision, m.down_revision)"`
Expected: 输出 `20260714_0013 20260713_0012`

- [ ] **Step 7: 提交**

```bash
git add app/db/models.py alembic/versions/20260714_0013_cost_quota.py tests/cost/test_models.py
git commit -m "feat(cost): add cost/quota models and migration"
```

---

## Task 3: Prometheus 指标

**Files:**
- Modify: `app/observability/metrics.py`
- Test: `tests/cost/test_cost_metrics.py`

**Interfaces:**
- Produces: `LLM_TOKENS_TOTAL`（labels `provider`, `model`, `direction`）、`LLM_COST_TOTAL`（labels `provider`, `model`, `currency`）、`QUOTA_REJECTED_TOTAL`（labels `scope_type`），从 `app.observability.metrics` 导出。

- [ ] **Step 1: 写失败测试**

创建 `tests/cost/test_cost_metrics.py`：

```python
"""成本与配额 Prometheus 指标可用且可自增。"""
from app.observability.metrics import (
    LLM_COST_TOTAL,
    LLM_TOKENS_TOTAL,
    QUOTA_REJECTED_TOTAL,
)


def test_counters_increment():
    LLM_TOKENS_TOTAL.labels(provider="ark", model="m", direction="input").inc(10)
    LLM_COST_TOTAL.labels(provider="ark", model="m", currency="CNY").inc(0.5)
    QUOTA_REJECTED_TOTAL.labels(scope_type="tenant").inc()
    assert LLM_TOKENS_TOTAL.labels(provider="ark", model="m", direction="input")._value.get() > 0
    assert LLM_COST_TOTAL.labels(provider="ark", model="m", currency="CNY")._value.get() > 0
    assert QUOTA_REJECTED_TOTAL.labels(scope_type="tenant")._value.get() > 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/cost/test_cost_metrics.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 在 `app/observability/metrics.py` 添加指标**

在 `QA_EVALUATIONS_TOTAL` 定义之后添加：

```python
LLM_TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed by direction.",
    ["provider", "model", "direction"],
)
LLM_COST_TOTAL = Counter(
    "llm_cost_total",
    "Total LLM cost in currency units.",
    ["provider", "model", "currency"],
)
QUOTA_REJECTED_TOTAL = Counter(
    "quota_rejected_total",
    "Total requests rejected by quota enforcement.",
    ["scope_type"],
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/cost/test_cost_metrics.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/observability/metrics.py tests/cost/test_cost_metrics.py
git commit -m "feat(cost): add token/cost/quota prometheus counters"
```

---

## Task 4: 价格解析与成本折算（`pricing.py`）

**Files:**
- Create: `app/cost/__init__.py`, `app/cost/pricing.py`
- Test: `tests/cost/test_pricing.py`

**Interfaces:**
- Consumes: `ModelPrice`（Task 2）。
- Produces:
  - `resolve_price(db: Session, provider: str, model: str, at: datetime) -> ModelPrice | None`
  - `compute_cost(input_tokens: int, output_tokens: int, price: ModelPrice | None) -> tuple[Decimal, str]` —— 返回 `(cost_amount, currency)`；`price` 为 None 时返回 `(Decimal("0"), "CNY")`。

- [ ] **Step 1: 写失败测试**

创建 `tests/cost/test_pricing.py`：

```python
"""价格解析与成本折算。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cost.pricing import compute_cost, resolve_price
from app.db.models import Base, ModelPrice


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _price(s, eff, inp="0.002", out="0.008"):
    p = ModelPrice(
        provider="ark",
        model="m",
        input_price_per_1k=Decimal(inp),
        output_price_per_1k=Decimal(out),
        currency="CNY",
        effective_from=eff,
    )
    s.add(p)
    s.commit()
    return p


def test_resolve_price_picks_latest_effective():
    s = _session()
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    _price(s, now - timedelta(days=10), inp="0.001")
    _price(s, now - timedelta(days=1), inp="0.002")
    _price(s, now + timedelta(days=1), inp="0.009")  # 未来价，不选
    price = resolve_price(s, "ark", "m", now)
    assert price is not None
    assert price.input_price_per_1k == Decimal("0.002")


def test_resolve_price_none_when_no_match():
    s = _session()
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    assert resolve_price(s, "ark", "missing", now) is None


def test_compute_cost_basic():
    s = _session()
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    p = _price(s, now - timedelta(days=1))
    # 1000 input * 0.002/1k + 2000 output * 0.008/1k = 0.002 + 0.016 = 0.018
    cost, currency = compute_cost(1000, 2000, p)
    assert cost == Decimal("0.018000")
    assert currency == "CNY"


def test_compute_cost_no_price_returns_zero():
    cost, currency = compute_cost(1000, 2000, None)
    assert cost == Decimal("0")
    assert currency == "CNY"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/cost/test_pricing.py -v`
Expected: FAIL（`ModuleNotFoundError: app.cost`）

- [ ] **Step 3: 创建模块**

创建 `app/cost/__init__.py`（空文件）。

创建 `app/cost/pricing.py`：

```python
"""价格解析与成本折算。

缺价不阻断计量：折算返回 0 成本，token 照常记录。
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import ModelPrice
from app.observability.logging import get_logger

logger = get_logger("luna.cost.pricing")

_THOUSAND = Decimal(1000)


def resolve_price(
    db: Session, provider: str, model: str, at: datetime
) -> ModelPrice | None:
    """取 (provider, model) 下 effective_from <= at 的最新一条价格。"""
    return (
        db.query(ModelPrice)
        .filter(
            ModelPrice.provider == provider,
            ModelPrice.model == model,
            ModelPrice.effective_from <= at,
        )
        .order_by(ModelPrice.effective_from.desc())
        .first()
    )


def compute_cost(
    input_tokens: int, output_tokens: int, price: ModelPrice | None
) -> tuple[Decimal, str]:
    """按单价折算成本；无价格时返回 (0, 'CNY') 并 log warning。"""
    if price is None:
        logger.warning("compute_cost_no_price")
        return Decimal("0"), "CNY"
    cost = (
        Decimal(input_tokens) / _THOUSAND * price.input_price_per_1k
        + Decimal(output_tokens) / _THOUSAND * price.output_price_per_1k
    )
    return cost, price.currency
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/cost/test_pricing.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add app/cost/__init__.py app/cost/pricing.py tests/cost/test_pricing.py
git commit -m "feat(cost): add pricing resolution and cost computation"
```

---

## Task 5: LLM 层用量捕获

**Files:**
- Modify: `app/services/llm.py`
- Test: `tests/cost/test_llm_usage.py`

**Interfaces:**
- Produces:
  - `@dataclass TokenUsage`：`input_tokens: int`、`output_tokens: int`、`model: str`、`provider: str`。
  - `extract_usage(response, provider: str, model: str) -> TokenUsage | None` —— 从 LangChain 响应的 `usage_metadata` 提取；缺失返回 None。
  - `generate_response_with_usage(prompt: str, context: str | None = None) -> tuple[str, TokenUsage | None]`
  - `generate_streaming_response(prompt, context=None, usage_holder: dict | None = None)` —— 若传入 `usage_holder`，流结束时把 `TokenUsage` 存入 `usage_holder["usage"]`（失败则不设或设 None）。
- Consumes: `get_chat_model()`、`settings`（既有）。

- [ ] **Step 1: 写失败测试**

创建 `tests/cost/test_llm_usage.py`：

```python
"""LLM 层 token 用量捕获。"""
import asyncio
from types import SimpleNamespace

from app.services import llm
from app.services.llm import TokenUsage, extract_usage


def test_extract_usage_from_metadata():
    resp = SimpleNamespace(usage_metadata={"input_tokens": 12, "output_tokens": 34})
    usage = extract_usage(resp, "ark", "m")
    assert usage == TokenUsage(input_tokens=12, output_tokens=34, model="m", provider="ark")


def test_extract_usage_missing_returns_none():
    resp = SimpleNamespace()  # 无 usage_metadata
    assert extract_usage(resp, "ark", "m") is None


def test_generate_response_with_usage(monkeypatch):
    fake_resp = SimpleNamespace(
        content="hello",
        usage_metadata={"input_tokens": 5, "output_tokens": 7},
    )

    class FakeChat:
        def invoke(self, _prompt):
            return fake_resp

    monkeypatch.setattr(llm, "get_chat_model", lambda: FakeChat())
    monkeypatch.setattr(llm.settings, "llm_provider", SimpleNamespace(value="ark"))
    monkeypatch.setattr(llm.settings, "ark_model", "deepseek")

    text, usage = llm.generate_response_with_usage("q")
    assert text == "hello"
    assert usage.input_tokens == 5
    assert usage.output_tokens == 7


def test_streaming_fills_usage_holder(monkeypatch):
    class Chunk(SimpleNamespace):
        pass

    async def fake_astream(_prompt):
        yield SimpleNamespace(content="a", usage_metadata=None)
        yield SimpleNamespace(
            content="b", usage_metadata={"input_tokens": 3, "output_tokens": 4}
        )

    class FakeChat:
        def astream(self, prompt):
            return fake_astream(prompt)

    monkeypatch.setattr(llm, "get_chat_model", lambda: FakeChat())
    monkeypatch.setattr(llm.settings, "llm_provider", SimpleNamespace(value="ark"))
    monkeypatch.setattr(llm.settings, "ark_model", "deepseek")

    holder: dict = {}

    async def run():
        out = ""
        async for tok in llm.generate_streaming_response("q", usage_holder=holder):
            out += tok
        return out

    out = asyncio.run(run())
    assert out == "ab"
    assert holder["usage"].input_tokens == 3
    assert holder["usage"].output_tokens == 4
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/cost/test_llm_usage.py -v`
Expected: FAIL（`ImportError: TokenUsage`）

- [ ] **Step 3: 修改 `app/services/llm.py`**

在文件顶部导入区添加：

```python
from dataclasses import dataclass
```

在 `settings = get_settings()` 之后添加：

```python
@dataclass
class TokenUsage:
    """一次 LLM 调用的 token 用量。"""

    input_tokens: int
    output_tokens: int
    model: str
    provider: str


def extract_usage(response, provider: str, model: str) -> TokenUsage | None:
    """从 LangChain 响应的 usage_metadata 提取用量；缺失或异常返回 None。"""
    try:
        meta = getattr(response, "usage_metadata", None)
        if not meta:
            return None
        return TokenUsage(
            input_tokens=int(meta.get("input_tokens", 0)),
            output_tokens=int(meta.get("output_tokens", 0)),
            model=model,
            provider=provider,
        )
    except Exception:
        return None
```

在 `get_chat_model` 中，Ark 分支的 `ChatOpenAI` 增加 `stream_usage=True`（放入构造参数）：

```python
        return ChatOpenAI(
            model=settings.ark_model,
            api_key=settings.ark_api_key,
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            temperature=0.7,
            stream_usage=True,
            model_kwargs={"stream": False},
        )
```

新增 `generate_response_with_usage`，并让 `generate_response` 委托它：

```python
def generate_response_with_usage(
    prompt: str, context: str | None = None
) -> tuple[str, TokenUsage | None]:
    """生成响应并返回 (文本, 用量)。用量缺失时为 None。"""
    chat = get_chat_model()
    if context:
        full_prompt = f"""Based on the following context, answer the question.

Context:
{context}

Question: {prompt}

Answer:"""
    else:
        full_prompt = prompt

    response = chat.invoke(full_prompt)
    text = response.content if hasattr(response, "content") else str(response)
    usage = extract_usage(
        response, settings.llm_provider.value, settings.ark_model
    )
    return text, usage
```

将现有 `generate_response` 函数体替换为委托：

```python
def generate_response(prompt: str, context: str | None = None) -> str:
    """Generate response from LLM."""
    text, _usage = generate_response_with_usage(prompt, context)
    return text
```

将 `generate_streaming_response` 改造为支持 `usage_holder`：

```python
async def generate_streaming_response(
    prompt: str, context: str | None = None, usage_holder: dict | None = None
):
    """流式生成响应；若传入 usage_holder，流末尾将 TokenUsage 存入其 'usage' 键。"""
    chat = get_chat_model()
    if context:
        full_prompt = f"""Based on the following context, answer the question.

Context:
{context}

Question: {prompt}

Answer:"""
    else:
        full_prompt = prompt

    last_usage = None
    async for chunk in chat.astream(full_prompt):
        found = extract_usage(chunk, settings.llm_provider.value, settings.ark_model)
        if found is not None:
            last_usage = found
        yield chunk.content if hasattr(chunk, "content") else str(chunk)

    if usage_holder is not None:
        usage_holder["usage"] = last_usage
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/cost/test_llm_usage.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 回归既有 LLM/图测试**

Run: `.venv/bin/pytest tests/graph tests/services -v`
Expected: PASS（无回归；若无对应目录则跳过该路径）

- [ ] **Step 6: 提交**

```bash
git add app/services/llm.py tests/cost/test_llm_usage.py
git commit -m "feat(cost): capture token usage in LLM layer (sync + streaming)"
```

---

## Task 6: rag_graph 透传 usage

**Files:**
- Modify: `app/graph/state.py`
- Modify: `app/graph/rag_graph.py`
- Test: `tests/cost/test_rag_usage_passthrough.py`

**Interfaces:**
- Consumes: `generate_response_with_usage`、`generate_streaming_response(usage_holder=...)`（Task 5）。
- Produces: `RAGState` 新增可选字段 `usage`；`generate_node` 返回 dict 增加 `usage`；`answer_question(...)` 返回 dict 增加键 `usage`（`TokenUsage | None`）；`answer_question_stream(question, knowledge_base_id, usage_holder=None)` 接受可选 `usage_holder` 并在流末尾填充。

- [ ] **Step 1: 阅读现有调用点**

确认结构：`app/graph/state.py` 的 `RAGState`(TypedDict) 字段以 `prompt_version_id: str | None` 结尾；`generate_node`（`app/graph/rag_graph.py` ~195 行）以 `return {"answer": answer, "sources": sources, "prompt_version_id": prompt_version_id}` 结尾，其中 `answer = generate_response(prompt=full_prompt, context=None)`（~262 行）；`answer_question`（~306 行）调用 `graph.invoke(...)` 后返回 dict；`answer_question_stream`（~348 行）内 `generate_streaming_response` 调用点（~431 行）。

- [ ] **Step 2: 写失败测试**

创建 `tests/cost/test_rag_usage_passthrough.py`：

```python
"""answer_question 在返回中透传 usage。"""
from types import SimpleNamespace

from app.graph import rag_graph
from app.services.llm import TokenUsage


def test_answer_question_includes_usage(monkeypatch):
    fake_usage = TokenUsage(input_tokens=5, output_tokens=6, model="m", provider="ark")

    class FakeGraph:
        def invoke(self, _state):
            return {
                "answer": "A",
                "sources": [],
                "prompt_version_id": None,
                "usage": fake_usage,
            }

    monkeypatch.setattr(rag_graph, "get_rag_graph", lambda: FakeGraph())
    result = rag_graph.answer_question("q", knowledge_base_id="kb")
    assert result["usage"] == fake_usage
```

说明：本任务把 `usage` 通过图 state 传出。若现有图节点结构使 state 注入复杂，可退化为在 `answer_question` 内直接调用 `generate_response_with_usage`（见 Step 3 备选）。

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv/bin/pytest tests/cost/test_rag_usage_passthrough.py -v`
Expected: FAIL（`KeyError: 'usage'`）

- [ ] **Step 4: 在 `RAGState` 增加可选字段**

`app/graph/state.py` 的 `RAGState` 中，`prompt_version_id: str | None` 之后添加：

```python
    usage: Any | None
```

顶部导入区确保有 `from typing import Annotated, Any`（若已有 `Annotated`，补 `Any`）。

- [ ] **Step 5: 修改 `generate_node` 捕获 usage**

`app/graph/rag_graph.py` 顶部 `from app.services.llm import ...` 行加入 `generate_response_with_usage`。

将 `generate_node` 中生成段（~260 行）：

```python
    with time_stage(LLM_GENERATION_DURATION, provider=settings.llm_provider.value):
        answer = generate_response(prompt=full_prompt, context=None)
```

改为：

```python
    with time_stage(LLM_GENERATION_DURATION, provider=settings.llm_provider.value):
        answer, usage = generate_response_with_usage(prompt=full_prompt, context=None)
```

并将该节点 return 改为：

```python
    return {
        "answer": answer,
        "sources": sources,
        "prompt_version_id": prompt_version_id,
        "usage": usage,
    }
```

- [ ] **Step 6: 修改 `answer_question` 透出 usage**

`answer_question` 的返回 dict 增加 `"usage": result.get("usage")`：

```python
    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "processing_time_ms": processing_time_ms,
        "retrieval_mode": settings.retrieval_mode.value,
        "prompt_version_id": result.get("prompt_version_id"),
        "usage": result.get("usage"),
    }
```

- [ ] **Step 7: 修改 `answer_question_stream` 接受 usage_holder**

签名改为 `async def answer_question_stream(question, knowledge_base_id, usage_holder=None)`，把 `usage_holder` 透传给 `generate_streaming_response(prompt=..., context=..., usage_holder=usage_holder)`（~431 行调用点）。

> 注意：`answer_question_multi_turn_stream`（~492 行）与 `direct` 模式的 `generate_streaming_response` 调用（~610 行）本期不接 usage_holder（仅问答生成主路径纳入计量），保持原签名不变。

- [ ] **Step 8: 运行测试确认通过**

Run: `.venv/bin/pytest tests/cost/test_rag_usage_passthrough.py -v`
Expected: PASS

- [ ] **Step 9: 回归**

Run: `.venv/bin/pytest tests/graph tests/quality/test_rag_graph_mode.py -v`
Expected: PASS（无回归）

- [ ] **Step 10: 提交**

```bash
git add app/graph/state.py app/graph/rag_graph.py tests/cost/test_rag_usage_passthrough.py
git commit -m "feat(cost): thread token usage through rag graph"
```

---

## Task 7: 用量记录与计数器累加（`recorder.py`）

**Files:**
- Create: `app/cost/recorder.py`
- Test: `tests/cost/test_recorder.py`

**Interfaces:**
- Consumes: `compute_cost`、`resolve_price`（Task 4）；`TokenUsage`（Task 5）；模型（Task 2）；指标（Task 3）；`AuthenticatedRequestContext`（提供 `tenant.id`/`workspace.id`/`knowledge_base.id`）。
- Produces:
  - `record_usage(db: Session, *, tenant_id: str, workspace_id: str, knowledge_base_id: str, interaction_id: str | None, usage: TokenUsage | None) -> None`
  - `bump_counter(db: Session, *, scope_type: str, scope_id: str, usage_date: date, token_delta: int, cost_delta: Decimal) -> None` —— 可移植原子累加（UPDATE→0行INSERT→IntegrityError重试UPDATE）。

- [ ] **Step 1: 写失败测试**

创建 `tests/cost/test_recorder.py`：

```python
"""用量记录与计数器累加。"""
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cost.recorder import bump_counter, record_usage
from app.db.models import Base, ModelPrice, QuotaCounter, UsageRecord
from app.services.llm import TokenUsage
from datetime import datetime, timezone


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _seed_price(s):
    s.add(
        ModelPrice(
            provider="ark",
            model="m",
            input_price_per_1k=Decimal("0.002"),
            output_price_per_1k=Decimal("0.008"),
            currency="CNY",
            effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
    )
    s.commit()


def test_bump_counter_inserts_then_accumulates():
    s = _session()
    d = date(2026, 7, 14)
    bump_counter(s, scope_type="tenant", scope_id="t1", usage_date=d, token_delta=10, cost_delta=Decimal("0.5"))
    bump_counter(s, scope_type="tenant", scope_id="t1", usage_date=d, token_delta=5, cost_delta=Decimal("0.25"))
    row = s.query(QuotaCounter).one()
    assert row.token_used == 15
    assert row.cost_used == Decimal("0.750000")


def test_record_usage_writes_record_and_two_counters():
    s = _session()
    _seed_price(s)
    usage = TokenUsage(input_tokens=1000, output_tokens=1000, model="m", provider="ark")
    record_usage(
        s,
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="kb1",
        interaction_id="i1",
        usage=usage,
    )
    assert s.query(UsageRecord).count() == 1
    # 租户 + 工作区各一行计数器
    assert s.query(QuotaCounter).count() == 2
    rec = s.query(UsageRecord).one()
    assert rec.total_tokens == 2000
    assert rec.cost_amount == Decimal("0.010000")  # 0.002 + 0.008


def test_record_usage_none_usage_is_noop():
    s = _session()
    record_usage(
        s,
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="kb1",
        interaction_id=None,
        usage=None,
    )
    assert s.query(UsageRecord).count() == 0
    assert s.query(QuotaCounter).count() == 0


def test_record_usage_swallows_errors():
    broken = MagicMock()
    broken.add.side_effect = RuntimeError("db down")
    usage = TokenUsage(input_tokens=1, output_tokens=1, model="m", provider="ark")
    # 不应抛出
    record_usage(
        broken,
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="kb1",
        interaction_id=None,
        usage=usage,
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/cost/test_recorder.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 创建 `app/cost/recorder.py`**

```python
"""用量明细记录与日度计数器累加（旁路容错）。

任何失败都 log + rollback + swallow，绝不影响 QA 响应。
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.cost.pricing import compute_cost, resolve_price
from app.db.models import QuotaCounter, UsageRecord
from app.observability.logging import get_logger
from app.observability.metrics import LLM_COST_TOTAL, LLM_TOKENS_TOTAL
from app.services.llm import TokenUsage

logger = get_logger("luna.cost.recorder")


def bump_counter(
    db: Session,
    *,
    scope_type: str,
    scope_id: str,
    usage_date: date,
    token_delta: int,
    cost_delta: Decimal,
) -> None:
    """可移植原子累加：先 UPDATE，命中 0 行则 INSERT，竞争 IntegrityError 时重试 UPDATE。"""
    updated = (
        db.query(QuotaCounter)
        .filter(
            QuotaCounter.scope_type == scope_type,
            QuotaCounter.scope_id == scope_id,
            QuotaCounter.usage_date == usage_date,
        )
        .update(
            {
                QuotaCounter.token_used: QuotaCounter.token_used + token_delta,
                QuotaCounter.cost_used: QuotaCounter.cost_used + cost_delta,
            },
            synchronize_session=False,
        )
    )
    if updated:
        return
    try:
        db.add(
            QuotaCounter(
                scope_type=scope_type,
                scope_id=scope_id,
                usage_date=usage_date,
                token_used=token_delta,
                cost_used=cost_delta,
            )
        )
        db.flush()
    except IntegrityError:
        db.rollback()
        db.query(QuotaCounter).filter(
            QuotaCounter.scope_type == scope_type,
            QuotaCounter.scope_id == scope_id,
            QuotaCounter.usage_date == usage_date,
        ).update(
            {
                QuotaCounter.token_used: QuotaCounter.token_used + token_delta,
                QuotaCounter.cost_used: QuotaCounter.cost_used + cost_delta,
            },
            synchronize_session=False,
        )


def record_usage(
    db: Session,
    *,
    tenant_id: str,
    workspace_id: str,
    knowledge_base_id: str,
    interaction_id: str | None,
    usage: TokenUsage | None,
) -> None:
    """折算成本、写明细、累加租户与工作区计数器、打指标。失败静默。"""
    if usage is None:
        logger.info("record_usage_skipped_no_usage", knowledge_base_id=knowledge_base_id)
        return
    try:
        now = datetime.now(timezone.utc)
        today = now.date()
        price = resolve_price(db, usage.provider, usage.model, now)
        cost, currency = compute_cost(usage.input_tokens, usage.output_tokens, price)
        total_tokens = usage.input_tokens + usage.output_tokens

        db.add(
            UsageRecord(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                knowledge_base_id=knowledge_base_id,
                interaction_id=interaction_id,
                provider=usage.provider,
                model=usage.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=total_tokens,
                cost_amount=cost,
                currency=currency,
            )
        )
        bump_counter(
            db,
            scope_type="tenant",
            scope_id=tenant_id,
            usage_date=today,
            token_delta=total_tokens,
            cost_delta=cost,
        )
        bump_counter(
            db,
            scope_type="workspace",
            scope_id=workspace_id,
            usage_date=today,
            token_delta=total_tokens,
            cost_delta=cost,
        )
        db.commit()

        LLM_TOKENS_TOTAL.labels(
            provider=usage.provider, model=usage.model, direction="input"
        ).inc(usage.input_tokens)
        LLM_TOKENS_TOTAL.labels(
            provider=usage.provider, model=usage.model, direction="output"
        ).inc(usage.output_tokens)
        LLM_COST_TOTAL.labels(
            provider=usage.provider, model=usage.model, currency=currency
        ).inc(float(cost))
    except Exception:
        logger.warning(
            "record_usage_failed",
            knowledge_base_id=knowledge_base_id,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/cost/test_recorder.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add app/cost/recorder.py tests/cost/test_recorder.py
git commit -m "feat(cost): record usage details and accumulate daily counters"
```

---

## Task 8: 配额准入（`enforcement.py`）

**Files:**
- Create: `app/cost/enforcement.py`
- Test: `tests/cost/test_enforcement.py`

**Interfaces:**
- Consumes: `QuotaLimit`、`QuotaCounter`（Task 2）；`QUOTA_REJECTED_TOTAL`（Task 3）；`settings.cost_enforcement_enabled`（Task 1）。
- Produces:
  - `check_quota(db: Session, tenant_id: str, workspace_id: str) -> None` —— 超限抛 `QuotaExceeded`；fail-open（读取异常时放行）；总开关关闭时放行。
  - `class QuotaExceeded(Exception)`：属性 `scope_type: str`、`dimension: str`（`token`/`cost`）。

- [ ] **Step 1: 写失败测试**

创建 `tests/cost/test_enforcement.py`：

```python
"""配额准入逻辑。"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cost import enforcement
from app.cost.enforcement import QuotaExceeded, check_quota
from app.db.models import Base, QuotaCounter, QuotaLimit


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _counter(s, scope_type, scope_id, tokens=0, cost="0"):
    s.add(
        QuotaCounter(
            scope_type=scope_type,
            scope_id=scope_id,
            usage_date=datetime.now(timezone.utc).date(),
            token_used=tokens,
            cost_used=Decimal(cost),
        )
    )
    s.commit()


def test_no_limit_configured_passes():
    s = _session()
    check_quota(s, "t1", "w1")  # 不抛


def test_under_limit_passes():
    s = _session()
    s.add(QuotaLimit(scope_type="tenant", scope_id="t1", daily_token_limit=1000, currency="CNY"))
    _counter(s, "tenant", "t1", tokens=500)
    check_quota(s, "t1", "w1")  # 不抛


def test_tenant_token_over_limit_rejects():
    s = _session()
    s.add(QuotaLimit(scope_type="tenant", scope_id="t1", daily_token_limit=1000, currency="CNY"))
    _counter(s, "tenant", "t1", tokens=1000)
    with pytest.raises(QuotaExceeded) as exc:
        check_quota(s, "t1", "w1")
    assert exc.value.scope_type == "tenant"
    assert exc.value.dimension == "token"


def test_workspace_cost_over_limit_rejects():
    s = _session()
    s.add(QuotaLimit(scope_type="workspace", scope_id="w1", daily_cost_limit=Decimal("1.0"), currency="CNY"))
    _counter(s, "workspace", "w1", cost="1.5")
    with pytest.raises(QuotaExceeded) as exc:
        check_quota(s, "t1", "w1")
    assert exc.value.scope_type == "workspace"
    assert exc.value.dimension == "cost"


def test_disabled_toggle_passes(monkeypatch):
    s = _session()
    s.add(QuotaLimit(scope_type="tenant", scope_id="t1", daily_token_limit=1, currency="CNY"))
    _counter(s, "tenant", "t1", tokens=999)
    monkeypatch.setattr(enforcement.settings, "cost_enforcement_enabled", False)
    check_quota(s, "t1", "w1")  # 关闭开关，放行


def test_db_error_fails_open(monkeypatch):
    from unittest.mock import MagicMock

    broken = MagicMock()
    broken.query.side_effect = RuntimeError("db down")
    # fail-open：不抛
    check_quota(broken, "t1", "w1")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/cost/test_enforcement.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 创建 `app/cost/enforcement.py`**

```python
"""配额准入：事前检查 + fail-open。"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import QuotaCounter, QuotaLimit
from app.observability.logging import get_logger

settings = get_settings()
logger = get_logger("luna.cost.enforcement")


class QuotaExceeded(Exception):
    """配额超限。"""

    def __init__(self, scope_type: str, dimension: str) -> None:
        self.scope_type = scope_type
        self.dimension = dimension
        super().__init__(f"{scope_type} daily {dimension} quota exceeded")


def _check_scope(db: Session, scope_type: str, scope_id: str, usage_date) -> None:
    limit = (
        db.query(QuotaLimit)
        .filter(QuotaLimit.scope_type == scope_type, QuotaLimit.scope_id == scope_id)
        .first()
    )
    if limit is None:
        return
    if limit.daily_token_limit is None and limit.daily_cost_limit is None:
        return
    counter = (
        db.query(QuotaCounter)
        .filter(
            QuotaCounter.scope_type == scope_type,
            QuotaCounter.scope_id == scope_id,
            QuotaCounter.usage_date == usage_date,
        )
        .first()
    )
    token_used = counter.token_used if counter else 0
    cost_used = counter.cost_used if counter else 0
    if limit.daily_token_limit is not None and token_used >= limit.daily_token_limit:
        raise QuotaExceeded(scope_type, "token")
    if limit.daily_cost_limit is not None and cost_used >= limit.daily_cost_limit:
        raise QuotaExceeded(scope_type, "cost")


def check_quota(db: Session, tenant_id: str, workspace_id: str) -> None:
    """检查租户与工作区当日配额；超限抛 QuotaExceeded，读取异常时 fail-open 放行。"""
    if not settings.cost_enforcement_enabled:
        return
    usage_date = datetime.now(timezone.utc).date()
    try:
        _check_scope(db, "tenant", tenant_id, usage_date)
        _check_scope(db, "workspace", workspace_id, usage_date)
    except QuotaExceeded:
        raise
    except Exception:
        logger.warning("check_quota_failed_open", exc_info=True)
        return
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/cost/test_enforcement.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add app/cost/enforcement.py tests/cost/test_enforcement.py
git commit -m "feat(cost): add fail-open quota enforcement check"
```

---

## Task 9: 接入 QA 路由（准入 + 记录）

**Files:**
- Modify: `app/api/routes.py`
- Test: `tests/api/test_cost_enforcement_api.py`

**Interfaces:**
- Consumes: `check_quota`、`QuotaExceeded`（Task 8）；`record_usage`（Task 7）；`answer_question`（返回含 `usage`，Task 6）；`answer_question_stream(usage_holder=...)`（Task 6）；`AuthenticatedRequestContext`。
- Produces: `/qa/query` 在生成前 `check_quota`，超限返回 429；生成后调用 `record_usage`。`/qa/stream` 同理，流结束后记录 usage。

- [ ] **Step 1: 写失败测试**

创建 `tests/api/test_cost_enforcement_api.py`（复用 `tests/api/test_review_api.py` 的 fixture 骨架，含 RBAC seed）：

```python
"""QA 配额硬限流集成测试。"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS, PermissionSlug, RoleSlug
from app.db.database import get_db
from app.db.models import (
    Base,
    KnowledgeBase,
    Permission,
    QuotaCounter,
    QuotaLimit,
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
    s = Session()
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="R", slug="r", tenant=tenant)
    kb = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    s.add(kb)
    s.flush()
    # RBAC：admin 角色含 QA_QUERY
    perms = {}
    for slug in (PermissionSlug.QA_QUERY,):
        p = Permission(name=slug, slug=slug, description=slug)
        s.add(p)
        perms[slug] = p
    role = Role(name="admin", slug="admin", is_system=True, permissions=list(perms.values()))
    s.add(role)
    user = User(email="u@x.com", display_name="U", is_active=True)
    s.add(user)
    s.flush()
    s.add(WorkspaceMembership(user_id=user.id, workspace_id=workspace.id, is_active=True, roles=[role]))
    # 租户 token 配额=1，已用 5 → 必超
    s.add(QuotaLimit(scope_type="tenant", scope_id=tenant.id, daily_token_limit=1, currency="CNY"))
    s.add(QuotaCounter(scope_type="tenant", scope_id=tenant.id, usage_date=datetime.now(timezone.utc).date(), token_used=5, cost_used=Decimal("0")))
    s.commit()
    ctx = {"tenant": tenant.id, "workspace": workspace.id, "kb": kb.id, "user": user.id}
    s.close()
    yield engine, Session, ctx
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


def test_qa_query_rejected_when_over_quota(client, app_db):
    _, _, ctx = app_db
    resp = client.post(
        "/api/v1/qa/query",
        json={"question": "hi"},
        headers={
            "X-User-Id": ctx["user"],
            "X-Tenant-Id": ctx["tenant"],
            "X-Workspace-Id": ctx["workspace"],
            "X-Knowledge-Base-Id": ctx["kb"],
        },
    )
    assert resp.status_code == 429
    assert "quota exceeded" in resp.json()["detail"]
```

（`User` 若必须字段更多，参照 `tests/api/test_review_api.py` 的构造补齐；本测试仅验证准入 429，不触达真实 LLM。）

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/api/test_cost_enforcement_api.py -v`
Expected: FAIL（返回 200 或非 429，因未接入准入）

- [ ] **Step 3: 在 `app/api/routes.py` 接入**

顶部导入区添加：

```python
from app.cost.enforcement import QuotaExceeded, check_quota
from app.cost.recorder import record_usage
```

在 `query`（`/qa/query`）函数体开头、`filters_payload` 处理之前插入准入：

```python
    try:
        check_quota(db, context.tenant.id, context.workspace.id)
    except QuotaExceeded as exc:
        QUOTA_REJECTED_TOTAL.labels(scope_type=exc.scope_type).inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
```

顶部补充导入 `QUOTA_REJECTED_TOTAL`：现有 `from app.observability.metrics import INDEX_TASK_DURATION` 一行改为 `from app.observability.metrics import INDEX_TASK_DURATION, QUOTA_REJECTED_TOTAL`。（`status` 已从 fastapi 导入，无需再加。）

在 `record_interaction(...)` 调用之后、`return AnswerResponse(...)` 之前插入用量记录：

```python
    record_usage(
        db,
        tenant_id=context.tenant.id,
        workspace_id=context.workspace.id,
        knowledge_base_id=context.knowledge_base.id,
        interaction_id=answer_id,
        usage=result.get("usage"),
    )
```

- [ ] **Step 4: 接入流式路由 `/qa/stream`**

在 `stream_query` 中，`AuditService().record(...)` 之后、构造 `StreamingResponse` 之前插入准入（同上 try/except 429 块）。

修改 `stream_event_generator` 使其接受 context 与 db 以便流末尾记录 usage。将其签名改为：

```python
async def stream_event_generator(
    question: str,
    knowledge_base_id: str,
    db: Session,
    tenant_id: str,
    workspace_id: str,
) -> AsyncGenerator[str, None]:
    usage_holder: dict = {}
    try:
        async for event in answer_question_stream(
            question, knowledge_base_id, usage_holder=usage_holder
        ):
            yield f"data: {json.dumps(event)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'event': 'error', 'data': str(e)})}\n\n"
    finally:
        record_usage(
            db,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
            interaction_id=None,
            usage=usage_holder.get("usage"),
        )
```

`stream_query` 中调用改为：

```python
    return StreamingResponse(
        stream_event_generator(
            question_req.question,
            context.knowledge_base.id,
            db,
            context.tenant.id,
            context.workspace.id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/bin/pytest tests/api/test_cost_enforcement_api.py -v`
Expected: PASS

- [ ] **Step 6: 回归 QA 相关测试**

Run: `.venv/bin/pytest tests/api -k "qa or audit or review or quality" -v`
Expected: PASS（无回归）

- [ ] **Step 7: 提交**

```bash
git add app/api/routes.py tests/api/test_cost_enforcement_api.py
git commit -m "feat(cost): enforce quota and record usage in QA routes"
```

---

## Task 10: 管理 API（配额配置 / 用量查询 / 价格）

**Files:**
- Create: `app/cost/service.py`, `app/api/cost_routes.py`
- Modify: `app/main.py`
- Test: `tests/api/test_cost_api.py`

**Interfaces:**
- Consumes: 模型（Task 2）；`require_permission`、`AuthenticatedRequestContext`；`PermissionSlug.COST_MANAGE/COST_READ`（Task 1）。
- Produces: `cost_router`（`APIRouter(prefix="/api/v1")`），端点见 §8。`app/cost/service.py` 提供 `upsert_quota_limit`、`get_current_usage`、`list_usage_records`、`upsert_model_price`。

- [ ] **Step 1: 写失败测试**

创建 `tests/api/test_cost_api.py`，seed RBAC 含 `COST_MANAGE`、`COST_READ`（骨架同 Task 9 fixture，权限集合改为这两个 + 用 `DEFAULT_ROLE_PERMISSIONS` 无关；直接建 Permission）：

```python
"""成本管理 API 集成测试。"""
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
    s = Session()
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="R", slug="r", tenant=tenant)
    kb = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    s.add(kb)
    s.flush()
    perms = []
    for slug in (PermissionSlug.COST_MANAGE, PermissionSlug.COST_READ):
        p = Permission(name=slug, slug=slug, description=slug)
        s.add(p)
        perms.append(p)
    role = Role(name="admin", slug="admin", is_system=True, permissions=perms)
    s.add(role)
    user = User(email="u@x.com", display_name="U", is_active=True)
    s.add(user)
    s.flush()
    s.add(WorkspaceMembership(user_id=user.id, workspace_id=workspace.id, is_active=True, roles=[role]))
    s.commit()
    ctx = {"tenant": tenant.id, "workspace": workspace.id, "kb": kb.id, "user": user.id}
    s.close()
    yield engine, Session, ctx
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


def _headers(ctx):
    return {
        "X-User-Id": ctx["user"],
        "X-Tenant-Id": ctx["tenant"],
        "X-Workspace-Id": ctx["workspace"],
        "X-Knowledge-Base-Id": ctx["kb"],
    }


def test_put_quota_limit_then_get_usage(client, app_db):
    _, _, ctx = app_db
    put = client.put(
        "/api/v1/quota/limits",
        json={"scope_type": "tenant", "scope_id": ctx["tenant"], "daily_token_limit": 1000, "currency": "CNY"},
        headers=_headers(ctx),
    )
    assert put.status_code == 200
    got = client.get("/api/v1/quota/usage", headers=_headers(ctx))
    assert got.status_code == 200
    body = got.json()
    assert body["tenant"]["daily_token_limit"] == 1000
    assert body["tenant"]["token_used"] == 0


def test_records_endpoint_empty(client, app_db):
    _, _, ctx = app_db
    got = client.get("/api/v1/cost/records", headers=_headers(ctx))
    assert got.status_code == 200
    assert got.json()["total"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/api/test_cost_api.py -v`
Expected: FAIL（404，路由未注册）

- [ ] **Step 3: 创建 `app/cost/service.py`**

```python
"""成本管理业务逻辑：配额配置、用量查询、价格维护。"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import ModelPrice, QuotaCounter, QuotaLimit, UsageRecord


def upsert_quota_limit(
    db: Session,
    *,
    scope_type: str,
    scope_id: str,
    daily_token_limit: int | None,
    daily_cost_limit: Decimal | None,
    currency: str,
) -> QuotaLimit:
    limit = (
        db.query(QuotaLimit)
        .filter(QuotaLimit.scope_type == scope_type, QuotaLimit.scope_id == scope_id)
        .first()
    )
    if limit is None:
        limit = QuotaLimit(scope_type=scope_type, scope_id=scope_id)
        db.add(limit)
    limit.daily_token_limit = daily_token_limit
    limit.daily_cost_limit = daily_cost_limit
    limit.currency = currency
    db.commit()
    db.refresh(limit)
    return limit


def _scope_usage(db: Session, scope_type: str, scope_id: str) -> dict:
    today = datetime.now(timezone.utc).date()
    limit = (
        db.query(QuotaLimit)
        .filter(QuotaLimit.scope_type == scope_type, QuotaLimit.scope_id == scope_id)
        .first()
    )
    counter = (
        db.query(QuotaCounter)
        .filter(
            QuotaCounter.scope_type == scope_type,
            QuotaCounter.scope_id == scope_id,
            QuotaCounter.usage_date == today,
        )
        .first()
    )
    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "daily_token_limit": limit.daily_token_limit if limit else None,
        "daily_cost_limit": (str(limit.daily_cost_limit) if limit and limit.daily_cost_limit is not None else None),
        "token_used": counter.token_used if counter else 0,
        "cost_used": str(counter.cost_used) if counter else "0",
    }


def get_current_usage(db: Session, tenant_id: str, workspace_id: str) -> dict:
    return {
        "tenant": _scope_usage(db, "tenant", tenant_id),
        "workspace": _scope_usage(db, "workspace", workspace_id),
    }


def list_usage_records(
    db: Session, *, tenant_id: str, limit: int = 50, offset: int = 0
) -> tuple[list[UsageRecord], int]:
    q = db.query(UsageRecord).filter(UsageRecord.tenant_id == tenant_id)
    total = q.count()
    rows = (
        q.order_by(UsageRecord.created_at.desc()).limit(limit).offset(offset).all()
    )
    return rows, total


def upsert_model_price(
    db: Session,
    *,
    provider: str,
    model: str,
    input_price_per_1k: Decimal,
    output_price_per_1k: Decimal,
    currency: str,
    effective_from: datetime,
) -> ModelPrice:
    price = ModelPrice(
        provider=provider,
        model=model,
        input_price_per_1k=input_price_per_1k,
        output_price_per_1k=output_price_per_1k,
        currency=currency,
        effective_from=effective_from,
    )
    db.add(price)
    db.commit()
    db.refresh(price)
    return price
```

- [ ] **Step 4: 创建 `app/api/cost_routes.py`**

```python
"""成本与配额管理 API。"""
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
from app.cost import service
from app.db.database import get_db

router = APIRouter(prefix="/api/v1", tags=["cost"])


class QuotaLimitRequest(BaseModel):
    scope_type: str = Field(..., pattern="^(tenant|workspace)$")
    scope_id: str
    daily_token_limit: int | None = None
    daily_cost_limit: Decimal | None = None
    currency: str = "CNY"


class QuotaLimitResponse(BaseModel):
    scope_type: str
    scope_id: str
    daily_token_limit: int | None
    daily_cost_limit: Decimal | None
    currency: str

    model_config = ConfigDict(from_attributes=True)


class UsageRecordResponse(BaseModel):
    id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_amount: Decimal
    currency: str

    model_config = ConfigDict(from_attributes=True)


class UsageRecordListResponse(BaseModel):
    records: list[UsageRecordResponse]
    total: int


class ModelPriceRequest(BaseModel):
    provider: str
    model: str
    input_price_per_1k: Decimal
    output_price_per_1k: Decimal
    currency: str = "CNY"
    effective_from: datetime


@router.put("/quota/limits", response_model=QuotaLimitResponse)
async def put_quota_limit(
    req: QuotaLimitRequest,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.COST_MANAGE)),
    ],
) -> QuotaLimitResponse:
    limit = service.upsert_quota_limit(
        db,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        daily_token_limit=req.daily_token_limit,
        daily_cost_limit=req.daily_cost_limit,
        currency=req.currency,
    )
    return QuotaLimitResponse.model_validate(limit)


@router.get("/quota/usage")
async def get_quota_usage(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.COST_READ)),
    ],
) -> dict:
    return service.get_current_usage(db, context.tenant.id, context.workspace.id)


@router.get("/cost/records", response_model=UsageRecordListResponse)
async def get_cost_records(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.COST_READ)),
    ],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> UsageRecordListResponse:
    rows, total = service.list_usage_records(
        db, tenant_id=context.tenant.id, limit=limit, offset=offset
    )
    return UsageRecordListResponse(
        records=[UsageRecordResponse.model_validate(r) for r in rows],
        total=total,
    )


@router.put("/cost/prices", response_model=dict)
async def put_model_price(
    req: ModelPriceRequest,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.COST_MANAGE)),
    ],
) -> dict:
    price = service.upsert_model_price(
        db,
        provider=req.provider,
        model=req.model,
        input_price_per_1k=req.input_price_per_1k,
        output_price_per_1k=req.output_price_per_1k,
        currency=req.currency,
        effective_from=req.effective_from,
    )
    return {"id": price.id}
```

- [ ] **Step 5: 在 `app/main.py` 注册路由**

导入区添加：

```python
from app.api.cost_routes import router as cost_router
```

`create_app` 中其他 `include_router` 之后添加：

```python
    app.include_router(cost_router)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `.venv/bin/pytest tests/api/test_cost_api.py -v`
Expected: PASS（2 passed）

- [ ] **Step 7: 全量回归**

Run: `.venv/bin/pytest tests/cost tests/api -v`
Expected: PASS（无回归）

- [ ] **Step 8: 提交**

```bash
git add app/cost/service.py app/api/cost_routes.py app/main.py tests/api/test_cost_api.py
git commit -m "feat(cost): add cost/quota management API endpoints"
```

---

## 收尾（非任务，执行完成后手动操作）

- 运行 `.venv/bin/alembic upgrade head` 应用迁移 `0013`（与项目既有约定一致，需手动执行）。
- 通过 `PUT /cost/prices` 写入初始价格：Ark 模型的实际单价 + Ollama 本地模型 0 价。
- 更新记忆：新增 `cost_quota` 里程碑条目。
