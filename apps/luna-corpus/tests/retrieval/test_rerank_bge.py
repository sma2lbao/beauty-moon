"""Tests for the local BGE cross-encoder reranker."""
from app.retrieval.rerank import bge


class _FakeModel:
    """Stand-in for CrossEncoder: score = length of content string."""

    def __init__(self):
        self.predict_calls = []

    def predict(self, pairs, batch_size=32):
        self.predict_calls.append((pairs, batch_size))
        return [float(len(content)) for _query, content in pairs]


def _cand(chunk_id, content):
    return {
        "chunk_id": chunk_id,
        "document_id": f"doc-{chunk_id}",
        "content": content,
        "score": 0.0,
    }


def test_rerank_orders_by_model_score_and_truncates(monkeypatch):
    reranker = bge.BgeReranker()
    monkeypatch.setattr(reranker, "_load_model", lambda: _FakeModel())

    candidates = [_cand("a", "xx"), _cand("b", "xxxxxx"), _cand("c", "xxxx")]
    result = reranker.rerank("q", candidates, top_k=2)

    # Longer content -> higher fake score -> "b" then "c".
    assert [r["chunk_id"] for r in result] == ["b", "c"]
    assert result[0]["score"] == 6.0


def test_rerank_empty_candidates_skips_model(monkeypatch):
    reranker = bge.BgeReranker()

    def _boom():
        raise AssertionError("model must not load for empty candidates")

    monkeypatch.setattr(reranker, "_load_model", _boom)
    assert reranker.rerank("q", [], top_k=5) == []


def test_rerank_preserves_result_contract(monkeypatch):
    reranker = bge.BgeReranker()
    monkeypatch.setattr(reranker, "_load_model", lambda: _FakeModel())

    result = reranker.rerank("q", [_cand("a", "xx")], top_k=5)
    assert set(result[0].keys()) == {"chunk_id", "document_id", "content", "score"}
