"""Reranker abstraction and backend dispatch."""
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import RerankProvider, get_settings
from app.observability.logging import get_logger
from app.observability.metrics import RAG_RERANK_DURATION, time_stage

settings = get_settings()


class Reranker(ABC):
    """Reorders retrieval candidates by query relevance."""

    @abstractmethod
    def rerank(
        self, query: str, candidates: list[dict[str, Any]], *, top_k: int
    ) -> list[dict[str, Any]]:
        """Return the best-first ``top_k`` candidates, ``score`` overwritten
        with the reranker's relevance score."""


# Module-level singleton cache (reranker is KB-independent).
_instance: Reranker | None = None


def _build_reranker() -> Reranker:
    """Construct the reranker for the configured provider."""
    if settings.reranker_provider == RerankProvider.BGE:
        from app.retrieval.rerank.bge import BgeReranker

        return BgeReranker()
    raise ValueError(f"Unknown reranker provider: {settings.reranker_provider}")


def get_reranker() -> Reranker:
    """Return the cached reranker singleton, building it on first use."""
    global _instance
    if _instance is None:
        _instance = _build_reranker()
    return _instance


def reset_reranker_cache() -> None:
    """Drop the cached reranker (test helper)."""
    global _instance
    _instance = None


logger = get_logger("luna.retrieval.rerank")


def rerank_results(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    top_k: int,
    knowledge_base_id: str,
) -> list[dict[str, Any]]:
    """Rerank fused candidates, degrading to fused order on any failure.

    Reranking must never break Q&A: model load / inference / missing-dependency
    errors are logged and we return ``candidates[:top_k]`` unchanged.
    """
    # 空候选直接返回，避免无谓的模型加载与指标记录。
    if not candidates:
        return []
    try:
        with time_stage(RAG_RERANK_DURATION):
            return get_reranker().rerank(query, candidates, top_k=top_k)
    except Exception:  # Rerank must never break Q&A — degrade to fused order.
        logger.warning(
            "rerank_failed_degrading_to_fused",
            knowledge_base_id=knowledge_base_id,
            exc_info=True,
        )
        return candidates[:top_k]
