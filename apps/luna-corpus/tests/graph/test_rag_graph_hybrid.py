"""retrieve_node routes retrieval through hybrid_search."""
from app.graph import rag_graph


def test_retrieve_node_calls_hybrid_search(monkeypatch):
    captured = {}

    def fake_hybrid(query, query_embedding, *, top_k, knowledge_base_id):
        captured["query"] = query
        captured["kb"] = knowledge_base_id
        return [
            {"chunk_id": "c1", "document_id": "d1", "content": "hello", "score": 0.5}
        ]

    monkeypatch.setattr(rag_graph, "embed_text", lambda q: [0.1, 0.2])
    monkeypatch.setattr(rag_graph, "hybrid_search", fake_hybrid)
    monkeypatch.setattr(
        rag_graph,
        "validate_retrieved_docs_for_knowledge_base",
        lambda docs, kb: docs,
    )

    out = rag_graph.retrieve_node(
        {"question": "什么是向量检索", "knowledge_base_id": "kb-1"}
    )

    assert captured["query"] == "什么是向量检索"
    assert captured["kb"] == "kb-1"
    assert out["retrieved_docs"][0]["chunk_id"] == "c1"
