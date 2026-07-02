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
