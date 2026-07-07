"""Rerank stage: cross-encoder precision reranking over fused candidates.

Enabled via ``retrieval_mode=rerank``. Backend selected by
``reranker_provider`` (currently ``bge``, local CrossEncoder). Reranking must
never break Q&A: failures degrade to the fused results (see ``rerank_results``).
"""
from app.retrieval.rerank.base import (
    Reranker,
    get_reranker,
    rerank_results,
    reset_reranker_cache,
)

__all__ = ["Reranker", "get_reranker", "rerank_results", "reset_reranker_cache"]
