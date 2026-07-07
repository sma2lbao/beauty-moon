"""Tests for the hybrid retrieval orchestrator."""
import pytest

from app.core.config import RetrievalMode, Settings
from app.retrieval import hybrid
from app.retrieval.bm25 import Bm25Result
from app.retrieval.rerank import base as rerank_base


class _FakeBm25Index:
    def __init__(self, results):
        self._results = results

    def search(self, query, top_k):
        return self._results[:top_k]


def _vdoc(chunk_id):
    return {
        "chunk_id": chunk_id,
        "document_id": f"doc-{chunk_id}",
        "content": f"content {chunk_id}",
        "score": 0.9,
    }


def _bm25hit(chunk_id):
    return Bm25Result(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        content=f"content {chunk_id}",
        score=3.0,
    )


def _configure(monkeypatch, mode, vector_results, bm25_results=None, raise_bm25=False):
    monkeypatch.setattr(hybrid, "settings", Settings(retrieval_mode=mode))
    captured: dict = {}

    def _fake_vector_search(query_embedding, top_k, knowledge_base_id):
        captured["vector_top_k"] = top_k
        return list(vector_results)

    monkeypatch.setattr(hybrid, "search_vectorstore", _fake_vector_search)
    if raise_bm25:
        def _boom(kb_id):
            raise RuntimeError("bm25 down")
        monkeypatch.setattr(hybrid, "get_bm25_index", _boom)
    else:
        monkeypatch.setattr(
            hybrid, "get_bm25_index",
            lambda kb_id: _FakeBm25Index(bm25_results or []),
        )
    return captured


def test_vector_mode_returns_vector_results_only(monkeypatch):
    _configure(monkeypatch, RetrievalMode.VECTOR, [_vdoc("a"), _vdoc("b")])

    results = hybrid.hybrid_search(
        "q", [0.1, 0.2], top_k=5, knowledge_base_id="kb-1"
    )

    assert [r["chunk_id"] for r in results] == ["a", "b"]
    assert set(results[0].keys()) == {"chunk_id", "document_id", "content", "score"}


def test_hybrid_mode_fuses_both_paths(monkeypatch):
    _configure(
        monkeypatch,
        RetrievalMode.HYBRID,
        vector_results=[_vdoc("a"), _vdoc("b")],
        bm25_results=[_bm25hit("a"), _bm25hit("c")],
    )

    results = hybrid.hybrid_search(
        "q", [0.1, 0.2], top_k=5, knowledge_base_id="kb-1"
    )

    ids = [r["chunk_id"] for r in results]
    # "a" appears in both paths -> ranks first after RRF
    assert ids[0] == "a"
    assert set(ids) == {"a", "b", "c"}
    assert set(results[0].keys()) == {"chunk_id", "document_id", "content", "score"}


def test_hybrid_mode_degrades_to_vector_on_bm25_error(monkeypatch):
    _configure(
        monkeypatch,
        RetrievalMode.HYBRID,
        vector_results=[_vdoc("a"), _vdoc("b")],
        raise_bm25=True,
    )

    results = hybrid.hybrid_search(
        "q", [0.1, 0.2], top_k=5, knowledge_base_id="kb-1"
    )

    assert [r["chunk_id"] for r in results] == ["a", "b"]


def test_hybrid_mode_requests_candidate_k_from_vector_store(monkeypatch):
    captured = _configure(
        monkeypatch,
        RetrievalMode.HYBRID,
        vector_results=[_vdoc("a")],
        bm25_results=[_bm25hit("a")],
    )

    hybrid.hybrid_search("q", [0.1, 0.2], top_k=5, knowledge_base_id="kb-1")

    # HYBRID should over-fetch to retrieval_candidate_k, not caller's top_k.
    assert captured["vector_top_k"] == Settings().retrieval_candidate_k
    assert captured["vector_top_k"] != 5


def test_vector_mode_passes_caller_top_k_to_vector_store(monkeypatch):
    captured = _configure(
        monkeypatch,
        RetrievalMode.VECTOR,
        vector_results=[_vdoc("a")],
    )

    hybrid.hybrid_search("q", [0.1, 0.2], top_k=5, knowledge_base_id="kb-1")

    assert captured["vector_top_k"] == 5


def test_hybrid_degrade_slice_respects_top_k(monkeypatch):
    # 7 vector docs > top_k=5, BM25 raises, degrade path must slice to 5.
    _configure(
        monkeypatch,
        RetrievalMode.HYBRID,
        vector_results=[_vdoc(f"c{i}") for i in range(7)],
        raise_bm25=True,
    )

    results = hybrid.hybrid_search(
        "q", [0.1, 0.2], top_k=5, knowledge_base_id="kb-1"
    )

    assert len(results) == 5
    assert [r["chunk_id"] for r in results] == [f"c{i}" for i in range(5)]


def test_rerank_mode_reranks_fused_candidates(monkeypatch):
    _configure(
        monkeypatch,
        RetrievalMode.RERANK,
        vector_results=[_vdoc("a"), _vdoc("b")],
        bm25_results=[_bm25hit("c")],
    )

    # Stub reranker: pick "c" to the top to prove rerank ran after fusion.
    class _StubReranker:
        def rerank(self, query, candidates, *, top_k):
            ordered = sorted(candidates, key=lambda d: d["chunk_id"] != "c")
            return ordered[:top_k]

    monkeypatch.setattr(rerank_base, "get_reranker", lambda: _StubReranker())

    results = hybrid.hybrid_search(
        "q", [0.1, 0.2], top_k=2, knowledge_base_id="kb-1"
    )

    assert results[0]["chunk_id"] == "c"
    assert len(results) == 2


def test_rerank_mode_overfetches_candidate_k(monkeypatch):
    captured = _configure(
        monkeypatch,
        RetrievalMode.RERANK,
        vector_results=[_vdoc("a")],
        bm25_results=[_bm25hit("a")],
    )
    monkeypatch.setattr(
        rerank_base, "get_reranker",
        lambda: type("R", (), {"rerank": lambda self, q, c, *, top_k: c[:top_k]})(),
    )

    hybrid.hybrid_search("q", [0.1, 0.2], top_k=5, knowledge_base_id="kb-1")

    assert captured["vector_top_k"] == Settings().rerank_candidate_k


def test_rerank_mode_degrades_when_reranker_raises(monkeypatch):
    _configure(
        monkeypatch,
        RetrievalMode.RERANK,
        vector_results=[_vdoc("a"), _vdoc("b")],
        bm25_results=[_bm25hit("c")],
    )

    def _boom():
        raise RuntimeError("reranker down")

    monkeypatch.setattr(rerank_base, "get_reranker", _boom)

    results = hybrid.hybrid_search(
        "q", [0.1, 0.2], top_k=5, knowledge_base_id="kb-1"
    )

    # Degrades to fused results; "a" (both paths) still ranks first.
    assert results[0]["chunk_id"] == "a"
    assert {r["chunk_id"] for r in results} == {"a", "b", "c"}
