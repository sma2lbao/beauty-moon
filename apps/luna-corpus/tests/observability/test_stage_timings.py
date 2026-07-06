"""Business-stage timing instrumentation."""
from unittest.mock import patch

from app.observability.metrics import EMBEDDING_DURATION, RAG_RETRIEVAL_DURATION


def test_embed_text_records_duration():
    provider = "ark"
    before = EMBEDDING_DURATION.labels(provider=provider)._sum.get()
    with patch("app.services.llm.get_embeddings_model") as m, patch(
        "app.services.llm.get_settings"
    ) as s:
        s.return_value.llm_provider.value = provider
        m.return_value.embed_query.return_value = [0.1, 0.2]
        from app.services.llm import embed_text

        embed_text("hello")
    after = EMBEDDING_DURATION.labels(provider=provider)._sum.get()
    assert after >= before


def test_retrieve_node_records_duration():
    before = RAG_RETRIEVAL_DURATION._sum.get()
    with patch("app.graph.rag_graph.embed_text", return_value=[0.1]), patch(
        "app.graph.rag_graph.search_vectorstore", return_value=[]
    ):
        from app.graph.rag_graph import retrieve_node

        retrieve_node({"question": "q", "knowledge_base_id": "kb-1"})
    after = RAG_RETRIEVAL_DURATION._sum.get()
    assert after >= before


def _get_count(metric, **labels):
    """Extract observation count from a labeled Histogram via collect()."""
    for s in metric.labels(**labels).collect():
        for sample in s.samples:
            if sample.name.endswith("_count"):
                return sample.value
    return 0.0


def test_index_task_failure_records_metric():
    from app.observability.metrics import INDEX_TASK_DURATION

    before = _get_count(INDEX_TASK_DURATION, result="failure")
    with patch("app.api.routes.SessionLocal"), patch(
        "app.api.routes.TaskService"
    ), patch(
        "app.services.document_processor.DocumentProcessor"
    ) as mock_proc, patch("app.api.routes.AuditService"):
        mock_proc.return_value.process_document.side_effect = RuntimeError("boom")
        from app.api.routes import _run_index_task

        _run_index_task("task-1", "doc-1")
    after = _get_count(INDEX_TASK_DURATION, result="failure")
    assert after - before == 1
