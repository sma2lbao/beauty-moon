"""Reranker abstraction and backend dispatch."""
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import RerankProvider, get_settings

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
