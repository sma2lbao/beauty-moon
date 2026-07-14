"""配额准入逻辑。"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cost import enforcement
from app.cost.enforcement import QuotaExceeded, check_quota
from app.db.models import Base, QuotaCounter, QuotaLimit


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _counter(s, scope_type, scope_id, tokens=0, cost="0"):
    s.add(
        QuotaCounter(
            scope_type=scope_type,
            scope_id=scope_id,
            usage_date=datetime.now(timezone.utc).date(),
            token_used=tokens,
            cost_used=Decimal(cost),
        )
    )
    s.commit()


def test_no_limit_configured_passes():
    s = _session()
    check_quota(s, "t1", "w1")  # 不抛


def test_under_limit_passes():
    s = _session()
    s.add(QuotaLimit(scope_type="tenant", scope_id="t1", daily_token_limit=1000, currency="CNY"))
    _counter(s, "tenant", "t1", tokens=500)
    check_quota(s, "t1", "w1")  # 不抛


def test_tenant_token_over_limit_rejects():
    s = _session()
    s.add(QuotaLimit(scope_type="tenant", scope_id="t1", daily_token_limit=1000, currency="CNY"))
    _counter(s, "tenant", "t1", tokens=1000)
    with pytest.raises(QuotaExceeded) as exc:
        check_quota(s, "t1", "w1")
    assert exc.value.scope_type == "tenant"
    assert exc.value.dimension == "token"


def test_workspace_cost_over_limit_rejects():
    s = _session()
    s.add(QuotaLimit(scope_type="workspace", scope_id="w1", daily_cost_limit=Decimal("1.0"), currency="CNY"))
    _counter(s, "workspace", "w1", cost="1.5")
    with pytest.raises(QuotaExceeded) as exc:
        check_quota(s, "t1", "w1")
    assert exc.value.scope_type == "workspace"
    assert exc.value.dimension == "cost"


def test_disabled_toggle_passes(monkeypatch):
    s = _session()
    s.add(QuotaLimit(scope_type="tenant", scope_id="t1", daily_token_limit=1, currency="CNY"))
    _counter(s, "tenant", "t1", tokens=999)
    monkeypatch.setattr(enforcement.settings, "cost_enforcement_enabled", False)
    check_quota(s, "t1", "w1")  # 关闭开关，放行


def test_db_error_fails_open(monkeypatch):
    from unittest.mock import MagicMock

    broken = MagicMock()
    broken.query.side_effect = RuntimeError("db down")
    # fail-open：不抛
    check_quota(broken, "t1", "w1")
