"""Quality metrics counters exist and increment."""
from app.observability.metrics import (
    QA_EVALUATIONS_TOTAL,
    QA_FEEDBACK_TOTAL,
    QA_INTERACTIONS_TOTAL,
)


def test_counters_increment():
    QA_INTERACTIONS_TOTAL.inc()
    QA_FEEDBACK_TOTAL.labels(rating="up").inc()
    QA_EVALUATIONS_TOTAL.labels(status="completed").inc()
    # _value.get() 反映累计值；只要 >0 即证明可用
    assert QA_INTERACTIONS_TOTAL._value.get() > 0
    assert QA_FEEDBACK_TOTAL.labels(rating="up")._value.get() > 0
    assert QA_EVALUATIONS_TOTAL.labels(status="completed")._value.get() > 0