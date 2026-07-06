"""Metric definitions and time_stage helper tests."""
import pytest

from app.observability.metrics import (
    EMBEDDING_DURATION,
    RAG_RETRIEVAL_DURATION,
    render_metrics,
    time_stage,
)


def _sample_count(histogram, **labels):
    metric = histogram.labels(**labels) if labels else histogram
    return metric._sum.get(), sum(b.get() for b in metric._buckets)


def test_time_stage_observes_on_success():
    before = RAG_RETRIEVAL_DURATION._sum.get()
    with time_stage(RAG_RETRIEVAL_DURATION):
        pass
    assert RAG_RETRIEVAL_DURATION._sum.get() >= before


def test_time_stage_observes_on_exception():
    before = EMBEDDING_DURATION.labels(provider="ark")._sum.get()
    with pytest.raises(ValueError), time_stage(EMBEDDING_DURATION, provider="ark"):
        raise ValueError("boom")
    after = EMBEDDING_DURATION.labels(provider="ark")._sum.get()
    assert after >= before


def test_render_metrics_returns_prometheus_text():
    body, content_type = render_metrics()
    assert b"rag_retrieval_duration_seconds" in body
    assert "text/plain" in content_type
