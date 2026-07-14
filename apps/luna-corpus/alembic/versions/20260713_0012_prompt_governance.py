"""prompt governance: prompt_versions, prompt_experiments, qa_interactions.prompt_version_id

Revision ID: 20260713_0012
Revises: 20260713_0011
Create Date: 2026-07-13

"""
import sqlalchemy as sa
from alembic import op

revision = "20260713_0012"
down_revision = "20260713_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("prompt_key", sa.String(length=50), nullable=False),
        sa.Column("version_label", sa.String(length=100), nullable=False),
        sa.Column("lang", sa.String(length=10), nullable=False),
        sa.Column("template_text", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("draft", "active", "archived", name="promptstatus"), nullable=False),
        sa.Column("source", sa.Enum("file", "db", name="promptsource"), nullable=False),
        sa.Column("knowledge_base_id", sa.CHAR(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_prompt_versions_prompt_key", "prompt_versions", ["prompt_key"])
    op.create_index("ix_prompt_versions_knowledge_base_id", "prompt_versions", ["knowledge_base_id"])

    op.create_table(
        "prompt_experiments",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("knowledge_base_id", sa.CHAR(36), nullable=False),
        sa.Column("prompt_key", sa.String(length=50), nullable=False),
        sa.Column("status", sa.Enum("running", "stopped", name="experimentstatus"), nullable=False),
        sa.Column("variants", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_prompt_experiments_knowledge_base_id", "prompt_experiments", ["knowledge_base_id"])
    op.create_index("ix_prompt_experiments_prompt_key", "prompt_experiments", ["prompt_key"])

    op.add_column(
        "qa_interactions",
        sa.Column("prompt_version_id", sa.CHAR(36), nullable=True),
    )
    op.create_index(
        "ix_qa_interactions_prompt_version_id", "qa_interactions", ["prompt_version_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_qa_interactions_prompt_version_id", table_name="qa_interactions")
    op.drop_column("qa_interactions", "prompt_version_id")
    op.drop_index("ix_prompt_experiments_prompt_key", table_name="prompt_experiments")
    op.drop_index("ix_prompt_experiments_knowledge_base_id", table_name="prompt_experiments")
    op.drop_table("prompt_experiments")
    op.drop_index("ix_prompt_versions_knowledge_base_id", table_name="prompt_versions")
    op.drop_index("ix_prompt_versions_prompt_key", table_name="prompt_versions")
    op.drop_table("prompt_versions")
