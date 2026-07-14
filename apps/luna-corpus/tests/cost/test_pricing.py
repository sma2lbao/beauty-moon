"""价格解析与成本折算。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cost.pricing import compute_cost, resolve_price
from app.db.models import Base, ModelPrice


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _price(s, eff, inp="0.002", out="0.008"):
    p = ModelPrice(
        provider="ark",
        model="m",
        input_price_per_1k=Decimal(inp),
        output_price_per_1k=Decimal(out),
        currency="CNY",
        effective_from=eff,
    )
    s.add(p)
    s.commit()
    return p


def test_resolve_price_picks_latest_effective():
    s = _session()
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    _price(s, now - timedelta(days=10), inp="0.001")
    _price(s, now - timedelta(days=1), inp="0.002")
    _price(s, now + timedelta(days=1), inp="0.009")  # 未来价，不选
    price = resolve_price(s, "ark", "m", now)
    assert price is not None
    assert price.input_price_per_1k == Decimal("0.002")


def test_resolve_price_none_when_no_match():
    s = _session()
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    assert resolve_price(s, "ark", "missing", now) is None


def test_compute_cost_basic():
    s = _session()
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    p = _price(s, now - timedelta(days=1))
    # 1000 input * 0.002/1k + 2000 output * 0.008/1k = 0.002 + 0.016 = 0.018
    cost, currency = compute_cost(1000, 2000, p)
    assert cost == Decimal("0.018000")
    assert currency == "CNY"


def test_compute_cost_no_price_returns_zero():
    cost, currency = compute_cost(1000, 2000, None)
    assert cost == Decimal("0")
    assert currency == "CNY"
