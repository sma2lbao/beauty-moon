# Hybrid Retrieval (BM25 + RRF) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a BM25 keyword-retrieval path alongside the existing vector search, fuse both with Reciprocal Rank Fusion (RRF), and gate it behind a `retrieval_mode` config switch.

**Architecture:** A new `app/retrieval/` package holds three focused modules — `bm25.py` (per-knowledge-base in-memory BM25 index with lazy build + active/TTL invalidation), `fusion.py` (pure RRF function), and `hybrid.py` (orchestrator that dispatches on `settings.retrieval_mode`). The existing `app/db/vectorstore.py` is untouched and called as one of the two paths. Call sites in `rag_graph.py` and `rag_search.py` swap `search_vectorstore(...)` for `hybrid_search(...)`; ingestion write/delete points call `invalidate_bm25_cache(...)`.

**Tech Stack:** Python 3.11+, `rank-bm25`, `jieba`, SQLAlchemy (MySQL), Chroma (existing), pytest, structlog, prometheus_client.

## Global Constraints

- Python: `>=3.11,<4` (matches `pyproject.toml`).
- `hybrid_search` return value MUST be `list[dict]` with keys `chunk_id`, `document_id`, `content`, `score` — identical shape to existing `search_vectorstore`, so call sites change minimally.
- Vector path stays the required path: on vector error, raise; on BM25 error, degrade to vector-only and log `warning` (never crash Q&A).
- KB isolation: BM25 index is built per `knowledge_base_id` via `Chunk JOIN Document WHERE Document.knowledge_base_id == kb_id`.
- Default `retrieval_mode` = `hybrid`.
- Stop words: built-in module constant (Chinese + English), NOT an external file.
- Follow existing enum style: `from enum import StrEnum`; config fields use `pydantic.Field(default=..., description=...)`.
- Config enums for retrieval live in `app/core/config.py` alongside the other `StrEnum`s.
- Do NOT modify `app/db/vectorstore.py`.
- New deps added to `apps/luna-corpus/pyproject.toml` `dependencies` list.

---

### Task 1: Add dependencies and retrieval config

**Files:**
- Modify: `apps/luna-corpus/pyproject.toml` (`dependencies` list, ends near line 40)
- Modify: `apps/luna-corpus/app/core/config.py` (add `RetrievalMode` enum near the other `StrEnum`s ~line 43; add fields in the `# RAG` block ~line 166)
- Test: `apps/luna-corpus/tests/core/test_config.py` (existing file — append a test)

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `RetrievalMode` StrEnum with members `VECTOR = "vector"`, `HYBRID = "hybrid"`.
  - `Settings.retrieval_mode: RetrievalMode` (default `HYBRID`)
  - `Settings.retrieval_candidate_k: int` (default `20`)
  - `Settings.rrf_k: int` (default `60`)
  - `Settings.bm25_cache_ttl_seconds: int` (default `600`)
  - Existing `Settings.retrieval_top_k: int` (default `5`) is reused as final result count.

- [ ] **Step 1: Write the failing test**

Append to `apps/luna-corpus/tests/core/test_config.py`:

```python
def test_retrieval_mode_defaults_to_hybrid():
    from app.core.config import RetrievalMode, Settings

    settings = Settings()
    assert settings.retrieval_mode == RetrievalMode.HYBRID
    assert settings.retrieval_candidate_k == 20
    assert settings.rrf_k == 60
    assert settings.bm25_cache_ttl_seconds == 600


def test_retrieval_mode_can_be_set_to_vector():
    from app.core.config import RetrievalMode, Settings

    settings = Settings(retrieval_mode="vector")
    assert settings.retrieval_mode == RetrievalMode.VECTOR
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx run luna-corpus:test -- tests/core/test_config.py -k retrieval_mode -v`
Expected: FAIL with `ImportError: cannot import name 'RetrievalMode'`

- [ ] **Step 3: Add the enum and config fields**

In `apps/luna-corpus/app/core/config.py`, after the `VectorStoreBackendType` StrEnum (~line 47), add:

```python
class RetrievalMode(StrEnum):
    """Retrieval strategies."""

    VECTOR = "vector"
    HYBRID = "hybrid"
```

In the `# RAG` block, right after the existing `retrieval_top_k` field (~line 166), add:

```python
    retrieval_mode: RetrievalMode = Field(
        default=RetrievalMode.HYBRID,
        description="检索模式：vector 仅向量；hybrid 向量+BM25 融合",
    )
    retrieval_candidate_k: int = Field(
        default=20, description="hybrid 模式下每路检索的候选数量"
    )
    rrf_k: int = Field(default=60, description="RRF 融合常数")
    bm25_cache_ttl_seconds: int = Field(
        default=600, description="BM25 索引缓存兜底过期时间（秒）"
    )
```

- [ ] **Step 4: Add dependencies to pyproject.toml**

In `apps/luna-corpus/pyproject.toml`, inside the `dependencies = [` list, add before the closing `]`:

```python
    # Hybrid retrieval (BM25 keyword search)
    "rank-bm25>=0.2.2",
    "jieba>=0.42.1",
```

Then install: `cd /Users/sma2lbao/Code/beauty-moon && uv sync`

- [ ] **Step 5: Run test to verify it passes**

Run: `pnpm nx run luna-corpus:test -- tests/core/test_config.py -k retrieval_mode -v`
Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/pyproject.toml apps/luna-corpus/app/core/config.py apps/luna-corpus/tests/core/test_config.py uv.lock
git commit -m "feat(corpus): add retrieval_mode config and BM25 deps"
```

---

### Task 2: RRF fusion (pure function)

**Files:**
- Create: `apps/luna-corpus/app/retrieval/__init__.py`
- Create: `apps/luna-corpus/app/retrieval/fusion.py`
- Test: `apps/luna-corpus/tests/retrieval/__init__.py`, `apps/luna-corpus/tests/retrieval/test_fusion.py`

**Interfaces:**
- Consumes: nothing (pure function).
- Produces:
  - `reciprocal_rank_fusion(result_lists: list[list[dict]], *, k: int = 60, top_k: int = 5) -> list[dict]`
  - Each input dict has at least `chunk_id`, `document_id`, `content`, `score`. Output dicts carry the same identity fields; `score` is replaced by the RRF score. First-seen `document_id`/`content` win for a given `chunk_id`.

- [ ] **Step 1: Create package markers**

Create `apps/luna-corpus/app/retrieval/__init__.py` (empty file, content: `"""Retrieval orchestration: vector, BM25, and fusion."""` ).
Create `apps/luna-corpus/tests/retrieval/__init__.py` (empty file).

- [ ] **Step 2: Write the failing test**

Create `apps/luna-corpus/tests/retrieval/test_fusion.py`:

```python
"""Tests for Reciprocal Rank Fusion."""
from app.retrieval.fusion import reciprocal_rank_fusion


def _doc(chunk_id, score):
    return {
        "chunk_id": chunk_id,
        "document_id": f"doc-{chunk_id}",
        "content": f"content {chunk_id}",
        "score": score,
    }


def test_single_chunk_in_both_lists_accumulates_score():
    vec = [_doc("a", 0.9), _doc("b", 0.5)]
    bm25 = [_doc("a", 3.0), _doc("c", 1.0)]

    fused = reciprocal_rank_fusion([vec, bm25], k=60, top_k=10)

    scores = {d["chunk_id"]: d["score"] for d in fused}
    # "a" is rank 0 in both lists: 1/60 + 1/60
    assert scores["a"] == 2 / 60
    # "b" only in vec at rank 1; "c" only in bm25 at rank 1
    assert scores["b"] == 1 / 61
    assert scores["c"] == 1 / 61
    # "a" ranks first
    assert fused[0]["chunk_id"] == "a"


def test_empty_list_degrades_to_other():
    vec = [_doc("a", 0.9), _doc("b", 0.5)]

    fused = reciprocal_rank_fusion([vec, []], k=60, top_k=10)

    assert [d["chunk_id"] for d in fused] == ["a", "b"]


def test_both_empty_returns_empty():
    assert reciprocal_rank_fusion([[], []], k=60, top_k=10) == []


def test_top_k_truncates():
    vec = [_doc("a", 0.9), _doc("b", 0.5), _doc("c", 0.1)]

    fused = reciprocal_rank_fusion([vec], k=60, top_k=2)

    assert len(fused) == 2
    assert [d["chunk_id"] for d in fused] == ["a", "b"]


def test_output_preserves_identity_fields():
    vec = [_doc("a", 0.9)]

    fused = reciprocal_rank_fusion([vec], k=60, top_k=1)

    assert fused[0]["document_id"] == "doc-a"
    assert fused[0]["content"] == "content a"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pnpm nx run luna-corpus:test -- tests/retrieval/test_fusion.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.retrieval.fusion'`

- [ ] **Step 4: Implement `fusion.py`**

Create `apps/luna-corpus/app/retrieval/fusion.py`:

```python
"""Reciprocal Rank Fusion for combining ranked retrieval result lists."""
from typing import Any


def reciprocal_rank_fusion(
    result_lists: list[list[dict[str, Any]]],
    *,
    k: int = 60,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Fuse multiple ranked result lists via RRF.

    Each list must already be sorted best-first. Results are aggregated by
    ``chunk_id`` with ``score = sum(1 / (k + rank))`` across the lists in
    which the chunk appears (rank is 0-based). Identity fields
    (``document_id``, ``content``) from the first occurrence win.

    Args:
        result_lists: Ranked result dicts, one list per retrieval path.
        k: RRF constant; larger values flatten the contribution of rank.
        top_k: Maximum number of fused results to return.

    Returns:
        Fused results sorted by descending RRF score, truncated to ``top_k``.
    """
    fused: dict[str, dict[str, Any]] = {}

    for results in result_lists:
        for rank, item in enumerate(results):
            chunk_id = item["chunk_id"]
            contribution = 1.0 / (k + rank)
            if chunk_id in fused:
                fused[chunk_id]["score"] += contribution
            else:
                fused[chunk_id] = {
                    "chunk_id": chunk_id,
                    "document_id": item.get("document_id"),
                    "content": item.get("content"),
                    "score": contribution,
                }

    ranked = sorted(fused.values(), key=lambda d: d["score"], reverse=True)
    return ranked[:top_k]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pnpm nx run luna-corpus:test -- tests/retrieval/test_fusion.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/app/retrieval/__init__.py apps/luna-corpus/app/retrieval/fusion.py apps/luna-corpus/tests/retrieval/
git commit -m "feat(corpus): add RRF fusion for hybrid retrieval"
```

---

### Task 3: BM25 index with tokenization

**Files:**
- Create: `apps/luna-corpus/app/retrieval/bm25.py`
- Test: `apps/luna-corpus/tests/retrieval/test_bm25.py`

**Interfaces:**
- Consumes: `app.db.database.SessionLocal`, `app.db.models.Chunk`, `app.db.models.Document`, `app.core.config.get_settings`.
- Produces:
  - `Bm25Result` frozen dataclass: `chunk_id: str`, `document_id: str`, `content: str`, `score: float`.
  - `class Bm25Index` with `search(self, query: str, top_k: int) -> list[Bm25Result]`.
  - `get_bm25_index(kb_id: str) -> Bm25Index` (lazy build + cache, honoring TTL).
  - `invalidate_bm25_cache(kb_id: str) -> None`.
  - `reset_bm25_cache() -> None` (test helper: clears all entries).
  - `_tokenize(text: str) -> list[str]` (jieba search-mode cut minus stop words/whitespace).
  - `_build_index(kb_id: str) -> Bm25Index`.
  - Module clock indirection `_now() -> float` (wraps `time.monotonic`) so tests can monkeypatch it for TTL.

- [ ] **Step 1: Write the failing test**

Create `apps/luna-corpus/tests/retrieval/test_bm25.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx run luna-corpus:test -- tests/retrieval/test_bm25.py -v`
Expected: FAIL with `AttributeError`/`ImportError` (module members not defined)

- [ ] **Step 3: Implement `bm25.py`**

Create `apps/luna-corpus/app/retrieval/bm25.py`:

```python
"""Per-knowledge-base in-memory BM25 index with lazy build and caching."""
import re
import time
from dataclasses import dataclass

import jieba
from rank_bm25 import BM25Okapi

from app.core.config import get_settings
from app.db.database import SessionLocal
from app.db.models import Chunk, Document
from app.observability.logging import get_logger

logger = get_logger("luna.retrieval.bm25")
settings = get_settings()

# Built-in stop words (Chinese + English). Intentionally small; no external file.
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "的", "了", "和", "是", "在", "我", "有", "也", "就", "都", "而", "及",
        "与", "或", "一个", "这", "那", "这是", "关于", "对于", "以及", "然后",
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is",
        "are", "be", "this", "that", "with", "as", "it",
    }
)
_WHITESPACE = re.compile(r"\s+")


def _now() -> float:
    """Monotonic clock indirection so tests can control TTL."""
    return time.monotonic()


@dataclass(frozen=True)
class Bm25Result:
    """A single BM25 hit."""

    chunk_id: str
    document_id: str
    content: str
    score: float


class Bm25Index:
    """BM25 index over the chunks of one knowledge base."""

    def __init__(
        self,
        kb_id: str,
        chunk_ids: list[str],
        document_ids: list[str],
        contents: list[str],
        tokenized_corpus: list[list[str]],
        bm25: BM25Okapi | None,
    ) -> None:
        self.kb_id = kb_id
        self._chunk_ids = chunk_ids
        self._document_ids = document_ids
        self._contents = contents
        self._tokenized_corpus = tokenized_corpus
        self._bm25 = bm25

    def search(self, query: str, top_k: int) -> list[Bm25Result]:
        """Return up to ``top_k`` BM25 hits for ``query`` (best-first)."""
        if self._bm25 is None or not self._chunk_ids:
            return []
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scores = self._bm25.get_scores(query_tokens)
        ranked = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )[:top_k]
        return [
            Bm25Result(
                chunk_id=self._chunk_ids[i],
                document_id=self._document_ids[i],
                content=self._contents[i],
                score=float(scores[i]),
            )
            for i in ranked
            if scores[i] > 0
        ]


def _tokenize(text: str) -> list[str]:
    """Tokenize with jieba search mode, dropping whitespace and stop words."""
    if not text or not text.strip():
        return []
    tokens = jieba.lcut_for_search(text)
    return [
        t
        for t in tokens
        if t.strip() and not _WHITESPACE.fullmatch(t) and t.lower() not in _STOP_WORDS
    ]


def _load_chunks(kb_id: str) -> list[tuple[str, str, str]]:
    """Load (chunk_id, document_id, content) rows for one knowledge base."""
    db = SessionLocal()
    try:
        rows = (
            db.query(Chunk.id, Chunk.document_id, Chunk.content)
            .join(Document, Chunk.document_id == Document.id)
            .filter(Document.knowledge_base_id == kb_id)
            .all()
        )
        return [(r[0], r[1], r[2]) for r in rows]
    finally:
        db.close()


def _build_index(kb_id: str) -> Bm25Index:
    """Build a BM25 index by reading all chunks for the knowledge base."""
    rows = _load_chunks(kb_id)
    chunk_ids = [r[0] for r in rows]
    document_ids = [r[1] for r in rows]
    contents = [r[2] for r in rows]
    tokenized_corpus = [_tokenize(c) for c in contents]

    # BM25Okapi rejects an empty corpus; guard for empty / all-stopword KBs.
    non_empty = [toks for toks in tokenized_corpus if toks]
    bm25 = BM25Okapi(tokenized_corpus) if non_empty else None

    return Bm25Index(
        kb_id, chunk_ids, document_ids, contents, tokenized_corpus, bm25
    )


# Module-level cache: kb_id -> (index, built_at_monotonic)
_cache: dict[str, tuple[Bm25Index, float]] = {}


def get_bm25_index(kb_id: str) -> Bm25Index:
    """Return a cached BM25 index for the KB, rebuilding on miss or TTL expiry."""
    entry = _cache.get(kb_id)
    if entry is not None:
        index, built_at = entry
        if _now() - built_at < settings.bm25_cache_ttl_seconds:
            return index

    index = _build_index(kb_id)
    _cache[kb_id] = (index, _now())
    return index


def invalidate_bm25_cache(kb_id: str) -> None:
    """Drop the cached index for a KB so the next search rebuilds it."""
    _cache.pop(kb_id, None)


def reset_bm25_cache() -> None:
    """Clear the entire BM25 cache (test helper)."""
    _cache.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm nx run luna-corpus:test -- tests/retrieval/test_bm25.py -v`
Expected: PASS (8 tests). If jieba prints a build-cache line to stderr, that is fine.

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/retrieval/bm25.py apps/luna-corpus/tests/retrieval/test_bm25.py
git commit -m "feat(corpus): add per-KB BM25 index with jieba tokenization"
```

---

### Task 4: Hybrid orchestrator

**Files:**
- Create: `apps/luna-corpus/app/retrieval/hybrid.py`
- Test: `apps/luna-corpus/tests/retrieval/test_hybrid.py`

**Interfaces:**
- Consumes:
  - `app.db.vectorstore.search_vectorstore(query_embedding, top_k, knowledge_base_id) -> list[dict]`
  - `app.retrieval.bm25.get_bm25_index(kb_id) -> Bm25Index`
  - `app.retrieval.fusion.reciprocal_rank_fusion(result_lists, *, k, top_k) -> list[dict]`
  - `app.core.config.get_settings` (reads `retrieval_mode`, `retrieval_candidate_k`, `rrf_k`, `retrieval_top_k`)
- Produces:
  - `hybrid_search(query: str, query_embedding: list[float], *, top_k: int, knowledge_base_id: str) -> list[dict]` returning dicts with `chunk_id`/`document_id`/`content`/`score`.

- [ ] **Step 1: Write the failing test**

Create `apps/luna-corpus/tests/retrieval/test_hybrid.py`:

```python
"""Tests for the hybrid retrieval orchestrator."""
import pytest

from app.core.config import RetrievalMode, Settings
from app.retrieval import hybrid
from app.retrieval.bm25 import Bm25Result


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
    monkeypatch.setattr(
        hybrid, "search_vectorstore",
        lambda query_embedding, top_k, knowledge_base_id: list(vector_results),
    )
    if raise_bm25:
        def _boom(kb_id):
            raise RuntimeError("bm25 down")
        monkeypatch.setattr(hybrid, "get_bm25_index", _boom)
    else:
        monkeypatch.setattr(
            hybrid, "get_bm25_index",
            lambda kb_id: _FakeBm25Index(bm25_results or []),
        )


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx run luna-corpus:test -- tests/retrieval/test_hybrid.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.retrieval.hybrid'`

- [ ] **Step 3: Implement `hybrid.py`**

Create `apps/luna-corpus/app/retrieval/hybrid.py`:

```python
"""Hybrid retrieval orchestrator: vector + BM25 fused with RRF."""
from typing import Any

from app.core.config import RetrievalMode, get_settings
from app.db.vectorstore import search_vectorstore
from app.observability.logging import get_logger
from app.observability.metrics import RAG_RETRIEVAL_DURATION, time_stage
from app.retrieval.bm25 import get_bm25_index
from app.retrieval.fusion import reciprocal_rank_fusion

logger = get_logger("luna.retrieval.hybrid")
settings = get_settings()


def _bm25_results(query: str, knowledge_base_id: str, candidate_k: int) -> list[dict[str, Any]]:
    """Run BM25 keyword search, returning normalized result dicts."""
    index = get_bm25_index(knowledge_base_id)
    hits = index.search(query, top_k=candidate_k)
    return [
        {
            "chunk_id": hit.chunk_id,
            "document_id": hit.document_id,
            "content": hit.content,
            "score": hit.score,
        }
        for hit in hits
    ]


def hybrid_search(
    query: str,
    query_embedding: list[float],
    *,
    top_k: int,
    knowledge_base_id: str,
) -> list[dict[str, Any]]:
    """Retrieve chunks for a query, dispatching on ``settings.retrieval_mode``.

    In ``vector`` mode this is exactly the existing vector search. In
    ``hybrid`` mode it runs vector + BM25 (each up to ``retrieval_candidate_k``)
    and fuses them with RRF, returning ``top_k`` results. A BM25 failure
    degrades to vector-only (logged as a warning); a vector failure propagates.
    """
    with time_stage(RAG_RETRIEVAL_DURATION):
        vector_results = search_vectorstore(
            query_embedding=query_embedding,
            top_k=(
                settings.retrieval_candidate_k
                if settings.retrieval_mode == RetrievalMode.HYBRID
                else top_k
            ),
            knowledge_base_id=knowledge_base_id,
        )

        if settings.retrieval_mode != RetrievalMode.HYBRID:
            return vector_results

        try:
            keyword_results = _bm25_results(
                query, knowledge_base_id, settings.retrieval_candidate_k
            )
        except Exception:  # BM25 must never break Q&A — degrade to vector-only.
            logger.warning(
                "bm25_search_failed_degrading_to_vector",
                knowledge_base_id=knowledge_base_id,
                exc_info=True,
            )
            return vector_results[:top_k]

        return reciprocal_rank_fusion(
            [vector_results, keyword_results],
            k=settings.rrf_k,
            top_k=top_k,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm nx run luna-corpus:test -- tests/retrieval/test_hybrid.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/retrieval/hybrid.py apps/luna-corpus/tests/retrieval/test_hybrid.py
git commit -m "feat(corpus): add hybrid retrieval orchestrator with RRF fusion"
```

---

### Task 5: Wire hybrid_search into rag_graph and rag_search tool

**Files:**
- Modify: `apps/luna-corpus/app/graph/rag_graph.py` (import line 10; `retrieve_node` ~129-134; `answer_question_stream` ~305-314; `answer_question_multi_turn_stream` ~460-469)
- Modify: `apps/luna-corpus/app/agent/tools/rag_search.py` (import line 3; `_format_rag_results` ~27-32)
- Test: `apps/luna-corpus/tests/graph/test_rag_graph_hybrid.py` (new)

**Interfaces:**
- Consumes: `app.retrieval.hybrid.hybrid_search(query, query_embedding, *, top_k, knowledge_base_id) -> list[dict]`
- Produces: no new public interface; behavior change only. `retrieve_node` still returns `{"retrieved_docs": [...]}`.

- [ ] **Step 1: Write the failing test**

Create `apps/luna-corpus/tests/graph/test_rag_graph_hybrid.py` (create `tests/graph/__init__.py` first if it does not exist — check with `ls apps/luna-corpus/tests/graph/`):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx run luna-corpus:test -- tests/graph/test_rag_graph_hybrid.py -v`
Expected: FAIL with `AttributeError: <module 'app.graph.rag_graph'> does not have the attribute 'hybrid_search'`

- [ ] **Step 3: Edit `rag_graph.py` imports**

Replace line 10 `from app.db.vectorstore import search_vectorstore` with:

```python
from app.retrieval.hybrid import hybrid_search
```

- [ ] **Step 4: Edit `retrieve_node` (~line 128-134)**

Replace:

```python
    # Search vector store
    with time_stage(RAG_RETRIEVAL_DURATION):
        results = search_vectorstore(
            query_embedding=query_embedding,
            top_k=settings.retrieval_top_k,
            knowledge_base_id=knowledge_base_id,
        )
```

with (the `time_stage` wrapper now lives inside `hybrid_search`, so drop it here):

```python
    # Retrieve documents (vector or hybrid, per settings.retrieval_mode)
    results = hybrid_search(
        question,
        query_embedding,
        top_k=settings.retrieval_top_k,
        knowledge_base_id=knowledge_base_id,
    )
```

- [ ] **Step 5: Edit `answer_question_stream` (~line 302-314)**

Replace the status message and search block:

```python
    # Search vector store
    yield {
        "event": "retrieval_status",
        "data": "正在检索相似文档...",
    }

    results = search_vectorstore(
        query_embedding=query_embedding,
        top_k=settings.retrieval_top_k,
        knowledge_base_id=knowledge_base_id,
    )
```

with:

```python
    # Retrieve documents (vector or hybrid, per settings.retrieval_mode)
    yield {
        "event": "retrieval_status",
        "data": "正在进行混合检索（向量 + 关键词）...",
    }

    results = hybrid_search(
        question,
        query_embedding,
        top_k=settings.retrieval_top_k,
        knowledge_base_id=knowledge_base_id,
    )
```

- [ ] **Step 6: Edit `answer_question_multi_turn_stream` (~line 459-469)**

Replace:

```python
    # Search vector store
    yield {
        "event": "retrieval_status",
        "data": "正在检索相似文档...",
    }

    results = search_vectorstore(
        query_embedding=query_embedding,
        top_k=settings.retrieval_top_k,
        knowledge_base_id=knowledge_base_id,
    )
```

with:

```python
    # Retrieve documents (vector or hybrid, per settings.retrieval_mode)
    yield {
        "event": "retrieval_status",
        "data": "正在进行混合检索（向量 + 关键词）...",
    }

    results = hybrid_search(
        question,
        query_embedding,
        top_k=settings.retrieval_top_k,
        knowledge_base_id=knowledge_base_id,
    )
```

- [ ] **Step 7: Remove now-unused import**

If `RAG_RETRIEVAL_DURATION` is no longer referenced in `rag_graph.py` (it was only used in `retrieve_node`), remove it from the `from app.observability.metrics import (...)` block, keeping `LLM_GENERATION_DURATION` and `time_stage` (both still used in `generate_node`). Verify with:

Run: `cd /Users/sma2lbao/Code/beauty-moon/apps/luna-corpus && grep -n "RAG_RETRIEVAL_DURATION" app/graph/rag_graph.py`
Expected: no matches after edit.

- [ ] **Step 8: Edit `rag_search.py`**

Replace line 3 `from app.db.vectorstore import search_vectorstore` with:

```python
from app.retrieval.hybrid import hybrid_search
```

In `_format_rag_results` (~line 27-32), replace:

```python
        query_embedding = embed_text(query)
        results = search_vectorstore(
            query_embedding,
            top_k=top_k,
            knowledge_base_id=knowledge_base_id,
        )
```

with:

```python
        query_embedding = embed_text(query)
        results = hybrid_search(
            query,
            query_embedding,
            top_k=top_k,
            knowledge_base_id=knowledge_base_id,
        )
```

- [ ] **Step 9: Run the new test and the full retrieval + graph suites**

Run: `pnpm nx run luna-corpus:test -- tests/graph/test_rag_graph_hybrid.py tests/retrieval -v`
Expected: PASS (all)

- [ ] **Step 10: Commit**

```bash
git add apps/luna-corpus/app/graph/rag_graph.py apps/luna-corpus/app/agent/tools/rag_search.py apps/luna-corpus/tests/graph/
git commit -m "feat(corpus): route Q&A retrieval through hybrid_search"
```

---

### Task 6: Cache invalidation hooks in ingestion

**Files:**
- Modify: `apps/luna-corpus/app/services/document_processor.py` (import block ~line 9; after `add_chunks_to_vectorstore(...)` ~line 133)
- Modify: `apps/luna-corpus/app/services/ingestion/service.py` (import block ~line 13; after `delete_chunks_from_vectorstore(...)` ~line 261)
- Test: `apps/luna-corpus/tests/services/test_bm25_invalidation.py` (new)

**Interfaces:**
- Consumes: `app.retrieval.bm25.invalidate_bm25_cache(kb_id: str) -> None`
- Produces: no new interface; side-effect only.

- [ ] **Step 1: Write the failing test**

Check `ls apps/luna-corpus/tests/services/` and create `tests/services/__init__.py` if missing.
Create `apps/luna-corpus/tests/services/test_bm25_invalidation.py`:

```python
"""Ingestion write/delete paths invalidate the BM25 cache."""
from app.services import document_processor
from app.services.ingestion import service as ingestion_service


def test_document_processor_module_imports_invalidate():
    # Guards against the import being dropped in a future refactor.
    assert hasattr(document_processor, "invalidate_bm25_cache")


def test_ingestion_service_module_imports_invalidate():
    assert hasattr(ingestion_service, "invalidate_bm25_cache")
```

Note: these guard-tests confirm the hook is wired without standing up MySQL/storage. The behavioral wiring is verified by the existing ingestion integration tests plus manual code review of the two call sites below.

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx run luna-corpus:test -- tests/services/test_bm25_invalidation.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'invalidate_bm25_cache'`

- [ ] **Step 3: Edit `document_processor.py`**

Add to the import block (after line 9 `from app.db.vectorstore import ...`):

```python
from app.retrieval.bm25 import invalidate_bm25_cache
```

After the `add_chunks_to_vectorstore(...)` call (ends ~line 133), before `# Update status`, add:

```python
            # Refresh keyword index so new chunks are searchable immediately.
            invalidate_bm25_cache(document.knowledge_base_id)
```

- [ ] **Step 4: Edit `ingestion/service.py`**

Add to the import block (near line 13 `from app.db.vectorstore import delete_chunks_from_vectorstore`):

```python
from app.retrieval.bm25 import invalidate_bm25_cache
```

In `delete_file`, after the chunk-delete block (~line 260-261):

```python
        # Delete chunks from vector store before deleting document
        if upload.document and upload.document.chunks:
            delete_chunks_from_vectorstore([c.id for c in upload.document.chunks])
```

add:

```python
        # Drop keyword index so deleted chunks stop matching.
        invalidate_bm25_cache(knowledge_base_id)
```

- [ ] **Step 5: Run the guard test**

Run: `pnpm nx run luna-corpus:test -- tests/services/test_bm25_invalidation.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/app/services/document_processor.py apps/luna-corpus/app/services/ingestion/service.py apps/luna-corpus/tests/services/
git commit -m "feat(corpus): invalidate BM25 cache on chunk write and delete"
```

---

### Task 7: Full-suite regression and docs note

**Files:**
- Modify: `apps/luna-corpus/app/db/vectorstore.py` — NONE (confirm untouched).
- Modify: `apps/luna-corpus/README.md` OR a docstring in `app/retrieval/__init__.py` — brief note on `retrieval_mode`.

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: nothing new.

- [ ] **Step 1: Run the entire luna-corpus test suite**

Run: `pnpm nx run luna-corpus:test`
Expected: PASS. In particular `tests/db/test_vectorstore.py` and `tests/api/test_audit_qa_index.py` must still pass unchanged (vector path and return shape preserved).

- [ ] **Step 2: If any regression, fix before proceeding**

Common causes: a call site still importing `search_vectorstore` from `rag_graph`, or a test that patched `rag_graph.search_vectorstore` (now `hybrid_search`). Grep:

Run: `cd /Users/sma2lbao/Code/beauty-moon/apps/luna-corpus && grep -rn "search_vectorstore" app/graph app/agent`
Expected: no matches (both moved to `hybrid_search`).

- [ ] **Step 3: Confirm vectorstore.py untouched**

Run: `cd /Users/sma2lbao/Code/beauty-moon && git diff --name-only main -- apps/luna-corpus/app/db/vectorstore.py`
Expected: no output (file unchanged on this branch).

- [ ] **Step 4: Add a short usage note**

Append to `apps/luna-corpus/app/retrieval/__init__.py`:

```python
"""Retrieval orchestration: vector, BM25, and fusion.

Set ``retrieval_mode`` in settings to ``vector`` (vector-only, legacy
behavior) or ``hybrid`` (vector + BM25 fused with RRF, default). BM25 index
is per knowledge base, lazily built and cached with active invalidation on
chunk write/delete plus a ``bm25_cache_ttl_seconds`` fallback.
"""
```

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/retrieval/__init__.py
git commit -m "docs(corpus): document retrieval_mode in retrieval package"
```

---

## Self-Review

**Spec coverage:**
- Config switch `retrieval_mode` + candidate_k/rrf_k/ttl → Task 1 ✅
- New `app/retrieval/` package, `vectorstore.py` untouched → Tasks 2-4, verified Task 7 ✅
- `bm25.py` (lazy build, per-KB, jieba, cache, invalidation, TTL, built-in stopwords) → Task 3 ✅
- `fusion.py` RRF pure function → Task 2 ✅
- `hybrid.py` dispatch + return-shape parity + candidate_k-then-fuse + BM25-degrade-to-vector → Task 4 ✅
- Call sites: 3 in `rag_graph.py` + 1 in `rag_search.py`, stream status message change → Task 5 ✅
- Invalidation hooks in `document_processor.py` + `ingestion/service.py` → Task 6 ✅
- Observability: `time_stage(RAG_RETRIEVAL_DURATION)` moved into `hybrid_search` → Task 4/5 ✅
- Error handling (vector raises, BM25 degrades, empty results, empty query) → Tasks 3-4 ✅
- Tests under `tests/retrieval/` + graph + services → Tasks 2-6 ✅
- Deps `rank-bm25`, `jieba` → Task 1 ✅

**Placeholder scan:** No TBD/TODO; all code blocks complete and directly usable.

**Type consistency:** `hybrid_search(query, query_embedding, *, top_k, knowledge_base_id)` signature identical across Tasks 4, 5. `Bm25Result` fields (`chunk_id/document_id/content/score`) consistent across Tasks 3, 4. `Bm25Index.__init__` 6-arg form matches the fakes in Task 3 tests. `reciprocal_rank_fusion(result_lists, *, k, top_k)` consistent across Tasks 2, 4. `invalidate_bm25_cache(kb_id)` consistent across Tasks 3, 6.

**Note for executor:** Run all `pnpm nx` commands from the repo root `/Users/sma2lbao/Code/beauty-moon`.
