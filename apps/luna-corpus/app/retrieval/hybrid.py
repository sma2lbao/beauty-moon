"""Hybrid retrieval orchestrator: vector + BM25 fused with RRF."""
from typing import Any

from app.core.config import RetrievalMode, get_settings
from app.db.vectorstore import search_vectorstore
from app.observability.logging import get_logger
from app.observability.metrics import RAG_RETRIEVAL_DURATION, time_stage
from app.retrieval.bm25 import get_bm25_index
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.rerank import rerank_results

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

    ``vector`` mode is plain vector search. ``hybrid`` runs vector + BM25 (each
    up to ``retrieval_candidate_k``) fused with RRF to ``top_k``. ``rerank``
    fuses to ``rerank_candidate_k`` candidates then cross-encoder reranks to
    ``top_k``. BM25 failure degrades to vector-only; rerank failure degrades to
    fused order. A vector failure propagates.
    """
    mode = settings.retrieval_mode
    is_fused = mode in (RetrievalMode.HYBRID, RetrievalMode.RERANK)
    candidate_k = (
        settings.rerank_candidate_k
        if mode == RetrievalMode.RERANK
        else settings.retrieval_candidate_k
    )
    # rerank 先融合到 candidate_k，再交给精排；hybrid 直接融合到 top_k。
    fuse_top_k = candidate_k if mode == RetrievalMode.RERANK else top_k

    with time_stage(RAG_RETRIEVAL_DURATION):
        vector_results = search_vectorstore(
            query_embedding=query_embedding,
            top_k=candidate_k if is_fused else top_k,
            knowledge_base_id=knowledge_base_id,
        )

        if not is_fused:
            return vector_results

        try:
            keyword_results = _bm25_results(
                query, knowledge_base_id, candidate_k
            )
        except Exception:  # BM25 must never break Q&A — degrade to vector-only.
            logger.warning(
                "bm25_search_failed_degrading_to_vector",
                knowledge_base_id=knowledge_base_id,
                exc_info=True,
            )
            return vector_results[:top_k]

        fused = reciprocal_rank_fusion(
            [vector_results, keyword_results],
            k=settings.rrf_k,
            top_k=fuse_top_k,
        )

        if mode == RetrievalMode.RERANK:
            return rerank_results(
                query,
                fused,
                top_k=top_k,
                knowledge_base_id=knowledge_base_id,
            )
        return fused
