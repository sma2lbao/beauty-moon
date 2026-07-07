"""全库分面聚合：按知识库统计各维度取值的文档命中数。"""
from collections import Counter

from sqlalchemy.orm import Session

from app.db.models import ContentStatus, Document
from app.metadata.models import MetadataFieldDefinition
from app.metadata.schema import FieldType

_STRING_TOP_N = 20
_NUMBER_BUCKETS = 5


def _sorted_buckets(counter: Counter) -> list[dict]:
    """按 count 降序（次序稳定：count 相同按 value 升序）。"""
    items = sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return [{"value": v, "count": c} for v, c in items]


def _number_buckets(values: list[float]) -> list[dict]:
    lo, hi = min(values), max(values)
    if lo == hi:
        return [{"value": f"{lo:.2f}-{hi:.2f}", "count": len(values)}]
    width = (hi - lo) / _NUMBER_BUCKETS
    counter: Counter = Counter()
    labels: list[str] = []
    for i in range(_NUMBER_BUCKETS):
        b_lo = lo + i * width
        b_hi = lo + (i + 1) * width
        labels.append(f"{b_lo:.2f}-{b_hi:.2f}")
    for v in values:
        idx = min(int((v - lo) / width), _NUMBER_BUCKETS - 1)
        counter[labels[idx]] += 1
    return [
        {"value": label, "count": counter[label]}
        for label in labels
        if counter[label] > 0
    ]


def _buckets_for_field(
    field: MetadataFieldDefinition, values: list
) -> list[dict]:
    if field.field_type == FieldType.TAGS:
        counter: Counter = Counter()
        for v in values:
            for tag in v or []:
                counter[tag] += 1
        return _sorted_buckets(counter)
    if field.field_type == FieldType.DATE:
        return _sorted_buckets(Counter(str(v)[:7] for v in values))
    if field.field_type == FieldType.NUMBER:
        nums = [float(v) for v in values]
        return _number_buckets(nums) if nums else []
    buckets = _sorted_buckets(Counter(values))
    if field.field_type == FieldType.STRING:
        return buckets[:_STRING_TOP_N]
    return buckets


def compute_facets(db: Session, kb_id: str) -> list[dict]:
    """对可分面字段聚合 COMPLETED 文档的 doc_metadata。"""
    fields = (
        db.query(MetadataFieldDefinition)
        .filter(
            MetadataFieldDefinition.knowledge_base_id == kb_id,
            MetadataFieldDefinition.is_facetable.is_(True),
        )
        .all()
    )
    rows = (
        db.query(Document.doc_metadata)
        .filter(
            Document.knowledge_base_id == kb_id,
            Document.status == ContentStatus.COMPLETED,
        )
        .all()
    )
    metadatas = [r[0] or {} for r in rows]

    facets: list[dict] = []
    for field in fields:
        values = [m[field.key] for m in metadatas if field.key in m]
        facets.append({
            "key": field.key,
            "label": field.label,
            "field_type": field.field_type.value,
            "buckets": _buckets_for_field(field, values),
        })
    return facets
