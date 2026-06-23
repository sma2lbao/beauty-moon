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
