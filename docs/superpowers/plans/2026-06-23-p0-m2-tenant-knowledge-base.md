# P0-M2 Tenant Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tenant, workspace, and knowledge-base context to `luna-corpus` so documents, conversations, and RAG retrieval are isolated by knowledge base.

**Architecture:** Add SQLAlchemy models for `Tenant`, `Workspace`, and `KnowledgeBase`; bind `Document` and `Conversation` to `KnowledgeBase`; and validate a temporary request context from `X-Tenant-Id`, `X-Workspace-Id`, and `X-Knowledge-Base-Id`. Keep Chroma as one collection and isolate retrieval by writing and querying `knowledge_base_id` metadata.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLAlchemy 2, Alembic, Chroma, LangGraph, Nx, uv, pytest.

## Global Constraints

- Do not implement User, Membership, Role, Permission, or RBAC.
- Do not implement JWT/OIDC, login, session authentication, or API keys.
- Header context is temporary routing context, not an authorization proof.
- Use `X-Tenant-Id`, `X-Workspace-Id`, and `X-Knowledge-Base-Id` for knowledge-base isolated API paths.
- `Document` and `Conversation` must have non-null `knowledge_base_id`.
- `Chunk` inherits knowledge-base ownership through `Document`; do not add `knowledge_base_id` to `chunks` SQL table.
- `Message` inherits knowledge-base ownership through `Conversation`; do not add `knowledge_base_id` to `messages` SQL table.
- Chroma metadata must include `knowledge_base_id`; query paths must filter by `knowledge_base_id` and must not fall back to global retrieval.
- Prefer `pnpm nx run luna-corpus:<target>` over direct tool commands for tests, lint, and migration checks.
- Do not guess Nx flags; use existing project targets and focused pytest args passed after `-- --`.

---

## File Structure

- Modify `apps/luna-corpus/app/db/models.py`: add `Tenant`, `Workspace`, `KnowledgeBase`; add `knowledge_base_id` relationships to `Document` and `Conversation`.
- Modify `apps/luna-corpus/tests/db/test_models.py`: add model tests for hierarchy, uniqueness, and knowledge-base ownership.
- Create `apps/luna-corpus/alembic/versions/20260623_0002_tenant_knowledge_base_context.py`: add P0-M2 schema migration and default hierarchy backfill.
- Modify `apps/luna-corpus/tests/db/test_alembic_config.py`: assert the P0-M2 migration exists and contains required schema/backfill operations.
- Create `apps/luna-corpus/app/api/context.py`: request context dependency that validates tenant/workspace/knowledge-base headers.
- Create `apps/luna-corpus/tests/api/test_context.py`: dependency tests for missing headers, not found resources, mismatches, and valid context.
- Create `apps/luna-corpus/app/api/tenant_routes.py`: minimal tenant/workspace/knowledge-base creation and listing routes.
- Create `apps/luna-corpus/tests/api/test_tenant_routes.py`: API tests for tenant structure endpoints.
- Modify `apps/luna-corpus/app/api/routes.py`: require request context for document and QA paths; filter documents and conversations by knowledge base.
- Create `apps/luna-corpus/tests/api/test_document_context.py`: tests for document creation/listing/access isolation.
- Create `apps/luna-corpus/tests/api/test_conversation_context.py`: tests for conversation creation/access isolation.
- Modify `apps/luna-corpus/app/services/document_processor.py`: pass `knowledge_base_id` into Chroma chunk metadata.
- Modify `apps/luna-corpus/app/db/vectorstore.py`: accept and apply `knowledge_base_id` metadata/filter.
- Modify `apps/luna-corpus/tests/db/test_vectorstore.py`: assert Chroma metadata and filter behavior.
- Modify `apps/luna-corpus/app/graph/state.py`: add `knowledge_base_id` to `RAGState`.
- Modify `apps/luna-corpus/app/graph/rag_graph.py`: thread `knowledge_base_id` through non-streaming, streaming, and multi-turn retrieval.
- Create `apps/luna-corpus/tests/graph/test_knowledge_base_filter.py`: focused tests for RAG/vectorstore filter propagation.
- Modify `apps/luna-corpus/app/services/memory.py`: require `knowledge_base_id` when creating conversations; support scoped conversation lookup.
- Modify `apps/luna-corpus/README.md`: document header context and default hierarchy behavior.
- Modify `apps/luna-corpus/tests/test_docs.py`: assert README documents P0-M2 header context.

---

### Task 1: Add Tenant, Workspace, and KnowledgeBase Models

**Files:**
- Modify: `apps/luna-corpus/app/db/models.py`
- Modify: `apps/luna-corpus/tests/db/test_models.py`

**Interfaces:**
- Produces: `Tenant`, `Workspace`, `KnowledgeBase` SQLAlchemy models.
- Produces: `Document.knowledge_base_id: str` and `Document.knowledge_base: KnowledgeBase`.
- Produces: `Conversation.knowledge_base_id: str` and `Conversation.knowledge_base: KnowledgeBase`.
- Produces: relationship names `Tenant.workspaces`, `Workspace.tenant`, `Workspace.knowledge_bases`, `KnowledgeBase.workspace`, `KnowledgeBase.documents`, `KnowledgeBase.conversations`.

- [ ] **Step 1: Write failing model tests**

Append these tests to `apps/luna-corpus/tests/db/test_models.py` and update its import to include `Conversation`, `KnowledgeBase`, `Tenant`, and `Workspace`:

```python
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Base,
    Chunk,
    ContentStatus,
    ContentType,
    Conversation,
    Document,
    KnowledgeBase,
    Tenant,
    Workspace,
)


def create_knowledge_base(db_session):
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="Research", slug="research", tenant=tenant)
    knowledge_base = KnowledgeBase(
        name="Docs",
        slug="docs",
        description="Product documentation",
        workspace=workspace,
    )
    db_session.add(knowledge_base)
    db_session.commit()
    return tenant, workspace, knowledge_base


def test_tenant_workspace_knowledge_base_hierarchy(db_session):
    tenant, workspace, knowledge_base = create_knowledge_base(db_session)

    assert tenant.id is not None
    assert workspace.tenant_id == tenant.id
    assert knowledge_base.workspace_id == workspace.id
    assert tenant.workspaces == [workspace]
    assert workspace.knowledge_bases == [knowledge_base]


def test_workspace_slug_unique_per_tenant(db_session):
    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()

    db_session.add_all([
        Workspace(name="One", slug="docs", tenant_id=tenant.id),
        Workspace(name="Two", slug="docs", tenant_id=tenant.id),
    ])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_knowledge_base_slug_unique_per_workspace(db_session):
    tenant, workspace, _ = create_knowledge_base(db_session)

    db_session.add_all([
        KnowledgeBase(name="One", slug="duplicate", workspace_id=workspace.id),
        KnowledgeBase(name="Two", slug="duplicate", workspace_id=workspace.id),
    ])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_document_belongs_to_knowledge_base(db_session):
    _, _, knowledge_base = create_knowledge_base(db_session)

    doc = Document(
        title="Scoped Document",
        content="Scoped content",
        knowledge_base_id=knowledge_base.id,
    )
    db_session.add(doc)
    db_session.commit()

    assert doc.knowledge_base_id == knowledge_base.id
    assert doc.knowledge_base == knowledge_base
    assert knowledge_base.documents == [doc]


def test_conversation_belongs_to_knowledge_base(db_session):
    _, _, knowledge_base = create_knowledge_base(db_session)

    conversation = Conversation(
        title="Scoped Conversation",
        knowledge_base_id=knowledge_base.id,
    )
    db_session.add(conversation)
    db_session.commit()

    assert conversation.knowledge_base_id == knowledge_base.id
    assert conversation.knowledge_base == knowledge_base
    assert knowledge_base.conversations == [conversation]
```

- [ ] **Step 2: Update existing model tests to create a knowledge base**

In `apps/luna-corpus/tests/db/test_models.py`, update existing `Document(...)` calls so every document has `knowledge_base_id=create_knowledge_base(db_session)[2].id`. Example replacement for `test_document_creation`:

```python
def test_document_creation(db_session):
    _, _, knowledge_base = create_knowledge_base(db_session)
    doc = Document(
        title="Test Document",
        content="This is test content.",
        source="test://example",
        knowledge_base_id=knowledge_base.id,
    )
    db_session.add(doc)
    db_session.commit()

    assert doc.id is not None
    assert doc.title == "Test Document"
    assert doc.status == ContentStatus.PENDING
    assert doc.created_at is not None
```

Apply the same pattern in `test_chunk_creation`, `test_chunk_with_metadata`, and `test_document_chunks_relationship`.

- [ ] **Step 3: Run model tests to verify they fail**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/db/test_models.py -v`

Expected: FAIL with import errors for `Tenant`, `Workspace`, or `KnowledgeBase`, or constructor errors for `knowledge_base_id`.

- [ ] **Step 4: Implement SQLAlchemy models and relationships**

Modify `apps/luna-corpus/app/db/models.py` imports to include `UniqueConstraint`:

```python
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
```

Add these classes after `MessageRole` and before `Document`:

```python
class Tenant(Base):
    """Tenant boundary for workspaces."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    workspaces: Mapped[list["Workspace"]] = relationship(
        "Workspace", back_populates="tenant", cascade="all, delete-orphan"
    )


class Workspace(Base):
    """Workspace within a tenant."""

    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="workspaces")
    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(
        "KnowledgeBase", back_populates="workspace", cascade="all, delete-orphan"
    )


class KnowledgeBase(Base):
    """Knowledge base within a workspace."""

    __tablename__ = "knowledge_bases"
    __table_args__ = (UniqueConstraint("workspace_id", "slug"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped[Workspace] = relationship(
        "Workspace", back_populates="knowledge_bases"
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="knowledge_base", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="knowledge_base", cascade="all, delete-orphan"
    )
```

Add this field and relationship to `Document`:

```python
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
```

```python
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase", back_populates="documents"
    )
```

Add this field and relationship to `Conversation`:

```python
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
```

```python
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase", back_populates="conversations"
    )
```

- [ ] **Step 5: Run model tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/db/test_models.py -v`

Expected: PASS for all model tests.

- [ ] **Step 6: Run existing integration import test**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/test_integration.py::test_api_routes_import apps/luna-corpus/tests/test_integration.py::test_main_app_import -v`

Expected: PASS; adding models does not break app imports.

- [ ] **Step 7: Commit**

```bash
git add apps/luna-corpus/app/db/models.py apps/luna-corpus/tests/db/test_models.py
git commit -m "feat(corpus): add tenant knowledge base models"
```

---

### Task 2: Add P0-M2 Alembic Migration

**Files:**
- Create: `apps/luna-corpus/alembic/versions/20260623_0002_tenant_knowledge_base_context.py`
- Modify: `apps/luna-corpus/tests/db/test_alembic_config.py`

**Interfaces:**
- Consumes: models from Task 1.
- Produces: Alembic revision id `20260623_0002` with `down_revision = "20260622_0001"`.
- Produces: default hierarchy ids `00000000-0000-0000-0000-000000000001`, `00000000-0000-0000-0000-000000000002`, `00000000-0000-0000-0000-000000000003`.

- [ ] **Step 1: Write failing migration tests**

Append these tests to `apps/luna-corpus/tests/db/test_alembic_config.py`:

```python

def test_tenant_context_migration_exists():
    project_root = Path(__file__).parents[2]
    migration_path = (
        project_root
        / "alembic"
        / "versions"
        / "20260623_0002_tenant_knowledge_base_context.py"
    )

    assert migration_path.is_file()


def test_tenant_context_migration_defines_required_schema():
    project_root = Path(__file__).parents[2]
    migration_path = (
        project_root
        / "alembic"
        / "versions"
        / "20260623_0002_tenant_knowledge_base_context.py"
    )
    migration_source = migration_path.read_text()

    for table_name in ["tenants", "workspaces", "knowledge_bases"]:
        assert f'op.create_table("{table_name}"' in migration_source

    assert 'op.add_column("documents", sa.Column("knowledge_base_id"' in migration_source
    assert 'op.add_column("conversations", sa.Column("knowledge_base_id"' in migration_source
    assert "default-tenant" in migration_source
    assert "default-workspace" in migration_source
    assert "default-knowledge-base" in migration_source
```

- [ ] **Step 2: Run migration tests to verify they fail**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/db/test_alembic_config.py -v`

Expected: FAIL because the P0-M2 migration file does not exist.

- [ ] **Step 3: Create the migration file**

Create `apps/luna-corpus/alembic/versions/20260623_0002_tenant_knowledge_base_context.py` with:

```python
"""Tenant knowledge base context.

Revision ID: 20260623_0002
Revises: 20260622_0001
Create Date: 2026-06-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "20260623_0002"
down_revision: str | None = "20260622_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000002"
DEFAULT_KNOWLEDGE_BASE_ID = "00000000-0000-0000-0000-000000000003"


def timestamp_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("tenant_id", mysql.CHAR(36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "slug"),
    )
    op.create_table(
        "knowledge_bases",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("workspace_id", mysql.CHAR(36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "slug"),
    )

    tenants = sa.table(
        "tenants",
        sa.column("id", mysql.CHAR(36)),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
    )
    workspaces = sa.table(
        "workspaces",
        sa.column("id", mysql.CHAR(36)),
        sa.column("tenant_id", mysql.CHAR(36)),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
    )
    knowledge_bases = sa.table(
        "knowledge_bases",
        sa.column("id", mysql.CHAR(36)),
        sa.column("workspace_id", mysql.CHAR(36)),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("description", sa.Text()),
    )

    op.bulk_insert(
        tenants,
        [{"id": DEFAULT_TENANT_ID, "name": "Default Tenant", "slug": "default-tenant"}],
    )
    op.bulk_insert(
        workspaces,
        [
            {
                "id": DEFAULT_WORKSPACE_ID,
                "tenant_id": DEFAULT_TENANT_ID,
                "name": "Default Workspace",
                "slug": "default-workspace",
            }
        ],
    )
    op.bulk_insert(
        knowledge_bases,
        [
            {
                "id": DEFAULT_KNOWLEDGE_BASE_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "name": "Default Knowledge Base",
                "slug": "default-knowledge-base",
                "description": "Default knowledge base for existing records",
            }
        ],
    )

    op.add_column(
        "documents",
        sa.Column("knowledge_base_id", mysql.CHAR(36), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE documents SET knowledge_base_id = :knowledge_base_id "
            "WHERE knowledge_base_id IS NULL"
        ).bindparams(knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID)
    )
    op.alter_column("documents", "knowledge_base_id", nullable=False)
    op.create_foreign_key(
        "fk_documents_knowledge_base_id_knowledge_bases",
        "documents",
        "knowledge_bases",
        ["knowledge_base_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_documents_knowledge_base_id",
        "documents",
        ["knowledge_base_id"],
    )

    op.add_column(
        "conversations",
        sa.Column("knowledge_base_id", mysql.CHAR(36), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE conversations SET knowledge_base_id = :knowledge_base_id "
            "WHERE knowledge_base_id IS NULL"
        ).bindparams(knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID)
    )
    op.alter_column("conversations", "knowledge_base_id", nullable=False)
    op.create_foreign_key(
        "fk_conversations_knowledge_base_id_knowledge_bases",
        "conversations",
        "knowledge_bases",
        ["knowledge_base_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_conversations_knowledge_base_id",
        "conversations",
        ["knowledge_base_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_knowledge_base_id", table_name="conversations")
    op.drop_constraint(
        "fk_conversations_knowledge_base_id_knowledge_bases",
        "conversations",
        type_="foreignkey",
    )
    op.drop_column("conversations", "knowledge_base_id")

    op.drop_index("ix_documents_knowledge_base_id", table_name="documents")
    op.drop_constraint(
        "fk_documents_knowledge_base_id_knowledge_bases",
        "documents",
        type_="foreignkey",
    )
    op.drop_column("documents", "knowledge_base_id")

    op.drop_table("knowledge_bases")
    op.drop_table("workspaces")
    op.drop_table("tenants")
```

- [ ] **Step 4: Run migration structure tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/db/test_alembic_config.py -v`

Expected: PASS for all Alembic structure tests.

- [ ] **Step 5: Run model tests again**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/db/test_models.py -v`

Expected: PASS; model metadata and migration assumptions remain aligned.

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/alembic/versions/20260623_0002_tenant_knowledge_base_context.py apps/luna-corpus/tests/db/test_alembic_config.py
git commit -m "feat(corpus): add tenant knowledge base migration"
```

---

### Task 3: Add Request Context Dependency

**Files:**
- Create: `apps/luna-corpus/app/api/context.py`
- Create: `apps/luna-corpus/tests/api/test_context.py`
- Create: `apps/luna-corpus/tests/api/__init__.py`

**Interfaces:**
- Consumes: `Tenant`, `Workspace`, `KnowledgeBase` from Task 1.
- Produces: `RequestContext` dataclass with fields `tenant`, `workspace`, `knowledge_base`.
- Produces: `get_request_context(db: Session, x_tenant_id: str | None, x_workspace_id: str | None, x_knowledge_base_id: str | None) -> RequestContext`.
- Produces: `require_request_context(...) -> RequestContext` FastAPI dependency wrapper.

- [ ] **Step 1: Write failing request context tests**

Create directory `apps/luna-corpus/tests/api` and file `apps/luna-corpus/tests/api/__init__.py`.

Create `apps/luna-corpus/tests/api/test_context.py` with:

```python
"""Tests for request knowledge-base context."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.context import get_request_context
from app.db.models import Base, KnowledgeBase, Tenant, Workspace


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def create_context_records(db_session):
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="Research", slug="research", tenant=tenant)
    knowledge_base = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    db_session.add(knowledge_base)
    db_session.commit()
    return tenant, workspace, knowledge_base


@pytest.mark.parametrize(
    ("tenant_id", "workspace_id", "knowledge_base_id", "missing"),
    [
        (None, "workspace", "kb", "X-Tenant-Id"),
        ("tenant", None, "kb", "X-Workspace-Id"),
        ("tenant", "workspace", None, "X-Knowledge-Base-Id"),
    ],
)
def test_get_request_context_rejects_missing_headers(
    db_session,
    tenant_id,
    workspace_id,
    knowledge_base_id,
    missing,
):
    with pytest.raises(HTTPException) as exc_info:
        get_request_context(db_session, tenant_id, workspace_id, knowledge_base_id)

    assert exc_info.value.status_code == 400
    assert missing in exc_info.value.detail


def test_get_request_context_rejects_unknown_context(db_session):
    with pytest.raises(HTTPException) as exc_info:
        get_request_context(db_session, "missing", "missing", "missing")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Knowledge base context not found"


def test_get_request_context_rejects_workspace_tenant_mismatch(db_session):
    tenant, workspace, knowledge_base = create_context_records(db_session)
    other_tenant = Tenant(name="Other", slug="other")
    db_session.add(other_tenant)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_request_context(
            db_session,
            other_tenant.id,
            workspace.id,
            knowledge_base.id,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Knowledge base context not found"


def test_get_request_context_rejects_knowledge_base_workspace_mismatch(db_session):
    tenant, workspace, knowledge_base = create_context_records(db_session)
    other_workspace = Workspace(name="Other", slug="other", tenant_id=tenant.id)
    db_session.add(other_workspace)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_request_context(
            db_session,
            tenant.id,
            other_workspace.id,
            knowledge_base.id,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Knowledge base context not found"


def test_get_request_context_returns_valid_context(db_session):
    tenant, workspace, knowledge_base = create_context_records(db_session)

    context = get_request_context(
        db_session,
        tenant.id,
        workspace.id,
        knowledge_base.id,
    )

    assert context.tenant == tenant
    assert context.workspace == workspace
    assert context.knowledge_base == knowledge_base
```

- [ ] **Step 2: Run context tests to verify they fail**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/api/test_context.py -v`

Expected: FAIL because `app.api.context` does not exist.

- [ ] **Step 3: Implement context dependency**

Create `apps/luna-corpus/app/api/context.py` with:

```python
"""Request context dependencies for knowledge-base scoped APIs."""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import KnowledgeBase, Tenant, Workspace


@dataclass(frozen=True)
class RequestContext:
    tenant: Tenant
    workspace: Workspace
    knowledge_base: KnowledgeBase


def get_request_context(
    db: Session,
    x_tenant_id: str | None,
    x_workspace_id: str | None,
    x_knowledge_base_id: str | None,
) -> RequestContext:
    missing_headers = []
    if not x_tenant_id:
        missing_headers.append("X-Tenant-Id")
    if not x_workspace_id:
        missing_headers.append("X-Workspace-Id")
    if not x_knowledge_base_id:
        missing_headers.append("X-Knowledge-Base-Id")

    if missing_headers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required header: {', '.join(missing_headers)}",
        )

    tenant = db.query(Tenant).filter(Tenant.id == x_tenant_id).first()
    workspace = db.query(Workspace).filter(Workspace.id == x_workspace_id).first()
    knowledge_base = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.id == x_knowledge_base_id)
        .first()
    )

    if not tenant or not workspace or not knowledge_base:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base context not found",
        )

    if workspace.tenant_id != tenant.id or knowledge_base.workspace_id != workspace.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base context not found",
        )

    return RequestContext(
        tenant=tenant,
        workspace=workspace,
        knowledge_base=knowledge_base,
    )


def require_request_context(
    db: Annotated[Session, Depends(get_db)],
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
    x_knowledge_base_id: Annotated[
        str | None,
        Header(alias="X-Knowledge-Base-Id"),
    ] = None,
) -> RequestContext:
    return get_request_context(
        db=db,
        x_tenant_id=x_tenant_id,
        x_workspace_id=x_workspace_id,
        x_knowledge_base_id=x_knowledge_base_id,
    )
```

- [ ] **Step 4: Run context tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/api/test_context.py -v`

Expected: PASS.

- [ ] **Step 5: Run import test**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/test_integration.py::test_api_routes_import -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/app/api/context.py apps/luna-corpus/tests/api/__init__.py apps/luna-corpus/tests/api/test_context.py
git commit -m "feat(corpus): add knowledge base request context"
```

---

### Task 4: Add Tenant Structure API Routes

**Files:**
- Create: `apps/luna-corpus/app/api/tenant_routes.py`
- Modify: `apps/luna-corpus/app/main.py`
- Create: `apps/luna-corpus/tests/api/test_tenant_routes.py`

**Interfaces:**
- Consumes: `Tenant`, `Workspace`, `KnowledgeBase` from Task 1.
- Produces: router `app.api.tenant_routes.router`.
- Produces: endpoints `POST /api/v1/tenants`, `GET /api/v1/tenants`, `POST /api/v1/workspaces`, `GET /api/v1/workspaces`, `POST /api/v1/knowledge-bases`, `GET /api/v1/knowledge-bases`.

- [ ] **Step 1: Write failing tenant route tests**

Create `apps/luna-corpus/tests/api/test_tenant_routes.py` with:

```python
"""Tests for tenant structure API routes."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base
from app.main import create_app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

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
    engine.dispose()


def test_create_and_list_tenant(client):
    response = client.post(
        "/api/v1/tenants",
        json={"name": "Acme", "slug": "acme"},
    )

    assert response.status_code == 201
    tenant = response.json()
    assert tenant["id"]
    assert tenant["name"] == "Acme"
    assert tenant["slug"] == "acme"

    response = client.get("/api/v1/tenants")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["tenants"][0]["id"] == tenant["id"]


def test_create_and_list_workspace(client):
    tenant = client.post(
        "/api/v1/tenants",
        json={"name": "Acme", "slug": "acme"},
    ).json()

    response = client.post(
        "/api/v1/workspaces",
        json={"tenant_id": tenant["id"], "name": "Research", "slug": "research"},
    )

    assert response.status_code == 201
    workspace = response.json()
    assert workspace["tenant_id"] == tenant["id"]

    response = client.get(f"/api/v1/workspaces?tenant_id={tenant['id']}")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["workspaces"][0]["id"] == workspace["id"]


def test_create_and_list_knowledge_base(client):
    tenant = client.post(
        "/api/v1/tenants",
        json={"name": "Acme", "slug": "acme"},
    ).json()
    workspace = client.post(
        "/api/v1/workspaces",
        json={"tenant_id": tenant["id"], "name": "Research", "slug": "research"},
    ).json()

    response = client.post(
        "/api/v1/knowledge-bases",
        json={
            "workspace_id": workspace["id"],
            "name": "Docs",
            "slug": "docs",
            "description": "Product docs",
        },
    )

    assert response.status_code == 201
    knowledge_base = response.json()
    assert knowledge_base["workspace_id"] == workspace["id"]
    assert knowledge_base["description"] == "Product docs"

    response = client.get(f"/api/v1/knowledge-bases?workspace_id={workspace['id']}")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["knowledge_bases"][0]["id"] == knowledge_base["id"]
```

- [ ] **Step 2: Run tenant route tests to verify they fail**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/api/test_tenant_routes.py -v`

Expected: FAIL with `404 Not Found` for new endpoints.

- [ ] **Step 3: Implement tenant routes**

Create `apps/luna-corpus/app/api/tenant_routes.py` with:

```python
"""Tenant, workspace, and knowledge-base API routes."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import KnowledgeBase, Tenant, Workspace

router = APIRouter(prefix="/api/v1", tags=["tenants"])


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255)


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class TenantListResponse(BaseModel):
    tenants: list[TenantResponse]
    total: int


class WorkspaceCreate(BaseModel):
    tenant_id: str
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255)


class WorkspaceResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceResponse]
    total: int


class KnowledgeBaseCreate(BaseModel):
    workspace_id: str
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class KnowledgeBaseResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    slug: str
    description: str | None

    model_config = ConfigDict(from_attributes=True)


class KnowledgeBaseListResponse(BaseModel):
    knowledge_bases: list[KnowledgeBaseResponse]
    total: int


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(
    tenant: TenantCreate,
    db: Annotated[Session, Depends(get_db)],
) -> TenantResponse:
    db_tenant = Tenant(name=tenant.name, slug=tenant.slug)
    db.add(db_tenant)
    db.commit()
    db.refresh(db_tenant)
    return TenantResponse.model_validate(db_tenant)


@router.get("/tenants", response_model=TenantListResponse)
def list_tenants(db: Annotated[Session, Depends(get_db)]) -> TenantListResponse:
    tenants = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    return TenantListResponse(tenants=tenants, total=len(tenants))


@router.post(
    "/workspaces",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace(
    workspace: WorkspaceCreate,
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceResponse:
    tenant = db.query(Tenant).filter(Tenant.id == workspace.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    db_workspace = Workspace(
        tenant_id=workspace.tenant_id,
        name=workspace.name,
        slug=workspace.slug,
    )
    db.add(db_workspace)
    db.commit()
    db.refresh(db_workspace)
    return WorkspaceResponse.model_validate(db_workspace)


@router.get("/workspaces", response_model=WorkspaceListResponse)
def list_workspaces(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: str | None = Query(default=None),
) -> WorkspaceListResponse:
    query = db.query(Workspace)
    if tenant_id:
        query = query.filter(Workspace.tenant_id == tenant_id)
    workspaces = query.order_by(Workspace.created_at.desc()).all()
    return WorkspaceListResponse(workspaces=workspaces, total=len(workspaces))


@router.post(
    "/knowledge-bases",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_base(
    knowledge_base: KnowledgeBaseCreate,
    db: Annotated[Session, Depends(get_db)],
) -> KnowledgeBaseResponse:
    workspace = (
        db.query(Workspace)
        .filter(Workspace.id == knowledge_base.workspace_id)
        .first()
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    db_knowledge_base = KnowledgeBase(
        workspace_id=knowledge_base.workspace_id,
        name=knowledge_base.name,
        slug=knowledge_base.slug,
        description=knowledge_base.description,
    )
    db.add(db_knowledge_base)
    db.commit()
    db.refresh(db_knowledge_base)
    return KnowledgeBaseResponse.model_validate(db_knowledge_base)


@router.get("/knowledge-bases", response_model=KnowledgeBaseListResponse)
def list_knowledge_bases(
    db: Annotated[Session, Depends(get_db)],
    workspace_id: str | None = Query(default=None),
) -> KnowledgeBaseListResponse:
    query = db.query(KnowledgeBase)
    if workspace_id:
        query = query.filter(KnowledgeBase.workspace_id == workspace_id)
    knowledge_bases = query.order_by(KnowledgeBase.created_at.desc()).all()
    return KnowledgeBaseListResponse(
        knowledge_bases=knowledge_bases,
        total=len(knowledge_bases),
    )
```

- [ ] **Step 4: Include tenant router in FastAPI app**

Modify `apps/luna-corpus/app/main.py` imports:

```python
from app.api.tenant_routes import router as tenant_router
```

Add this include after existing routers in `create_app()`:

```python
    app.include_router(tenant_router)
```

- [ ] **Step 5: Run tenant route tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/api/test_tenant_routes.py -v`

Expected: PASS.

- [ ] **Step 6: Run app import test**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/test_integration.py::test_main_app_import -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/luna-corpus/app/api/tenant_routes.py apps/luna-corpus/app/main.py apps/luna-corpus/tests/api/test_tenant_routes.py
git commit -m "feat(corpus): add tenant structure api"
```

---

### Task 5: Scope Document APIs by Knowledge Base

**Files:**
- Modify: `apps/luna-corpus/app/api/routes.py`
- Create: `apps/luna-corpus/tests/api/test_document_context.py`

**Interfaces:**
- Consumes: `RequestContext` and `require_request_context` from Task 3.
- Consumes: `Document.knowledge_base_id` from Task 1.
- Produces: document endpoints that require valid header context and filter by `context.knowledge_base.id`.

- [ ] **Step 1: Write failing document context tests**

Create `apps/luna-corpus/tests/api/test_document_context.py` with:

```python
"""Tests for knowledge-base scoped document APIs."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, KnowledgeBase, Tenant, Workspace
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
    kb_one = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    kb_two = KnowledgeBase(name="Notes", slug="notes", workspace=workspace)
    session.add_all([kb_one, kb_two])
    session.commit()

    context = {
        "tenant_id": tenant.id,
        "workspace_id": workspace.id,
        "kb_one_id": kb_one.id,
        "kb_two_id": kb_two.id,
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


def headers(context, knowledge_base_id):
    return {
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": knowledge_base_id,
    }


def test_create_document_requires_context(client):
    response = client.post(
        "/api/v1/documents",
        json={"title": "Doc", "content": "Content"},
    )

    assert response.status_code == 400
    assert "X-Tenant-Id" in response.json()["detail"]


def test_document_create_and_list_are_scoped_to_knowledge_base(client, app_db):
    _, _, context = app_db

    created = client.post(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"]),
        json={"title": "Doc One", "content": "Content one"},
    )

    assert created.status_code == 201
    document = created.json()
    assert document["title"] == "Doc One"

    kb_one_list = client.get(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"]),
    )
    kb_two_list = client.get(
        "/api/v1/documents",
        headers=headers(context, context["kb_two_id"]),
    )

    assert kb_one_list.status_code == 200
    assert kb_one_list.json()["total"] == 1
    assert kb_one_list.json()["documents"][0]["id"] == document["id"]
    assert kb_two_list.status_code == 200
    assert kb_two_list.json()["total"] == 0


def test_document_detail_delete_and_process_reject_cross_knowledge_base(client, app_db):
    _, _, context = app_db
    created = client.post(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"]),
        json={"title": "Doc One", "content": "Content one"},
    ).json()

    detail = client.get(
        f"/api/v1/documents/{created['id']}",
        headers=headers(context, context["kb_two_id"]),
    )
    delete = client.delete(
        f"/api/v1/documents/{created['id']}",
        headers=headers(context, context["kb_two_id"]),
    )
    process = client.post(
        f"/api/v1/documents/{created['id']}/process",
        headers=headers(context, context["kb_two_id"]),
    )

    assert detail.status_code == 404
    assert delete.status_code == 404
    assert process.status_code == 404
```

- [ ] **Step 2: Run document context tests to verify they fail**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/api/test_document_context.py -v`

Expected: FAIL because document endpoints do not require context and do not set `knowledge_base_id`.

- [ ] **Step 3: Import request context in routes**

Modify `apps/luna-corpus/app/api/routes.py` imports:

```python
from app.api.context import RequestContext, require_request_context
```

- [ ] **Step 4: Add context dependency to document endpoints**

Update signatures in `apps/luna-corpus/app/api/routes.py`:

```python
async def create_document(
    doc: DocumentCreate,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_request_context)],
) -> DocumentResponse:
```

```python
async def list_documents(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_request_context)],
    status_filter: ContentStatus | None = None,
) -> DocumentListResponse:
```

```python
async def get_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_request_context)],
) -> DocumentResponse:
```

```python
async def delete_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_request_context)],
) -> None:
```

```python
async def process_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_request_context)],
) -> ProcessResponse:
```

- [ ] **Step 5: Scope document queries and writes**

In `create_document`, add `knowledge_base_id`:

```python
    db_doc = Document(
        title=doc.title,
        content=doc.content,
        source=doc.source,
        has_tables="|" in doc.content and "---" in doc.content,
        has_code="```" in doc.content or "def " in doc.content,
        knowledge_base_id=context.knowledge_base.id,
    )
```

In `list_documents`, replace the query initialization with:

```python
    query = db.query(Document).filter(
        Document.knowledge_base_id == context.knowledge_base.id
    )
```

In `get_document`, `delete_document`, and `process_document`, replace document lookup with:

```python
    doc = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.knowledge_base_id == context.knowledge_base.id,
        )
        .first()
    )
```

- [ ] **Step 6: Run document context tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/api/test_document_context.py -v`

Expected: PASS.

- [ ] **Step 7: Run existing document processor tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/services/test_document_processor.py -v`

Expected: PASS after updating any test document fixtures in that file to create a knowledge base and pass `knowledge_base_id`.

If this test fails with `NOT NULL constraint failed: documents.knowledge_base_id`, update its document fixtures using the same helper pattern from Task 1:

```python
tenant = Tenant(name="Acme", slug="acme")
workspace = Workspace(name="Research", slug="research", tenant=tenant)
knowledge_base = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
db_session.add(knowledge_base)
db_session.commit()

document = Document(
    title="Test",
    content="Content",
    knowledge_base_id=knowledge_base.id,
)
```

- [ ] **Step 8: Commit**

```bash
git add apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/api/test_document_context.py apps/luna-corpus/tests/services/test_document_processor.py
git commit -m "feat(corpus): scope document api by knowledge base"
```

---

### Task 6: Add Knowledge Base Metadata and Filters to Vector Retrieval

**Files:**
- Modify: `apps/luna-corpus/app/db/vectorstore.py`
- Modify: `apps/luna-corpus/app/services/document_processor.py`
- Modify: `apps/luna-corpus/app/graph/state.py`
- Modify: `apps/luna-corpus/app/graph/rag_graph.py`
- Modify: `apps/luna-corpus/tests/db/test_vectorstore.py`
- Create: `apps/luna-corpus/tests/graph/test_knowledge_base_filter.py`

**Interfaces:**
- Consumes: `Document.knowledge_base_id` from Task 1.
- Produces: `add_chunks_to_vectorstore(chunks: list[dict[str, Any]], embeddings: list[list[float]]) -> None` requiring each chunk dict to include `knowledge_base_id`.
- Produces: `search_vectorstore(query_embedding: list[float], top_k: int | None = None, knowledge_base_id: str | None = None) -> list[dict[str, Any]]`.
- Produces: `answer_question(question: str, knowledge_base_id: str) -> dict[str, Any]`.
- Produces: `answer_question_stream(question: str, knowledge_base_id: str) -> AsyncGenerator[dict[str, Any], None]`.
- Produces: `answer_question_multi_turn(question: str, knowledge_base_id: str, conversation_id: str | None = None, include_history: bool = True) -> dict[str, Any]`.
- Produces: `answer_question_multi_turn_stream(question: str, knowledge_base_id: str, conversation_id: str | None = None, include_history: bool = True) -> AsyncGenerator[dict[str, Any], None]`.

- [ ] **Step 1: Update vectorstore tests for metadata filter**

Modify chunks in `apps/luna-corpus/tests/db/test_vectorstore.py` to include `knowledge_base_id`:

```python
chunks = [
    {
        "id": "chunk-1",
        "document_id": "doc-1",
        "knowledge_base_id": "kb-1",
        "content": "First chunk",
    },
    {
        "id": "chunk-2",
        "document_id": "doc-1",
        "knowledge_base_id": "kb-1",
        "content": "Second chunk",
    },
]
```

Add this test to the file:

```python

def test_search_vectorstore_filters_by_knowledge_base(temp_chroma_dir, monkeypatch):
    from app.db import vectorstore

    monkeypatch.setattr(
        vectorstore, "settings", Settings(chroma_data_dir=temp_chroma_dir)
    )

    chunks = [
        {
            "id": "chunk-1",
            "document_id": "doc-1",
            "knowledge_base_id": "kb-1",
            "content": "Python code",
        },
        {
            "id": "chunk-2",
            "document_id": "doc-2",
            "knowledge_base_id": "kb-2",
            "content": "JavaScript code",
        },
    ]
    embeddings = [[0.1, 0.1, 0.1], [0.1, 0.1, 0.1]]
    vectorstore.add_chunks_to_vectorstore(chunks, embeddings)

    results = vectorstore.search_vectorstore(
        [0.1, 0.1, 0.1],
        top_k=2,
        knowledge_base_id="kb-1",
    )

    assert len(results) == 1
    assert results[0]["document_id"] == "doc-1"
```

- [ ] **Step 2: Write failing RAG filter propagation tests**

Create `apps/luna-corpus/tests/graph/test_knowledge_base_filter.py` with:

```python
"""Tests for knowledge-base filter propagation in RAG flows."""

from unittest.mock import patch

from app.graph import rag_graph


def test_retrieve_node_passes_knowledge_base_filter():
    with patch("app.graph.rag_graph.embed_text", return_value=[0.1]), patch(
        "app.graph.rag_graph.search_vectorstore",
        return_value=[],
    ) as search:
        rag_graph.retrieve_node({"question": "What?", "knowledge_base_id": "kb-1"})

    search.assert_called_once_with(
        query_embedding=[0.1],
        top_k=rag_graph.settings.retrieval_top_k,
        knowledge_base_id="kb-1",
    )


def test_answer_question_sets_knowledge_base_id_in_graph_state():
    class FakeGraph:
        def invoke(self, state):
            assert state["knowledge_base_id"] == "kb-1"
            return {"answer": "Answer", "sources": []}

    with patch("app.graph.rag_graph.get_rag_graph", return_value=FakeGraph()):
        result = rag_graph.answer_question("What?", knowledge_base_id="kb-1")

    assert result["answer"] == "Answer"
```

- [ ] **Step 3: Run vectorstore and RAG tests to verify they fail**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/db/test_vectorstore.py apps/luna-corpus/tests/graph/test_knowledge_base_filter.py -v`

Expected: FAIL because vectorstore does not store/filter `knowledge_base_id` and RAG signatures do not accept it.

- [ ] **Step 4: Update vectorstore metadata and filter**

Modify `apps/luna-corpus/app/db/vectorstore.py` metadata creation:

```python
    metadatas = [
        {
            "chunk_id": chunk["id"],
            "document_id": chunk["document_id"],
            "knowledge_base_id": chunk["knowledge_base_id"],
        }
        for chunk in chunks
    ]
```

Modify `search_vectorstore` signature and query call:

```python
def search_vectorstore(
    query_embedding: list[float],
    top_k: int | None = None,
    knowledge_base_id: str | None = None,
) -> list[dict[str, Any]]:
```

```python
    query_kwargs: dict[str, Any] = {
        "query_embeddings": [query_embedding],
        "n_results": top_k,
    }
    if knowledge_base_id is not None:
        query_kwargs["where"] = {"knowledge_base_id": knowledge_base_id}

    results = collection.query(**query_kwargs)
```

- [ ] **Step 5: Update DocumentProcessor chunk payloads**

In `apps/luna-corpus/app/services/document_processor.py`, modify the `add_chunks_to_vectorstore` chunk dict:

```python
                chunks=[
                    {
                        "id": c.id,
                        "document_id": c.document_id,
                        "knowledge_base_id": document.knowledge_base_id,
                        "content": c.content,
                    }
                    for c in chunks
                ],
```

- [ ] **Step 6: Update RAG state and retrieval signatures**

In `apps/luna-corpus/app/graph/state.py`, add this field to `RAGState`:

```python
    knowledge_base_id: str | None
```

In `apps/luna-corpus/app/graph/rag_graph.py`, update `retrieve_node`:

```python
    knowledge_base_id = state.get("knowledge_base_id")
```

```python
    results = search_vectorstore(
        query_embedding=query_embedding,
        top_k=settings.retrieval_top_k,
        knowledge_base_id=knowledge_base_id,
    )
```

Update `answer_question` signature and graph state:

```python
def answer_question(question: str, knowledge_base_id: str) -> dict[str, Any]:
```

```python
    result = graph.invoke({
        "question": question,
        "knowledge_base_id": knowledge_base_id,
        "conversation_id": None,
        "conversation_history": [],
        "retrieved_docs": [],
        "needs_summarization": False,
    })
```

Update `answer_question_stream` signature and search call:

```python
async def answer_question_stream(
    question: str,
    knowledge_base_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
```

```python
    results = search_vectorstore(
        query_embedding=query_embedding,
        top_k=settings.retrieval_top_k,
        knowledge_base_id=knowledge_base_id,
    )
```

Update `answer_question_multi_turn` signature and state:

```python
def answer_question_multi_turn(
    question: str,
    knowledge_base_id: str,
    conversation_id: str | None = None,
    include_history: bool = True,
) -> dict[str, Any]:
```

```python
    result = graph.invoke({
        "question": question,
        "knowledge_base_id": knowledge_base_id,
        "conversation_id": conversation_id if include_history else None,
        "conversation_history": [],
        "retrieved_docs": [],
        "needs_summarization": False,
    })
```

Update `answer_question_multi_turn_stream` signature and search call:

```python
async def answer_question_multi_turn_stream(
    question: str,
    knowledge_base_id: str,
    conversation_id: str | None = None,
    include_history: bool = True,
) -> AsyncGenerator[dict[str, Any], None]:
```

```python
    results = search_vectorstore(
        query_embedding=query_embedding,
        top_k=settings.retrieval_top_k,
        knowledge_base_id=knowledge_base_id,
    )
```

- [ ] **Step 7: Run vectorstore and RAG tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/db/test_vectorstore.py apps/luna-corpus/tests/graph/test_knowledge_base_filter.py -v`

Expected: PASS.

- [ ] **Step 8: Run document processor tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/services/test_document_processor.py -v`

Expected: PASS; processor now includes `knowledge_base_id` in vector metadata.

- [ ] **Step 9: Commit**

```bash
git add apps/luna-corpus/app/db/vectorstore.py apps/luna-corpus/app/services/document_processor.py apps/luna-corpus/app/graph/state.py apps/luna-corpus/app/graph/rag_graph.py apps/luna-corpus/tests/db/test_vectorstore.py apps/luna-corpus/tests/graph/test_knowledge_base_filter.py
git commit -m "feat(corpus): filter retrieval by knowledge base"
```

---

### Task 7: Scope QA and Conversation APIs by Knowledge Base

**Files:**
- Modify: `apps/luna-corpus/app/api/routes.py`
- Modify: `apps/luna-corpus/app/services/memory.py`
- Create: `apps/luna-corpus/tests/api/test_conversation_context.py`

**Interfaces:**
- Consumes: `RequestContext` from Task 3.
- Consumes: RAG functions updated in Task 6.
- Produces: `create_conversation(db: Session, knowledge_base_id: str, title: str | None = None) -> Conversation`.
- Produces: `get_conversation(db: Session, conversation_id: str, knowledge_base_id: str | None = None) -> Conversation | None`.
- Produces: QA and conversation endpoints that reject cross-knowledge-base access.

- [ ] **Step 1: Write failing conversation context tests**

Create `apps/luna-corpus/tests/api/test_conversation_context.py` with:

```python
"""Tests for knowledge-base scoped conversation and QA APIs."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, KnowledgeBase, Tenant, Workspace
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
    kb_one = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    kb_two = KnowledgeBase(name="Notes", slug="notes", workspace=workspace)
    session.add_all([kb_one, kb_two])
    session.commit()

    context = {
        "tenant_id": tenant.id,
        "workspace_id": workspace.id,
        "kb_one_id": kb_one.id,
        "kb_two_id": kb_two.id,
    }
    session.close()

    yield engine, Session, context
    engine.dispose()


@pytest.fixture
def client(app_db):
    _, Session, _ = app_db

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


def headers(context, knowledge_base_id):
    return {
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": knowledge_base_id,
    }


def test_create_conversation_binds_current_knowledge_base(client, app_db):
    _, _, context = app_db

    response = client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"]),
        json={"title": "Chat"},
    )

    assert response.status_code == 201
    conversation = response.json()

    kb_one_response = client.get(
        f"/api/v1/conversations/{conversation['id']}",
        headers=headers(context, context["kb_one_id"]),
    )
    kb_two_response = client.get(
        f"/api/v1/conversations/{conversation['id']}",
        headers=headers(context, context["kb_two_id"]),
    )

    assert kb_one_response.status_code == 200
    assert kb_two_response.status_code == 404


def test_conversation_list_is_scoped_to_knowledge_base(client, app_db):
    _, _, context = app_db
    client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"]),
        json={"title": "Chat"},
    )

    kb_one_response = client.get(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"]),
    )
    kb_two_response = client.get(
        "/api/v1/conversations",
        headers=headers(context, context["kb_two_id"]),
    )

    assert kb_one_response.status_code == 200
    assert kb_one_response.json()["total"] == 1
    assert kb_two_response.status_code == 200
    assert kb_two_response.json()["total"] == 0


def test_qa_query_passes_current_knowledge_base(client, app_db):
    _, _, context = app_db

    with patch(
        "app.api.routes.answer_question",
        return_value={"answer": "Answer", "sources": [], "processing_time_ms": 1},
    ) as answer_question:
        response = client.post(
            "/api/v1/qa/query",
            headers=headers(context, context["kb_one_id"]),
            json={"question": "What?"},
        )

    assert response.status_code == 200
    answer_question.assert_called_once_with("What?", knowledge_base_id=context["kb_one_id"])


def test_multi_turn_rejects_cross_knowledge_base_conversation(client, app_db):
    _, _, context = app_db
    conversation = client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"]),
        json={"title": "Chat"},
    ).json()

    response = client.post(
        "/api/v1/qa/multi-turn",
        headers=headers(context, context["kb_two_id"]),
        json={"question": "What?", "conversation_id": conversation["id"]},
    )

    assert response.status_code == 404
```

- [ ] **Step 2: Run conversation context tests to verify they fail**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/api/test_conversation_context.py -v`

Expected: FAIL because conversation and QA endpoints do not require context.

- [ ] **Step 3: Update memory service signatures**

Modify `apps/luna-corpus/app/services/memory.py` `get_conversation`:

```python
def get_conversation(
    db: Session,
    conversation_id: str,
    knowledge_base_id: str | None = None,
) -> Conversation | None:
    query = db.query(Conversation).filter(Conversation.id == conversation_id)
    if knowledge_base_id is not None:
        query = query.filter(Conversation.knowledge_base_id == knowledge_base_id)
    return query.first()
```

Modify `create_conversation`:

```python
def create_conversation(
    db: Session,
    knowledge_base_id: str,
    title: str | None = None,
) -> Conversation:
    if not title:
        title = f"Conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    conversation = Conversation(title=title, knowledge_base_id=knowledge_base_id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return conversation
```

Keep `delete_conversation`, `clear_conversation_messages`, and `get_memory_context` compatible by allowing `get_conversation` calls without a `knowledge_base_id` inside lower-level memory functions.

- [ ] **Step 4: Add context dependency to QA endpoints**

In `apps/luna-corpus/app/api/routes.py`, update `query`:

```python
async def query(
    question_req: QuestionRequest,
    context: Annotated[RequestContext, Depends(require_request_context)],
) -> AnswerResponse:
    result = answer_question(
        question_req.question,
        knowledge_base_id=context.knowledge_base.id,
    )
```

Update `stream_query`:

```python
async def stream_query(
    question_req: QuestionRequest,
    context: Annotated[RequestContext, Depends(require_request_context)],
):
    return StreamingResponse(
        stream_event_generator(question_req.question, context.knowledge_base.id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

Update `stream_event_generator` signature and call:

```python
async def stream_event_generator(
    question: str,
    knowledge_base_id: str,
) -> AsyncGenerator[str, None]:
```

```python
        async for event in answer_question_stream(question, knowledge_base_id):
```

- [ ] **Step 5: Add context dependency to conversation endpoints**

Update conversation endpoint signatures in `apps/luna-corpus/app/api/routes.py` to include:

```python
    context: Annotated[RequestContext, Depends(require_request_context)],
```

For `create_conversation_endpoint`, call:

```python
    db_conv = create_conversation(db, context.knowledge_base.id, conv.title)
```

For `list_conversations`, initialize the query with:

```python
    query = db.query(Conversation, message_count_subq.c.message_count).outerjoin(
        message_count_subq,
        Conversation.id == message_count_subq.c.conversation_id,
    ).filter(Conversation.knowledge_base_id == context.knowledge_base.id)
```

For `get_conversation_endpoint`, call:

```python
    conv = get_conversation(db, conversation_id, context.knowledge_base.id)
```

Apply the same scoped `get_conversation(db, conversation_id, context.knowledge_base.id)` check in:

- `get_conversation_messages_endpoint`
- `delete_conversation_endpoint`
- `clear_conversation_endpoint`
- `multi_turn_query`
- `stream_multi_turn_query`

- [ ] **Step 6: Update multi-turn creation and RAG calls**

In `multi_turn_query`, replace new conversation creation with:

```python
        db_conv = create_conversation(db, context.knowledge_base.id)
```

Update `answer_question_multi_turn` call:

```python
    result = answer_question_multi_turn(
        question=req.question,
        knowledge_base_id=context.knowledge_base.id,
        conversation_id=conversation_id if req.include_history else None,
        include_history=req.include_history,
    )
```

In `stream_multi_turn_query`, replace new conversation creation with:

```python
        db_conv = create_conversation(db, context.knowledge_base.id)
```

Update stream generator call:

```python
        async for event in answer_question_multi_turn_stream(
            question=req.question,
            knowledge_base_id=context.knowledge_base.id,
            conversation_id=conversation_id if req.include_history else None,
            include_history=req.include_history,
        ):
```

- [ ] **Step 7: Run conversation context tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/api/test_conversation_context.py -v`

Expected: PASS.

- [ ] **Step 8: Run agent and graph tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/graph apps/luna-corpus/tests/agent -v`

Expected: PASS after updating tests that call RAG functions to pass `knowledge_base_id="kb-test"`.

For direct calls in tests, update examples like:

```python
answer_question("What?")
```

to:

```python
answer_question("What?", knowledge_base_id="kb-test")
```

- [ ] **Step 9: Commit**

```bash
git add apps/luna-corpus/app/api/routes.py apps/luna-corpus/app/services/memory.py apps/luna-corpus/tests/api/test_conversation_context.py apps/luna-corpus/tests/graph apps/luna-corpus/tests/agent
git commit -m "feat(corpus): scope qa conversations by knowledge base"
```

---

### Task 8: Document P0-M2 Context and Run Final Verification

**Files:**
- Modify: `apps/luna-corpus/README.md`
- Modify: `apps/luna-corpus/tests/test_docs.py`

**Interfaces:**
- Consumes: all P0-M2 implementation from Tasks 1-7.
- Produces: README documentation for tenant structure APIs and header context.

- [ ] **Step 1: Write failing docs test**

Append this test to `apps/luna-corpus/tests/test_docs.py`:

```python

def test_readme_documents_knowledge_base_context_headers():
    readme = (PROJECT_ROOT / "README.md").read_text()

    assert "X-Tenant-Id" in readme
    assert "X-Workspace-Id" in readme
    assert "X-Knowledge-Base-Id" in readme
    assert "POST /api/v1/tenants" in readme
    assert "POST /api/v1/knowledge-bases" in readme
```

- [ ] **Step 2: Run docs test to verify it fails**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/test_docs.py -v`

Expected: FAIL because README does not document P0-M2 headers and endpoints.

- [ ] **Step 3: Update README**

Add this section to `apps/luna-corpus/README.md` after the database migrations section:

````markdown
## Tenant and knowledge-base context

P0-M2 scopes documents, conversations, and RAG retrieval by knowledge base. Create the hierarchy first:

```bash
POST /api/v1/tenants
POST /api/v1/workspaces
POST /api/v1/knowledge-bases
```

Knowledge-base scoped endpoints require these headers:

```http
X-Tenant-Id: <tenant-id>
X-Workspace-Id: <workspace-id>
X-Knowledge-Base-Id: <knowledge-base-id>
```

The headers provide temporary request context only. They are not authentication or authorization credentials.

The scoped endpoints include document creation/listing/detail/deletion/processing, single-turn QA, streaming QA, conversations, and multi-turn QA. Requests using a document or conversation from another knowledge base return `404`.
````

- [ ] **Step 4: Run docs tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/test_docs.py -v`

Expected: PASS.

- [ ] **Step 5: Run full luna-corpus tests**

Run: `pnpm nx run luna-corpus:test`

Expected: PASS with no failed tests.

- [ ] **Step 6: Run lint**

Run: `pnpm nx run luna-corpus:lint`

Expected: PASS with no Ruff errors.

- [ ] **Step 7: Verify Nx project targets still resolve**

Run: `pnpm nx show project luna-corpus --json`

Expected: output includes `test`, `lint`, `serve`, `db-migrate`, and `db-revision` targets.

- [ ] **Step 8: Verify migration command if local services are configured**

Run: `pnpm nx run luna-corpus:db-migrate`

Expected when `DATABASE_URL` points to a reachable database: Alembic upgrades through `20260623_0002`. If the local database is not running, capture the connection error and do not mark this command as passed.

- [ ] **Step 9: Inspect final working tree**

Run: `git status --short`

Expected: only intended P0-M2 files are modified before the final commit.

- [ ] **Step 10: Commit docs and verification fixes**

```bash
git add apps/luna-corpus/README.md apps/luna-corpus/tests/test_docs.py
git commit -m "docs(corpus): document knowledge base context"
```

If final verification required code fixes, include only those fixed files in this commit and use:

```bash
git add <fixed-files>
git commit -m "fix(corpus): stabilize knowledge base context"
```

---

## Self-Review

- Spec coverage: Tasks 1-2 cover tenant/workspace/knowledge-base models and migration; Task 3 covers header context; Task 4 covers minimal hierarchy APIs; Task 5 covers document isolation; Task 6 covers Chroma metadata/filter and RAG propagation; Task 7 covers conversations and QA routes; Task 8 covers documentation and final verification.
- Placeholder scan: this plan contains concrete files, commands, signatures, tests, and implementation snippets for every task.
- Type consistency: `RequestContext`, `require_request_context`, `knowledge_base_id`, `Tenant`, `Workspace`, `KnowledgeBase`, and updated RAG signatures are defined before later tasks consume them.
