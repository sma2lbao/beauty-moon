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
    op.create_table("tenants",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table("workspaces",
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
    op.create_table("knowledge_bases",
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
