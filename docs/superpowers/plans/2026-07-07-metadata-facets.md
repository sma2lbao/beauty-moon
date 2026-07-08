# 元数据与分面过滤模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为知识库引入类型化元数据 Schema、分面过滤检索与全库分面聚合，让检索可按业务维度收窄并为前端提供筛选器数据源。

**Architecture:** 新增 `app/metadata` 包（字段定义 ORM、Pydantic schema、校验归一化、分面聚合）与 `app/retrieval/filters.py`（过滤条件模型 + Chroma where 下推 + BM25 post-filter 谓词）。摄取时校验归一化元数据并存 `Document.doc_metadata`，随 chunk 传播到 Chroma；检索时向量侧下推 `where`、BM25 侧 post-filter；分面按知识库聚合 `Document.doc_metadata`。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、Alembic、ChromaDB、rank-bm25、Pydantic v2、pytest。

## Global Constraints

- 所有测试命令在 `apps/luna-corpus` 目录下用 `pytest` 运行。
- 中文注释/文档；代码风格贴合现有模块（dataclass、`get_settings()`、structlog logger、`from app.xxx import`）。
- Chroma metadata 仅支持标量（str/int/float/bool），**禁止**写 list —— `tags` 一律布尔展开为 `tag__<value>=True`。
- 无 `filters` 时 `hybrid_search` 行为必须与现状完全一致（零回归）。
- API 前缀 `/api/v1`；RBAC 权限 slug 复用现有值：`knowledge_base:manage` / `knowledge_base:read` / `document:write` / `qa:query`。
- alembic 迁移命名 `YYYYMMDD_000N_<name>.py`，本模块用 `20260707_0007_metadata_facets.py`。
- `doc_metadata` 归一化字典的键序不保证；测试断言用集合/排序，勿依赖插入顺序。

---

## 文件结构

**新增：**
- `app/metadata/__init__.py` — 包 docstring + 导出
- `app/metadata/schema.py` — `FieldType` 枚举 + 字段定义 Pydantic 模型
- `app/metadata/models.py` — `MetadataFieldDefinition` ORM
- `app/metadata/validation.py` — `validate_and_normalize` + `MetadataValidationError`
- `app/metadata/facets.py` — `compute_facets` 全库分面聚合
- `app/retrieval/filters.py` — `FilterOp`/`MetadataCondition`/`MetadataFilter` + `to_chroma_where` + `make_post_filter` + `to_chroma_metadata` + `FilterFieldError`
- `app/api/metadata_routes.py` — Schema 管理端点 + 分面端点
- 测试：`tests/test_metadata_schema.py`、`tests/test_retrieval_filters.py`、`tests/test_metadata_validation.py`、`tests/test_metadata_facets.py`、`tests/test_hybrid_filters.py`、`tests/test_metadata_api.py`

**修改：**
- `app/core/config.py` — 新增 `filter_over_fetch_multiplier`
- `app/db/models.py` — `Document` 增 `doc_metadata` JSON 列
- `app/db/vectorstore.py` — `VectorChunkInput`/`add_chunks`/`search` 支持元数据与额外 where
- `app/retrieval/hybrid.py` — `hybrid_search` 增 `filters` 参数
- `app/services/document_processor.py` — chunk 携带 `doc_metadata` 写向量库
- `app/services/ingestion/service.py` — 上传校验元数据
- `app/api/routes.py` — 检索端点接收 `filters`；`create_document`/`upload_file` 接收 metadata；挂载 metadata_routes
- `app/graph/rag_graph.py` + `app/graph/state.py` — filters 透传
- `app/agent/tools/rag_search.py` — filters 透传
- `app/observability/metrics.py` — 新增 `rag_facet_duration_seconds`
- `alembic/versions/20260707_0007_metadata_facets.py` — 迁移

---

### Task 1: 新增配置 `filter_over_fetch_multiplier`

**Files:**
- Modify: `apps/luna-corpus/app/core/config.py`（RAG 配置区，`bm25_cache_ttl_seconds` 之后）
- Test: `apps/luna-corpus/tests/test_project_config.py`

**Interfaces:**
- Produces: `settings.filter_over_fetch_multiplier: int`（默认 3）

- [ ] **Step 1: 写失败测试**

在 `tests/test_project_config.py` 末尾追加：

```python
def test_filter_over_fetch_multiplier_default():
    from app.core.config import Settings

    settings = Settings()
    assert settings.filter_over_fetch_multiplier == 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_project_config.py::test_filter_over_fetch_multiplier_default -v`
Expected: FAIL（`AttributeError: 'Settings' object has no attribute 'filter_over_fetch_multiplier'`）

- [ ] **Step 3: 实现**

在 `app/core/config.py` 的 `bm25_cache_ttl_seconds` 字段之后新增：

```python
    filter_over_fetch_multiplier: int = Field(
        default=3,
        description="有元数据过滤时放大候选窗口的倍数，补偿 post-filter 损耗",
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && pytest tests/test_project_config.py::test_filter_over_fetch_multiplier_default -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/core/config.py apps/luna-corpus/tests/test_project_config.py
git commit -m "feat(corpus): add filter_over_fetch_multiplier config"
```

---

### Task 2: 元数据字段类型与字段定义 Pydantic 模型

**Files:**
- Create: `apps/luna-corpus/app/metadata/__init__.py`
- Create: `apps/luna-corpus/app/metadata/schema.py`
- Test: `apps/luna-corpus/tests/test_metadata_schema.py`

**Interfaces:**
- Produces:
  - `FieldType(StrEnum)`：`ENUM="enum"`、`STRING="string"`、`DATE="date"`、`NUMBER="number"`、`TAGS="tags"`
  - `FieldDefinitionCreate(BaseModel)`：`key: str`、`label: str`、`field_type: FieldType`、`options: list[str] | None = None`、`required: bool = False`、`is_facetable: bool = True`
  - `FieldDefinitionUpdate(BaseModel)`：`label: str | None`、`options: list[str] | None`、`required: bool | None`、`is_facetable: bool | None`（全部可选）
  - `FieldDefinitionRead(BaseModel)`：`id`、`knowledge_base_id`、`key`、`label`、`field_type`、`options`、`required`、`is_facetable`；`model_config = ConfigDict(from_attributes=True)`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_metadata_schema.py`：

```python
"""元数据字段定义 Pydantic 模型与类型枚举测试。"""
import pytest
from pydantic import ValidationError

from app.metadata.schema import (
    FieldDefinitionCreate,
    FieldDefinitionUpdate,
    FieldType,
)


def test_field_type_values():
    assert FieldType.ENUM == "enum"
    assert FieldType.STRING == "string"
    assert FieldType.DATE == "date"
    assert FieldType.NUMBER == "number"
    assert FieldType.TAGS == "tags"


def test_field_definition_create_defaults():
    f = FieldDefinitionCreate(key="category", label="类别", field_type="enum")
    assert f.options is None
    assert f.required is False
    assert f.is_facetable is True


def test_field_definition_create_key_required():
    with pytest.raises(ValidationError):
        FieldDefinitionCreate(label="缺 key", field_type="string")


def test_field_definition_update_all_optional():
    u = FieldDefinitionUpdate()
    assert u.label is None
    assert u.options is None
    assert u.required is None
    assert u.is_facetable is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_metadata_schema.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.metadata'`）

- [ ] **Step 3: 实现**

创建 `app/metadata/__init__.py`：

```python
"""元数据 Schema、校验与分面聚合。

`schema` 定义字段类型与字段定义的 Pydantic 模型；`models` 是字段定义 ORM；
`validation` 按 schema 校验并归一化上传元数据；`facets` 做全库分面聚合。
过滤条件到 Chroma where / post-filter 的翻译在 `app.retrieval.filters`。
"""
```

创建 `app/metadata/schema.py`：

```python
"""元数据字段类型与字段定义 Pydantic 模型。"""
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FieldType(StrEnum):
    """元数据字段类型。"""

    ENUM = "enum"
    STRING = "string"
    DATE = "date"
    NUMBER = "number"
    TAGS = "tags"


class FieldDefinitionCreate(BaseModel):
    """创建字段定义的请求模型。"""

    key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=255)
    field_type: FieldType
    options: list[str] | None = None
    required: bool = False
    is_facetable: bool = True


class FieldDefinitionUpdate(BaseModel):
    """更新字段定义的请求模型（字段类型与 key 不可改）。"""

    label: str | None = Field(default=None, min_length=1, max_length=255)
    options: list[str] | None = None
    required: bool | None = None
    is_facetable: bool | None = None


class FieldDefinitionRead(BaseModel):
    """字段定义响应模型。"""

    id: str
    knowledge_base_id: str
    key: str
    label: str
    field_type: FieldType
    options: list[str] | None
    required: bool
    is_facetable: bool

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && pytest tests/test_metadata_schema.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/metadata/__init__.py apps/luna-corpus/app/metadata/schema.py apps/luna-corpus/tests/test_metadata_schema.py
git commit -m "feat(corpus): add metadata FieldType and field definition schemas"
```

---

### Task 3: `MetadataFieldDefinition` ORM 与迁移

**Files:**
- Create: `apps/luna-corpus/app/metadata/models.py`
- Modify: `apps/luna-corpus/app/db/models.py`（`Document` 增 `doc_metadata` 列）
- Create: `apps/luna-corpus/alembic/versions/20260707_0007_metadata_facets.py`
- Test: `apps/luna-corpus/tests/test_metadata_models.py`

**Interfaces:**
- Consumes: `app.db.models.Base`、`FieldType`（Task 2）
- Produces:
  - `MetadataFieldDefinition` ORM，表名 `metadata_field_definitions`，列：`id`(CHAR36 PK)、`knowledge_base_id`(CHAR36 FK CASCADE)、`key`(String64)、`label`(String255)、`field_type`(Enum(FieldType))、`options`(JSON nullable)、`required`(Boolean)、`is_facetable`(Boolean)、`created_at`/`updated_at`；`UniqueConstraint("knowledge_base_id","key")`
  - `Document.doc_metadata: Mapped[dict | None]`（JSON nullable）

**注意：** `MetadataFieldDefinition` 定义在 `app/metadata/models.py`，但复用 `app.db.models.Base`。为确保 alembic autogenerate 与建表能发现它，`app/db/models.py` 末尾 import 它（见 Step 3）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_metadata_models.py`：

```python
"""MetadataFieldDefinition ORM 与 Document.doc_metadata 列测试。"""
from app.db.models import Document
from app.metadata.models import MetadataFieldDefinition


def test_metadata_field_definition_table():
    assert MetadataFieldDefinition.__tablename__ == "metadata_field_definitions"
    cols = set(MetadataFieldDefinition.__table__.columns.keys())
    assert {
        "id", "knowledge_base_id", "key", "label", "field_type",
        "options", "required", "is_facetable", "created_at", "updated_at",
    } <= cols


def test_metadata_field_definition_unique_constraint():
    uniques = [
        c for c in MetadataFieldDefinition.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    cols = {tuple(sorted(col.name for col in u.columns)) for u in uniques}
    assert ("key", "knowledge_base_id") in cols


def test_document_has_doc_metadata_column():
    assert "doc_metadata" in Document.__table__.columns.keys()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_metadata_models.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.metadata.models'`）

- [ ] **Step 3: 实现**

创建 `app/metadata/models.py`：

```python
"""元数据字段定义 ORM。"""
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import CHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base
from app.metadata.schema import FieldType


class MetadataFieldDefinition(Base):
    """知识库级元数据字段定义。"""

    __tablename__ = "metadata_field_definitions"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "key"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[FieldType] = mapped_column(Enum(FieldType), nullable=False)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_facetable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

在 `app/db/models.py` 的 `Document` 类中，`source` 列之后新增列：

```python
    doc_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

在 `app/db/models.py` 文件**末尾**追加（确保 metadata 表被注册；放末尾避免循环 import）：

```python
# 注册元数据字段定义表到同一 Base.metadata（供建表 / alembic 发现）。
from app.metadata.models import MetadataFieldDefinition  # noqa: E402,F401
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && pytest tests/test_metadata_models.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 写迁移**

创建 `alembic/versions/20260707_0007_metadata_facets.py`（`down_revision` 指向现有最新版本 `20260630_0006`；若本地 `alembic heads` 显示不同，以实际为准）：

```python
"""metadata field definitions and document doc_metadata

Revision ID: 20260707_0007
Revises: 20260630_0006
Create Date: 2026-07-07

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import CHAR

revision = "20260707_0007"
down_revision = "20260630_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metadata_field_definitions",
        sa.Column("id", CHAR(36), primary_key=True),
        sa.Column("knowledge_base_id", CHAR(36), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column(
            "field_type",
            sa.Enum("enum", "string", "date", "number", "tags", name="fieldtype"),
            nullable=False,
        ),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "is_facetable", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("knowledge_base_id", "key"),
    )
    op.add_column("documents", sa.Column("doc_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "doc_metadata")
    op.drop_table("metadata_field_definitions")
```

- [ ] **Step 6: 校验迁移可离线生成 SQL**

Run: `cd apps/luna-corpus && python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; ScriptDirectory.from_config(Config('alembic.ini')).walk_revisions()" && echo OK`
Expected: 打印 `OK`，无 revision 链断裂报错。（若报 `down_revision` 不匹配，运行 `alembic heads` 用实际最新版本修正。）

- [ ] **Step 7: 提交**

```bash
git add apps/luna-corpus/app/metadata/models.py apps/luna-corpus/app/db/models.py apps/luna-corpus/alembic/versions/20260707_0007_metadata_facets.py apps/luna-corpus/tests/test_metadata_models.py
git commit -m "feat(corpus): add MetadataFieldDefinition ORM and doc_metadata column"
```

---

### Task 4: 元数据校验与归一化

**Files:**
- Create: `apps/luna-corpus/app/metadata/validation.py`
- Test: `apps/luna-corpus/tests/test_metadata_validation.py`

**Interfaces:**
- Consumes: `MetadataFieldDefinition`（Task 3）、`FieldType`（Task 2）、`Session`
- Produces:
  - `class MetadataValidationError(Exception)`：`__init__(self, errors: list[str])`，`self.errors` 保存逐字段错误
  - `load_field_definitions(db: Session, kb_id: str) -> list[MetadataFieldDefinition]`
  - `validate_and_normalize(db: Session, kb_id: str, raw: dict | None) -> dict`：返回归一化字典（`raw` 为 None/{} 且无必填字段时返回 `{}`）

归一化规则：`enum`/`string` → trim 后的 str（enum 若定义 options 须命中）；`date` → `YYYY-MM-DD` 字符串（用 `datetime.date.fromisoformat` 校验）；`number` → float；`tags` → 去空去重后的 `list[str]`（若定义 options 每项须命中，顺序按首次出现）。未知 key、缺必填、类型错误 → 收集进 `MetadataValidationError.errors`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_metadata_validation.py`：

```python
"""元数据校验与归一化测试（用内存 SQLite + 真实 ORM）。"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, KnowledgeBase, Tenant, Workspace
from app.metadata.models import MetadataFieldDefinition
from app.metadata.validation import (
    MetadataValidationError,
    validate_and_normalize,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="T", slug="t")
    session.add(tenant)
    session.flush()
    ws = Workspace(tenant_id=tenant.id, name="W", slug="w")
    session.add(ws)
    session.flush()
    kb = KnowledgeBase(workspace_id=ws.id, name="KB", slug="kb")
    session.add(kb)
    session.flush()
    session.kb_id = kb.id
    yield session
    session.close()


def _add_field(db, **kwargs):
    f = MetadataFieldDefinition(knowledge_base_id=db.kb_id, **kwargs)
    db.add(f)
    db.flush()
    return f


def test_empty_metadata_no_required_returns_empty(db):
    assert validate_and_normalize(db, db.kb_id, None) == {}
    assert validate_and_normalize(db, db.kb_id, {}) == {}


def test_enum_valid(db):
    _add_field(db, key="category", label="类别", field_type="enum",
               options=["合同", "发票"])
    out = validate_and_normalize(db, db.kb_id, {"category": " 合同 "})
    assert out == {"category": "合同"}


def test_enum_not_in_options_raises(db):
    _add_field(db, key="category", label="类别", field_type="enum",
               options=["合同"])
    with pytest.raises(MetadataValidationError) as e:
        validate_and_normalize(db, db.kb_id, {"category": "发票"})
    assert any("category" in msg for msg in e.value.errors)


def test_unknown_key_raises(db):
    with pytest.raises(MetadataValidationError) as e:
        validate_and_normalize(db, db.kb_id, {"nope": "x"})
    assert any("nope" in msg for msg in e.value.errors)


def test_required_missing_raises(db):
    _add_field(db, key="category", label="类别", field_type="string",
               required=True)
    with pytest.raises(MetadataValidationError):
        validate_and_normalize(db, db.kb_id, {})


def test_date_normalized(db):
    _add_field(db, key="published_at", label="发布", field_type="date")
    out = validate_and_normalize(db, db.kb_id, {"published_at": "2025-03-01"})
    assert out == {"published_at": "2025-03-01"}


def test_date_invalid_raises(db):
    _add_field(db, key="published_at", label="发布", field_type="date")
    with pytest.raises(MetadataValidationError):
        validate_and_normalize(db, db.kb_id, {"published_at": "not-a-date"})


def test_number_coerced(db):
    _add_field(db, key="amount", label="金额", field_type="number")
    out = validate_and_normalize(db, db.kb_id, {"amount": "100.5"})
    assert out == {"amount": 100.5}


def test_number_invalid_raises(db):
    _add_field(db, key="amount", label="金额", field_type="number")
    with pytest.raises(MetadataValidationError):
        validate_and_normalize(db, db.kb_id, {"amount": "abc"})


def test_tags_dedup_and_trim(db):
    _add_field(db, key="tags", label="标签", field_type="tags")
    out = validate_and_normalize(
        db, db.kb_id, {"tags": [" a ", "b", "a", ""]}
    )
    assert out == {"tags": ["a", "b"]}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_metadata_validation.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.metadata.validation'`）

- [ ] **Step 3: 实现**

创建 `app/metadata/validation.py`：

```python
"""按知识库 schema 校验并归一化上传元数据。"""
from datetime import date

from sqlalchemy.orm import Session

from app.metadata.models import MetadataFieldDefinition
from app.metadata.schema import FieldType


class MetadataValidationError(Exception):
    """元数据校验失败，聚合逐字段错误信息。"""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def load_field_definitions(
    db: Session, kb_id: str
) -> list[MetadataFieldDefinition]:
    """加载知识库的全部字段定义。"""
    return (
        db.query(MetadataFieldDefinition)
        .filter(MetadataFieldDefinition.knowledge_base_id == kb_id)
        .all()
    )


def _normalize_value(
    field: MetadataFieldDefinition, value: object, errors: list[str]
) -> object | None:
    """按字段类型归一化单个值；出错时追加到 errors 并返回 None。"""
    key = field.key
    if field.field_type == FieldType.ENUM:
        v = str(value).strip()
        if field.options and v not in field.options:
            errors.append(f"字段 {key} 的值 '{v}' 不在候选项内")
            return None
        return v
    if field.field_type == FieldType.STRING:
        return str(value).strip()
    if field.field_type == FieldType.DATE:
        try:
            return date.fromisoformat(str(value).strip()).isoformat()
        except ValueError:
            errors.append(f"字段 {key} 不是合法日期(YYYY-MM-DD): '{value}'")
            return None
    if field.field_type == FieldType.NUMBER:
        try:
            return float(value)
        except (TypeError, ValueError):
            errors.append(f"字段 {key} 不是合法数值: '{value}'")
            return None
    if field.field_type == FieldType.TAGS:
        if not isinstance(value, list):
            errors.append(f"字段 {key} 必须是标签数组")
            return None
        seen: list[str] = []
        for item in value:
            t = str(item).strip()
            if not t or t in seen:
                continue
            if field.options and t not in field.options:
                errors.append(f"字段 {key} 的标签 '{t}' 不在候选项内")
                continue
            seen.append(t)
        return seen
    errors.append(f"字段 {key} 类型未知")
    return None


def validate_and_normalize(
    db: Session, kb_id: str, raw: dict | None
) -> dict:
    """按 schema 校验并归一化上传元数据，成功返回归一化字典。"""
    raw = raw or {}
    fields = {f.key: f for f in load_field_definitions(db, kb_id)}
    errors: list[str] = []

    # 未知字段（严格模式）
    for key in raw:
        if key not in fields:
            errors.append(f"未定义的元数据字段: {key}")

    normalized: dict = {}
    for key, field in fields.items():
        if key not in raw or raw[key] is None:
            if field.required:
                errors.append(f"缺少必填字段: {key}")
            continue
        result = _normalize_value(field, raw[key], errors)
        if result is not None:
            normalized[key] = result

    if errors:
        raise MetadataValidationError(errors)
    return normalized
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && pytest tests/test_metadata_validation.py -v`
Expected: PASS（11 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/metadata/validation.py apps/luna-corpus/tests/test_metadata_validation.py
git commit -m "feat(corpus): add metadata validation and normalization"
```

---

### Task 5: 过滤条件模型与翻译（filters.py）

**Files:**
- Create: `apps/luna-corpus/app/retrieval/filters.py`
- Test: `apps/luna-corpus/tests/test_retrieval_filters.py`

**Interfaces:**
- Consumes: `FieldType`（Task 2）
- Produces:
  - `class FilterOp(StrEnum)`：`EQ="eq"`、`IN="in"`、`GTE="gte"`、`LTE="lte"`、`CONTAINS_ANY="contains_any"`、`CONTAINS_ALL="contains_all"`
  - `class MetadataCondition(BaseModel)`：`key: str`、`op: FilterOp`、`value: str | float | list[str]`
  - `class MetadataFilter(BaseModel)`：`conditions: list[MetadataCondition]`
  - `class FilterFieldError(Exception)`：引用未定义字段时抛出，`self.key`
  - `to_chroma_metadata(doc_metadata: dict, field_types: dict[str, FieldType]) -> dict`：把归一化元数据转成 Chroma 标量 metadata（tags 布尔展开为 `tag__<v>=True`）
  - `to_chroma_where(f: MetadataFilter, field_types: dict[str, FieldType]) -> dict`：翻译成 Chroma where（不含 kb 隔离，调用方合并）
  - `make_post_filter(f: MetadataFilter, field_types: dict[str, FieldType]) -> Callable[[dict], bool]`：读候选原始 `doc_metadata` 判定

`field_types: dict[str, FieldType]` 是「字段 key → 类型」映射，由调用方从字段定义构造。若 condition/metadata 的 key 不在其中，`to_chroma_where`/`make_post_filter` 抛 `FilterFieldError`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_retrieval_filters.py`：

```python
"""过滤条件模型与 Chroma where / post-filter 翻译测试。"""
import pytest

from app.metadata.schema import FieldType
from app.retrieval.filters import (
    FilterFieldError,
    FilterOp,
    MetadataCondition,
    MetadataFilter,
    make_post_filter,
    to_chroma_metadata,
    to_chroma_where,
)

FIELD_TYPES = {
    "category": FieldType.ENUM,
    "author": FieldType.STRING,
    "published_at": FieldType.DATE,
    "amount": FieldType.NUMBER,
    "tags": FieldType.TAGS,
}


def test_to_chroma_metadata_scalars_and_tags():
    out = to_chroma_metadata(
        {"category": "合同", "amount": 100.0, "tags": ["a", "b"]},
        FIELD_TYPES,
    )
    assert out["category"] == "合同"
    assert out["amount"] == 100.0
    assert out["tag__a"] is True
    assert out["tag__b"] is True
    assert "tags" not in out


def test_to_chroma_where_eq():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.EQ, value="合同")
    ])
    assert to_chroma_where(f, FIELD_TYPES) == {"category": "合同"}


def test_to_chroma_where_in():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.IN, value=["合同", "发票"])
    ])
    assert to_chroma_where(f, FIELD_TYPES) == {
        "category": {"$in": ["合同", "发票"]}
    }


def test_to_chroma_where_date_range_multi_condition():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="published_at", op=FilterOp.GTE, value="2025-01-01"),
        MetadataCondition(key="published_at", op=FilterOp.LTE, value="2025-12-31"),
    ])
    where = to_chroma_where(f, FIELD_TYPES)
    assert where == {"$and": [
        {"published_at": {"$gte": "2025-01-01"}},
        {"published_at": {"$lte": "2025-12-31"}},
    ]}


def test_to_chroma_where_contains_any():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="tags", op=FilterOp.CONTAINS_ANY, value=["a", "b"])
    ])
    assert to_chroma_where(f, FIELD_TYPES) == {
        "$or": [{"tag__a": True}, {"tag__b": True}]
    }


def test_to_chroma_where_contains_all():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="tags", op=FilterOp.CONTAINS_ALL, value=["a", "b"])
    ])
    assert to_chroma_where(f, FIELD_TYPES) == {
        "$and": [{"tag__a": True}, {"tag__b": True}]
    }


def test_to_chroma_where_unknown_field_raises():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="ghost", op=FilterOp.EQ, value="x")
    ])
    with pytest.raises(FilterFieldError):
        to_chroma_where(f, FIELD_TYPES)


def test_post_filter_eq_and_range():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.EQ, value="合同"),
        MetadataCondition(key="amount", op=FilterOp.GTE, value=50.0),
    ])
    pred = make_post_filter(f, FIELD_TYPES)
    assert pred({"category": "合同", "amount": 100.0}) is True
    assert pred({"category": "发票", "amount": 100.0}) is False
    assert pred({"category": "合同", "amount": 10.0}) is False
    assert pred({"category": "合同"}) is False  # 缺字段不通过


def test_post_filter_contains_any_all():
    any_f = MetadataFilter(conditions=[
        MetadataCondition(key="tags", op=FilterOp.CONTAINS_ANY, value=["a", "z"])
    ])
    all_f = MetadataFilter(conditions=[
        MetadataCondition(key="tags", op=FilterOp.CONTAINS_ALL, value=["a", "b"])
    ])
    assert make_post_filter(any_f, FIELD_TYPES)({"tags": ["a"]}) is True
    assert make_post_filter(any_f, FIELD_TYPES)({"tags": ["x"]}) is False
    assert make_post_filter(all_f, FIELD_TYPES)({"tags": ["a", "b"]}) is True
    assert make_post_filter(all_f, FIELD_TYPES)({"tags": ["a"]}) is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_retrieval_filters.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.retrieval.filters'`）

- [ ] **Step 3: 实现**

创建 `app/retrieval/filters.py`：

```python
"""元数据过滤条件模型，及其到 Chroma where / post-filter 谓词的翻译。

同一 ``MetadataFilter`` 翻译两次：向量侧下推 ``to_chroma_where``；BM25 侧
``make_post_filter`` 读候选原始 ``doc_metadata`` 判定。``tags`` 在 Chroma 侧
布尔展开为 ``tag__<value>=True``（Chroma metadata 不支持 list）。
"""
from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel

from app.metadata.schema import FieldType


class FilterOp(StrEnum):
    """过滤操作符。"""

    EQ = "eq"
    IN = "in"
    GTE = "gte"
    LTE = "lte"
    CONTAINS_ANY = "contains_any"
    CONTAINS_ALL = "contains_all"


class MetadataCondition(BaseModel):
    """单个过滤条件。"""

    key: str
    op: FilterOp
    value: str | float | list[str]


class MetadataFilter(BaseModel):
    """多条件 AND 组合的过滤器。"""

    conditions: list[MetadataCondition]


class FilterFieldError(Exception):
    """过滤条件引用了未定义字段。"""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"过滤字段未定义: {key}")


def to_chroma_metadata(
    doc_metadata: dict, field_types: dict[str, FieldType]
) -> dict:
    """把归一化元数据转成 Chroma 标量 metadata（tags 布尔展开）。"""
    out: dict = {}
    for key, value in doc_metadata.items():
        ftype = field_types.get(key)
        if ftype == FieldType.TAGS and isinstance(value, list):
            for tag in value:
                out[f"tag__{tag}"] = True
        else:
            out[key] = value
    return out


def _tag_clauses(values: list[str]) -> list[dict]:
    return [{f"tag__{v}": True} for v in values]


def to_chroma_where(
    f: MetadataFilter, field_types: dict[str, FieldType]
) -> dict:
    """翻译成 Chroma where（不含 kb 隔离，调用方负责合并）。"""
    clauses: list[dict] = []
    for cond in f.conditions:
        if cond.key not in field_types:
            raise FilterFieldError(cond.key)
        if cond.op == FilterOp.EQ:
            clauses.append({cond.key: cond.value})
        elif cond.op == FilterOp.IN:
            clauses.append({cond.key: {"$in": cond.value}})
        elif cond.op == FilterOp.GTE:
            clauses.append({cond.key: {"$gte": cond.value}})
        elif cond.op == FilterOp.LTE:
            clauses.append({cond.key: {"$lte": cond.value}})
        elif cond.op == FilterOp.CONTAINS_ANY:
            clauses.append({"$or": _tag_clauses(cond.value)})
        elif cond.op == FilterOp.CONTAINS_ALL:
            clauses.extend(_tag_clauses(cond.value))
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _match(cond: MetadataCondition, meta: dict) -> bool:
    if cond.op in (FilterOp.CONTAINS_ANY, FilterOp.CONTAINS_ALL):
        have = set(meta.get(cond.key) or [])
        want = set(cond.value)
        if cond.op == FilterOp.CONTAINS_ANY:
            return bool(have & want)
        return want <= have
    if cond.key not in meta:
        return False
    actual = meta[cond.key]
    if cond.op == FilterOp.EQ:
        return actual == cond.value
    if cond.op == FilterOp.IN:
        return actual in cond.value
    if cond.op == FilterOp.GTE:
        return actual >= cond.value
    if cond.op == FilterOp.LTE:
        return actual <= cond.value
    return False


def make_post_filter(
    f: MetadataFilter, field_types: dict[str, FieldType]
) -> Callable[[dict], bool]:
    """构造 BM25 侧 post-filter 谓词，读候选原始 doc_metadata 判定。"""
    for cond in f.conditions:
        if cond.key not in field_types:
            raise FilterFieldError(cond.key)

    def predicate(meta: dict) -> bool:
        meta = meta or {}
        return all(_match(cond, meta) for cond in f.conditions)

    return predicate
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && pytest tests/test_retrieval_filters.py -v`
Expected: PASS（10 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/retrieval/filters.py apps/luna-corpus/tests/test_retrieval_filters.py
git commit -m "feat(corpus): add metadata filter model and chroma/post-filter translation"
```

---

### Task 6: 分面聚合（facets.py）

**Files:**
- Create: `apps/luna-corpus/app/metadata/facets.py`
- Test: `apps/luna-corpus/tests/test_metadata_facets.py`

**Interfaces:**
- Consumes: `MetadataFieldDefinition`（Task 3）、`FieldType`（Task 2）、`Document`、`ContentStatus`、`Session`
- Produces:
  - `compute_facets(db: Session, kb_id: str) -> list[dict]`：对 `is_facetable=True` 字段聚合 `status=COMPLETED` 文档的 `doc_metadata`，返回 `[{"key","label","field_type","buckets":[{"value","count"},...]}, ...]`

分桶规则：`enum` 按值计数降序；`string` 按值计数降序取 Top-20；`tags` 每标签一桶降序；`date` 取 `YYYY-MM`（前 7 字符）计数降序；`number` 等宽 5 桶，桶 `value` 形如 `"0.00-100.00"`，按区间下界升序，min==max 时单桶。所有类型：跳过缺该字段/空值的文档。为简单起见全部在 Python 内存聚合（低频端点）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_metadata_facets.py`：

```python
"""全库分面聚合测试（内存 SQLite + 真实 ORM）。"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    ContentStatus,
    Document,
    KnowledgeBase,
    Tenant,
    Workspace,
)
from app.metadata.facets import compute_facets
from app.metadata.models import MetadataFieldDefinition


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="T", slug="t")
    session.add(tenant)
    session.flush()
    ws = Workspace(tenant_id=tenant.id, name="W", slug="w")
    session.add(ws)
    session.flush()
    kb = KnowledgeBase(workspace_id=ws.id, name="KB", slug="kb")
    session.add(kb)
    session.flush()
    session.kb_id = kb.id
    yield session
    session.close()


def _field(db, **kw):
    db.add(MetadataFieldDefinition(knowledge_base_id=db.kb_id, **kw))
    db.flush()


def _doc(db, meta, status=ContentStatus.COMPLETED):
    db.add(Document(
        knowledge_base_id=db.kb_id, title="t", content="c",
        status=status, doc_metadata=meta,
    ))
    db.flush()


def _facet(facets, key):
    return next(f for f in facets if f["key"] == key)


def test_enum_facet_counts(db):
    _field(db, key="category", label="类别", field_type="enum")
    _doc(db, {"category": "合同"})
    _doc(db, {"category": "合同"})
    _doc(db, {"category": "发票"})
    facets = compute_facets(db, db.kb_id)
    buckets = _facet(facets, "category")["buckets"]
    assert buckets[0] == {"value": "合同", "count": 2}
    assert {"value": "发票", "count": 1} in buckets


def test_only_completed_documents_counted(db):
    _field(db, key="category", label="类别", field_type="enum")
    _doc(db, {"category": "合同"})
    _doc(db, {"category": "合同"}, status=ContentStatus.PENDING)
    buckets = _facet(compute_facets(db, db.kb_id), "category")["buckets"]
    assert buckets == [{"value": "合同", "count": 1}]


def test_is_facetable_false_excluded(db):
    _field(db, key="secret", label="隐藏", field_type="string",
           is_facetable=False)
    _doc(db, {"secret": "x"})
    assert all(f["key"] != "secret" for f in compute_facets(db, db.kb_id))


def test_tags_facet_multi_count(db):
    _field(db, key="tags", label="标签", field_type="tags")
    _doc(db, {"tags": ["a", "b"]})
    _doc(db, {"tags": ["a"]})
    buckets = _facet(compute_facets(db, db.kb_id), "tags")["buckets"]
    assert buckets[0] == {"value": "a", "count": 2}
    assert {"value": "b", "count": 1} in buckets


def test_date_bucketed_by_month(db):
    _field(db, key="d", label="日期", field_type="date")
    _doc(db, {"d": "2025-03-01"})
    _doc(db, {"d": "2025-03-20"})
    _doc(db, {"d": "2025-02-10"})
    buckets = _facet(compute_facets(db, db.kb_id), "d")["buckets"]
    assert {"value": "2025-03", "count": 2} in buckets
    assert {"value": "2025-02", "count": 1} in buckets


def test_number_equal_width_buckets(db):
    _field(db, key="amount", label="金额", field_type="number")
    for v in [0.0, 50.0, 100.0]:
        _doc(db, {"amount": v})
    buckets = _facet(compute_facets(db, db.kb_id), "amount")["buckets"]
    assert sum(b["count"] for b in buckets) == 3
    assert len(buckets) <= 5


def test_string_top_20(db):
    _field(db, key="author", label="作者", field_type="string")
    for i in range(25):
        _doc(db, {"author": f"a{i}"})
    buckets = _facet(compute_facets(db, db.kb_id), "author")["buckets"]
    assert len(buckets) == 20
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_metadata_facets.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.metadata.facets'`）

- [ ] **Step 3: 实现**

创建 `app/metadata/facets.py`：

```python
"""全库分面聚合：按知识库统计各维度取值的文档命中数。"""
from collections import Counter

from sqlalchemy.orm import Session

from app.db.models import ContentStatus, Document
from app.metadata.models import MetadataFieldDefinition
from app.metadata.schema import FieldType

_STRING_TOP_N = 20
_NUMBER_BUCKETS = 5


def _sorted_buckets(counter: Counter) -> list[dict]:
    """按 count 降序（次序稳定：count 相同按 value 升序）。"""
    items = sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return [{"value": v, "count": c} for v, c in items]


def _number_buckets(values: list[float]) -> list[dict]:
    lo, hi = min(values), max(values)
    if lo == hi:
        return [{"value": f"{lo:.2f}-{hi:.2f}", "count": len(values)}]
    width = (hi - lo) / _NUMBER_BUCKETS
    counter: Counter = Counter()
    labels: list[str] = []
    for i in range(_NUMBER_BUCKETS):
        b_lo = lo + i * width
        b_hi = lo + (i + 1) * width
        labels.append(f"{b_lo:.2f}-{b_hi:.2f}")
    for v in values:
        idx = min(int((v - lo) / width), _NUMBER_BUCKETS - 1)
        counter[labels[idx]] += 1
    return [
        {"value": label, "count": counter[label]}
        for label in labels
        if counter[label] > 0
    ]


def _buckets_for_field(
    field: MetadataFieldDefinition, values: list
) -> list[dict]:
    if field.field_type == FieldType.TAGS:
        counter: Counter = Counter()
        for v in values:
            for tag in v or []:
                counter[tag] += 1
        return _sorted_buckets(counter)
    if field.field_type == FieldType.DATE:
        return _sorted_buckets(Counter(str(v)[:7] for v in values))
    if field.field_type == FieldType.NUMBER:
        nums = [float(v) for v in values]
        return _number_buckets(nums) if nums else []
    buckets = _sorted_buckets(Counter(values))
    if field.field_type == FieldType.STRING:
        return buckets[:_STRING_TOP_N]
    return buckets


def compute_facets(db: Session, kb_id: str) -> list[dict]:
    """对可分面字段聚合 COMPLETED 文档的 doc_metadata。"""
    fields = (
        db.query(MetadataFieldDefinition)
        .filter(
            MetadataFieldDefinition.knowledge_base_id == kb_id,
            MetadataFieldDefinition.is_facetable.is_(True),
        )
        .all()
    )
    rows = (
        db.query(Document.doc_metadata)
        .filter(
            Document.knowledge_base_id == kb_id,
            Document.status == ContentStatus.COMPLETED,
        )
        .all()
    )
    metadatas = [r[0] or {} for r in rows]

    facets: list[dict] = []
    for field in fields:
        values = [m[field.key] for m in metadatas if field.key in m]
        facets.append({
            "key": field.key,
            "label": field.label,
            "field_type": field.field_type.value,
            "buckets": _buckets_for_field(field, values),
        })
    return facets
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && pytest tests/test_metadata_facets.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/metadata/facets.py apps/luna-corpus/tests/test_metadata_facets.py
git commit -m "feat(corpus): add full-corpus facet aggregation"
```

---

### Task 7: 向量库支持元数据写入与额外 where 过滤

**Files:**
- Modify: `apps/luna-corpus/app/db/vectorstore.py`
- Test: `apps/luna-corpus/tests/test_vectorstore_metadata.py`

**Interfaces:**
- Consumes: 现有 `VectorChunkInput`、`BaseChromaBackend`
- Produces（改动后签名）：
  - `VectorChunkInput` 增字段 `metadata: dict | None = None`（已归一化 → Chroma 标量的 dict，即 `to_chroma_metadata` 输出）
  - `BaseChromaBackend.search(query_embedding, *, top_k, knowledge_base_id, where=None)`：`where` 为额外过滤子句，与 kb 隔离合并
  - `add_chunks_to_vectorstore` 的 chunk dict 支持可选 `"metadata"` 键
  - `search_vectorstore(query_embedding, top_k=None, knowledge_base_id=None, where=None)`

Chroma 合并规则：无额外 where → `{"knowledge_base_id": kb}`；有额外 where → `{"$and": [{"knowledge_base_id": kb}, where]}`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_vectorstore_metadata.py`：

```python
"""向量库元数据写入与 where 合并测试（mock Chroma collection）。"""
from unittest.mock import MagicMock

from app.db.vectorstore import BaseChromaBackend, VectorChunkInput
from app.core.config import get_settings


def _backend_with_mock_collection():
    backend = BaseChromaBackend(get_settings())
    collection = MagicMock()
    backend._collection = collection
    return backend, collection


def test_add_chunks_writes_metadata():
    backend, collection = _backend_with_mock_collection()
    backend.add_chunks(
        [VectorChunkInput(
            id="c1", document_id="d1", knowledge_base_id="kb1",
            content="hello", metadata={"category": "合同", "tag__a": True},
        )],
        [[0.1, 0.2]],
    )
    _, kwargs = collection.add.call_args
    md = kwargs["metadatas"][0]
    assert md["knowledge_base_id"] == "kb1"
    assert md["category"] == "合同"
    assert md["tag__a"] is True


def test_search_without_where_uses_kb_isolation_only():
    backend, collection = _backend_with_mock_collection()
    collection.query.return_value = {"ids": [[]]}
    backend.search([0.1], top_k=5, knowledge_base_id="kb1")
    _, kwargs = collection.query.call_args
    assert kwargs["where"] == {"knowledge_base_id": "kb1"}


def test_search_with_where_merges_and():
    backend, collection = _backend_with_mock_collection()
    collection.query.return_value = {"ids": [[]]}
    backend.search(
        [0.1], top_k=5, knowledge_base_id="kb1",
        where={"category": "合同"},
    )
    _, kwargs = collection.query.call_args
    assert kwargs["where"] == {
        "$and": [{"knowledge_base_id": "kb1"}, {"category": "合同"}]
    }
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_vectorstore_metadata.py -v`
Expected: FAIL（`VectorChunkInput` 无 `metadata` 参数 / `search` 无 `where` 参数）

- [ ] **Step 3: 实现**

在 `app/db/vectorstore.py`：

1) `VectorChunkInput` dataclass 增字段（放在 `content` 之后）：

```python
    metadata: dict | None = None
```

2) `BaseChromaBackend.add_chunks` 的 metadatas 构造改为合并业务元数据：

```python
        collection.add(
            ids=[chunk.id for chunk in chunks],
            documents=[chunk.content for chunk in chunks],
            embeddings=embeddings,
            metadatas=[
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "knowledge_base_id": chunk.knowledge_base_id,
                    **(chunk.metadata or {}),
                }
                for chunk in chunks
            ],
        )
```

3) `BaseChromaBackend.search` 增 `where` 参数并合并：

```python
    def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int,
        knowledge_base_id: str,
        where: dict | None = None,
    ) -> list[VectorSearchResult]:
        _validate_knowledge_base_id(knowledge_base_id)
        collection = self.get_collection()
        kb_clause = {"knowledge_base_id": knowledge_base_id}
        merged = kb_clause if not where else {"$and": [kb_clause, where]}
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=merged,
        )
        return _parse_query_results(results)
```

4) 同步更新 `VectorStoreBackend` Protocol 的 `search` 签名加上 `where: dict | None = None`。

5) `add_chunks_to_vectorstore` 支持可选 `metadata`：

```python
    normalized = [
        VectorChunkInput(
            id=chunk["id"],
            document_id=chunk["document_id"],
            knowledge_base_id=chunk["knowledge_base_id"],
            content=chunk["content"],
            metadata=chunk.get("metadata"),
        )
        for chunk in chunks
    ]
```

6) `search_vectorstore` 增 `where` 参数并透传：

```python
def search_vectorstore(
    query_embedding: list[float],
    top_k: int | None = None,
    knowledge_base_id: str | None = None,
    where: dict | None = None,
) -> list[dict[str, Any]]:
    if top_k is None:
        top_k = settings.retrieval_top_k
    _validate_knowledge_base_id(knowledge_base_id)
    results = get_vectorstore_backend().search(
        query_embedding,
        top_k=top_k,
        knowledge_base_id=knowledge_base_id,
        where=where,
    )
    return [
        {
            "chunk_id": result.chunk_id,
            "document_id": result.document_id,
            "content": result.content,
            "score": result.score,
        }
        for result in results
    ]
```

- [ ] **Step 4: 运行测试确认通过 + 回归**

Run: `cd apps/luna-corpus && pytest tests/test_vectorstore_metadata.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/db/vectorstore.py apps/luna-corpus/tests/test_vectorstore_metadata.py
git commit -m "feat(corpus): vectorstore metadata write and where filter support"
```

---

### Task 8: `hybrid_search` 接入 filters（向量下推 + BM25 post-filter）

**Files:**
- Modify: `apps/luna-corpus/app/retrieval/hybrid.py`
- Test: `apps/luna-corpus/tests/test_hybrid_filters.py`

**Interfaces:**
- Consumes: `MetadataFilter`/`to_chroma_where`/`make_post_filter`（Task 5）、`search_vectorstore(where=...)`（Task 7）、`settings.filter_over_fetch_multiplier`（Task 1）
- Produces（改动后签名）：
  - `hybrid_search(query, query_embedding, *, top_k, knowledge_base_id, filters=None, field_types=None)`
    - `filters: MetadataFilter | None`；`field_types: dict[str, FieldType] | None`（filters 非空时必传）
  - 新增内部辅助 `_load_chunk_metadata(chunk_ids: list[str]) -> dict[str, dict]`：批量查 `Chunk.chunk_metadata`（供 BM25 post-filter）

行为：
- `filters` 为 None → 与现状完全一致（不改调用形状）。
- `filters` 非空：向量侧算 `where = to_chroma_where(filters, field_types)` 传 `search_vectorstore`；候选窗口 `candidate_k *= settings.filter_over_fetch_multiplier`；BM25 召回后用 `make_post_filter` 谓词（读 `_load_chunk_metadata` 补的元数据）过滤；融合后截断到 `top_k`。
- `to_chroma_where` 或 BM25 侧构造抛异常 → 记 `filter_degraded_no_op` 日志并退回无过滤路径（检索不因过滤崩）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_hybrid_filters.py`：

```python
"""hybrid_search filters 接入测试（mock 各检索源）。"""
from unittest.mock import patch

import pytest

from app.core.config import RetrievalMode
from app.metadata.schema import FieldType
from app.retrieval import hybrid
from app.retrieval.filters import FilterOp, MetadataCondition, MetadataFilter


@pytest.fixture(autouse=True)
def _hybrid_mode(monkeypatch):
    monkeypatch.setattr(hybrid.settings, "retrieval_mode", RetrievalMode.HYBRID)
    monkeypatch.setattr(hybrid.settings, "retrieval_candidate_k", 10)
    monkeypatch.setattr(hybrid.settings, "filter_over_fetch_multiplier", 3)


def test_no_filters_matches_current_behavior():
    vec = [{"chunk_id": "a", "document_id": "d", "content": "x", "score": 1.0}]
    with patch.object(hybrid, "search_vectorstore", return_value=vec) as sv, \
         patch.object(hybrid, "_bm25_results", return_value=[]):
        out = hybrid.hybrid_search("q", [0.1], top_k=5, knowledge_base_id="kb")
    # 无 filters 时向量侧不传 where
    _, kwargs = sv.call_args
    assert kwargs.get("where") is None
    assert out and out[0]["chunk_id"] == "a"


def test_filters_pushdown_where_to_vector():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.EQ, value="合同")
    ])
    ft = {"category": FieldType.ENUM}
    with patch.object(hybrid, "search_vectorstore", return_value=[]) as sv, \
         patch.object(hybrid, "_bm25_results", return_value=[]):
        hybrid.hybrid_search(
            "q", [0.1], top_k=5, knowledge_base_id="kb",
            filters=f, field_types=ft,
        )
    _, kwargs = sv.call_args
    assert kwargs["where"] == {"category": "合同"}
    # over-fetch 放大候选窗口
    assert kwargs["top_k"] == 10 * 3


def test_bm25_post_filter_drops_non_matching():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.EQ, value="合同")
    ])
    ft = {"category": FieldType.ENUM}
    bm = [
        {"chunk_id": "a", "document_id": "d1", "content": "x", "score": 1.0},
        {"chunk_id": "b", "document_id": "d2", "content": "y", "score": 0.9},
    ]
    meta = {"a": {"category": "合同"}, "b": {"category": "发票"}}
    with patch.object(hybrid, "search_vectorstore", return_value=[]), \
         patch.object(hybrid, "_bm25_results", return_value=bm), \
         patch.object(hybrid, "_load_chunk_metadata", return_value=meta):
        out = hybrid.hybrid_search(
            "q", [0.1], top_k=5, knowledge_base_id="kb",
            filters=f, field_types=ft,
        )
    ids = {r["chunk_id"] for r in out}
    assert "a" in ids and "b" not in ids


def test_where_build_error_degrades_to_no_filter():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="ghost", op=FilterOp.EQ, value="x")
    ])
    ft = {"category": FieldType.ENUM}  # ghost 未定义 -> FilterFieldError
    vec = [{"chunk_id": "a", "document_id": "d", "content": "x", "score": 1.0}]
    with patch.object(hybrid, "search_vectorstore", return_value=vec) as sv, \
         patch.object(hybrid, "_bm25_results", return_value=[]):
        out = hybrid.hybrid_search(
            "q", [0.1], top_k=5, knowledge_base_id="kb",
            filters=f, field_types=ft,
        )
    _, kwargs = sv.call_args
    assert kwargs.get("where") is None  # 降级为无过滤
    assert out and out[0]["chunk_id"] == "a"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_hybrid_filters.py -v`
Expected: FAIL（`hybrid_search` 不接受 `filters` / 无 `_load_chunk_metadata`）

- [ ] **Step 3: 实现**

改写 `app/retrieval/hybrid.py`。顶部 import 增加：

```python
from app.db.database import SessionLocal
from app.db.models import Chunk
from app.metadata.schema import FieldType
from app.retrieval.filters import (
    FilterFieldError,
    MetadataFilter,
    make_post_filter,
    to_chroma_where,
)
```

新增辅助函数：

```python
def _load_chunk_metadata(chunk_ids: list[str]) -> dict[str, dict]:
    """批量读取 chunk 原始归一化元数据，供 BM25 post-filter。"""
    if not chunk_ids:
        return {}
    db = SessionLocal()
    try:
        rows = (
            db.query(Chunk.id, Chunk.chunk_metadata)
            .filter(Chunk.id.in_(chunk_ids))
            .all()
        )
        return {r[0]: (r[1] or {}) for r in rows}
    finally:
        db.close()
```

改写 `hybrid_search` 签名与主体（保留原 mode 分派逻辑，插入过滤）：

```python
def hybrid_search(
    query: str,
    query_embedding: list[float],
    *,
    top_k: int,
    knowledge_base_id: str,
    filters: MetadataFilter | None = None,
    field_types: dict[str, FieldType] | None = None,
) -> list[dict[str, Any]]:
    """检索 chunks，按 ``settings.retrieval_mode`` 分派，可选元数据过滤。

    ``filters`` 为空时行为与无过滤时完全一致。非空时向量侧下推 Chroma where、
    BM25 侧 post-filter，并按 ``filter_over_fetch_multiplier`` 放大候选窗口。
    过滤构造失败降级为无过滤（检索不因过滤崩）。
    """
    mode = settings.retrieval_mode
    is_fused = mode in (RetrievalMode.HYBRID, RetrievalMode.RERANK)

    where = None
    post_filter = None
    over_fetch = 1
    if filters is not None and filters.conditions:
        try:
            where = to_chroma_where(filters, field_types or {})
            post_filter = make_post_filter(filters, field_types or {})
            over_fetch = settings.filter_over_fetch_multiplier
            logger.info(
                "filter_applied",
                knowledge_base_id=knowledge_base_id,
                num_conditions=len(filters.conditions),
            )
        except (FilterFieldError, Exception):
            logger.warning(
                "filter_degraded_no_op",
                knowledge_base_id=knowledge_base_id,
                exc_info=True,
            )
            where = None
            post_filter = None
            over_fetch = 1

    base_candidate_k = (
        settings.rerank_candidate_k
        if mode == RetrievalMode.RERANK
        else settings.retrieval_candidate_k
    )
    candidate_k = base_candidate_k * over_fetch
    fuse_top_k = candidate_k if mode == RetrievalMode.RERANK else top_k

    with time_stage(RAG_RETRIEVAL_DURATION):
        vector_results = search_vectorstore(
            query_embedding=query_embedding,
            top_k=candidate_k if is_fused else (top_k * over_fetch),
            knowledge_base_id=knowledge_base_id,
            where=where,
        )

        if not is_fused:
            if post_filter is None:
                return vector_results
            filtered = _apply_post_filter(vector_results, post_filter)
            return filtered[:top_k]

        try:
            keyword_results = _bm25_results(query, knowledge_base_id, candidate_k)
        except Exception:  # BM25 must never break Q&A — degrade to vector-only.
            logger.warning(
                "bm25_search_failed_degrading_to_vector",
                knowledge_base_id=knowledge_base_id,
                exc_info=True,
            )
            base = vector_results
            if post_filter is not None:
                base = _apply_post_filter(base, post_filter)
            return base[:top_k]

        if post_filter is not None:
            keyword_results = _apply_post_filter(keyword_results, post_filter)

        fused = reciprocal_rank_fusion(
            [vector_results, keyword_results],
            k=settings.rrf_k,
            top_k=fuse_top_k,
        )

        if mode == RetrievalMode.RERANK:
            return rerank_results(
                query, fused, top_k=top_k, knowledge_base_id=knowledge_base_id
            )
        return fused[:top_k]
```

新增 post-filter 应用辅助（向量结果需补元数据，BM25 结果同样按 chunk_id 补）：

```python
def _apply_post_filter(
    results: list[dict[str, Any]], predicate
) -> list[dict[str, Any]]:
    """按 chunk_id 补元数据后应用 post-filter 谓词。"""
    chunk_ids = [r["chunk_id"] for r in results if r.get("chunk_id")]
    meta_by_id = _load_chunk_metadata(chunk_ids)
    return [r for r in results if predicate(meta_by_id.get(r.get("chunk_id"), {}))]
```

> 说明：向量侧已经下推 where，理论上向量结果已满足过滤；但 `_apply_post_filter` 对向量结果再跑一遍谓词是幂等的安全网，且统一了「非融合模式」的过滤路径。

- [ ] **Step 4: 运行测试确认通过 + 回归**

Run: `cd apps/luna-corpus && pytest tests/test_hybrid_filters.py -v && pytest tests/ -k "hybrid or retrieval or bm25 or fusion or rerank" -q`
Expected: 新测试 PASS（4 passed）；已有检索相关测试全绿（零回归）。

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/retrieval/hybrid.py apps/luna-corpus/tests/test_hybrid_filters.py
git commit -m "feat(corpus): route metadata filters through hybrid_search"
```

---

### Task 9: 文档处理时把 doc_metadata 传播到向量库

**Files:**
- Modify: `apps/luna-corpus/app/services/document_processor.py`
- Test: `apps/luna-corpus/tests/test_document_processor_metadata.py`

**Interfaces:**
- Consumes: `Document.doc_metadata`（Task 3）、`to_chroma_metadata`（Task 5）、`load_field_definitions`（Task 4）、`add_chunks_to_vectorstore`（metadata 支持，Task 7）
- Produces: 处理时 chunk 的 `chunk_metadata` 存归一化 `doc_metadata`；写向量库的 chunk dict 带 `to_chroma_metadata` 输出

- [ ] **Step 1: 写失败测试**

创建 `tests/test_document_processor_metadata.py`：

```python
"""文档处理把 doc_metadata 传播到 chunk 与向量库的测试。"""
from unittest.mock import MagicMock, patch

from app.metadata.schema import FieldType
from app.services.document_processor import DocumentProcessor


def test_chunk_metadata_and_vector_metadata_propagated():
    proc = DocumentProcessor(chunk_size=1000, chunk_overlap=0)
    document = MagicMock()
    document.id = "doc1"
    document.knowledge_base_id = "kb1"
    document.content = "一段内容。"
    document.doc_metadata = {"category": "合同", "tags": ["a"]}
    document.status = None

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = document
    db.query.return_value.filter.return_value.all.return_value = []

    field_types = {"category": FieldType.ENUM, "tags": FieldType.TAGS}

    with patch(
        "app.services.document_processor.embed_texts", return_value=[[0.1]]
    ), patch(
        "app.services.document_processor.add_chunks_to_vectorstore"
    ) as add_mock, patch(
        "app.services.document_processor.invalidate_bm25_cache"
    ), patch(
        "app.services.document_processor._field_types_for_kb",
        return_value=field_types,
    ):
        proc.process_document(db, "doc1")

    chunks_arg = add_mock.call_args.kwargs["chunks"]
    md = chunks_arg[0]["metadata"]
    assert md["category"] == "合同"
    assert md["tag__a"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_document_processor_metadata.py -v`
Expected: FAIL（向量 chunk dict 无 `metadata` 键 / 无 `_field_types_for_kb`）

- [ ] **Step 3: 实现**

在 `app/services/document_processor.py` 顶部 import 增加：

```python
from app.metadata.schema import FieldType
from app.metadata.validation import load_field_definitions
from app.retrieval.filters import to_chroma_metadata
```

新增模块级辅助：

```python
def _field_types_for_kb(db: Session, kb_id: str) -> dict[str, FieldType]:
    """构造知识库的 字段key -> 类型 映射。"""
    return {f.key: f.field_type for f in load_field_definitions(db, kb_id)}
```

在 `split_document` 里把 `doc_metadata` 写进每个 chunk 的 `chunk_metadata`（替换原来的 `"chunk_metadata": None`）。改 `split_document` 签名接收归一化元数据：

```python
    def split_document(
        self, document: Document, doc_metadata: dict | None = None
    ) -> list[dict[str, Any]]:
        langchain_doc = LCDocument(
            page_content=document.content,
            metadata={"document_id": document.id},
        )
        splits = self.text_splitter.split_documents([langchain_doc])
        chunks = []
        for i, split in enumerate(splits):
            chunks.append({
                "document_id": document.id,
                "content": split.page_content,
                "content_type": self.detect_content_type(split.page_content),
                "chunk_metadata": doc_metadata or None,
                "chunk_index": i,
            })
        return chunks
```

在 `process_document` 内：读取 `doc_metadata` 与 `field_types`，传入 `split_document`，并给写向量库的 chunk dict 加 `metadata`：

```python
            doc_metadata = document.doc_metadata or {}
            field_types = _field_types_for_kb(db, document.knowledge_base_id)
            chroma_metadata = to_chroma_metadata(doc_metadata, field_types)

            # Split into chunks
            chunk_dicts = self.split_document(document, doc_metadata)
```

以及 `add_chunks_to_vectorstore` 的 chunks 构造加 `"metadata": chroma_metadata`：

```python
            add_chunks_to_vectorstore(
                chunks=[
                    {
                        "id": c.id,
                        "document_id": c.document_id,
                        "knowledge_base_id": document.knowledge_base_id,
                        "content": c.content,
                        "metadata": chroma_metadata,
                    }
                    for c in chunks
                ],
                embeddings=embeddings,
            )
```

（文件顶部若尚未 import `Session`，从 `sqlalchemy.orm` 导入——现有文件已 `from sqlalchemy.orm import Session`，无需重复。）

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && pytest tests/test_document_processor_metadata.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/services/document_processor.py apps/luna-corpus/tests/test_document_processor_metadata.py
git commit -m "feat(corpus): propagate doc_metadata to chunks and vector store"
```

---

### Task 10: 摄取服务校验上传元数据

**Files:**
- Modify: `apps/luna-corpus/app/services/ingestion/service.py`
- Modify: `apps/luna-corpus/app/services/ingestion/exceptions.py`
- Test: `apps/luna-corpus/tests/test_ingestion_metadata.py`

**Interfaces:**
- Consumes: `validate_and_normalize`（Task 4）、`MetadataValidationError`（Task 4）
- Produces（改动后签名）：
  - `IngestionService.ingest_file(db, file, knowledge_base_id, metadata=None)`：`metadata: dict | None`
  - 校验在存 `Document` 前进行；失败抛 `MetadataValidationError`（由 API 层转 422）；成功把归一化值写入 `Document.doc_metadata`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_ingestion_metadata.py`：

```python
"""摄取服务元数据校验测试。"""
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from app.metadata.validation import MetadataValidationError
from app.services.ingestion.service import IngestionService


def _service():
    storage = MagicMock()
    storage.save = AsyncMock()
    storage.delete = AsyncMock()
    registry = MagicMock()
    registry.is_supported.return_value = True
    parser = MagicMock()
    parser.parse.return_value = "parsed text"
    registry.get_parser.return_value = parser
    return IngestionService(storage=storage, parser_registry=registry)


def _upload():
    f = UploadFile(filename="a.txt", file=io.BytesIO(b"hello"))
    f._content_type = "text/plain"
    return f


@pytest.mark.asyncio
async def test_invalid_metadata_rejects_before_persist():
    service = _service()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    with patch(
        "app.services.ingestion.service.validate_and_normalize",
        side_effect=MetadataValidationError(["坏字段"]),
    ):
        with pytest.raises(MetadataValidationError):
            await service.ingest_file(
                db, _upload(), "kb1", metadata={"x": "y"}
            )
    # 校验失败：未提交文件记录
    db.add.assert_not_called()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_ingestion_metadata.py -v`
Expected: FAIL（`ingest_file` 不接受 `metadata` 参数）

- [ ] **Step 3: 实现**

在 `app/services/ingestion/service.py` 顶部 import：

```python
from app.metadata.validation import validate_and_normalize
```

`ingest_file` 增 `metadata` 参数，并在**任何 DB 写入 / 存储之前**校验（放在 MIME 校验之后、读 content 之前即可，但必须在 `db.add(upload)` 之前）：

```python
    async def ingest_file(
        self,
        db: Session,
        file: UploadFile,
        knowledge_base_id: str,
        metadata: dict | None = None,
    ) -> tuple[FileUpload, Document | None]:
        ...
        # MIME 校验之后、任何持久化之前：校验元数据（失败则整个上传失败）
        normalized_metadata = validate_and_normalize(
            db, knowledge_base_id, metadata
        )
```

在创建 `Document` 时写入：

```python
            document = Document(
                knowledge_base_id=knowledge_base_id,
                file_id=upload.id,
                title=filename or "Untitled",
                content=parsed_text,
                source=f"file://{filename}",
                has_tables="|" in parsed_text and "---" in parsed_text,
                has_code="```" in parsed_text or "def " in parsed_text,
                status=ContentStatus.PENDING,
                doc_metadata=normalized_metadata or None,
            )
```

> `MetadataValidationError` 在校验步骤抛出时，尚未 `db.add`、未写存储，天然满足「不产生半成品」。无需额外回滚代码。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && pytest tests/test_ingestion_metadata.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/services/ingestion/service.py apps/luna-corpus/tests/test_ingestion_metadata.py
git commit -m "feat(corpus): validate upload metadata in ingestion service"
```

---

### Task 11: 新增分面耗时指标

**Files:**
- Modify: `apps/luna-corpus/app/observability/metrics.py`
- Test: `apps/luna-corpus/tests/test_metrics_facet.py`

**Interfaces:**
- Produces: `RAG_FACET_DURATION`（Histogram，metric 名 `rag_facet_duration_seconds`）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_metrics_facet.py`：

```python
"""分面耗时指标存在性测试。"""
from app.observability import metrics


def test_facet_duration_metric_defined():
    assert hasattr(metrics, "RAG_FACET_DURATION")
    payload, _ = metrics.render_metrics()
    with metrics.time_stage(metrics.RAG_FACET_DURATION):
        pass
    payload2, _ = metrics.render_metrics()
    assert b"rag_facet_duration_seconds" in payload2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_metrics_facet.py -v`
Expected: FAIL（`module has no attribute 'RAG_FACET_DURATION'`）

- [ ] **Step 3: 实现**

在 `app/observability/metrics.py` 的 `RAG_RERANK_DURATION` 之后新增：

```python
RAG_FACET_DURATION = Histogram(
    "rag_facet_duration_seconds",
    "Facet aggregation latency in seconds.",
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && pytest tests/test_metrics_facet.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/observability/metrics.py apps/luna-corpus/tests/test_metrics_facet.py
git commit -m "feat(corpus): add rag_facet_duration_seconds metric"
```

---

### Task 12: 元数据 Schema 管理与分面 API 路由

**Files:**
- Create: `apps/luna-corpus/app/api/metadata_routes.py`
- Modify: `apps/luna-corpus/app/main.py`（挂载 router）
- Test: `apps/luna-corpus/tests/test_metadata_api.py`

**Interfaces:**
- Consumes: `FieldDefinitionCreate`/`FieldDefinitionUpdate`/`FieldDefinitionRead`（Task 2）、`MetadataFieldDefinition`（Task 3）、`compute_facets`（Task 6）、`RAG_FACET_DURATION`（Task 11）、`require_permission`/`AuthenticatedRequestContext`、`PermissionSlug`、`get_db`
- Produces: `router = APIRouter(prefix="/api/v1", tags=["metadata"])` 挂到 app，端点：
  - `POST /knowledge-bases/{kb_id}/metadata-fields` → `knowledge_base:manage`；`key` 重复返回 409
  - `GET /knowledge-bases/{kb_id}/metadata-fields` → `knowledge_base:read`
  - `PATCH /metadata-fields/{field_id}` → `knowledge_base:manage`
  - `DELETE /metadata-fields/{field_id}` → `knowledge_base:manage`，204
  - `GET /knowledge-bases/{kb_id}/facets` → `knowledge_base:read`

> RBAC 依赖用现有 `require_permission(...)`。`kb_id` 路径参数用于定位字段；`context.knowledge_base.id` 用于隔离校验（路径 kb 必须等于 header 解析出的 kb，否则 404），与既有路由风格一致。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_metadata_api.py`。用现有集成测试风格（`app.main.app` + `TestClient`），依赖 RBAC 头。参考 `tests/test_integration.py` 与既有需要鉴权的路由测试构造 fixture；此处给出核心断言，fixture 复用 `conftest`/现有测试里已建的 tenant/workspace/kb/user/role 装配（若不存在，按 `test_integration.py` 的 mock 方式补一个最小 DB 装配 helper 到本测试文件）：

```python
"""元数据 Schema 与分面 API 集成测试。"""
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers_rbac import seed_kb_admin_headers  # 见 Step 3 说明


def test_create_and_list_metadata_field(db_session):
    client = TestClient(app)
    headers = seed_kb_admin_headers(db_session)
    kb_id = headers["X-Knowledge-Base-Id"]

    resp = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/metadata-fields",
        json={"key": "category", "label": "类别", "field_type": "enum",
              "options": ["合同", "发票"]},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["key"] == "category"

    # 重复 key -> 409
    dup = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/metadata-fields",
        json={"key": "category", "label": "重复", "field_type": "string"},
        headers=headers,
    )
    assert dup.status_code == 409

    listed = client.get(
        f"/api/v1/knowledge-bases/{kb_id}/metadata-fields", headers=headers
    )
    assert listed.status_code == 200
    assert any(f["key"] == "category" for f in listed.json())


def test_facets_endpoint(db_session):
    client = TestClient(app)
    headers = seed_kb_admin_headers(db_session)
    kb_id = headers["X-Knowledge-Base-Id"]
    client.post(
        f"/api/v1/knowledge-bases/{kb_id}/metadata-fields",
        json={"key": "category", "label": "类别", "field_type": "enum"},
        headers=headers,
    )
    resp = client.get(
        f"/api/v1/knowledge-bases/{kb_id}/facets", headers=headers
    )
    assert resp.status_code == 200
    assert "facets" in resp.json()
```

> **Step 3 说明**：若仓库已有 RBAC 集成测试的 fixture/helper（搜索 `require_permission` 相关测试或 `conftest` 中的 DB 装配），直接复用其头部装配，不要新造。若没有，创建 `tests/helpers_rbac.py`，用内存/测试 DB 建 tenant→workspace→kb→user→membership→role(带 `knowledge_base:manage`+`knowledge_base:read`+`document:write`+`qa:query`) 并返回 `{"X-User-Id","X-Tenant-Id","X-Workspace-Id","X-Knowledge-Base-Id"}` 头。`db_session` fixture 同样复用现有测试 DB 依赖覆盖方式（`app.dependency_overrides[get_db]`）。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_metadata_api.py -v`
Expected: FAIL（路由不存在 → 404 / import 错误）

- [ ] **Step 3: 实现**

创建 `app/api/metadata_routes.py`：

```python
"""元数据 Schema 管理与分面聚合 API。"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
from app.db.database import get_db
from app.metadata.facets import compute_facets
from app.metadata.models import MetadataFieldDefinition
from app.metadata.schema import (
    FieldDefinitionCreate,
    FieldDefinitionRead,
    FieldDefinitionUpdate,
)
from app.observability.metrics import RAG_FACET_DURATION, time_stage

router = APIRouter(prefix="/api/v1", tags=["metadata"])


def _ensure_kb_scope(kb_id: str, context: AuthenticatedRequestContext) -> None:
    if kb_id != context.knowledge_base.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Knowledge base not found")


@router.post(
    "/knowledge-bases/{kb_id}/metadata-fields",
    response_model=FieldDefinitionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_metadata_field(
    kb_id: str,
    payload: FieldDefinitionCreate,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_MANAGE)),
    ],
) -> FieldDefinitionRead:
    _ensure_kb_scope(kb_id, context)
    exists = (
        db.query(MetadataFieldDefinition)
        .filter(
            MetadataFieldDefinition.knowledge_base_id == kb_id,
            MetadataFieldDefinition.key == payload.key,
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"字段已存在: {payload.key}")
    field = MetadataFieldDefinition(
        knowledge_base_id=kb_id,
        key=payload.key,
        label=payload.label,
        field_type=payload.field_type,
        options=payload.options,
        required=payload.required,
        is_facetable=payload.is_facetable,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return FieldDefinitionRead.model_validate(field)


@router.get(
    "/knowledge-bases/{kb_id}/metadata-fields",
    response_model=list[FieldDefinitionRead],
)
def list_metadata_fields(
    kb_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
) -> list[FieldDefinitionRead]:
    _ensure_kb_scope(kb_id, context)
    fields = (
        db.query(MetadataFieldDefinition)
        .filter(MetadataFieldDefinition.knowledge_base_id == kb_id)
        .all()
    )
    return [FieldDefinitionRead.model_validate(f) for f in fields]


@router.patch(
    "/metadata-fields/{field_id}", response_model=FieldDefinitionRead
)
def update_metadata_field(
    field_id: str,
    payload: FieldDefinitionUpdate,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_MANAGE)),
    ],
) -> FieldDefinitionRead:
    field = (
        db.query(MetadataFieldDefinition)
        .filter(MetadataFieldDefinition.id == field_id)
        .first()
    )
    if not field or field.knowledge_base_id != context.knowledge_base.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="字段不存在")
    data = payload.model_dump(exclude_unset=True)
    for attr, value in data.items():
        setattr(field, attr, value)
    db.commit()
    db.refresh(field)
    return FieldDefinitionRead.model_validate(field)


@router.delete(
    "/metadata-fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_metadata_field(
    field_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_MANAGE)),
    ],
) -> None:
    field = (
        db.query(MetadataFieldDefinition)
        .filter(MetadataFieldDefinition.id == field_id)
        .first()
    )
    if not field or field.knowledge_base_id != context.knowledge_base.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="字段不存在")
    db.delete(field)
    db.commit()


@router.get("/knowledge-bases/{kb_id}/facets")
def get_facets(
    kb_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
) -> dict:
    _ensure_kb_scope(kb_id, context)
    with time_stage(RAG_FACET_DURATION):
        facets = compute_facets(db, kb_id)
    return {"facets": facets}
```

在 `app/main.py` 挂载（找到现有 `app.include_router(...)` 处，照同样方式添加）：

```python
from app.api.metadata_routes import router as metadata_router
app.include_router(metadata_router)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && pytest tests/test_metadata_api.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/api/metadata_routes.py apps/luna-corpus/app/main.py apps/luna-corpus/tests/test_metadata_api.py apps/luna-corpus/tests/helpers_rbac.py
git commit -m "feat(corpus): add metadata schema management and facet API"
```

---

### Task 13: `/qa/query` 透传 filters 到检索

**Files:**
- Modify: `apps/luna-corpus/app/graph/state.py`（`RAGState` 增 `filters`）
- Modify: `apps/luna-corpus/app/graph/rag_graph.py`（`answer_question` 接收 filters、`retrieve_node` 使用）
- Modify: `apps/luna-corpus/app/api/routes.py`（`QuestionRequest` 增 `filters`、`query` 端点构造并透传）
- Test: `apps/luna-corpus/tests/test_query_filters.py`

**Interfaces:**
- Consumes: `MetadataFilter`（Task 5）、`hybrid_search(filters=, field_types=)`（Task 8）、`load_field_definitions`（Task 4）
- Produces：
  - `QuestionRequest.filters: MetadataFilter | None = None`
  - `answer_question(question, knowledge_base_id, filters=None, field_types=None)`
  - `RAGState` 增键 `filters: dict | None`、`field_types: dict | None`（存 key→类型字符串映射，`retrieve_node` 内还原为 `MetadataFilter`/`FieldType`）

> 说明：LangGraph state 需可序列化，故 state 里存 `filters` 的 dict 形态（`MetadataFilter.model_dump()`）与 `field_types` 的 `{key: field_type_value}` 字符串映射；`retrieve_node` 内还原。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_query_filters.py`：

```python
"""retrieve_node 使用 filters 透传的单元测试。"""
from unittest.mock import patch

from app.graph.rag_graph import retrieve_node
from app.metadata.schema import FieldType
from app.retrieval.filters import FilterOp, MetadataCondition, MetadataFilter


def test_retrieve_node_passes_filters_to_hybrid_search():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.EQ, value="合同")
    ])
    state = {
        "question": "q",
        "knowledge_base_id": "kb1",
        "filters": f.model_dump(),
        "field_types": {"category": "enum"},
    }
    with patch("app.graph.rag_graph.embed_text", return_value=[0.1]), \
         patch("app.graph.rag_graph.hybrid_search", return_value=[]) as hs, \
         patch(
             "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
             side_effect=lambda docs, kb: docs,
         ):
        retrieve_node(state)
    _, kwargs = hs.call_args
    assert isinstance(kwargs["filters"], MetadataFilter)
    assert kwargs["field_types"] == {"category": FieldType.ENUM}


def test_retrieve_node_no_filters_passes_none():
    state = {"question": "q", "knowledge_base_id": "kb1"}
    with patch("app.graph.rag_graph.embed_text", return_value=[0.1]), \
         patch("app.graph.rag_graph.hybrid_search", return_value=[]) as hs, \
         patch(
             "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
             side_effect=lambda docs, kb: docs,
         ):
        retrieve_node(state)
    _, kwargs = hs.call_args
    assert kwargs.get("filters") is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_query_filters.py -v`
Expected: FAIL（`retrieve_node` 未把 filters 传给 `hybrid_search`）

- [ ] **Step 3: 实现**

1) `app/graph/state.py` 的 `RAGState` 增两个可选键：

```python
    filters: dict | None
    field_types: dict | None
```

2) `app/graph/rag_graph.py` 顶部 import 增加：

```python
from app.metadata.schema import FieldType
from app.retrieval.filters import MetadataFilter
```

3) `retrieve_node` 内还原 filters 并透传（替换现有 `hybrid_search(...)` 调用块）：

```python
    filters_raw = state.get("filters")
    field_types_raw = state.get("field_types")
    filters = MetadataFilter(**filters_raw) if filters_raw else None
    field_types = (
        {k: FieldType(v) for k, v in field_types_raw.items()}
        if field_types_raw
        else None
    )

    results = hybrid_search(
        question,
        query_embedding,
        top_k=settings.retrieval_top_k,
        knowledge_base_id=knowledge_base_id,
        filters=filters,
        field_types=field_types,
    )
```

4) `answer_question` 增参数并写入 invoke 的 state：

```python
def answer_question(
    question: str,
    knowledge_base_id: str,
    filters: dict | None = None,
    field_types: dict | None = None,
) -> dict[str, Any]:
    start_time = time.time()
    graph = get_rag_graph()
    result = graph.invoke({
        "question": question,
        "knowledge_base_id": knowledge_base_id,
        "conversation_id": None,
        "conversation_history": [],
        "retrieved_docs": [],
        "needs_summarization": False,
        "filters": filters,
        "field_types": field_types,
    })
    processing_time_ms = int((time.time() - start_time) * 1000)
    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "processing_time_ms": processing_time_ms,
    }
```

5) `app/api/routes.py`：`QuestionRequest` 增字段：

```python
from app.retrieval.filters import MetadataFilter  # 顶部 import


class QuestionRequest(BaseModel):
    """Question request model."""

    question: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: MetadataFilter | None = None
```

`query` 端点内，调用 `answer_question` 前构造 field_types 并透传（新增 import `from app.metadata.validation import load_field_definitions`、`from app.metadata.schema import FieldType`）：

```python
    filters_payload = None
    field_types_payload = None
    if question_req.filters and question_req.filters.conditions:
        filters_payload = question_req.filters.model_dump()
        field_types_payload = {
            f.key: f.field_type.value
            for f in load_field_definitions(db, context.knowledge_base.id)
        }

    result = answer_question(
        question_req.question,
        knowledge_base_id=context.knowledge_base.id,
        filters=filters_payload,
        field_types=field_types_payload,
    )
```

- [ ] **Step 4: 运行测试确认通过 + 回归**

Run: `cd apps/luna-corpus && pytest tests/test_query_filters.py -v && pytest tests/ -k "graph or query or rag" -q`
Expected: 新测试 PASS（2 passed）；相关测试全绿。

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/graph/state.py apps/luna-corpus/app/graph/rag_graph.py apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/test_query_filters.py
git commit -m "feat(corpus): thread metadata filters through /qa/query"
```

---

### Task 14: filters 透传 agent rag_search 工具 + 全量回归

**Files:**
- Modify: `apps/luna-corpus/app/agent/tools/rag_search.py`
- Test: `apps/luna-corpus/tests/test_rag_search_filters.py`

**Interfaces:**
- Consumes: `hybrid_search(filters=, field_types=)`（Task 8）、`MetadataFilter`/`FieldType`
- Produces: `create_rag_search_tool(knowledge_base_id, filters=None, field_types=None)`：闭包捕获 filters/field_types 并传给 `hybrid_search`；`filters` 为 `MetadataFilter | None`、`field_types` 为 `dict[str, FieldType] | None`

> 范围说明：agent 工具是「按当前会话固定过滤」的透传（不让 LLM 动态改 filters，YAGNI）；`/qa/stream` 与 `/qa/multi-turn` 的 filters 透传与 Task 13 的 `/qa/query` 模式一致，若本次不实现，则在 `create_rag_search_tool` 与流式端点保持 `filters=None` 的默认，行为与现状一致（零回归）。本任务只落地 agent 工具签名扩展与单测，保证接口就绪。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_rag_search_filters.py`：

```python
"""rag_search 工具 filters 透传测试。"""
from unittest.mock import patch

from app.agent.tools.rag_search import create_rag_search_tool
from app.metadata.schema import FieldType
from app.retrieval.filters import FilterOp, MetadataCondition, MetadataFilter


def test_rag_search_tool_passes_filters():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.EQ, value="合同")
    ])
    ft = {"category": FieldType.ENUM}
    tool = create_rag_search_tool("kb1", filters=f, field_types=ft)
    with patch(
        "app.agent.tools.rag_search.embed_text", return_value=[0.1]
    ), patch(
        "app.agent.tools.rag_search.hybrid_search", return_value=[]
    ) as hs:
        tool.func(query="q")
    _, kwargs = hs.call_args
    assert kwargs["filters"] is f
    assert kwargs["field_types"] is ft


def test_rag_search_tool_default_no_filters():
    tool = create_rag_search_tool("kb1")
    with patch(
        "app.agent.tools.rag_search.embed_text", return_value=[0.1]
    ), patch(
        "app.agent.tools.rag_search.hybrid_search", return_value=[]
    ) as hs:
        tool.func(query="q")
    _, kwargs = hs.call_args
    assert kwargs.get("filters") is None
```

> `tool.func` 指向被 `tool(...)` 装饰的可调用；若 `Tool` 暴露的属性名不同（如 `tool.fn`/`tool.callable`），按 `app/agent/tool.py` 实际属性名调整测试与断言。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && pytest tests/test_rag_search_filters.py -v`
Expected: FAIL（`create_rag_search_tool` 不接受 `filters`）

- [ ] **Step 3: 实现**

改写 `app/agent/tools/rag_search.py`：`_format_rag_results` 与 `create_rag_search_tool` 接收并透传 filters/field_types。顶部 import：

```python
from app.metadata.schema import FieldType
from app.retrieval.filters import MetadataFilter
```

`_format_rag_results` 增参数并透传：

```python
def _format_rag_results(
    query: str,
    knowledge_base_id: str,
    top_k: int = 5,
    filters: MetadataFilter | None = None,
    field_types: dict[str, FieldType] | None = None,
) -> str:
    try:
        query_embedding = embed_text(query)
        results = hybrid_search(
            query,
            query_embedding,
            top_k=top_k,
            knowledge_base_id=knowledge_base_id,
            filters=filters,
            field_types=field_types,
        )
        ...  # 其余格式化逻辑保持不变
```

`create_rag_search_tool` 捕获 filters/field_types：

```python
def create_rag_search_tool(
    knowledge_base_id: str,
    filters: MetadataFilter | None = None,
    field_types: dict[str, FieldType] | None = None,
) -> Tool:
    def _get_rag_results(query: str, top_k: int = 5) -> str:
        return _format_rag_results(
            query=query,
            top_k=top_k,
            knowledge_base_id=knowledge_base_id,
            filters=filters,
            field_types=field_types,
        )
    return tool(
        name="rag_search",
        description=(
            "Search the current knowledge base for relevant documents. "
            "Use this when the user asks about information that might be "
            "in the current documents."
        ),
        parameters_schema=_RAG_SEARCH_PARAMETERS,
    )(_get_rag_results)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && pytest tests/test_rag_search_filters.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 全量回归**

Run: `cd apps/luna-corpus && pytest tests/ -q`
Expected: 全绿。若有失败，定位到本模块改动引入的回归并修复（尤其 vectorstore、hybrid、routes 相关）。

- [ ] **Step 6: 提交**

```bash
git add apps/luna-corpus/app/agent/tools/rag_search.py apps/luna-corpus/tests/test_rag_search_filters.py
git commit -m "feat(corpus): support fixed metadata filters in rag_search tool"
```

---

## 收尾：文档

### Task 15: 更新检索/元数据文档

**Files:**
- Modify: `apps/luna-corpus/app/retrieval/__init__.py`（docstring 补充 filters）
- Create: `apps/luna-corpus/app/metadata/__init__.py` 已含 docstring（Task 2），如需补充在此完善

- [ ] **Step 1: 更新 `app/retrieval/__init__.py` docstring**

在现有 docstring 末尾补一段：

```
元数据过滤：``hybrid_search`` 接受可选 ``filters``（``MetadataFilter``）与
``field_types``。向量侧把条件下推为 Chroma ``where``，BM25 侧 post-filter，
并按 ``filter_over_fetch_multiplier`` 放大候选窗口补偿损耗。过滤构造失败降级
为无过滤。翻译逻辑见 ``app.retrieval.filters``。
```

- [ ] **Step 2: 提交**

```bash
git add apps/luna-corpus/app/retrieval/__init__.py
git commit -m "docs(corpus): document metadata filtering in retrieval package"
```

---

## 自查（写计划者已核对）

- **Spec 覆盖**：Schema 模型(Task 2/3)、校验归一化(Task 4)、filters 翻译(Task 5)、分面聚合(Task 6)、向量库元数据+where(Task 7)、hybrid filters(Task 8)、元数据传播(Task 9)、摄取校验(Task 10)、指标(Task 11)、Schema/分面 API(Task 12)、查询透传(Task 13)、agent 工具(Task 14)、文档(Task 15)、迁移(Task 3)、配置(Task 1) — spec 各节均有对应任务。
- **类型一致性**：`MetadataFilter`/`MetadataCondition`/`FilterOp`/`to_chroma_where`/`make_post_filter`/`to_chroma_metadata`/`FilterFieldError`（Task 5）在 Task 8/13/14 引用一致；`FieldType`（Task 2）贯穿；`validate_and_normalize`/`load_field_definitions`（Task 4）在 Task 9/10/13 一致；`compute_facets`（Task 6）在 Task 12 一致。
- **零回归**：Task 8 无 filters 分支保持原逻辑；Task 13/14 默认 `filters=None`。
