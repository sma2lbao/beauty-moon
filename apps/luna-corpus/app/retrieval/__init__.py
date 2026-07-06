"""Retrieval orchestration: vector, BM25, and fusion.

Set ``retrieval_mode`` in settings to ``vector`` (vector-only, legacy
behavior) or ``hybrid`` (vector + BM25 fused with RRF, default). BM25 index
is per knowledge base, lazily built and cached with active invalidation on
chunk write/delete plus a ``bm25_cache_ttl_seconds`` fallback.
"""
