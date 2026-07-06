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
