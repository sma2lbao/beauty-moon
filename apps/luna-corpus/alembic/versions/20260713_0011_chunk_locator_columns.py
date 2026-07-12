"""citation source enrichment: chunk locator columns

Revision ID: 20260713_0011
Revises: 20260712_0010
Create Date: 2026-07-13

"""
import sqlalchemy as sa
from alembic import op

revision = "20260713_0011"
down_revision = "20260712_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("char_start", sa.Integer(), nullable=True))
    op.add_column("chunks", sa.Column("char_end", sa.Integer(), nullable=True))
    op.add_column(
        "chunks", sa.Column("heading_path", sa.String(length=1000), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chunks", "heading_path")
    op.drop_column("chunks", "char_end")
    op.drop_column("chunks", "char_start")
