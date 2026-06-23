# P0-M3 RBAC Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add temporary `X-User-Id` request identity and workspace-scoped RBAC enforcement to `apps/luna-corpus`.

**Architecture:** Keep P0-M2 tenant/workspace/knowledge-base context validation in `app/api/context.py`, and add a separate authorization layer in `app/api/auth.py` that resolves a user, workspace membership, roles, and effective permissions. Seed system roles and permissions in an Alembic migration, then protect corpus routes with `require_permission(...)` while leaving health, agent routes, and bootstrap tenant/workspace creation outside RBAC.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLAlchemy 2, Alembic, Chroma, LangGraph, Nx, uv, pytest.

## Global Constraints

- Use temporary `X-User-Id` request identity only; do not implement JWT, OIDC, login, session cookies, password auth, or API keys.
- Do not expose custom role management APIs.
- Do not implement knowledge-base-specific grants.
- Do not implement tenant-wide roles.
- Do not implement system-level admin users.
- Protect tenant/workspace/knowledge-base read and knowledge-base management APIs, document APIs, QA APIs, and conversation APIs.
- Do not protect `agent_routes`, `/health`, `POST /tenants`, or `POST /workspaces`.
- Workspace membership roles apply to all knowledge bases under that workspace.
- Preserve P0-M2 tenant/workspace/knowledge-base mismatch behavior as `404 Not Found`.
- Prefer `pnpm nx run luna-corpus:<target>` over direct tool commands for tests, lint, and migration checks.
- Do not guess Nx flags; use existing project targets and focused pytest args passed after `-- --`.

---

## File Structure

- Modify `apps/luna-corpus/app/db/models.py`: add `User`, `WorkspaceMembership`, `Role`, `Permission`, and many-to-many tables; add relationships from `Workspace` to memberships.
- Modify `apps/luna-corpus/tests/db/test_models.py`: cover RBAC model constraints and relationships.
- Create `apps/luna-corpus/alembic/versions/20260623_0003_rbac_enforcement.py`: add RBAC tables and seed default roles/permissions.
- Modify `apps/luna-corpus/tests/db/test_alembic_config.py`: assert the P0-M3 migration creates and seeds the required schema.
- Create `apps/luna-corpus/app/auth/permissions.py`: define permission and role slugs plus the default role-permission mapping used by tests, migration, and authorization.
- Create `apps/luna-corpus/app/api/auth.py`: define `AuthenticatedRequestContext`, `get_authenticated_context`, and `require_permission`.
- Create `apps/luna-corpus/tests/api/test_auth_context.py`: unit-test temporary identity and permission resolution.
- Modify `apps/luna-corpus/app/api/tenant_routes.py`: keep bootstrap create routes open, scope tenant/workspace lists by user membership, and protect knowledge-base routes.
- Modify `apps/luna-corpus/tests/api/test_tenant_routes.py`: cover bootstrap behavior, user-scoped lists, and knowledge-base role checks.
- Modify `apps/luna-corpus/app/api/routes.py`: replace P0-M2-only context dependencies with permission dependencies on document, QA, and conversation routes.
- Modify `apps/luna-corpus/tests/api/test_document_context.py`: add role-based document permission tests while preserving KB isolation tests.
- Modify `apps/luna-corpus/tests/api/test_conversation_context.py`: add role-based conversation and QA permission tests while preserving KB isolation tests.
- Modify `apps/luna-corpus/README.md`: document `X-User-Id`, seeded roles/permissions, and bootstrap-only endpoints.
- Modify `apps/luna-corpus/tests/test_docs.py`: assert README documents P0-M3 authorization behavior.

---

### Task 1: Add RBAC Model Layer

**Files:**
- Modify: `apps/luna-corpus/app/db/models.py`
- Modify: `apps/luna-corpus/tests/db/test_models.py`

**Interfaces:**
- Produces: `User`, `WorkspaceMembership`, `Role`, `Permission` SQLAlchemy models.
- Produces: `role_permissions` association table.
- Produces: `workspace_membership_roles` association table.
- Produces: `Workspace.memberships: list[WorkspaceMembership]`.
- Produces: `User.workspace_memberships: list[WorkspaceMembership]`.
- Produces: `WorkspaceMembership.roles: list[Role]`.
- Produces: `Role.permissions: list[Permission]`.
- Consumes: existing `Workspace` model from P0-M2.

- [ ] **Step 1: Write failing model imports**

Update the import in `apps/luna-corpus/tests/db/test_models.py` to include the new models:

```python
from app.db.models import (
    Base,
    Chunk,
    ContentStatus,
    ContentType,
    Conversation,
    Document,
    KnowledgeBase,
    Permission,
    Role,
    Tenant,
    User,
    Workspace,
    WorkspaceMembership,
)
```

- [ ] **Step 2: Add failing user and membership tests**

Append these tests to `apps/luna-corpus/tests/db/test_models.py`:

```python
def test_user_email_is_unique(db_session):
    db_session.add_all([
        User(email="owner@example.com", display_name="Owner"),
        User(email="owner@example.com", display_name="Duplicate"),
    ])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_workspace_membership_is_unique_per_user_and_workspace(db_session):
    _, workspace, _ = create_knowledge_base(db_session)
    user = User(email="member@example.com", display_name="Member")
    db_session.add(user)
    db_session.commit()

    db_session.add_all([
        WorkspaceMembership(user_id=user.id, workspace_id=workspace.id),
        WorkspaceMembership(user_id=user.id, workspace_id=workspace.id),
    ])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_workspace_membership_relationships(db_session):
    _, workspace, _ = create_knowledge_base(db_session)
    user = User(email="member@example.com", display_name="Member")
    membership = WorkspaceMembership(user=user, workspace=workspace)
    db_session.add(membership)
    db_session.commit()

    assert membership.id is not None
    assert membership.is_active is True
    assert membership.user == user
    assert membership.workspace == workspace
    assert user.workspace_memberships == [membership]
    assert workspace.memberships == [membership]
```

- [ ] **Step 3: Add failing role and permission tests**

Append these tests to `apps/luna-corpus/tests/db/test_models.py`:

```python
def test_role_slug_is_unique(db_session):
    db_session.add_all([
        Role(name="Reader", slug="kb_reader", is_system=True),
        Role(name="Duplicate Reader", slug="kb_reader", is_system=True),
    ])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_permission_slug_is_unique(db_session):
    db_session.add_all([
        Permission(name="Document Read", slug="document:read"),
        Permission(name="Duplicate Document Read", slug="document:read"),
    ])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_role_permission_relationship(db_session):
    permission = Permission(name="Document Read", slug="document:read")
    role = Role(
        name="Knowledge Base Reader",
        slug="kb_reader",
        description="Read knowledge-base content",
        is_system=True,
        permissions=[permission],
    )
    db_session.add(role)
    db_session.commit()

    assert role.id is not None
    assert role.permissions == [permission]
    assert permission.roles == [role]


def test_workspace_membership_role_relationship(db_session):
    _, workspace, _ = create_knowledge_base(db_session)
    user = User(email="member@example.com", display_name="Member")
    role = Role(name="Editor", slug="kb_editor", is_system=True)
    membership = WorkspaceMembership(user=user, workspace=workspace, roles=[role])
    db_session.add(membership)
    db_session.commit()

    assert membership.roles == [role]
    assert role.workspace_memberships == [membership]
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/db/test_models.py -v
```

Expected: FAIL because `Permission`, `Role`, `User`, and `WorkspaceMembership` are not defined.

- [ ] **Step 5: Add SQLAlchemy association tables**

In `apps/luna-corpus/app/db/models.py`, add `Table` to the SQLAlchemy imports:

```python
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
```

Add these association tables after `MessageRole` and before `Tenant`:

```python
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "role_id",
        CHAR(36),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        CHAR(36),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

workspace_membership_roles = Table(
    "workspace_membership_roles",
    Base.metadata,
    Column(
        "membership_id",
        CHAR(36),
        ForeignKey("workspace_memberships.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        CHAR(36),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
```

- [ ] **Step 6: Add RBAC model classes**

In `apps/luna-corpus/app/db/models.py`, add these classes after the association tables and before `Tenant`:

```python
class User(Base):
    """Application identity resolved from temporary request headers."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    workspace_memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        "WorkspaceMembership", back_populates="user", cascade="all, delete-orphan"
    )


class Permission(Base):
    """Seeded permission that can be assigned to roles."""

    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    roles: Mapped[list["Role"]] = relationship(
        "Role", secondary=role_permissions, back_populates="permissions"
    )


class Role(Base):
    """Seeded role that grants permissions to workspace memberships."""

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    permissions: Mapped[list[Permission]] = relationship(
        "Permission", secondary=role_permissions, back_populates="roles"
    )
    workspace_memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        "WorkspaceMembership",
        secondary=workspace_membership_roles,
        back_populates="roles",
    )


class WorkspaceMembership(Base):
    """User membership in a workspace."""

    __tablename__ = "workspace_memberships"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="workspace_memberships")
    workspace: Mapped["Workspace"] = relationship(
        "Workspace", back_populates="memberships"
    )
    roles: Mapped[list[Role]] = relationship(
        "Role", secondary=workspace_membership_roles, back_populates="workspace_memberships"
    )
```

- [ ] **Step 7: Add workspace membership relationship**

In `Workspace` in `apps/luna-corpus/app/db/models.py`, add this relationship after `knowledge_bases`:

```python
    memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        "WorkspaceMembership", back_populates="workspace", cascade="all, delete-orphan"
    )
```

- [ ] **Step 8: Run model tests**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/db/test_models.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/luna-corpus/app/db/models.py apps/luna-corpus/tests/db/test_models.py
git commit -m "feat(corpus): add rbac models"
```

---

### Task 2: Add RBAC Constants and P0-M3 Migration

**Files:**
- Create: `apps/luna-corpus/app/auth/permissions.py`
- Create: `apps/luna-corpus/app/auth/__init__.py`
- Create: `apps/luna-corpus/alembic/versions/20260623_0003_rbac_enforcement.py`
- Modify: `apps/luna-corpus/tests/db/test_alembic_config.py`

**Interfaces:**
- Produces: `PermissionSlug` constants with string permission slugs.
- Produces: `RoleSlug` constants with string role slugs.
- Produces: `DEFAULT_ROLE_PERMISSIONS: dict[str, tuple[str, ...]]`.
- Produces: Alembic revision `20260623_0003` with `down_revision = "20260623_0002"`.
- Consumes: model table names from Task 1.

- [ ] **Step 1: Write failing migration tests**

Append these tests to `apps/luna-corpus/tests/db/test_alembic_config.py`:

```python
def test_rbac_migration_exists():
    project_root = Path(__file__).parents[2]
    migration_path = (
        project_root
        / "alembic"
        / "versions"
        / "20260623_0003_rbac_enforcement.py"
    )

    assert migration_path.is_file()


def test_rbac_migration_defines_required_schema_and_seed_data():
    project_root = Path(__file__).parents[2]
    migration_path = (
        project_root
        / "alembic"
        / "versions"
        / "20260623_0003_rbac_enforcement.py"
    )
    migration_source = migration_path.read_text()

    for table_name in [
        "users",
        "permissions",
        "roles",
        "workspace_memberships",
        "role_permissions",
        "workspace_membership_roles",
    ]:
        assert re.search(rf'create_table\(\s*"{table_name}"', migration_source), (
            f"create_table call for '{table_name}' not found in migration"
        )

    for role_slug in ["workspace_admin", "kb_editor", "kb_reader"]:
        assert role_slug in migration_source

    for permission_slug in [
        "workspace:read",
        "workspace:manage",
        "knowledge_base:read",
        "knowledge_base:manage",
        "document:read",
        "document:write",
        "document:delete",
        "conversation:read",
        "conversation:write",
        "conversation:delete",
        "qa:query",
    ]:
        assert permission_slug in migration_source

    assert "bulk_insert" in migration_source
```

- [ ] **Step 2: Run migration tests to verify they fail**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/db/test_alembic_config.py -v
```

Expected: FAIL because `20260623_0003_rbac_enforcement.py` does not exist.

- [ ] **Step 3: Create auth package**

Create `apps/luna-corpus/app/auth/__init__.py`:

```python
"""Authorization support for luna-corpus."""
```

- [ ] **Step 4: Create permission constants**

Create `apps/luna-corpus/app/auth/permissions.py`:

```python
"""Seeded RBAC role and permission constants."""


class PermissionSlug:
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_MANAGE = "workspace:manage"
    KNOWLEDGE_BASE_READ = "knowledge_base:read"
    KNOWLEDGE_BASE_MANAGE = "knowledge_base:manage"
    DOCUMENT_READ = "document:read"
    DOCUMENT_WRITE = "document:write"
    DOCUMENT_DELETE = "document:delete"
    CONVERSATION_READ = "conversation:read"
    CONVERSATION_WRITE = "conversation:write"
    CONVERSATION_DELETE = "conversation:delete"
    QA_QUERY = "qa:query"


class RoleSlug:
    WORKSPACE_ADMIN = "workspace_admin"
    KB_EDITOR = "kb_editor"
    KB_READER = "kb_reader"


DEFAULT_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    RoleSlug.WORKSPACE_ADMIN: (
        PermissionSlug.WORKSPACE_READ,
        PermissionSlug.WORKSPACE_MANAGE,
        PermissionSlug.KNOWLEDGE_BASE_READ,
        PermissionSlug.KNOWLEDGE_BASE_MANAGE,
        PermissionSlug.DOCUMENT_READ,
        PermissionSlug.DOCUMENT_WRITE,
        PermissionSlug.DOCUMENT_DELETE,
        PermissionSlug.CONVERSATION_READ,
        PermissionSlug.CONVERSATION_WRITE,
        PermissionSlug.CONVERSATION_DELETE,
        PermissionSlug.QA_QUERY,
    ),
    RoleSlug.KB_EDITOR: (
        PermissionSlug.WORKSPACE_READ,
        PermissionSlug.KNOWLEDGE_BASE_READ,
        PermissionSlug.DOCUMENT_READ,
        PermissionSlug.DOCUMENT_WRITE,
        PermissionSlug.DOCUMENT_DELETE,
        PermissionSlug.CONVERSATION_READ,
        PermissionSlug.CONVERSATION_WRITE,
        PermissionSlug.CONVERSATION_DELETE,
        PermissionSlug.QA_QUERY,
    ),
    RoleSlug.KB_READER: (
        PermissionSlug.WORKSPACE_READ,
        PermissionSlug.KNOWLEDGE_BASE_READ,
        PermissionSlug.DOCUMENT_READ,
        PermissionSlug.CONVERSATION_READ,
        PermissionSlug.QA_QUERY,
    ),
}
```

- [ ] **Step 5: Create RBAC migration**

Create `apps/luna-corpus/alembic/versions/20260623_0003_rbac_enforcement.py`:

```python
"""RBAC enforcement.

Revision ID: 20260623_0003
Revises: 20260623_0002
Create Date: 2026-06-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260623_0003"
down_revision: str | None = "20260623_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = [
    ("perm-workspace-read", "Workspace Read", "workspace:read", "Read workspace metadata"),
    ("perm-workspace-manage", "Workspace Manage", "workspace:manage", "Manage workspace metadata"),
    ("perm-kb-read", "Knowledge Base Read", "knowledge_base:read", "Read knowledge bases"),
    ("perm-kb-manage", "Knowledge Base Manage", "knowledge_base:manage", "Manage knowledge bases"),
    ("perm-document-read", "Document Read", "document:read", "Read documents"),
    ("perm-document-write", "Document Write", "document:write", "Create and process documents"),
    ("perm-document-delete", "Document Delete", "document:delete", "Delete documents"),
    ("perm-conversation-read", "Conversation Read", "conversation:read", "Read conversations"),
    ("perm-conversation-write", "Conversation Write", "conversation:write", "Create and update conversations"),
    ("perm-conversation-delete", "Conversation Delete", "conversation:delete", "Delete conversations"),
    ("perm-qa-query", "QA Query", "qa:query", "Query the knowledge base"),
]

ROLES = [
    ("role-workspace-admin", "Workspace Admin", "workspace_admin", "Administer a workspace"),
    ("role-kb-editor", "Knowledge Base Editor", "kb_editor", "Edit knowledge-base content"),
    ("role-kb-reader", "Knowledge Base Reader", "kb_reader", "Read knowledge-base content"),
]

ROLE_PERMISSION_SLUGS = {
    "workspace_admin": [
        "workspace:read",
        "workspace:manage",
        "knowledge_base:read",
        "knowledge_base:manage",
        "document:read",
        "document:write",
        "document:delete",
        "conversation:read",
        "conversation:write",
        "conversation:delete",
        "qa:query",
    ],
    "kb_editor": [
        "workspace:read",
        "knowledge_base:read",
        "document:read",
        "document:write",
        "document:delete",
        "conversation:read",
        "conversation:write",
        "conversation:delete",
        "qa:query",
    ],
    "kb_reader": [
        "workspace:read",
        "knowledge_base:read",
        "document:read",
        "conversation:read",
        "qa:query",
    ],
}


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "permissions",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "roles",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "workspace_memberships",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("user_id", mysql.CHAR(36), nullable=False),
        sa.Column("workspace_id", mysql.CHAR(36), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "workspace_id"),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", mysql.CHAR(36), nullable=False),
        sa.Column("permission_id", mysql.CHAR(36), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )
    op.create_table(
        "workspace_membership_roles",
        sa.Column("membership_id", mysql.CHAR(36), nullable=False),
        sa.Column("role_id", mysql.CHAR(36), nullable=False),
        sa.ForeignKeyConstraint(["membership_id"], ["workspace_memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("membership_id", "role_id"),
    )

    permissions_table = sa.table(
        "permissions",
        sa.column("id", mysql.CHAR(36)),
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("description", sa.Text),
    )
    roles_table = sa.table(
        "roles",
        sa.column("id", mysql.CHAR(36)),
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_system", sa.Boolean),
    )
    role_permissions_table = sa.table(
        "role_permissions",
        sa.column("role_id", mysql.CHAR(36)),
        sa.column("permission_id", mysql.CHAR(36)),
    )

    op.bulk_insert(
        permissions_table,
        [
            {"id": permission_id, "name": name, "slug": slug, "description": description}
            for permission_id, name, slug, description in PERMISSIONS
        ],
    )
    op.bulk_insert(
        roles_table,
        [
            {"id": role_id, "name": name, "slug": slug, "description": description, "is_system": True}
            for role_id, name, slug, description in ROLES
        ],
    )

    permission_ids_by_slug = {slug: permission_id for permission_id, _, slug, _ in PERMISSIONS}
    role_ids_by_slug = {slug: role_id for role_id, _, slug, _ in ROLES}
    op.bulk_insert(
        role_permissions_table,
        [
            {"role_id": role_ids_by_slug[role_slug], "permission_id": permission_ids_by_slug[permission_slug]}
            for role_slug, permission_slugs in ROLE_PERMISSION_SLUGS.items()
            for permission_slug in permission_slugs
        ],
    )


def downgrade() -> None:
    op.drop_table("workspace_membership_roles")
    op.drop_table("role_permissions")
    op.drop_table("workspace_memberships")
    op.drop_table("roles")
    op.drop_table("permissions")
    op.drop_table("users")
```

- [ ] **Step 6: Run migration tests**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/db/test_alembic_config.py -v
```

Expected: PASS.

- [ ] **Step 7: Run model tests for migration/model consistency**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/db/test_models.py tests/db/test_alembic_config.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/luna-corpus/app/auth/__init__.py apps/luna-corpus/app/auth/permissions.py apps/luna-corpus/alembic/versions/20260623_0003_rbac_enforcement.py apps/luna-corpus/tests/db/test_alembic_config.py
git commit -m "feat(corpus): add rbac migration"
```

---

### Task 3: Add Authenticated Request Context

**Files:**
- Create: `apps/luna-corpus/app/api/auth.py`
- Create: `apps/luna-corpus/tests/api/test_auth_context.py`

**Interfaces:**
- Consumes: `get_request_context(db, x_tenant_id, x_workspace_id, x_knowledge_base_id) -> RequestContext` from `app/api/context.py`.
- Consumes: `PermissionSlug` constants from `app/auth/permissions.py`.
- Produces: `AuthenticatedRequestContext` dataclass with `user`, `tenant`, `workspace`, `knowledge_base`, `membership`, and `permissions: frozenset[str]`.
- Produces: `get_authenticated_context(db, x_user_id, x_tenant_id, x_workspace_id, x_knowledge_base_id, required_permissions) -> AuthenticatedRequestContext`.
- Produces: `require_permission(*required_permissions: str) -> Callable[..., AuthenticatedRequestContext]`.

- [ ] **Step 1: Create failing authorization tests**

Create `apps/luna-corpus/tests/api/test_auth_context.py`:

```python
"""Tests for authenticated request context and RBAC checks."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.auth import get_authenticated_context
from app.auth.permissions import PermissionSlug
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


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def create_auth_records(db_session, *, user_active=True, membership_active=True, permission_slugs=None):
    permission_slugs = permission_slugs or [PermissionSlug.DOCUMENT_READ]
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="Research", slug="research", tenant=tenant)
    knowledge_base = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    user = User(
        email="reader@example.com",
        display_name="Reader",
        is_active=user_active,
    )
    permissions = [
        Permission(name=slug, slug=slug, description=slug)
        for slug in permission_slugs
    ]
    role = Role(name="Role", slug="test_role", is_system=True, permissions=permissions)
    membership = WorkspaceMembership(
        user=user,
        workspace=workspace,
        is_active=membership_active,
        roles=[role],
    )
    db_session.add_all([knowledge_base, membership])
    db_session.commit()
    return tenant, workspace, knowledge_base, user, membership


def test_get_authenticated_context_rejects_missing_user_header(db_session):
    tenant, workspace, knowledge_base, _, _ = create_auth_records(db_session)

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            None,
            tenant.id,
            workspace.id,
            knowledge_base.id,
            [PermissionSlug.DOCUMENT_READ],
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Missing required header: X-User-Id"


def test_get_authenticated_context_rejects_unknown_user(db_session):
    tenant, workspace, knowledge_base, _, _ = create_auth_records(db_session)

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            "missing-user",
            tenant.id,
            workspace.id,
            knowledge_base.id,
            [PermissionSlug.DOCUMENT_READ],
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "User not found"


def test_get_authenticated_context_rejects_inactive_user(db_session):
    tenant, workspace, knowledge_base, user, _ = create_auth_records(
        db_session, user_active=False
    )

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            user.id,
            tenant.id,
            workspace.id,
            knowledge_base.id,
            [PermissionSlug.DOCUMENT_READ],
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "User is inactive"


def test_get_authenticated_context_rejects_missing_workspace_membership(db_session):
    tenant, workspace, knowledge_base, _, _ = create_auth_records(db_session)
    other_user = User(email="other@example.com", display_name="Other")
    db_session.add(other_user)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            other_user.id,
            tenant.id,
            workspace.id,
            knowledge_base.id,
            [PermissionSlug.DOCUMENT_READ],
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Workspace membership required"


def test_get_authenticated_context_rejects_inactive_membership(db_session):
    tenant, workspace, knowledge_base, user, _ = create_auth_records(
        db_session, membership_active=False
    )

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            user.id,
            tenant.id,
            workspace.id,
            knowledge_base.id,
            [PermissionSlug.DOCUMENT_READ],
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Workspace membership is inactive"


def test_get_authenticated_context_rejects_missing_permission(db_session):
    tenant, workspace, knowledge_base, user, _ = create_auth_records(
        db_session, permission_slugs=[PermissionSlug.DOCUMENT_READ]
    )

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            user.id,
            tenant.id,
            workspace.id,
            knowledge_base.id,
            [PermissionSlug.DOCUMENT_WRITE],
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Missing required permission: document:write"


def test_get_authenticated_context_returns_effective_permissions(db_session):
    tenant, workspace, knowledge_base, user, membership = create_auth_records(
        db_session,
        permission_slugs=[PermissionSlug.DOCUMENT_READ, PermissionSlug.QA_QUERY],
    )

    context = get_authenticated_context(
        db_session,
        user.id,
        tenant.id,
        workspace.id,
        knowledge_base.id,
        [PermissionSlug.DOCUMENT_READ],
    )

    assert context.user == user
    assert context.tenant == tenant
    assert context.workspace == workspace
    assert context.knowledge_base == knowledge_base
    assert context.membership == membership
    assert context.permissions == frozenset({PermissionSlug.DOCUMENT_READ, PermissionSlug.QA_QUERY})


def test_get_authenticated_context_rejects_cross_workspace_access(db_session):
    tenant, workspace, knowledge_base, user, _ = create_auth_records(db_session)
    other_workspace = Workspace(name="Other", slug="other", tenant=tenant)
    other_knowledge_base = KnowledgeBase(name="Other Docs", slug="other-docs", workspace=other_workspace)
    db_session.add(other_knowledge_base)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            user.id,
            tenant.id,
            other_workspace.id,
            other_knowledge_base.id,
            [PermissionSlug.DOCUMENT_READ],
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Workspace membership required"
```

- [ ] **Step 2: Run auth tests to verify they fail**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/api/test_auth_context.py -v
```

Expected: FAIL because `app.api.auth` does not exist.

- [ ] **Step 3: Implement authorization dependency**

Create `apps/luna-corpus/app/api/auth.py`:

```python
"""Authenticated request context and RBAC dependencies."""
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.context import RequestContext, get_request_context
from app.db.database import get_db
from app.db.models import Permission, User, WorkspaceMembership


@dataclass(frozen=True)
class AuthenticatedRequestContext(RequestContext):
    user: User
    membership: WorkspaceMembership
    permissions: frozenset[str]


def get_authenticated_context(
    db: Session,
    x_user_id: str | None,
    x_tenant_id: str | None,
    x_workspace_id: str | None,
    x_knowledge_base_id: str | None,
    required_permissions: Sequence[str],
) -> AuthenticatedRequestContext:
    resource_context = get_request_context(
        db=db,
        x_tenant_id=x_tenant_id,
        x_workspace_id=x_workspace_id,
        x_knowledge_base_id=x_knowledge_base_id,
    )

    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required header: X-User-Id",
        )

    user = db.query(User).filter(User.id == x_user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive",
        )

    membership = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.workspace_id == resource_context.workspace.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace membership required",
        )
    if not membership.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace membership is inactive",
        )

    effective_permissions = frozenset(
        permission.slug
        for role in membership.roles
        for permission in role.permissions
    )
    missing_permissions = [
        permission for permission in required_permissions if permission not in effective_permissions
    ]
    if missing_permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {missing_permissions[0]}",
        )

    return AuthenticatedRequestContext(
        tenant=resource_context.tenant,
        workspace=resource_context.workspace,
        knowledge_base=resource_context.knowledge_base,
        user=user,
        membership=membership,
        permissions=effective_permissions,
    )


def require_permission(
    *required_permissions: str,
) -> Callable[..., AuthenticatedRequestContext]:
    def dependency(
        db: Annotated[Session, Depends(get_db)],
        x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
        x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
        x_knowledge_base_id: Annotated[
            str | None,
            Header(alias="X-Knowledge-Base-Id"),
        ] = None,
    ) -> AuthenticatedRequestContext:
        return get_authenticated_context(
            db=db,
            x_user_id=x_user_id,
            x_tenant_id=x_tenant_id,
            x_workspace_id=x_workspace_id,
            x_knowledge_base_id=x_knowledge_base_id,
            required_permissions=required_permissions,
        )

    return dependency
```

- [ ] **Step 4: Run auth tests**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/api/test_auth_context.py -v
```

Expected: PASS.

- [ ] **Step 5: Run context regression tests**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/api/test_context.py tests/api/test_auth_context.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/app/api/auth.py apps/luna-corpus/tests/api/test_auth_context.py
git commit -m "feat(corpus): add authenticated request context"
```

---

### Task 4: Protect Tenant and Knowledge-Base Routes

**Files:**
- Modify: `apps/luna-corpus/app/api/tenant_routes.py`
- Modify: `apps/luna-corpus/tests/api/test_tenant_routes.py`

**Interfaces:**
- Consumes: `require_permission` from `app.api.auth`.
- Consumes: `PermissionSlug.WORKSPACE_READ` and `PermissionSlug.KNOWLEDGE_BASE_MANAGE`.
- Produces: `GET /tenants` scoped to tenants containing workspaces where `X-User-Id` has active membership.
- Produces: `GET /workspaces` scoped to active memberships for `X-User-Id`.
- Produces: `GET /knowledge-bases` requiring `knowledge_base:read` through full P0-M2 headers.
- Produces: `POST /knowledge-bases` requiring `knowledge_base:manage` through full P0-M2 headers.
- Preserves: `POST /tenants` and `POST /workspaces` remain bootstrap-only without `X-User-Id`.

- [ ] **Step 1: Update tenant route test imports**

Modify the import in `apps/luna-corpus/tests/api/test_tenant_routes.py`:

```python
from app.auth.permissions import PermissionSlug
from app.db.models import Base, KnowledgeBase, Permission, Role, User, WorkspaceMembership
```

- [ ] **Step 2: Add auth fixture helpers to tenant route tests**

Append these helpers after the `client` fixture in `apps/luna-corpus/tests/api/test_tenant_routes.py`:

```python
def create_user_with_role(client, workspace_id, role_slug, permission_slugs):
    db_generator = client.app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        user = User(email=f"{role_slug}@example.com", display_name=role_slug)
        permissions = []
        for slug in permission_slugs:
            permission = db.query(Permission).filter(Permission.slug == slug).first()
            if not permission:
                permission = Permission(name=slug, slug=slug, description=slug)
            permissions.append(permission)
        role = Role(name=role_slug, slug=role_slug, is_system=True, permissions=permissions)
        membership = WorkspaceMembership(user=user, workspace_id=workspace_id, roles=[role])
        db.add(membership)
        db.commit()
        return user.id
    finally:
        db.close()


def create_knowledge_base_record(client, workspace_id, name, slug):
    db_generator = client.app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        knowledge_base = KnowledgeBase(workspace_id=workspace_id, name=name, slug=slug)
        db.add(knowledge_base)
        db.commit()
        return {
            "id": knowledge_base.id,
            "workspace_id": knowledge_base.workspace_id,
            "name": knowledge_base.name,
            "slug": knowledge_base.slug,
            "description": knowledge_base.description,
        }
    finally:
        db.close()


def context_headers(user_id, tenant_id, workspace_id, knowledge_base_id):
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": tenant_id,
        "X-Workspace-Id": workspace_id,
        "X-Knowledge-Base-Id": knowledge_base_id,
    }
```

If the `with next(...)` pattern is rejected by the fixture generator, replace it in implementation with an explicit generator close:

```python
db_generator = client.app.dependency_overrides[get_db]()
db = next(db_generator)
try:
    ...
finally:
    db.close()
```

- [ ] **Step 3: Replace the old list assertions with user-scoped list tests**

Update `test_create_and_list_tenant` to keep the bootstrap create check and assert list now requires identity:

```python
def test_create_tenant_is_bootstrap_only_but_list_requires_user(client):
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

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing required header: X-User-Id"
```

Update `test_create_and_list_workspace` to keep bootstrap create check and assert list now requires identity:

```python
def test_create_workspace_is_bootstrap_only_but_list_requires_user(client):
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

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing required header: X-User-Id"
```

- [ ] **Step 4: Add tenant/workspace visibility tests**

Append this test to `apps/luna-corpus/tests/api/test_tenant_routes.py`:

```python
def test_tenant_and_workspace_lists_only_return_user_memberships(client):
    tenant_one = client.post("/api/v1/tenants", json={"name": "Acme", "slug": "acme"}).json()
    workspace_one = client.post(
        "/api/v1/workspaces",
        json={"tenant_id": tenant_one["id"], "name": "Research", "slug": "research"},
    ).json()
    tenant_two = client.post("/api/v1/tenants", json={"name": "Other", "slug": "other"}).json()
    client.post(
        "/api/v1/workspaces",
        json={"tenant_id": tenant_two["id"], "name": "Private", "slug": "private"},
    ).json()
    user_id = create_user_with_role(
        client,
        workspace_one["id"],
        "reader",
        [PermissionSlug.WORKSPACE_READ],
    )

    tenants = client.get("/api/v1/tenants", headers={"X-User-Id": user_id})
    workspaces = client.get("/api/v1/workspaces", headers={"X-User-Id": user_id})

    assert tenants.status_code == 200
    assert tenants.json()["total"] == 1
    assert tenants.json()["tenants"][0]["id"] == tenant_one["id"]
    assert workspaces.status_code == 200
    assert workspaces.json()["total"] == 1
    assert workspaces.json()["workspaces"][0]["id"] == workspace_one["id"]
```

- [ ] **Step 5: Add knowledge-base permission tests**

Replace `test_create_and_list_knowledge_base` with:

```python
def test_create_knowledge_base_requires_manage_permission(client):
    tenant = client.post(
        "/api/v1/tenants",
        json={"name": "Acme", "slug": "acme"},
    ).json()
    workspace = client.post(
        "/api/v1/workspaces",
        json={"tenant_id": tenant["id"], "name": "Research", "slug": "research"},
    ).json()
    bootstrap_kb = create_knowledge_base_record(
        client,
        workspace["id"],
        "Bootstrap",
        "bootstrap",
    )
    reader_id = create_user_with_role(
        client,
        workspace["id"],
        "reader",
        [PermissionSlug.KNOWLEDGE_BASE_READ],
    )

    response = client.post(
        "/api/v1/knowledge-bases",
        headers=context_headers(reader_id, tenant["id"], workspace["id"], bootstrap_kb["id"]),
        json={"workspace_id": workspace["id"], "name": "Docs", "slug": "docs"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing required permission: knowledge_base:manage"


def test_workspace_admin_can_create_and_list_knowledge_bases(client):
    tenant = client.post(
        "/api/v1/tenants",
        json={"name": "Acme", "slug": "acme"},
    ).json()
    workspace = client.post(
        "/api/v1/workspaces",
        json={"tenant_id": tenant["id"], "name": "Research", "slug": "research"},
    ).json()
    bootstrap_kb = create_knowledge_base_record(
        client,
        workspace["id"],
        "Bootstrap",
        "bootstrap",
    )
    admin_id = create_user_with_role(
        client,
        workspace["id"],
        "admin",
        [PermissionSlug.KNOWLEDGE_BASE_READ, PermissionSlug.KNOWLEDGE_BASE_MANAGE],
    )

    created = client.post(
        "/api/v1/knowledge-bases",
        headers=context_headers(admin_id, tenant["id"], workspace["id"], bootstrap_kb["id"]),
        json={"workspace_id": workspace["id"], "name": "Docs", "slug": "docs"},
    )
    listed = client.get(
        f"/api/v1/knowledge-bases?workspace_id={workspace['id']}",
        headers=context_headers(admin_id, tenant["id"], workspace["id"], bootstrap_kb["id"]),
    )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()["total"] == 2
```

- [ ] **Step 6: Run tenant route tests to verify they fail**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/api/test_tenant_routes.py -v
```

Expected: FAIL because routes do not enforce `X-User-Id` or permissions yet.

- [ ] **Step 7: Implement tenant/workspace user-scoped lists**

In `apps/luna-corpus/app/api/tenant_routes.py`, update imports:

```python
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
from app.db.models import KnowledgeBase, Tenant, User, Workspace, WorkspaceMembership
```

Update `list_tenants`:

```python
@router.get("/tenants", response_model=TenantListResponse)
def list_tenants(
    db: Annotated[Session, Depends(get_db)],
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> TenantListResponse:
    if not x_user_id:
        raise HTTPException(status_code=400, detail="Missing required header: X-User-Id")

    user = db.query(User).filter(User.id == x_user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")

    tenants = (
        db.query(Tenant)
        .join(Workspace)
        .join(WorkspaceMembership)
        .filter(
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.is_active == True,
        )
        .distinct()
        .order_by(Tenant.created_at.desc())
        .all()
    )
    return TenantListResponse(tenants=tenants, total=len(tenants))
```

Update `list_workspaces`:

```python
@router.get("/workspaces", response_model=WorkspaceListResponse)
def list_workspaces(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: str | None = Query(default=None),
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> WorkspaceListResponse:
    if not x_user_id:
        raise HTTPException(status_code=400, detail="Missing required header: X-User-Id")

    user = db.query(User).filter(User.id == x_user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")

    query = (
        db.query(Workspace)
        .join(WorkspaceMembership)
        .filter(
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.is_active == True,
        )
    )
    if tenant_id:
        query = query.filter(Workspace.tenant_id == tenant_id)
    workspaces = query.order_by(Workspace.created_at.desc()).all()
    return WorkspaceListResponse(workspaces=workspaces, total=len(workspaces))
```

- [ ] **Step 8: Protect knowledge-base routes**

In `apps/luna-corpus/app/api/tenant_routes.py`, update `create_knowledge_base` signature:

```python
def create_knowledge_base(
    knowledge_base: KnowledgeBaseCreate,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_MANAGE)),
    ],
) -> KnowledgeBaseResponse:
```

Add this check after loading `workspace` and before creating the knowledge base:

```python
    if workspace.id != context.workspace.id:
        raise HTTPException(status_code=404, detail="Workspace not found")
```

Update `list_knowledge_bases` signature:

```python
def list_knowledge_bases(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
    workspace_id: str | None = Query(default=None),
) -> KnowledgeBaseListResponse:
```

Replace its query body with:

```python
    query = db.query(KnowledgeBase).filter(KnowledgeBase.workspace_id == context.workspace.id)
    if workspace_id and workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    knowledge_bases = query.order_by(KnowledgeBase.created_at.desc()).all()
    return KnowledgeBaseListResponse(
        knowledge_bases=knowledge_bases,
        total=len(knowledge_bases),
    )
```

- [ ] **Step 9: Run tenant route tests**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/api/test_tenant_routes.py -v
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add apps/luna-corpus/app/api/tenant_routes.py apps/luna-corpus/tests/api/test_tenant_routes.py
git commit -m "feat(corpus): protect tenant knowledge base routes"
```

---

### Task 5: Enforce Document API Permissions

**Files:**
- Modify: `apps/luna-corpus/app/api/routes.py`
- Modify: `apps/luna-corpus/tests/api/test_document_context.py`

**Interfaces:**
- Consumes: `require_permission` from `app.api.auth`.
- Consumes: `PermissionSlug.DOCUMENT_READ`, `DOCUMENT_WRITE`, and `DOCUMENT_DELETE`.
- Produces: document routes protected by role permissions while retaining `knowledge_base_id` isolation.

- [ ] **Step 1: Update document context test imports**

Modify `apps/luna-corpus/tests/api/test_document_context.py` imports:

```python
from app.auth.permissions import PermissionSlug
from app.db.models import Base, KnowledgeBase, Permission, Role, Tenant, User, Workspace, WorkspaceMembership
```

- [ ] **Step 2: Update document test fixtures to create users**

Replace the `app_db` fixture in `apps/luna-corpus/tests/api/test_document_context.py` with:

```python
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
```

Append helpers:

```python
def create_user_with_permissions(Session, workspace_id, label, permission_slugs):
    session = Session()
    try:
        user = User(email=f"{label}@example.com", display_name=label)
        permissions = []
        for slug in permission_slugs:
            permission = session.query(Permission).filter(Permission.slug == slug).first()
            if not permission:
                permission = Permission(name=slug, slug=slug, description=slug)
            permissions.append(permission)
        role = Role(name=label, slug=label, is_system=True, permissions=permissions)
        membership = WorkspaceMembership(user=user, workspace_id=workspace_id, roles=[role])
        session.add(membership)
        session.commit()
        return user.id
    finally:
        session.close()
```

Replace `headers` helper with:

```python
def headers(context, knowledge_base_id, user_id):
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": knowledge_base_id,
    }
```

- [ ] **Step 3: Update missing context test for `X-User-Id`**

Replace `test_create_document_requires_context` with:

```python
def test_create_document_requires_user_context(client):
    response = client.post(
        "/api/v1/documents",
        json={"title": "Doc", "content": "Content"},
    )

    assert response.status_code == 400
    assert "X-Tenant-Id" in response.json()["detail"]
```

- [ ] **Step 4: Update scoped document test to use editor user**

Replace `test_document_create_and_list_are_scoped_to_knowledge_base` with:

```python
def test_document_create_and_list_are_scoped_to_knowledge_base(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "document_editor",
        [
            PermissionSlug.DOCUMENT_READ,
            PermissionSlug.DOCUMENT_WRITE,
            PermissionSlug.DOCUMENT_DELETE,
        ],
    )

    created = client.post(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"], user_id),
        json={"title": "Doc One", "content": "Content one"},
    )

    assert created.status_code == 201
    document = created.json()
    assert document["title"] == "Doc One"

    kb_one_list = client.get(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"], user_id),
    )
    kb_two_list = client.get(
        "/api/v1/documents",
        headers=headers(context, context["kb_two_id"], user_id),
    )

    assert kb_one_list.status_code == 200
    assert kb_one_list.json()["total"] == 1
    assert kb_one_list.json()["documents"][0]["id"] == document["id"]
    assert kb_two_list.status_code == 200
    assert kb_two_list.json()["total"] == 0
```

- [ ] **Step 5: Add reader/editor/delete permission tests**

Append these tests:

```python
def test_document_reader_cannot_create_or_delete_documents(client, app_db):
    _, Session, context = app_db
    reader_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "document_reader",
        [PermissionSlug.DOCUMENT_READ],
    )
    editor_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "document_editor_for_reader_test",
        [PermissionSlug.DOCUMENT_READ, PermissionSlug.DOCUMENT_WRITE, PermissionSlug.DOCUMENT_DELETE],
    )
    created = client.post(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"], editor_id),
        json={"title": "Doc One", "content": "Content one"},
    ).json()

    create_response = client.post(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"], reader_id),
        json={"title": "Forbidden", "content": "Nope"},
    )
    delete_response = client.delete(
        f"/api/v1/documents/{created['id']}",
        headers=headers(context, context["kb_one_id"], reader_id),
    )

    assert create_response.status_code == 403
    assert create_response.json()["detail"] == "Missing required permission: document:write"
    assert delete_response.status_code == 403
    assert delete_response.json()["detail"] == "Missing required permission: document:delete"


def test_document_write_permission_allows_processing(client, app_db):
    _, Session, context = app_db
    editor_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "document_processor",
        [PermissionSlug.DOCUMENT_READ, PermissionSlug.DOCUMENT_WRITE],
    )
    created = client.post(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"], editor_id),
        json={"title": "Doc One", "content": "Content one"},
    ).json()

    response = client.post(
        f"/api/v1/documents/{created['id']}/process",
        headers=headers(context, context["kb_one_id"], editor_id),
    )

    assert response.status_code == 200
```

- [ ] **Step 6: Update cross-KB regression test with user headers**

Replace `test_document_detail_delete_and_process_reject_cross_knowledge_base` with:

```python
def test_document_detail_delete_and_process_reject_cross_knowledge_base(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "document_admin",
        [
            PermissionSlug.DOCUMENT_READ,
            PermissionSlug.DOCUMENT_WRITE,
            PermissionSlug.DOCUMENT_DELETE,
        ],
    )
    created = client.post(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"], user_id),
        json={"title": "Doc One", "content": "Content one"},
    ).json()

    detail = client.get(
        f"/api/v1/documents/{created['id']}",
        headers=headers(context, context["kb_two_id"], user_id),
    )
    delete = client.delete(
        f"/api/v1/documents/{created['id']}",
        headers=headers(context, context["kb_two_id"], user_id),
    )
    process = client.post(
        f"/api/v1/documents/{created['id']}/process",
        headers=headers(context, context["kb_two_id"], user_id),
    )

    assert detail.status_code == 404
    assert delete.status_code == 404
    assert process.status_code == 404
```

- [ ] **Step 7: Run document tests to verify they fail**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/api/test_document_context.py -v
```

Expected: FAIL because document routes still use P0-M2 context only.

- [ ] **Step 8: Update route imports**

In `apps/luna-corpus/app/api/routes.py`, replace the context import:

```python
from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
```

Keep `RequestContext` imports only if another route still uses it; after this task and Task 6, document/QA/conversation routes should use `AuthenticatedRequestContext`.

- [ ] **Step 9: Protect document route signatures**

In `apps/luna-corpus/app/api/routes.py`, update document route context dependencies:

```python
context: Annotated[
    AuthenticatedRequestContext,
    Depends(require_permission(PermissionSlug.DOCUMENT_WRITE)),
]
```

Use that dependency for:

- `create_document`
- `process_document`

Use this dependency for `list_documents` and `get_document`:

```python
context: Annotated[
    AuthenticatedRequestContext,
    Depends(require_permission(PermissionSlug.DOCUMENT_READ)),
]
```

Use this dependency for `delete_document`:

```python
context: Annotated[
    AuthenticatedRequestContext,
    Depends(require_permission(PermissionSlug.DOCUMENT_DELETE)),
]
```

Do not change the existing SQL filters on `Document.knowledge_base_id == context.knowledge_base.id`.

- [ ] **Step 10: Run document tests**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/api/test_document_context.py -v
```

Expected: PASS.

- [ ] **Step 11: Run context regression tests**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/api/test_context.py tests/api/test_auth_context.py tests/api/test_document_context.py -v
```

Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/api/test_document_context.py
git commit -m "feat(corpus): enforce document permissions"
```

---

### Task 6: Enforce QA and Conversation Permissions

**Files:**
- Modify: `apps/luna-corpus/app/api/routes.py`
- Modify: `apps/luna-corpus/tests/api/test_conversation_context.py`

**Interfaces:**
- Consumes: `require_permission` from Task 3.
- Consumes: `PermissionSlug.QA_QUERY`, `CONVERSATION_READ`, `CONVERSATION_WRITE`, and `CONVERSATION_DELETE`.
- Produces: QA and conversation routes protected by role permissions while retaining `knowledge_base_id` isolation.

- [ ] **Step 1: Update conversation test imports**

Modify imports in `apps/luna-corpus/tests/api/test_conversation_context.py`:

```python
from app.auth.permissions import PermissionSlug
from app.db.models import Base, KnowledgeBase, Permission, Role, Tenant, User, Workspace, WorkspaceMembership
```

- [ ] **Step 2: Add conversation auth helpers**

Append this helper after the `client` fixture:

```python
def create_user_with_permissions(Session, workspace_id, label, permission_slugs):
    session = Session()
    try:
        user = User(email=f"{label}@example.com", display_name=label)
        permissions = []
        for slug in permission_slugs:
            permission = session.query(Permission).filter(Permission.slug == slug).first()
            if not permission:
                permission = Permission(name=slug, slug=slug, description=slug)
            permissions.append(permission)
        role = Role(name=label, slug=label, is_system=True, permissions=permissions)
        membership = WorkspaceMembership(user=user, workspace_id=workspace_id, roles=[role])
        session.add(membership)
        session.commit()
        return user.id
    finally:
        session.close()
```

Replace `headers` helper with:

```python
def headers(context, knowledge_base_id, user_id):
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": knowledge_base_id,
    }
```

- [ ] **Step 3: Update conversation creation test with writer user**

Replace `test_create_conversation_binds_current_knowledge_base` with:

```python
def test_create_conversation_binds_current_knowledge_base(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "conversation_writer",
        [PermissionSlug.CONVERSATION_READ, PermissionSlug.CONVERSATION_WRITE],
    )

    response = client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"], user_id),
        json={"title": "Chat"},
    )

    assert response.status_code == 201
    conversation = response.json()

    kb_one_response = client.get(
        f"/api/v1/conversations/{conversation['id']}",
        headers=headers(context, context["kb_one_id"], user_id),
    )
    kb_two_response = client.get(
        f"/api/v1/conversations/{conversation['id']}",
        headers=headers(context, context["kb_two_id"], user_id),
    )

    assert kb_one_response.status_code == 200
    assert kb_two_response.status_code == 404
```

- [ ] **Step 4: Update conversation list test with reader/writer user**

Replace `test_conversation_list_is_scoped_to_knowledge_base` with:

```python
def test_conversation_list_is_scoped_to_knowledge_base(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "conversation_lister",
        [PermissionSlug.CONVERSATION_READ, PermissionSlug.CONVERSATION_WRITE],
    )
    client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"], user_id),
        json={"title": "Chat"},
    )

    kb_one_response = client.get(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"], user_id),
    )
    kb_two_response = client.get(
        "/api/v1/conversations",
        headers=headers(context, context["kb_two_id"], user_id),
    )

    assert kb_one_response.status_code == 200
    assert kb_one_response.json()["total"] == 1
    assert kb_two_response.status_code == 200
    assert kb_two_response.json()["total"] == 0
```

- [ ] **Step 5: Update QA test with query user**

Replace `test_qa_query_passes_current_knowledge_base` with:

```python
def test_qa_query_passes_current_knowledge_base(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "qa_reader",
        [PermissionSlug.QA_QUERY],
    )

    with patch(
        "app.api.routes.answer_question",
        return_value={"answer": "Answer", "sources": [], "processing_time_ms": 1},
    ) as answer_question:
        response = client.post(
            "/api/v1/qa/query",
            headers=headers(context, context["kb_one_id"], user_id),
            json={"question": "What?"},
        )

    assert response.status_code == 200
    answer_question.assert_called_once_with(
        "What?", knowledge_base_id=context["kb_one_id"]
    )
```

- [ ] **Step 6: Add role behavior tests for conversations and QA**

Append these tests:

```python
def test_conversation_reader_cannot_create_clear_or_delete_conversation(client, app_db):
    _, Session, context = app_db
    reader_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "conversation_reader",
        [PermissionSlug.CONVERSATION_READ],
    )
    writer_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "conversation_writer_for_reader_test",
        [
            PermissionSlug.CONVERSATION_READ,
            PermissionSlug.CONVERSATION_WRITE,
            PermissionSlug.CONVERSATION_DELETE,
        ],
    )
    conversation = client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"], writer_id),
        json={"title": "Chat"},
    ).json()

    create_response = client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"], reader_id),
        json={"title": "Forbidden"},
    )
    clear_response = client.post(
        f"/api/v1/conversations/{conversation['id']}/clear",
        headers=headers(context, context["kb_one_id"], reader_id),
    )
    delete_response = client.delete(
        f"/api/v1/conversations/{conversation['id']}",
        headers=headers(context, context["kb_one_id"], reader_id),
    )

    assert create_response.status_code == 403
    assert create_response.json()["detail"] == "Missing required permission: conversation:write"
    assert clear_response.status_code == 403
    assert clear_response.json()["detail"] == "Missing required permission: conversation:write"
    assert delete_response.status_code == 403
    assert delete_response.json()["detail"] == "Missing required permission: conversation:delete"


def test_multi_turn_requires_qa_and_conversation_write_permissions(client, app_db):
    _, Session, context = app_db
    qa_only_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "qa_only",
        [PermissionSlug.QA_QUERY],
    )

    response = client.post(
        "/api/v1/qa/multi-turn",
        headers=headers(context, context["kb_one_id"], qa_only_id),
        json={"question": "What?"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing required permission: conversation:write"
```

- [ ] **Step 7: Update cross-KB multi-turn regression test**

Replace `test_multi_turn_rejects_cross_knowledge_base_conversation` with:

```python
def test_multi_turn_rejects_cross_knowledge_base_conversation(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "multi_turn_user",
        [
            PermissionSlug.QA_QUERY,
            PermissionSlug.CONVERSATION_READ,
            PermissionSlug.CONVERSATION_WRITE,
        ],
    )
    conversation = client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"], user_id),
        json={"title": "Chat"},
    ).json()

    response = client.post(
        "/api/v1/qa/multi-turn",
        headers=headers(context, context["kb_two_id"], user_id),
        json={"question": "What?", "conversation_id": conversation["id"]},
    )

    assert response.status_code == 404
```

- [ ] **Step 8: Run conversation tests to verify they fail**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/api/test_conversation_context.py -v
```

Expected: FAIL because QA and conversation routes still use P0-M2 context only.

- [ ] **Step 9: Protect QA route signatures**

In `apps/luna-corpus/app/api/routes.py`, update `query` and `stream_query` context dependencies:

```python
context: Annotated[
    AuthenticatedRequestContext,
    Depends(require_permission(PermissionSlug.QA_QUERY)),
]
```

Update `multi_turn_query` and `stream_multi_turn_query` context dependencies:

```python
context: Annotated[
    AuthenticatedRequestContext,
    Depends(require_permission(PermissionSlug.QA_QUERY, PermissionSlug.CONVERSATION_WRITE)),
]
```

- [ ] **Step 10: Protect conversation route signatures**

In `apps/luna-corpus/app/api/routes.py`, update `create_conversation_endpoint` and `clear_conversation_endpoint` context dependencies:

```python
context: Annotated[
    AuthenticatedRequestContext,
    Depends(require_permission(PermissionSlug.CONVERSATION_WRITE)),
]
```

Update `list_conversations`, `get_conversation_endpoint`, and `get_conversation_messages_endpoint` context dependencies:

```python
context: Annotated[
    AuthenticatedRequestContext,
    Depends(require_permission(PermissionSlug.CONVERSATION_READ)),
]
```

Update `delete_conversation_endpoint` context dependency:

```python
context: Annotated[
    AuthenticatedRequestContext,
    Depends(require_permission(PermissionSlug.CONVERSATION_DELETE)),
]
```

Do not change existing conversation lookups that pass `context.knowledge_base.id`.

- [ ] **Step 11: Run conversation tests**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/api/test_conversation_context.py -v
```

Expected: PASS.

- [ ] **Step 12: Run protected API test set**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/api/test_auth_context.py tests/api/test_tenant_routes.py tests/api/test_document_context.py tests/api/test_conversation_context.py -v
```

Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/api/test_conversation_context.py
git commit -m "feat(corpus): enforce qa conversation permissions"
```

---

### Task 7: Document P0-M3 RBAC Behavior

**Files:**
- Modify: `apps/luna-corpus/README.md`
- Modify: `apps/luna-corpus/tests/test_docs.py`

**Interfaces:**
- Consumes: P0-M3 API behavior from Tasks 3-6.
- Produces: README documentation for `X-User-Id`, seeded roles, permissions, and bootstrap endpoints.

- [ ] **Step 1: Write failing docs test**

Modify `apps/luna-corpus/tests/test_docs.py` to include this test:

```python
def test_readme_documents_p0_m3_rbac_context():
    readme = Path(__file__).parents[1] / "README.md"
    content = readme.read_text()

    assert "X-User-Id" in content
    assert "workspace_admin" in content
    assert "kb_editor" in content
    assert "kb_reader" in content
    assert "document:read" in content
    assert "qa:query" in content
    assert "POST /api/v1/tenants" in content
    assert "bootstrap" in content.lower()
    assert "not authentication" in content.lower()
```

If `Path` is not imported, add:

```python
from pathlib import Path
```

- [ ] **Step 2: Run docs tests to verify they fail**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/test_docs.py -v
```

Expected: FAIL because README does not document P0-M3 yet.

- [ ] **Step 3: Update README**

In `apps/luna-corpus/README.md`, replace the paragraph under the P0-M2 headers section with:

```markdown
P0-M3 adds workspace-scoped RBAC enforcement to protected corpus routes. Protected routes require the P0-M2 resource context headers plus temporary request identity:

```http
X-User-Id: <user-id>
X-Tenant-Id: <tenant-id>
X-Workspace-Id: <workspace-id>
X-Knowledge-Base-Id: <knowledge-base-id>
```

`X-User-Id` is temporary request identity for development and internal calls. It is not authentication and is not a production security credential.

Seeded roles are stored in the database:

- `workspace_admin`: all workspace, knowledge-base, document, conversation, and QA permissions.
- `kb_editor`: read knowledge-base metadata, read/write/delete documents, read/write/delete conversations, and query QA.
- `kb_reader`: read workspace and knowledge-base metadata, read documents, read conversations, and query QA.

Seeded permissions include `workspace:read`, `workspace:manage`, `knowledge_base:read`, `knowledge_base:manage`, `document:read`, `document:write`, `document:delete`, `conversation:read`, `conversation:write`, `conversation:delete`, and `qa:query`.

`POST /api/v1/tenants` and `POST /api/v1/workspaces` remain bootstrap-only setup endpoints and do not require `X-User-Id`. `GET /api/v1/tenants` and `GET /api/v1/workspaces` are scoped to the active workspaces where the current user has membership.

Requests using a document or conversation from another knowledge base still return `404`. Requests from users without the required workspace membership or permission return `403`.
```

- [ ] **Step 4: Run docs tests**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/test_docs.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/README.md apps/luna-corpus/tests/test_docs.py
git commit -m "docs(corpus): document p0-m3 rbac context"
```

---

### Task 8: Final Verification

**Files:**
- Verify: all changed P0-M3 files.

**Interfaces:**
- Consumes: completed Tasks 1-7.
- Produces: verified P0-M3 branch ready for review.

- [ ] **Step 1: Run focused RBAC test set**

Run:

```bash
pnpm nx run luna-corpus:test -- -- tests/db/test_models.py tests/db/test_alembic_config.py tests/api/test_context.py tests/api/test_auth_context.py tests/api/test_tenant_routes.py tests/api/test_document_context.py tests/api/test_conversation_context.py tests/test_docs.py -v
```

Expected: PASS.

- [ ] **Step 2: Run full luna-corpus tests**

Run:

```bash
pnpm nx run luna-corpus:test
```

Expected: PASS.

- [ ] **Step 3: Run lint**

Run:

```bash
pnpm nx run luna-corpus:lint
```

Expected: PASS.

- [ ] **Step 4: Inspect git status**

Run:

```bash
git status --short
```

Expected: no unstaged changes.

- [ ] **Step 5: If final verification required code fixes, commit them**

If Step 1, Step 2, or Step 3 required fixes, commit only those fixes:

```bash
git add <fixed-files>
git commit -m "fix(corpus): satisfy p0-m3 verification"
```

Expected: no commit is created if there were no fixes.
