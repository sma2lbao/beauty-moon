"""过滤条件模型与 Chroma where / post-filter 翻译测试。"""
import pytest

from app.metadata.schema import FieldType
from app.retrieval.filters import (
    FilterFieldError,
    FilterOp,
    MetadataCondition,
    MetadataFilter,
    make_post_filter,
    to_chroma_metadata,
    to_chroma_where,
)

FIELD_TYPES = {
    "category": FieldType.ENUM,
    "author": FieldType.STRING,
    "published_at": FieldType.DATE,
    "amount": FieldType.NUMBER,
    "tags": FieldType.TAGS,
}


def test_to_chroma_metadata_scalars_and_tags():
    out = to_chroma_metadata(
        {"category": "合同", "amount": 100.0, "tags": ["a", "b"]},
        FIELD_TYPES,
    )
    assert out["category"] == "合同"
    assert out["amount"] == 100.0
    assert out["tag__a"] is True
    assert out["tag__b"] is True
    assert "tags" not in out


def test_to_chroma_where_eq():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.EQ, value="合同")
    ])
    assert to_chroma_where(f, FIELD_TYPES) == {"category": "合同"}


def test_to_chroma_where_in():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.IN, value=["合同", "发票"])
    ])
    assert to_chroma_where(f, FIELD_TYPES) == {
        "category": {"$in": ["合同", "发票"]}
    }


def test_to_chroma_where_date_range_multi_condition():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="published_at", op=FilterOp.GTE, value="2025-01-01"),
        MetadataCondition(key="published_at", op=FilterOp.LTE, value="2025-12-31"),
    ])
    where = to_chroma_where(f, FIELD_TYPES)
    assert where == {"$and": [
        {"published_at": {"$gte": "2025-01-01"}},
        {"published_at": {"$lte": "2025-12-31"}},
    ]}


def test_to_chroma_where_contains_any():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="tags", op=FilterOp.CONTAINS_ANY, value=["a", "b"])
    ])
    assert to_chroma_where(f, FIELD_TYPES) == {
        "$or": [{"tag__a": True}, {"tag__b": True}]
    }


def test_to_chroma_where_contains_all():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="tags", op=FilterOp.CONTAINS_ALL, value=["a", "b"])
    ])
    assert to_chroma_where(f, FIELD_TYPES) == {
        "$and": [{"tag__a": True}, {"tag__b": True}]
    }


def test_to_chroma_where_unknown_field_raises():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="ghost", op=FilterOp.EQ, value="x")
    ])
    with pytest.raises(FilterFieldError):
        to_chroma_where(f, FIELD_TYPES)


def test_post_filter_eq_and_range():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.EQ, value="合同"),
        MetadataCondition(key="amount", op=FilterOp.GTE, value=50.0),
    ])
    pred = make_post_filter(f, FIELD_TYPES)
    assert pred({"category": "合同", "amount": 100.0}) is True
    assert pred({"category": "发票", "amount": 100.0}) is False
    assert pred({"category": "合同", "amount": 10.0}) is False
    assert pred({"category": "合同"}) is False  # 缺字段不通过


def test_post_filter_contains_any_all():
    any_f = MetadataFilter(conditions=[
        MetadataCondition(key="tags", op=FilterOp.CONTAINS_ANY, value=["a", "z"])
    ])
    all_f = MetadataFilter(conditions=[
        MetadataCondition(key="tags", op=FilterOp.CONTAINS_ALL, value=["a", "b"])
    ])
    assert make_post_filter(any_f, FIELD_TYPES)({"tags": ["a"]}) is True
    assert make_post_filter(any_f, FIELD_TYPES)({"tags": ["x"]}) is False
    assert make_post_filter(all_f, FIELD_TYPES)({"tags": ["a", "b"]}) is True
    assert make_post_filter(all_f, FIELD_TYPES)({"tags": ["a"]}) is False
