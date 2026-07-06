"""Tests for Reciprocal Rank Fusion."""
from app.retrieval.fusion import reciprocal_rank_fusion


def _doc(chunk_id, score):
    return {
        "chunk_id": chunk_id,
        "document_id": f"doc-{chunk_id}",
        "content": f"content {chunk_id}",
        "score": score,
    }


def test_single_chunk_in_both_lists_accumulates_score():
    vec = [_doc("a", 0.9), _doc("b", 0.5)]
    bm25 = [_doc("a", 3.0), _doc("c", 1.0)]

    fused = reciprocal_rank_fusion([vec, bm25], k=60, top_k=10)

    scores = {d["chunk_id"]: d["score"] for d in fused}
    # "a" is rank 0 in both lists: 1/60 + 1/60
    assert scores["a"] == 2 / 60
    # "b" only in vec at rank 1; "c" only in bm25 at rank 1
    assert scores["b"] == 1 / 61
    assert scores["c"] == 1 / 61
    # "a" ranks first
    assert fused[0]["chunk_id"] == "a"


def test_empty_list_degrades_to_other():
    vec = [_doc("a", 0.9), _doc("b", 0.5)]

    fused = reciprocal_rank_fusion([vec, []], k=60, top_k=10)

    assert [d["chunk_id"] for d in fused] == ["a", "b"]


def test_both_empty_returns_empty():
    assert reciprocal_rank_fusion([[], []], k=60, top_k=10) == []


def test_top_k_truncates():
    vec = [_doc("a", 0.9), _doc("b", 0.5), _doc("c", 0.1)]

    fused = reciprocal_rank_fusion([vec], k=60, top_k=2)

    assert len(fused) == 2
    assert [d["chunk_id"] for d in fused] == ["a", "b"]


def test_output_preserves_identity_fields():
    vec = [_doc("a", 0.9)]

    fused = reciprocal_rank_fusion([vec], k=60, top_k=1)

    assert fused[0]["document_id"] == "doc-a"
    assert fused[0]["content"] == "content a"
