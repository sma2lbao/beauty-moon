"""Tests for the reranker abstraction and backend dispatch."""
import pytest

from app.retrieval.rerank import base


class _FakeReranker(base.Reranker):
    def rerank(self, query, candidates, *, top_k):
        return candidates[:top_k]


def test_reranker_is_abstract():
    with pytest.raises(TypeError):
        base.Reranker()  # abstract, cannot instantiate


def test_get_reranker_returns_singleton(monkeypatch):
    base.reset_reranker_cache()
    monkeypatch.setattr(base, "_build_reranker", lambda: _FakeReranker())
    first = base.get_reranker()
    second = base.get_reranker()
    assert first is second


def test_get_reranker_unknown_provider_raises(monkeypatch):
    base.reset_reranker_cache()
    monkeypatch.setattr(base.settings, "reranker_provider", "nope")
    with pytest.raises(ValueError):
        base._build_reranker()
