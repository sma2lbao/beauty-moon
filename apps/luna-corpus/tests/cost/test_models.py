"""成本与配额数据模型。"""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    ModelPrice,
    QuotaCounter,
    QuotaLimit,
    UsageRecord,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_model_price_persists():
    s = _session()
    p = ModelPrice(
        provider="ark",
        model="deepseek-v4-pro-260425",
        input_price_per_1k=Decimal("0.002000"),
        output_price_per_1k=Decimal("0.008000"),
        currency="CNY",
        effective_from=datetime.now(timezone.utc),
    )
    s.add(p)
    s.commit()
    assert s.query(ModelPrice).count() == 1


def test_usage_record_persists():
    s = _session()
    r = UsageRecord(
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="kb1",
        interaction_id="i1",
        provider="ark",
        model="m",
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        cost_amount=Decimal("0.001000"),
        currency="CNY",
    )
    s.add(r)
    s.commit()
    assert s.query(UsageRecord).one().total_tokens == 30


def test_quota_limit_unique_scope():
    s = _session()
    s.add(QuotaLimit(scope_type="tenant", scope_id="t1", daily_token_limit=1000, currency="CNY"))
    s.commit()
    assert s.query(QuotaLimit).one().daily_token_limit == 1000


def test_quota_counter_persists():
    s = _session()
    c = QuotaCounter(
        scope_type="workspace",
        scope_id="w1",
        usage_date=date(2026, 7, 14),
        token_used=100,
        cost_used=Decimal("0.050000"),
    )
    s.add(c)
    s.commit()
    assert s.query(QuotaCounter).one().token_used == 100
