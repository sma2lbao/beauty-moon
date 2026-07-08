"""hybrid_search filters 接入测试（mock 各检索源）。"""
from unittest.mock import patch

import pytest

from app.core.config import RetrievalMode
from app.metadata.schema import FieldType
from app.retrieval import hybrid
from app.retrieval.filters import FilterOp, MetadataCondition, MetadataFilter


@pytest.fixture(autouse=True)
def _hybrid_mode(monkeypatch):
    monkeypatch.setattr(hybrid.settings, "retrieval_mode", RetrievalMode.HYBRID)
    monkeypatch.setattr(hybrid.settings, "retrieval_candidate_k", 10)
    monkeypatch.setattr(hybrid.settings, "filter_over_fetch_multiplier", 3)


def test_no_filters_matches_current_behavior():
    vec = [{"chunk_id": "a", "document_id": "d", "content": "x", "score": 1.0}]
    with patch.object(hybrid, "search_vectorstore", return_value=vec) as sv, \
         patch.object(hybrid, "_bm25_results", return_value=[]):
        out = hybrid.hybrid_search("q", [0.1], top_k=5, knowledge_base_id="kb")
    # 无 filters 时向量侧不传 where
    _, kwargs = sv.call_args
    assert kwargs.get("where") is None
    assert out and out[0]["chunk_id"] == "a"


def test_filters_pushdown_where_to_vector():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.EQ, value="合同")
    ])
    ft = {"category": FieldType.ENUM}
    with patch.object(hybrid, "search_vectorstore", return_value=[]) as sv, \
         patch.object(hybrid, "_bm25_results", return_value=[]):
        hybrid.hybrid_search(
            "q", [0.1], top_k=5, knowledge_base_id="kb",
            filters=f, field_types=ft,
        )
    _, kwargs = sv.call_args
    assert kwargs["where"] == {"category": "合同"}
    # over-fetch 放大候选窗口
    assert kwargs["top_k"] == 10 * 3


def test_bm25_post_filter_drops_non_matching():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.EQ, value="合同")
    ])
    ft = {"category": FieldType.ENUM}
    bm = [
        {"chunk_id": "a", "document_id": "d1", "content": "x", "score": 1.0},
        {"chunk_id": "b", "document_id": "d2", "content": "y", "score": 0.9},
    ]
    meta = {"a": {"category": "合同"}, "b": {"category": "发票"}}
    with patch.object(hybrid, "search_vectorstore", return_value=[]), \
         patch.object(hybrid, "_bm25_results", return_value=bm), \
         patch.object(hybrid, "_load_chunk_metadata", return_value=meta):
        out = hybrid.hybrid_search(
            "q", [0.1], top_k=5, knowledge_base_id="kb",
            filters=f, field_types=ft,
        )
    ids = {r["chunk_id"] for r in out}
    assert "a" in ids and "b" not in ids


def test_where_build_error_degrades_to_no_filter():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="ghost", op=FilterOp.EQ, value="x")
    ])
    ft = {"category": FieldType.ENUM}  # ghost 未定义 -> FilterFieldError
    vec = [{"chunk_id": "a", "document_id": "d", "content": "x", "score": 1.0}]
    with patch.object(hybrid, "search_vectorstore", return_value=vec) as sv, \
         patch.object(hybrid, "_bm25_results", return_value=[]):
        out = hybrid.hybrid_search(
            "q", [0.1], top_k=5, knowledge_base_id="kb",
            filters=f, field_types=ft,
        )
    _, kwargs = sv.call_args
    assert kwargs.get("where") is None  # 降级为无过滤
    assert out and out[0]["chunk_id"] == "a"
