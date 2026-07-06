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
