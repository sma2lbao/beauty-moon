"""分面耗时指标存在性测试。"""
from app.observability import metrics


def test_facet_duration_metric_defined():
    assert hasattr(metrics, "RAG_FACET_DURATION")
    payload, _ = metrics.render_metrics()
    with metrics.time_stage(metrics.RAG_FACET_DURATION):
        pass
    payload2, _ = metrics.render_metrics()
    assert b"rag_facet_duration_seconds" in payload2
