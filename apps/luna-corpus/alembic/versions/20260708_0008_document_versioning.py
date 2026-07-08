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