"""add file_uploads table and documents.file_id

Revision ID: 20260625_0004
Revises: 20260623_0003
Create Date: 2026-06-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260625_0004"
down_revision: str | None = "20260623_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_uploads",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("knowledge_base_id", mysql.CHAR(36), nullable=False),
        sa.Column("original_name", sa.String(500), nullable=False),
        sa.Column("stored_name", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("uploaded", "parsed", "error", name="fileuploadstatus"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("parsed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("documents", sa.Column("file_id", mysql.CHAR(36), nullable=True))
    op.create_foreign_key(None, "documents", "file_uploads", ["file_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint(None, "documents", type_="foreignkey")
    op.drop_column("documents", "file_id")
    op.drop_table("file_uploads")
    op.execute("DROP TYPE IF EXISTS fileuploadstatus")
