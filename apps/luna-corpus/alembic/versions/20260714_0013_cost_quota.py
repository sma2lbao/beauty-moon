"""cost & quota: model_prices, usage_records, quota_limits, quota_counters

Revision ID: 20260714_0013
Revises: 20260713_0012
Create Date: 2026-07-14

"""
import sqlalchemy as sa
from alembic import op

revision = "20260714_0013"
down_revision = "20260713_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_prices",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_price_per_1k", sa.Numeric(18, 6), nullable=False),
        sa.Column("output_price_per_1k", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_model_prices_lookup", "model_prices", ["provider", "model", "effective_from"]
    )

    op.create_table(
        "usage_records",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("workspace_id", sa.CHAR(36), nullable=False),
        sa.Column("knowledge_base_id", sa.CHAR(36), nullable=False),
        sa.Column("interaction_id", sa.CHAR(36), nullable=True),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_usage_records_tenant_id", "usage_records", ["tenant_id"])
    op.create_index("ix_usage_records_workspace_id", "usage_records", ["workspace_id"])
    op.create_index(
        "ix_usage_records_knowledge_base_id", "usage_records", ["knowledge_base_id"]
    )
    op.create_index("ix_usage_records_created_at", "usage_records", ["created_at"])

    op.create_table(
        "quota_limits",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("scope_type", sa.String(length=10), nullable=False),
        sa.Column("scope_id", sa.CHAR(36), nullable=False),
        sa.Column("daily_token_limit", sa.BigInteger(), nullable=True),
        sa.Column("daily_cost_limit", sa.Numeric(18, 6), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("scope_type", "scope_id", name="uq_quota_limits_scope"),
    )

    op.create_table(
        "quota_counters",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("scope_type", sa.String(length=10), nullable=False),
        sa.Column("scope_id", sa.CHAR(36), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("token_used", sa.BigInteger(), nullable=False),
        sa.Column("cost_used", sa.Numeric(18, 6), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "scope_type", "scope_id", "usage_date", name="uq_quota_counters_scope_date"
        ),
    )


def downgrade() -> None:
    op.drop_table("quota_counters")
    op.drop_table("quota_limits")
    op.drop_index("ix_usage_records_created_at", table_name="usage_records")
    op.drop_index("ix_usage_records_knowledge_base_id", table_name="usage_records")
    op.drop_index("ix_usage_records_workspace_id", table_name="usage_records")
    op.drop_index("ix_usage_records_tenant_id", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_index("ix_model_prices_lookup", table_name="model_prices")
    op.drop_table("model_prices")
