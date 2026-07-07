"""Tests for the rerank_results orchestration + degradation."""
from app.retrieval.rerank import base


class _StubReranker:
    def rerank(self, query, candidates, *, top_k):
        # Reverse order to prove reranking happened.
        return list(reversed(candidates))[:top_k]


def _cand(chunk_id):
    return {
        "chunk_id": chunk_id,
        "document_id": f"doc-{chunk_id}",
        "content": f"content {chunk_id}",
        "score": 0.5,
    }


def test_rerank_results_uses_reranker(monkeypatch):
    monkeypatch.setattr(base, "get_reranker", lambda: _StubReranker())
    candidates = [_cand("a"), _cand("b"), _cand("c")]

    result = base.rerank_results(
        "q", candidates, top_k=2, knowledge_base_id="kb-1"
    )

    assert [r["chunk_id"] for r in result] == ["c", "b"]


def test_rerank_results_degrades_on_error(monkeypatch):
    def _boom():
        raise RuntimeError("model exploded")

    monkeypatch.setattr(base, "get_reranker", _boom)
    candidates = [_cand("a"), _cand("b"), _cand("c")]

    result = base.rerank_results(
        "q", candidates, top_k=2, knowledge_base_id="kb-1"
    )

    # Degrades to fused order, sliced to top_k.
    assert [r["chunk_id"] for r in result] == ["a", "b"]


def test_rerank_results_degrades_on_import_error(monkeypatch):
    def _boom():
        raise ImportError("no sentence-transformers")

    monkeypatch.setattr(base, "get_reranker", _boom)
    candidates = [_cand("a"), _cand("b")]

    result = base.rerank_results(
        "q", candidates, top_k=5, knowledge_base_id="kb-1"
    )

    assert [r["chunk_id"] for r in result] == ["a", "b"]
