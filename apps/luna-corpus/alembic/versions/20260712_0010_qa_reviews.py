"""feedback review loop: qa_reviews

Revision ID: 20260712_0010
Revises: 20260709_0009
Create Date: 2026-07-12

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import CHAR

revision = "20260712_0010"
down_revision = "20260709_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qa_reviews",
        sa.Column("id", CHAR(36), primary_key=True),
        sa.Column("interaction_id", CHAR(36), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "resolved", "dismissed", name="reviewstatus"),
            nullable=False,
        ),
        sa.Column(
            "root_cause",
            sa.Enum(
                "knowledge_gap",
                "chunk_error",
                "hallucination",
                "outdated",
                "other",
                name="reviewrootcause",
            ),
            nullable=True,
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("assignee_user_id", CHAR(36), nullable=True),
        sa.Column("resolved_by_user_id", CHAR(36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["qa_interactions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("interaction_id", name="uq_qa_reviews_interaction"),
    )
    op.create_index(
        "ix_qa_reviews_interaction", "qa_reviews", ["interaction_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_qa_reviews_interaction", table_name="qa_reviews")
    op.drop_table("qa_reviews")
