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
