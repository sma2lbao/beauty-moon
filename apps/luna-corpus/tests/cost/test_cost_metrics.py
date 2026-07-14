"""成本与配额 Prometheus 指标可用且可自增。"""
from app.observability.metrics import (
    LLM_COST_TOTAL,
    LLM_TOKENS_TOTAL,
    QUOTA_REJECTED_TOTAL,
)


def test_counters_increment():
    LLM_TOKENS_TOTAL.labels(provider="ark", model="m", direction="input").inc(10)
    LLM_COST_TOTAL.labels(provider="ark", model="m", currency="CNY").inc(0.5)
    QUOTA_REJECTED_TOTAL.labels(scope_type="tenant").inc()
    assert LLM_TOKENS_TOTAL.labels(provider="ark", model="m", direction="input")._value.get() > 0
    assert LLM_COST_TOTAL.labels(provider="ark", model="m", currency="CNY")._value.get() > 0
    assert QUOTA_REJECTED_TOTAL.labels(scope_type="tenant")._value.get() > 0
