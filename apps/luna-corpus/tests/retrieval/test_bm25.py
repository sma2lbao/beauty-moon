"""Tests for the per-knowledge-base BM25 index."""
import pytest

from app.retrieval import bm25


@pytest.fixture(autouse=True)
def _clear_cache():
    bm25.reset_bm25_cache()
    yield
    bm25.reset_bm25_cache()


def test_tokenize_drops_stop_words_and_whitespace():
    tokens = bm25._tokenize("这是 一个 关于 向量检索 的 说明")
    assert "的" not in tokens
    assert "" not in tokens
    assert "向量检索" in tokens or "向量" in tokens


def test_tokenize_empty_query_returns_empty():
    assert bm25._tokenize("") == []
    assert bm25._tokenize("的 是 了") == []


def _make_index(monkeypatch, rows):
    """Build an index directly from (chunk_id, document_id, content) rows."""
    monkeypatch.setattr(bm25, "_load_chunks", lambda kb_id: rows)
    return bm25._build_index("kb-1")


def test_search_ranks_keyword_hit_first(monkeypatch):
    rows = [
        ("c1", "d1", "苹果 和 香蕉 都是 水果"),
        ("c2", "d2", "向量检索 使用 余弦相似度"),
        ("c3", "d3", "今天 天气 很好"),
    ]
    index = _make_index(monkeypatch, rows)

    results = index.search("向量检索", top_k=3)

    assert results[0].chunk_id == "c2"
    assert isinstance(results[0].score, float)


def test_empty_kb_returns_empty(monkeypatch):
    index = _make_index(monkeypatch, [])
    assert index.search("anything", top_k=5) == []


def test_empty_query_returns_empty(monkeypatch):
    rows = [("c1", "d1", "向量检索 使用 余弦相似度")]
    index = _make_index(monkeypatch, rows)
    assert index.search("的 是 了", top_k=5) == []


def test_cache_builds_once(monkeypatch):
    calls = {"n": 0}

    def fake_build(kb_id):
        calls["n"] += 1
        return bm25.Bm25Index("kb-1", [], [], [], [], None)

    monkeypatch.setattr(bm25, "_build_index", fake_build)

    bm25.get_bm25_index("kb-1")
    bm25.get_bm25_index("kb-1")

    assert calls["n"] == 1


def test_invalidate_forces_rebuild(monkeypatch):
    calls = {"n": 0}

    def fake_build(kb_id):
        calls["n"] += 1
        return bm25.Bm25Index("kb-1", [], [], [], [], None)

    monkeypatch.setattr(bm25, "_build_index", fake_build)

    bm25.get_bm25_index("kb-1")
    bm25.invalidate_bm25_cache("kb-1")
    bm25.get_bm25_index("kb-1")

    assert calls["n"] == 2


def test_ttl_expiry_forces_rebuild(monkeypatch):
    calls = {"n": 0}
    clock = {"t": 1000.0}

    def fake_build(kb_id):
        calls["n"] += 1
        return bm25.Bm25Index("kb-1", [], [], [], [], None)

    monkeypatch.setattr(bm25, "_build_index", fake_build)
    monkeypatch.setattr(bm25, "_now", lambda: clock["t"])

    bm25.get_bm25_index("kb-1")   # built at t=1000
    clock["t"] = 1000.0 + 601      # default TTL 600s exceeded
    bm25.get_bm25_index("kb-1")

    assert calls["n"] == 2
