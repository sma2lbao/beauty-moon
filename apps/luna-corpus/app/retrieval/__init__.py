"""Retrieval orchestration: vector, BM25, fusion, and rerank.

Set ``retrieval_mode`` in settings to ``vector`` (vector-only, legacy
behavior), ``hybrid`` (vector + BM25 fused with RRF, default), or ``rerank``
(hybrid fusion to ``rerank_candidate_k`` candidates, then a cross-encoder
reranks to ``top_k``). The BM25 index is per knowledge base, lazily built and
cached with active invalidation on chunk write/delete plus a
``bm25_cache_ttl_seconds`` fallback. Rerank uses a KB-independent model
singleton; ``sentence-transformers`` is an optional dependency (extra
``rerank``) and rerank failures degrade to the fused results.

Metadata filtering: ``hybrid_search`` accepts an optional ``filters``
(``MetadataFilter``) plus ``field_types``. The vector side pushes conditions
down to a Chroma ``where`` clause, the BM25 side applies a post-filter, and the
candidate window is widened by ``filter_over_fetch_multiplier`` to compensate
for post-filter loss. If filter construction fails, retrieval degrades to the
no-filter path. Translation logic lives in ``app.retrieval.filters``.
"""
