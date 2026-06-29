"""add ingestion_tasks table

Revision ID: 20260629_0005
Revises: 20260625_0004
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "20260629_0005"
down_revision: str | None = "20260625_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_tasks",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("type", sa.Enum("document_index", name="tasktype"), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="taskstatus",
            ),
            nullable=False,
        ),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("knowledge_base_id", mysql.CHAR(36), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ingestion_tasks")
    op.execute("DROP TYPE IF EXISTS tasktype")
    op.execute("DROP TYPE IF EXISTS taskstatus")
