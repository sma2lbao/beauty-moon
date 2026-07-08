# 文档变更检测与增量索引 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 luna-corpus 引入「文档身份 + 内容 hash 驱动」的变更检测与增量索引，重复上传返回 `created`/`updated`/`unchanged` 三态，避免重复索引与旧版本污染。

**Architecture:** 新增 `app/services/document_identity.py` 承载纯逻辑（`compute_content_hash` + `resolve_document_identity` + `ChangeType`）；`IngestionService.ingest_file` 在解析出正文、算出 `content_hash` 后按身份匹配走三态分支；`/files/upload`、`PUT /documents/{id}`、`POST /documents` 三个端点消费该逻辑。更新走既有异步索引链路（`IngestionTask` + `_run_index_task` + `DocumentProcessor.process_document`，后者已支持删旧建新）。

**Tech Stack:** Python 3.14、FastAPI、SQLAlchemy 2.x（`Mapped`/`mapped_column`）、Alembic、pytest、SQLite（测试内存库）、MySQL（生产 `CHAR(36)`）。

## Global Constraints

- 包管理器统一 `npm`；测试通过 `npm exec nx` 或直接在 `apps/luna-corpus` 内 `pytest` 运行。
- 生产禁用 `Base.metadata.create_all`；所有 schema 变更必须走 Alembic 迁移。
- `content_hash` 基于**解析后的 `Document.content`（文本）**的 SHA-256，而非上传文件字节。
- 身份匹配范围恒为**同一 `knowledge_base_id` 内**；匹配优先级 `document_id` > `external_id` > `original_name`（取 `title` 字段，多条取 `updated_at` 最新）。
- `version` 为单调递增计数器：新建=1，每次内容变更 +1，`unchanged` 不变；本次不保存历史内容。
- 移除全局 hash 去重逻辑与 `upload_duplicate_policy` 配置、`DuplicateFileError`。
- 迁移 revision 链：新迁移 `down_revision = "20260707_0007"`。

---

### Task 1: Document 数据模型字段与迁移

**Files:**
- Modify: `apps/luna-corpus/app/db/models.py:318-346`（`Document` 类）
- Create: `apps/luna-corpus/alembic/versions/20260708_0008_document_versioning.py`
- Test: `apps/luna-corpus/tests/db/test_document_versioning_model.py`

**Interfaces:**
- Produces: `Document.content_hash: str | None`、`Document.version: int`（default 1）、`Document.external_id: str | None`；表级约束 `UniqueConstraint("knowledge_base_id", "external_id", name="uq_documents_kb_external")`。

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/db/test_document_versioning_model.py`：

```python
"""Tests for Document versioning columns and constraints."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Document, KnowledgeBase, Tenant, Workspace


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="Research", slug="research", tenant=tenant)
    kb = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    db.add(kb)
    db.commit()
    yield db, kb.id
    db.close()
    engine.dispose()


def test_document_defaults_version_one(session):
    db, kb_id = session
    doc = Document(knowledge_base_id=kb_id, title="a.md", content="hello")
    db.add(doc)
    db.commit()
    db.refresh(doc)
    assert doc.version == 1
    assert doc.content_hash is None
    assert doc.external_id is None


def test_document_external_id_unique_per_kb(session):
    db, kb_id = session
    db.add(Document(knowledge_base_id=kb_id, title="a", content="x", external_id="HR-1"))
    db.commit()
    db.add(Document(knowledge_base_id=kb_id, title="b", content="y", external_id="HR-1"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_document_null_external_id_allows_many(session):
    db, kb_id = session
    db.add(Document(knowledge_base_id=kb_id, title="a", content="x"))
    db.add(Document(knowledge_base_id=kb_id, title="b", content="y"))
    db.commit()  # two NULL external_id rows coexist
    assert db.query(Document).count() == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/db/test_document_versioning_model.py -v`
Expected: FAIL（`TypeError: 'version' is an invalid keyword argument` 或 `content_hash` 属性不存在）

- [ ] **Step 3: 修改 `Document` 模型**

在 `apps/luna-corpus/app/db/models.py` 的 `Document` 类中，`doc_metadata` 行之后、`content` 行之前插入字段，并添加 `__table_args__`。将：

```python
class Document(Base):
    """Document model."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("file_uploads.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    doc_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
```

改为：

```python
class Document(Base):
    """Document model."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id", "external_id", name="uq_documents_kb_external"
        ),
    )

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("file_uploads.id"), nullable=True
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    doc_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
```

（`UniqueConstraint`、`String`、`Integer` 均已在文件顶部 import。）

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/db/test_document_versioning_model.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 创建 Alembic 迁移**

创建 `apps/luna-corpus/alembic/versions/20260708_0008_document_versioning.py`：

```python
"""document content_hash, version, external_id

Revision ID: 20260708_0008
Revises: 20260707_0007
Create Date: 2026-07-08

"""
import sqlalchemy as sa
from alembic import op

revision = "20260708_0008"
down_revision = "20260707_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("external_id", sa.String(255), nullable=True)
    )
    op.add_column(
        "documents", sa.Column("content_hash", sa.String(64), nullable=True)
    )
    op.add_column(
        "documents",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_unique_constraint(
        "uq_documents_kb_external", "documents", ["knowledge_base_id", "external_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_documents_kb_external", "documents", type_="unique")
    op.drop_column("documents", "version")
    op.drop_column("documents", "content_hash")
    op.drop_column("documents", "external_id")
```

- [ ] **Step 6: 校验迁移可加载**

Run: `cd apps/luna-corpus && python -c "import importlib.util,glob; [importlib.util.spec_from_file_location('m',p).loader.exec_module(importlib.util.module_from_spec(importlib.util.spec_from_file_location('m',p))) for p in glob.glob('alembic/versions/20260708_0008_document_versioning.py')]; print('ok')"`
Expected: 输出 `ok`（无语法/导入错误）

- [ ] **Step 7: 提交**

```bash
git add apps/luna-corpus/app/db/models.py apps/luna-corpus/alembic/versions/20260708_0008_document_versioning.py apps/luna-corpus/tests/db/test_document_versioning_model.py
git commit -m "feat(corpus): add Document content_hash/version/external_id + migration"
```

---

### Task 2: 文档身份与内容 hash 模块

**Files:**
- Create: `apps/luna-corpus/app/services/document_identity.py`
- Test: `apps/luna-corpus/tests/services/test_document_identity.py`

**Interfaces:**
- Consumes: `Document`（Task 1 字段）。
- Produces:
  - `class ChangeType(str, enum.Enum)`: `CREATED="created"`, `UPDATED="updated"`, `UNCHANGED="unchanged"`。
  - `compute_content_hash(text: str) -> str`：正文文本的 SHA-256 hex。
  - `resolve_document_identity(db: Session, knowledge_base_id: str, *, external_id: str | None = None, original_name: str | None = None) -> Document | None`：按 `external_id`（优先）或 `title == original_name`（多条取 `updated_at` 最新）匹配，未命中返回 `None`。

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/services/test_document_identity.py`：

```python
"""Tests for document identity resolution and content hashing."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Document, KnowledgeBase, Tenant, Workspace
from app.services.document_identity import (
    ChangeType,
    compute_content_hash,
    resolve_document_identity,
)


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="R", slug="r", tenant=tenant)
    kb = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    db.add(kb)
    db.commit()
    yield db, kb.id
    db.close()
    engine.dispose()


def test_compute_content_hash_stable_and_sensitive():
    assert compute_content_hash("hello") == compute_content_hash("hello")
    assert compute_content_hash("hello") != compute_content_hash("hello!")
    assert len(compute_content_hash("x")) == 64


def test_change_type_values():
    assert ChangeType.CREATED.value == "created"
    assert ChangeType.UPDATED.value == "updated"
    assert ChangeType.UNCHANGED.value == "unchanged"


def test_resolve_returns_none_when_no_match(session):
    db, kb_id = session
    assert resolve_document_identity(db, kb_id, original_name="missing.md") is None


def test_resolve_by_external_id_takes_priority(session):
    db, kb_id = session
    by_name = Document(knowledge_base_id=kb_id, title="doc.md", content="a")
    by_ext = Document(
        knowledge_base_id=kb_id, title="other.md", content="b", external_id="HR-1"
    )
    db.add_all([by_name, by_ext])
    db.commit()
    hit = resolve_document_identity(
        db, kb_id, external_id="HR-1", original_name="doc.md"
    )
    assert hit.id == by_ext.id


def test_resolve_by_original_name_when_no_external_id(session):
    db, kb_id = session
    doc = Document(knowledge_base_id=kb_id, title="doc.md", content="a")
    db.add(doc)
    db.commit()
    hit = resolve_document_identity(db, kb_id, original_name="doc.md")
    assert hit.id == doc.id


def test_resolve_by_name_picks_latest_updated(session):
    db, kb_id = session
    old = Document(knowledge_base_id=kb_id, title="dup.md", content="old")
    db.add(old)
    db.commit()
    new = Document(knowledge_base_id=kb_id, title="dup.md", content="new")
    db.add(new)
    db.commit()
    new.content = "touched"
    db.commit()  # bumps updated_at
    hit = resolve_document_identity(db, kb_id, original_name="dup.md")
    assert hit.id == new.id


def test_resolve_scoped_to_kb(session):
    db, kb_id = session
    other_kb = KnowledgeBase(
        name="Other", slug="other", workspace_id=db.query(KnowledgeBase).first().workspace_id
    )
    db.add(other_kb)
    db.commit()
    db.add(Document(knowledge_base_id=other_kb.id, title="doc.md", content="a"))
    db.commit()
    assert resolve_document_identity(db, kb_id, original_name="doc.md") is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/services/test_document_identity.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.services.document_identity'`）

- [ ] **Step 3: 实现模块**

创建 `apps/luna-corpus/app/services/document_identity.py`：

```python
"""文档身份解析与正文内容 hash。

变更检测的纯逻辑单元：不做任何写操作，只负责
「算 hash」与「按身份键找已有文档」。
"""
import enum
import hashlib

from sqlalchemy.orm import Session

from app.db.models import Document


class ChangeType(str, enum.Enum):
    """一次写入相对已有文档的变更类型。"""

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


def compute_content_hash(text: str) -> str:
    """计算文档正文的 SHA-256 hex（UTF-8 编码）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_document_identity(
    db: Session,
    knowledge_base_id: str,
    *,
    external_id: str | None = None,
    original_name: str | None = None,
) -> Document | None:
    """在同一知识库内按身份键匹配已有文档。

    优先级：external_id（若提供）> original_name（匹配 title，多条取
    updated_at 最新）。均未命中返回 None。
    """
    if external_id:
        return (
            db.query(Document)
            .filter(
                Document.knowledge_base_id == knowledge_base_id,
                Document.external_id == external_id,
            )
            .first()
        )
    if original_name:
        return (
            db.query(Document)
            .filter(
                Document.knowledge_base_id == knowledge_base_id,
                Document.title == original_name,
            )
            .order_by(Document.updated_at.desc())
            .first()
        )
    return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/services/test_document_identity.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/services/document_identity.py apps/luna-corpus/tests/services/test_document_identity.py
git commit -m "feat(corpus): add document identity resolution and content hashing"
```

---

### Task 3: IngestionService 三态摄取 + `/files/upload` 端点接入

**Files:**
- Modify: `apps/luna-corpus/app/services/ingestion/service.py:69-237`（`__init__` 与 `ingest_file`）
- Modify: `apps/luna-corpus/app/api/routes.py:258-263`（`FileUploadCreateResponse`）
- Modify: `apps/luna-corpus/app/api/routes.py:1112-1203`（`upload_file` 端点）
- Modify: `apps/luna-corpus/app/security/audit.py:14-20`（新增 `DOCUMENT_UPDATE`）
- Test: `apps/luna-corpus/tests/services/ingestion/test_service.py`（更新）
- Test: `apps/luna-corpus/tests/api/test_file_upload.py`（更新/新增三态用例）

**Interfaces:**
- Consumes: `resolve_document_identity`、`compute_content_hash`、`ChangeType`（Task 2）。
- Produces: `IngestionService.ingest_file(db, file, knowledge_base_id, metadata=None, external_id=None) -> tuple[FileUpload | None, Document | None, str | None]`（第三元素为 `ChangeType` 的 `.value`，解析失败时为 `None`）；`IngestionService.__init__` 去掉 `duplicate_policy` 参数；`FileUploadCreateResponse` 新增 `change_type: str | None`、`version: int | None`，`file` 改为可选。

- [ ] **Step 1: 更新 service 单元测试（写期望新行为）**

编辑 `apps/luna-corpus/tests/services/ingestion/test_service.py`：

1. 删除 `DuplicateFileError` 的 import（改为只 import `ParseError, UnsupportedFileTypeError`）。
2. 删除 `test_ingest_file_duplicate_reject` 与 `test_ingest_file_duplicate_replace` 两个测试整体。
3. `ingestion_service` fixture 去掉 `duplicate_policy="reject"` 参数。
4. `test_ingest_file_success`：解包三元组并断言 `change_type == "created"`。将：

```python
    upload, document = await ingestion_service.ingest_file(db, file, "kb-1")

    assert isinstance(upload, FileUpload)
    assert upload.status == FileUploadStatus.PARSED
```

改为：

```python
    upload, document, change_type = await ingestion_service.ingest_file(
        db, file, "kb-1"
    )

    assert isinstance(upload, FileUpload)
    assert upload.status == FileUploadStatus.PARSED
    assert change_type == "created"
```

5. `test_ingest_file_parse_error` 与 `test_ingest_file_generic_exception_rollback`：解包三元组（第三个变量命名 `_change`），断言不变（`result[0]`/`result[1]` 索引写法仍可用，无需改）。将 `test_ingest_file_generic_exception_rollback` 中：

```python
    upload, document = await ingestion_service.ingest_file(db, file, "kb-1")
```

改为：

```python
    upload, document, _change = await ingestion_service.ingest_file(db, file, "kb-1")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/services/ingestion/test_service.py -v`
Expected: FAIL（`ingest_file` 仍返回 2 元组 / `__init__` 仍要求 `duplicate_policy`）

- [ ] **Step 3: 重构 `IngestionService`**

编辑 `apps/luna-corpus/app/services/ingestion/service.py`。

3a. 顶部 import 增加：

```python
from app.services.document_identity import (
    ChangeType,
    compute_content_hash,
    resolve_document_identity,
)
```

并从 `app.db.models` import 中确保含 `Document, FileUpload`（已有）。

3b. `__init__` 去掉 duplicate policy。将：

```python
    def __init__(
        self,
        storage: StorageBackend,
        parser_registry: ParserRegistry,
        max_upload_size: int = 52428800,
        duplicate_policy: str = "reject",
    ):
        ...
        self.max_upload_size = max_upload_size
        self.duplicate_policy = duplicate_policy
```

改为：

```python
    def __init__(
        self,
        storage: StorageBackend,
        parser_registry: ParserRegistry,
        max_upload_size: int = 52428800,
    ):
        """Initialize ingestion service.

        Args:
            storage: Storage backend instance
            parser_registry: Parser registry instance
            max_upload_size: Maximum allowed file size in bytes
        """
        self.storage = storage
        self.parser_registry = parser_registry
        self.max_upload_size = max_upload_size
```

3c. 重写 `ingest_file`。将现有方法体（签名 + 至 `return upload, document` 与两个 except 分支的 `return upload, None`）整体替换为：

```python
    async def ingest_file(
        self,
        db: Session,
        file: UploadFile,
        knowledge_base_id: str,
        metadata: dict | None = None,
        external_id: str | None = None,
    ) -> tuple[FileUpload | None, Document | None, str | None]:
        """Ingest a file with change detection.

        Returns (FileUpload | None, Document | None, change_type). change_type
        is one of ChangeType.value ("created"/"updated"/"unchanged"), or None
        when parsing failed. Vectorization is the caller's responsibility.
        """
        # Validate file size
        if file.size and file.size > self.max_upload_size:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File too large. Maximum size: {self.max_upload_size} bytes",
            )

        # Validate MIME type
        mime_type = file.content_type or "application/octet-stream"
        if not self.parser_registry.is_supported(mime_type):
            supported = ", ".join(self.parser_registry.list_supported_types())
            raise UnsupportedFileTypeError(
                f"Unsupported file type: {mime_type}. Supported: {supported}"
            )

        # Validate & normalize metadata before any write.
        normalized_metadata = validate_and_normalize(db, knowledge_base_id, metadata)

        # Read content and compute file-byte hash (kept for file-layer record).
        content = file.file.read()
        content_hash = _compute_hash(content)
        file.file.seek(0)

        if len(content) == 0:
            raise EmptyFileError("Uploaded file is empty")

        if len(content) > self.max_upload_size:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File too large. Maximum size: {self.max_upload_size} bytes",
            )

        filename = file.filename or "unknown"
        stored_name = _generate_storage_path(knowledge_base_id, filename)

        # Create FileUpload record first (records the upload attempt; kept even
        # on parse failure so the error is queryable).
        upload = FileUpload(
            knowledge_base_id=knowledge_base_id,
            original_name=filename,
            stored_name=stored_name,
            mime_type=mime_type,
            size_bytes=file.size or len(content),
            content_hash=content_hash,
            status=FileUploadStatus.UPLOADED,
        )
        db.add(upload)
        db.commit()
        db.refresh(upload)

        try:
            await self.storage.save(file, stored_name)

            parser = self.parser_registry.get_parser(mime_type)
            parsed_text = parser.parse(content, filename)
            text_hash = compute_content_hash(parsed_text)

            existing = resolve_document_identity(
                db,
                knowledge_base_id,
                external_id=external_id,
                original_name=filename,
            )

            has_tables = "|" in parsed_text and "---" in parsed_text
            has_code = "```" in parsed_text or "def " in parsed_text

            if existing is None:
                # created
                document = Document(
                    knowledge_base_id=knowledge_base_id,
                    file_id=upload.id,
                    external_id=external_id,
                    title=filename or "Untitled",
                    content=parsed_text,
                    content_hash=text_hash,
                    version=1,
                    source=f"file://{filename}",
                    has_tables=has_tables,
                    has_code=has_code,
                    status=ContentStatus.PENDING,
                    doc_metadata=normalized_metadata or None,
                )
                db.add(document)
                db.commit()
                db.refresh(document)
                upload.status = FileUploadStatus.PARSED
                upload.parsed_at = datetime.now()
                db.commit()
                db.refresh(upload)
                return upload, document, ChangeType.CREATED.value

            if existing.content_hash == text_hash:
                # unchanged: roll back this redundant upload, keep existing doc.
                old_file = existing.file
                await self._discard_upload(db, upload)
                return old_file, existing, ChangeType.UNCHANGED.value

            # updated: update the existing document in place, repoint file_id,
            # delete the previously stored file.
            old_upload = existing.file
            existing.content = parsed_text
            existing.content_hash = text_hash
            existing.version = existing.version + 1
            existing.title = filename or existing.title
            existing.source = f"file://{filename}"
            existing.has_tables = has_tables
            existing.has_code = has_code
            existing.status = ContentStatus.PENDING
            existing.file_id = upload.id
            if external_id:
                existing.external_id = external_id
            if normalized_metadata:
                existing.doc_metadata = normalized_metadata
            upload.status = FileUploadStatus.PARSED
            upload.parsed_at = datetime.now()
            db.commit()
            db.refresh(existing)
            if old_upload is not None and old_upload.id != upload.id:
                await self._discard_upload(db, old_upload)
            return upload, existing, ChangeType.UPDATED.value

        except ParseError as e:
            upload.status = FileUploadStatus.ERROR
            upload.error_message = str(e)
            db.commit()
            with contextlib.suppress(StorageError):
                await self.storage.delete(stored_name)
            return upload, None, None

        except Exception as e:
            upload.status = FileUploadStatus.ERROR
            upload.error_message = str(e)
            db.commit()
            doc = (
                db.query(Document)
                .filter(
                    Document.file_id == upload.id,
                    Document.knowledge_base_id == knowledge_base_id,
                )
                .first()
            )
            if doc:
                db.delete(doc)
                db.commit()
            with contextlib.suppress(StorageError):
                await self.storage.delete(stored_name)
            return upload, None, None

    async def _discard_upload(self, db: Session, upload: FileUpload) -> None:
        """Delete a FileUpload row and its stored file (no document touched)."""
        with contextlib.suppress(StorageError):
            await self.storage.delete(upload.stored_name)
        db.delete(upload)
        db.commit()
```

（`Document, ContentStatus, FileUpload, FileUploadStatus` 已在文件顶部 import；`datetime`、`contextlib` 已 import。）

- [ ] **Step 4: 运行 service 测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/services/ingestion/test_service.py -v`
Expected: PASS（duplicate 两测试已删除，其余通过）

- [ ] **Step 5: 新增审计动作**

编辑 `apps/luna-corpus/app/security/audit.py`，在 `AuditAction` 枚举中 `DOCUMENT_CREATE` 之后添加：

```python
    DOCUMENT_CREATE = "document.create"
    DOCUMENT_UPDATE = "document.update"
    DOCUMENT_DELETE = "document.delete"
    DOCUMENT_INDEX = "document.index"
    QA_QUERY = "qa.query"
```

- [ ] **Step 6: 扩展 `FileUploadCreateResponse`**

编辑 `apps/luna-corpus/app/api/routes.py`，将：

```python
class FileUploadCreateResponse(BaseModel):
    """File upload creation response with document and task info."""

    file: FileUploadResponse
    document_id: str | None
    task_id: str | None
```

改为：

```python
class FileUploadCreateResponse(BaseModel):
    """File upload creation response with document and task info."""

    file: FileUploadResponse | None
    document_id: str | None
    task_id: str | None
    change_type: str | None = None
    version: int | None = None
```

- [ ] **Step 7: 改造 `upload_file` 端点**

编辑 `apps/luna-corpus/app/api/routes.py` 的 `upload_file`。

7a. 确保顶部 import 含 `Form` 与 `Response`：检查 `from fastapi import (...)`，若缺则加入 `Form`、`Response`。

7b. 函数签名加入 `external_id` 表单字段与 `response: Response`，并去掉构造时的 `duplicate_policy`。将签名与 service 构造改为：

```python
async def upload_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_WRITE)),
    ],
    external_id: Annotated[str | None, Form()] = None,
) -> FileUploadCreateResponse:
    """Upload a file with change detection; returns created/updated/unchanged."""
    storage = get_storage_backend()
    registry = get_parser_registry()

    service = IngestionService(
        storage=storage,
        parser_registry=registry,
        max_upload_size=get_settings().max_upload_size,
    )
```

7c. 删除 `except DuplicateFileError` 分支（连同其 import 使用），调用改为解包三元组：

```python
    try:
        upload, document, change_type = await service.ingest_file(
            db, file, context.knowledge_base.id, external_id=external_id
        )
    except EmptyFileError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except UnsupportedFileTypeError as e:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(e),
        ) from e
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
```

7d. 替换任务创建与响应构造段（从 `document_id = None` 到函数末尾 `return FileUploadCreateResponse(...)`）为：

```python
    document_id = None
    task_id = None
    version = None

    if document is not None:
        document_id = document.id
        version = document.version
        if change_type != ChangeType.UNCHANGED.value:
            task_service = TaskService()
            task = task_service.create_task(
                db, TaskType.DOCUMENT_INDEX, document.id, context.knowledge_base.id
            )
            task_id = task.id
            background_tasks.add_task(_run_index_task, task.id, document.id)
            audit_action = (
                AuditAction.DOCUMENT_UPDATE
                if change_type == ChangeType.UPDATED.value
                else AuditAction.DOCUMENT_CREATE
            )
            AuditService().record(
                db,
                action=audit_action,
                resource_type="document",
                resource_id=document.id,
                result=AuditResult.SUCCESS,
                context=context,
            )
            db.commit()

    if change_type == ChangeType.CREATED.value:
        response.status_code = status.HTTP_201_CREATED
    else:
        response.status_code = status.HTTP_200_OK

    file_response = (
        FileUploadResponse(
            id=upload.id,
            knowledge_base_id=upload.knowledge_base_id,
            original_name=upload.original_name,
            mime_type=upload.mime_type,
            size_bytes=upload.size_bytes,
            content_hash=upload.content_hash,
            status=upload.status.value,
            error_message=upload.error_message,
            parsed_at=upload.parsed_at.isoformat() if upload.parsed_at else None,
            created_at=upload.created_at.isoformat(),
            updated_at=upload.updated_at.isoformat(),
        )
        if upload is not None
        else None
    )

    return FileUploadCreateResponse(
        file=file_response,
        document_id=document_id,
        task_id=task_id,
        change_type=change_type,
        version=version,
    )
```

7e. 顶部 import：加入 `from app.services.document_identity import ChangeType`；确保 `AuditService, AuditAction, AuditResult` 已 import（`create_document` 已使用，故已在）。

- [ ] **Step 8: 更新/新增上传集成测试**

编辑 `apps/luna-corpus/tests/api/test_file_upload.py`：

8a. `test_upload_file_success` 中把 parser mock 改为回显内容，便于后续 hash 区分。将：

```python
    parser = type("Parser", (), {"parse": lambda self, c, n: "Parsed text"})()
```

改为：

```python
    parser = type("Parser", (), {"parse": lambda self, c, n: c.decode("utf-8")})()
```

并在断言末尾补：

```python
    assert data["change_type"] == "created"
    assert data["version"] == 1
```

8b. 追加三态测试（放在文件末尾）：

```python
@patch("app.services.document_processor.DocumentProcessor")
@patch("app.api.routes.SessionLocal")
@patch("app.api.routes.get_storage_backend")
@patch("app.api.routes.get_parser_registry")
def test_upload_same_name_same_content_unchanged(
    mock_registry, mock_storage, mock_session_local, mock_processor, client, app_db
):
    """Re-uploading identical content under same name -> unchanged, no task."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session, context["workspace_id"], "u", [PermissionSlug.DOCUMENT_WRITE]
    )
    storage = mock_storage.return_value

    async def mock_save(f, p):
        return p

    async def mock_delete(p):
        return None

    storage.save = mock_save
    storage.delete = mock_delete
    registry = mock_registry.return_value
    registry.is_supported.return_value = True
    parser = type("Parser", (), {"parse": lambda self, c, n: c.decode("utf-8")})()
    registry.get_parser.return_value = parser
    mock_processor.return_value.process_document.return_value = None
    headers = _auth_headers(context, context["kb_one_id"], user_id)

    first = client.post(
        "/api/v1/files/upload",
        headers=headers,
        files={"file": ("doc.txt", io.BytesIO(b"same body"), "text/plain")},
    )
    assert first.status_code == 201
    assert first.json()["change_type"] == "created"

    second = client.post(
        "/api/v1/files/upload",
        headers=headers,
        files={"file": ("doc.txt", io.BytesIO(b"same body"), "text/plain")},
    )
    assert second.status_code == 200
    body = second.json()
    assert body["change_type"] == "unchanged"
    assert body["task_id"] is None
    assert body["version"] == 1
    assert body["document_id"] == first.json()["document_id"]


@patch("app.services.document_processor.DocumentProcessor")
@patch("app.api.routes.SessionLocal")
@patch("app.api.routes.get_storage_backend")
@patch("app.api.routes.get_parser_registry")
def test_upload_same_name_new_content_updated(
    mock_registry, mock_storage, mock_session_local, mock_processor, client, app_db
):
    """Re-uploading changed content under same name -> updated, version bumps."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session, context["workspace_id"], "u", [PermissionSlug.DOCUMENT_WRITE]
    )
    storage = mock_storage.return_value

    async def mock_save(f, p):
        return p

    async def mock_delete(p):
        return None

    storage.save = mock_save
    storage.delete = mock_delete
    registry = mock_registry.return_value
    registry.is_supported.return_value = True
    parser = type("Parser", (), {"parse": lambda self, c, n: c.decode("utf-8")})()
    registry.get_parser.return_value = parser
    mock_processor.return_value.process_document.return_value = None
    headers = _auth_headers(context, context["kb_one_id"], user_id)

    first = client.post(
        "/api/v1/files/upload",
        headers=headers,
        files={"file": ("doc.txt", io.BytesIO(b"version one"), "text/plain")},
    )
    doc_id = first.json()["document_id"]

    second = client.post(
        "/api/v1/files/upload",
        headers=headers,
        files={"file": ("doc.txt", io.BytesIO(b"version two"), "text/plain")},
    )
    assert second.status_code == 200
    body = second.json()
    assert body["change_type"] == "updated"
    assert body["version"] == 2
    assert body["task_id"] is not None
    assert body["document_id"] == doc_id


@patch("app.services.document_processor.DocumentProcessor")
@patch("app.api.routes.SessionLocal")
@patch("app.api.routes.get_storage_backend")
@patch("app.api.routes.get_parser_registry")
def test_upload_renamed_same_content_creates_new(
    mock_registry, mock_storage, mock_session_local, mock_processor, client, app_db
):
    """Same content under a different name -> created (no global dedup)."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session, context["workspace_id"], "u", [PermissionSlug.DOCUMENT_WRITE]
    )
    storage = mock_storage.return_value

    async def mock_save(f, p):
        return p

    async def mock_delete(p):
        return None

    storage.save = mock_save
    storage.delete = mock_delete
    registry = mock_registry.return_value
    registry.is_supported.return_value = True
    parser = type("Parser", (), {"parse": lambda self, c, n: c.decode("utf-8")})()
    registry.get_parser.return_value = parser
    mock_processor.return_value.process_document.return_value = None
    headers = _auth_headers(context, context["kb_one_id"], user_id)

    a = client.post(
        "/api/v1/files/upload",
        headers=headers,
        files={"file": ("a.txt", io.BytesIO(b"shared body"), "text/plain")},
    )
    b = client.post(
        "/api/v1/files/upload",
        headers=headers,
        files={"file": ("b.txt", io.BytesIO(b"shared body"), "text/plain")},
    )
    assert b.status_code == 201
    assert b.json()["change_type"] == "created"
    assert b.json()["document_id"] != a.json()["document_id"]
```

- [ ] **Step 9: 运行上传集成测试**

Run: `cd apps/luna-corpus && python -m pytest tests/api/test_file_upload.py -v`
Expected: PASS（含新增 3 个三态用例）

- [ ] **Step 10: 提交**

```bash
git add apps/luna-corpus/app/services/ingestion/service.py apps/luna-corpus/app/api/routes.py apps/luna-corpus/app/security/audit.py apps/luna-corpus/tests/services/ingestion/test_service.py apps/luna-corpus/tests/api/test_file_upload.py
git commit -m "feat(corpus): three-state change detection in file upload ingestion"
```

---

### Task 4: `PUT /documents/{id}` 与 `POST /documents` 变更检测

**Files:**
- Modify: `apps/luna-corpus/app/api/routes.py:96-117`（`DocumentCreate`、`DocumentResponse`）
- Modify: `apps/luna-corpus/app/api/routes.py:437-491`（`create_document`）
- Create（新增端点）: `apps/luna-corpus/app/api/routes.py`（在 `create_document` 之后新增 `update_document`）
- Test: `apps/luna-corpus/tests/api/test_document_versioning_api.py`

**Interfaces:**
- Consumes: `compute_content_hash`、`resolve_document_identity`、`ChangeType`（Task 2）；`AuditAction.DOCUMENT_UPDATE`（Task 3）。
- Produces: `PUT /api/v1/documents/{document_id}`（权限 `DOCUMENT_WRITE`，请求体 `DocumentCreate`，返回 `DocumentResponse`，状态 200，`change_type` ∈ updated/unchanged，404 越权/不存在）；`DocumentCreate.external_id: str | None`；`DocumentResponse` 增 `version: int`、`external_id: str | None`、`change_type: str | None`。

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/api/test_document_versioning_api.py`（复用与 `test_file_upload.py` 相同的 `app_db`/`client`/`create_user_with_permissions`/`_auth_headers` 夹具，此处内联）：

```python
"""Integration tests for document create/update change detection."""
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
    session.add(kb)
    session.commit()
    context = {
        "tenant_id": tenant.id,
        "workspace_id": workspace.id,
        "kb_one_id": kb.id,
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
        session.add(WorkspaceMembership(user=user, workspace_id=workspace_id, roles=[role]))
        session.commit()
        return user.id
    finally:
        session.close()


def _headers(context, user_id):
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": context["kb_one_id"],
    }


def test_create_document_sets_version_and_hash(client, app_db):
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"],
                [PermissionSlug.DOCUMENT_WRITE, PermissionSlug.DOCUMENT_READ])
    resp = client.post(
        "/api/v1/documents",
        headers=_headers(context, uid),
        json={"title": "T", "content": "hello", "external_id": "HR-1"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["version"] == 1
    assert body["external_id"] == "HR-1"


def test_create_document_duplicate_external_id_conflicts(client, app_db):
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"], [PermissionSlug.DOCUMENT_WRITE])
    payload = {"title": "T", "content": "hello", "external_id": "HR-1"}
    first = client.post("/api/v1/documents", headers=_headers(context, uid), json=payload)
    assert first.status_code == 201
    dup = client.post(
        "/api/v1/documents",
        headers=_headers(context, uid),
        json={"title": "T2", "content": "other", "external_id": "HR-1"},
    )
    assert dup.status_code == 409


def test_put_document_updated_and_unchanged(client, app_db):
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"], [PermissionSlug.DOCUMENT_WRITE])
    created = client.post(
        "/api/v1/documents",
        headers=_headers(context, uid),
        json={"title": "T", "content": "v1"},
    )
    doc_id = created.json()["id"]

    updated = client.put(
        f"/api/v1/documents/{doc_id}",
        headers=_headers(context, uid),
        json={"title": "T", "content": "v2"},
    )
    assert updated.status_code == 200
    assert updated.json()["change_type"] == "updated"
    assert updated.json()["version"] == 2

    same = client.put(
        f"/api/v1/documents/{doc_id}",
        headers=_headers(context, uid),
        json={"title": "T", "content": "v2"},
    )
    assert same.status_code == 200
    assert same.json()["change_type"] == "unchanged"
    assert same.json()["version"] == 2


def test_put_document_not_found(client, app_db):
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"], [PermissionSlug.DOCUMENT_WRITE])
    resp = client.put(
        "/api/v1/documents/missing-id",
        headers=_headers(context, uid),
        json={"title": "T", "content": "x"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/api/test_document_versioning_api.py -v`
Expected: FAIL（`DocumentCreate` 无 `external_id` / 响应无 `version` / `PUT` 路由 404 not found → 405）

- [ ] **Step 3: 扩展 `DocumentCreate` 与 `DocumentResponse`**

编辑 `apps/luna-corpus/app/api/routes.py`。将：

```python
class DocumentCreate(BaseModel):
    """Document creation model."""

    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    source: str | None = None


class DocumentResponse(BaseModel):
    """Document response model."""

    id: str
    title: str
    source: str | None
    content: str
    has_tables: bool
    has_code: bool
    status: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)
```

改为：

```python
class DocumentCreate(BaseModel):
    """Document creation model."""

    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    source: str | None = None
    external_id: str | None = Field(default=None, max_length=255)


class DocumentResponse(BaseModel):
    """Document response model."""

    id: str
    title: str
    source: str | None
    content: str
    has_tables: bool
    has_code: bool
    status: str
    version: int = 1
    external_id: str | None = None
    change_type: str | None = None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 4: 更新 `create_document` 端点**

编辑 `apps/luna-corpus/app/api/routes.py` 的 `create_document`。将其函数体（`db_doc = Document(...)` 到 `return DocumentResponse(...)`）替换为：

```python
    if doc.external_id:
        conflict = resolve_document_identity(
            db, context.knowledge_base.id, external_id=doc.external_id
        )
        if conflict is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"external_id '{doc.external_id}' already exists as document "
                    f"{conflict.id}; use PUT /documents/{{id}} to update"
                ),
            )

    db_doc = Document(
        title=doc.title,
        content=doc.content,
        content_hash=compute_content_hash(doc.content),
        version=1,
        external_id=doc.external_id,
        source=doc.source,
        has_tables="|" in doc.content and "---" in doc.content,
        has_code="```" in doc.content or "def " in doc.content,
        knowledge_base_id=context.knowledge_base.id,
    )
    db.add(db_doc)
    db.flush()
    AuditService().record(
        db,
        action=AuditAction.DOCUMENT_CREATE,
        resource_type="document",
        resource_id=db_doc.id,
        result=AuditResult.SUCCESS,
        context=context,
    )
    db.commit()
    db.refresh(db_doc)

    return DocumentResponse(
        id=db_doc.id,
        title=db_doc.title,
        source=db_doc.source,
        content=db_doc.content,
        has_tables=db_doc.has_tables,
        has_code=db_doc.has_code,
        status=db_doc.status.value,
        version=db_doc.version,
        external_id=db_doc.external_id,
        change_type=ChangeType.CREATED.value,
        created_at=db_doc.created_at.isoformat(),
        updated_at=db_doc.updated_at.isoformat(),
    )
```

- [ ] **Step 5: 新增 `update_document` 端点**

在 `apps/luna-corpus/app/api/routes.py` 的 `create_document` 函数之后插入：

```python
@router.put("/documents/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: str,
    doc: DocumentCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_WRITE)),
    ],
) -> DocumentResponse:
    """Update a document by id with content change detection.

    Same content -> unchanged (no re-index); changed -> updated (version+1,
    async re-index). 404 if the document is missing or outside this KB.
    """
    existing = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.knowledge_base_id == context.knowledge_base.id,
        )
        .first()
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Document not found")

    new_hash = compute_content_hash(doc.content)
    if existing.content_hash == new_hash:
        change_type = ChangeType.UNCHANGED.value
    else:
        existing.title = doc.title
        existing.content = doc.content
        existing.content_hash = new_hash
        existing.version = existing.version + 1
        existing.source = doc.source
        existing.has_tables = "|" in doc.content and "---" in doc.content
        existing.has_code = "```" in doc.content or "def " in doc.content
        existing.status = ContentStatus.PENDING
        if doc.external_id:
            existing.external_id = doc.external_id
        AuditService().record(
            db,
            action=AuditAction.DOCUMENT_UPDATE,
            resource_type="document",
            resource_id=existing.id,
            result=AuditResult.SUCCESS,
            context=context,
        )
        db.commit()
        db.refresh(existing)
        task_service = TaskService()
        task = task_service.create_task(
            db, TaskType.DOCUMENT_INDEX, existing.id, context.knowledge_base.id
        )
        background_tasks.add_task(_run_index_task, task.id, existing.id)
        change_type = ChangeType.UPDATED.value

    return DocumentResponse(
        id=existing.id,
        title=existing.title,
        source=existing.source,
        content=existing.content,
        has_tables=existing.has_tables,
        has_code=existing.has_code,
        status=existing.status.value,
        version=existing.version,
        external_id=existing.external_id,
        change_type=change_type,
        created_at=existing.created_at.isoformat(),
        updated_at=existing.updated_at.isoformat(),
    )
```

（`ContentStatus`、`TaskType`、`TaskService`、`_run_index_task`、`BackgroundTasks` 均已在 routes.py 使用/导入。）

- [ ] **Step 6: 确保 import**

编辑 `apps/luna-corpus/app/api/routes.py` 顶部 import：确认存在

```python
from app.services.document_identity import (
    ChangeType,
    compute_content_hash,
    resolve_document_identity,
)
```

（Task 3 已引入 `ChangeType`；此处将 import 补全为三个符号。）

- [ ] **Step 7: 运行文档版本 API 测试**

Run: `cd apps/luna-corpus && python -m pytest tests/api/test_document_versioning_api.py -v`
Expected: PASS（5 passed）

- [ ] **Step 8: 提交**

```bash
git add apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/api/test_document_versioning_api.py
git commit -m "feat(corpus): PUT /documents change detection and external_id on create"
```

---

### Task 5: 移除 `duplicate_policy` 配置与 `DuplicateFileError`（清理）

**Files:**
- Modify: `apps/luna-corpus/app/core/config.py:251-254`
- Modify: `apps/luna-corpus/app/services/ingestion/exceptions.py`
- Modify: `apps/luna-corpus/app/services/ingestion/__init__.py`（若导出 `DuplicateFileError`）
- Test: 全量回归

**Interfaces:**
- Consumes: Task 3/4 已移除所有 `duplicate_policy`/`DuplicateFileError` 的运行时使用。
- Produces: 配置与异常表面清理，无残留引用。

- [ ] **Step 1: 确认无运行时引用残留**

Run: `cd apps/luna-corpus && grep -rn "duplicate_policy\|DuplicateFileError\|upload_duplicate_policy" app/ tests/`
Expected: 仅剩 `app/core/config.py`、`app/services/ingestion/exceptions.py`、可能的 `app/services/ingestion/__init__.py` 中的**定义**；无 `app/api`、`app/services/ingestion/service.py`、`tests/` 的使用（若 `tests/` 仍有引用，说明前序任务遗漏，回到对应任务修复）。

- [ ] **Step 2: 移除 config 字段**

编辑 `apps/luna-corpus/app/core/config.py`，删除：

```python
    upload_duplicate_policy: str = Field(
        default="reject",
        description="Duplicate file policy: reject or replace",
    )
```

- [ ] **Step 3: 移除 `DuplicateFileError` 类**

编辑 `apps/luna-corpus/app/services/ingestion/exceptions.py`，删除：

```python
class DuplicateFileError(IngestionError):
    """Raised when a duplicate file is detected and policy is reject."""

    pass
```

- [ ] **Step 4: 清理 `__init__` 导出（若有）**

Run: `cd apps/luna-corpus && grep -n "DuplicateFileError" app/services/ingestion/__init__.py`
若有匹配行，编辑 `apps/luna-corpus/app/services/ingestion/__init__.py` 删除对应 import/`__all__` 条目；无匹配则跳过。

- [ ] **Step 5: 再次确认无残留**

Run: `cd apps/luna-corpus && grep -rn "duplicate_policy\|DuplicateFileError\|upload_duplicate_policy" app/ tests/`
Expected: 无输出

- [ ] **Step 6: 全量回归**

Run: `cd apps/luna-corpus && python -m pytest -q`
Expected: 全部通过（无 import 错误、无失败）

- [ ] **Step 7: 提交**

```bash
git add apps/luna-corpus/app/core/config.py apps/luna-corpus/app/services/ingestion/exceptions.py apps/luna-corpus/app/services/ingestion/__init__.py
git commit -m "chore(corpus): remove duplicate_policy config and DuplicateFileError"
```

---

## Self-Review

**Spec coverage：**
- 三级身份匹配（document_id/external_id/original_name）→ Task 2 `resolve_document_identity` + Task 4 PUT 主键定位。✅
- content_hash 基于正文 → Task 2 `compute_content_hash`（对 `parsed_text`/`doc.content`）。✅
- 三态 created/updated/unchanged → Task 3（上传）+ Task 4（PUT/POST）。✅
- 原地更新、version+1、不留历史 → Task 3 updated 分支 + Task 4 PUT。✅
- 旧 chunks 删除重建 → 复用 `process_document`（异步任务），无需改。✅
- 旧存储文件删除 → Task 3 `_discard_upload`（updated/unchanged）。✅
- 显式 PUT + 重新上传自动匹配 → Task 4 + Task 3。✅
- 更新走异步索引链路 → Task 3/4 均 `create_task` + `_run_index_task`。✅
- 移除全局 hash 去重与 duplicate_policy → Task 3（逻辑）+ Task 5（配置/异常）。✅
- external_id 唯一约束 + 409 → Task 1（约束）+ Task 4（POST 409）。✅
- 状态码 created→201 / updated·unchanged→200 → Task 3（`response.status_code`）+ Task 4（PUT 默认 200）。✅
- 审计 DOCUMENT_UPDATE/CREATE，unchanged 不记 → Task 3（上传分支内）+ Task 4（PUT/POST）。✅
- 存量文档 content_hash=NULL 首次更新回填 → Task 3 updated 分支（`existing.content_hash` 从 None 变为新 hash，None != hash 触发 updated）+ Task 4 PUT 同理。✅
- Alembic 迁移 + 禁用 create_all → Task 1。✅

**Placeholder scan：** 无 TBD/TODO；所有代码步骤含完整代码。✅

**Type consistency：** `ingest_file` 三元组返回在 Task 3 定义、Task 3 route 消费一致；`ChangeType.value` 字符串在 Task 2 定义，Task 3/4 统一用 `.value` 比较；`compute_content_hash`/`resolve_document_identity` 签名在 Task 2 定义，Task 3/4 调用参数一致（关键字参数 `external_id=`/`original_name=`）。✅

**注意（实现者需知）：** 存量文档若 `content_hash IS NULL`，PUT/上传更新时 `None != new_hash` 判定为 `updated`（version 由默认 1 → 2），符合「首次更新回填」预期，不会误判为 unchanged。
