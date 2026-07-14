"""用量记录与计数器累加。"""
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cost.recorder import bump_counter, record_usage
from app.db.models import Base, ModelPrice, QuotaCounter, UsageRecord
from app.services.llm import TokenUsage
from datetime import datetime, timezone


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _seed_price(s):
    s.add(
        ModelPrice(
            provider="ark",
            model="m",
            input_price_per_1k=Decimal("0.002"),
            output_price_per_1k=Decimal("0.008"),
            currency="CNY",
            effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
    )
    s.commit()


def test_bump_counter_inserts_then_accumulates():
    s = _session()
    d = date(2026, 7, 14)
    bump_counter(s, scope_type="tenant", scope_id="t1", usage_date=d, token_delta=10, cost_delta=Decimal("0.5"))
    bump_counter(s, scope_type="tenant", scope_id="t1", usage_date=d, token_delta=5, cost_delta=Decimal("0.25"))
    row = s.query(QuotaCounter).one()
    assert row.token_used == 15
    assert row.cost_used == Decimal("0.750000")


def test_record_usage_writes_record_and_two_counters():
    s = _session()
    _seed_price(s)
    usage = TokenUsage(input_tokens=1000, output_tokens=1000, model="m", provider="ark")
    record_usage(
        s,
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="kb1",
        interaction_id="i1",
        usage=usage,
    )
    assert s.query(UsageRecord).count() == 1
    # 租户 + 工作区各一行计数器
    assert s.query(QuotaCounter).count() == 2
    rec = s.query(UsageRecord).one()
    assert rec.total_tokens == 2000
    assert rec.cost_amount == Decimal("0.010000")  # 0.002 + 0.008


def test_record_usage_none_usage_is_noop():
    s = _session()
    record_usage(
        s,
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="kb1",
        interaction_id=None,
        usage=None,
    )
    assert s.query(UsageRecord).count() == 0
    assert s.query(QuotaCounter).count() == 0


def test_record_usage_swallows_errors():
    broken = MagicMock()
    broken.add.side_effect = RuntimeError("db down")
    usage = TokenUsage(input_tokens=1, output_tokens=1, model="m", provider="ark")
    # 不应抛出
    record_usage(
        broken,
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="kb1",
        interaction_id=None,
        usage=usage,
    )
