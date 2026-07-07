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
