"""quality evaluation: qa_interactions, qa_feedback, qa_evaluations

Revision ID: 20260709_0009
Revises: 20260708_0008
Create Date: 2026-07-09

"""
import sqlalchemy as sa
from alembic import op

revision = "20260709_0009"
down_revision = "20260708_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qa_interactions",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("knowledge_base_id", sa.CHAR(36), nullable=False),
        sa.Column("conversation_id", sa.CHAR(36), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("retrieval_mode", sa.String(20), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_qa_interactions_kb", "qa_interactions", ["knowledge_base_id"]
    )

    op.create_table(
        "qa_feedback",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("interaction_id", sa.CHAR(36), nullable=False),
        sa.Column(
            "rating", sa.Enum("up", "down", name="feedbackrating"), nullable=False
        ),
        sa.Column(
            "error_type",
            sa.Enum(
                "hallucination",
                "irrelevant",
                "incomplete",
                "wrong_citation",
                "other",
                name="feedbackerrortype",
            ),
            nullable=True,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.CHAR(36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["qa_interactions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_qa_feedback_interaction", "qa_feedback", ["interaction_id"]
    )

    op.create_table(
        "qa_evaluations",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("interaction_id", sa.CHAR(36), nullable=False),
        sa.Column("faithfulness", sa.Float(), nullable=True),
        sa.Column("answer_relevance", sa.Float(), nullable=True),
        sa.Column("citation_accuracy", sa.Float(), nullable=True),
        sa.Column("judge_model", sa.String(50), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "completed", "failed", name="evaluationstatus"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["qa_interactions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_qa_evaluations_interaction", "qa_evaluations", ["interaction_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_qa_evaluations_interaction", table_name="qa_evaluations")
    op.drop_table("qa_evaluations")
    op.drop_index("ix_qa_feedback_interaction", table_name="qa_feedback")
    op.drop_table("qa_feedback")
    op.drop_index("ix_qa_interactions_kb", table_name="qa_interactions")
    op.drop_table("qa_interactions")