"""Hybrid retrieval orchestrator: vector + BM25 fused with RRF."""
from typing import Any

from app.core.config import RetrievalMode, get_settings
from app.db.database import SessionLocal
from app.db.models import Chunk
from app.db.vectorstore import search_vectorstore
from app.metadata.schema import FieldType
from app.observability.logging import get_logger
from app.observability.metrics import RAG_RETRIEVAL_DURATION, time_stage
from app.retrieval.bm25 import get_bm25_index
from app.retrieval.filters import (
    MetadataFilter,
    make_post_filter,
    to_chroma_where,
)
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


def _load_chunk_metadata(chunk_ids: list[str]) -> dict[str, dict]:
    """批量读取 chunk 原始归一化元数据，供 BM25 post-filter。"""
    if not chunk_ids:
        return {}
    db = SessionLocal()
    try:
        rows = (
            db.query(Chunk.id, Chunk.chunk_metadata)
            .filter(Chunk.id.in_(chunk_ids))
            .all()
        )
        return {r[0]: (r[1] or {}) for r in rows}
    finally:
        db.close()


def _apply_post_filter(
    results: list[dict[str, Any]], predicate
) -> list[dict[str, Any]]:
    """按 chunk_id 补元数据后应用 post-filter 谓词。"""
    chunk_ids = [r["chunk_id"] for r in results if r.get("chunk_id")]
    meta_by_id = _load_chunk_metadata(chunk_ids)
    return [r for r in results if predicate(meta_by_id.get(r.get("chunk_id"), {}))]


def hybrid_search(
    query: str,
    query_embedding: list[float],
    *,
    top_k: int,
    knowledge_base_id: str,
    filters: MetadataFilter | None = None,
    field_types: dict[str, FieldType] | None = None,
) -> list[dict[str, Any]]:
    """检索 chunks，按 ``settings.retrieval_mode`` 分派，可选元数据过滤。

    ``filters`` 为空时行为与无过滤时完全一致。非空时向量侧下推 Chroma where、
    BM25 侧 post-filter，并按 ``filter_over_fetch_multiplier`` 放大候选窗口。
    过滤构造失败降级为无过滤（检索不因过滤崩）。
    """
    mode = settings.retrieval_mode
    is_fused = mode in (RetrievalMode.HYBRID, RetrievalMode.RERANK)

    where: dict | None = None
    post_filter = None
    over_fetch = 1
    if filters is not None and filters.conditions:
        try:
            where = to_chroma_where(filters, field_types or {})
            post_filter = make_post_filter(filters, field_types or {})
            over_fetch = settings.filter_over_fetch_multiplier
            logger.info(
                "filter_applied",
                knowledge_base_id=knowledge_base_id,
                num_conditions=len(filters.conditions),
            )
        except Exception:
            logger.warning(
                "filter_degraded_no_op",
                knowledge_base_id=knowledge_base_id,
                exc_info=True,
            )
            where = None
            post_filter = None
            over_fetch = 1

    base_candidate_k = (
        settings.rerank_candidate_k
        if mode == RetrievalMode.RERANK
        else settings.retrieval_candidate_k
    )
    candidate_k = base_candidate_k * over_fetch
    fuse_top_k = candidate_k if mode == RetrievalMode.RERANK else top_k

    vector_top_k = candidate_k if is_fused else (top_k * over_fetch)
    vector_kwargs: dict[str, Any] = {
        "query_embedding": query_embedding,
        "top_k": vector_top_k,
        "knowledge_base_id": knowledge_base_id,
    }
    if where is not None:
        vector_kwargs["where"] = where

    with time_stage(RAG_RETRIEVAL_DURATION):
        vector_results = search_vectorstore(**vector_kwargs)

        if not is_fused:
            if post_filter is None:
                return vector_results
            filtered = _apply_post_filter(vector_results, post_filter)
            return filtered[:top_k]

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
            base = vector_results
            if post_filter is not None:
                base = _apply_post_filter(base, post_filter)
            return base[:top_k]

        if post_filter is not None:
            keyword_results = _apply_post_filter(keyword_results, post_filter)

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
        return fused[:top_k]
