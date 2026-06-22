"""Initial schema.

Revision ID: 20260622_0001
Revises:
Create Date: 2026-06-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "20260622_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=1000), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("has_tables", sa.Boolean(), nullable=False),
        sa.Column("has_code", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "completed",
                "error",
                name="contentstatus",
            ),
            nullable=False,
        ),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "conversations",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chunks",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("document_id", mysql.CHAR(36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "content_type",
            sa.Enum("text", "table", "code", name="contenttype"),
            nullable=False,
        ),
        sa.Column("chunk_metadata", sa.JSON(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        timestamp_column("created_at"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "messages",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("conversation_id", mysql.CHAR(36), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", "system", name="messagerole"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        timestamp_column("created_at"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("chunks")
    op.drop_table("conversations")
    op.drop_table("documents")
