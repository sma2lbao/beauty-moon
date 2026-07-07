"""Tests for the rerank duration metric."""
from app.observability.metrics import RAG_RERANK_DURATION, time_stage


def test_rerank_duration_metric_records():
    before = RAG_RERANK_DURATION._sum.get()
    with time_stage(RAG_RERANK_DURATION):
        pass
    after = RAG_RERANK_DURATION._sum.get()
    assert after >= before
