"""元数据过滤条件模型，及其到 Chroma where / post-filter 谓词的翻译。

同一 ``MetadataFilter`` 翻译两次：向量侧下推 ``to_chroma_where``；BM25 侧
``make_post_filter`` 读候选原始 ``doc_metadata`` 判定。``tags`` 在 Chroma 侧
布尔展开为 ``tag__<value>=True``（Chroma metadata 不支持 list）。
"""
from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel

from app.metadata.schema import FieldType


class FilterOp(StrEnum):
    """过滤操作符。"""

    EQ = "eq"
    IN = "in"
    GTE = "gte"
    LTE = "lte"
    CONTAINS_ANY = "contains_any"
    CONTAINS_ALL = "contains_all"


class MetadataCondition(BaseModel):
    """单个过滤条件。"""

    key: str
    op: FilterOp
    value: str | float | list[str]


class MetadataFilter(BaseModel):
    """多条件 AND 组合的过滤器。"""

    conditions: list[MetadataCondition]


class FilterFieldError(Exception):
    """过滤条件引用了未定义字段。"""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"过滤字段未定义: {key}")


def to_chroma_metadata(
    doc_metadata: dict, field_types: dict[str, FieldType]
) -> dict:
    """把归一化元数据转成 Chroma 标量 metadata（tags 布尔展开）。"""
    out: dict = {}
    for key, value in doc_metadata.items():
        ftype = field_types.get(key)
        if ftype == FieldType.TAGS and isinstance(value, list):
            for tag in value:
                out[f"tag__{tag}"] = True
        else:
            out[key] = value
    return out


def _tag_clauses(values: list[str]) -> list[dict]:
    return [{f"tag__{v}": True} for v in values]


def to_chroma_where(
    f: MetadataFilter, field_types: dict[str, FieldType]
) -> dict:
    """翻译成 Chroma where（不含 kb 隔离，调用方负责合并）。"""
    clauses: list[dict] = []
    for cond in f.conditions:
        if cond.key not in field_types:
            raise FilterFieldError(cond.key)
        if cond.op == FilterOp.EQ:
            clauses.append({cond.key: cond.value})
        elif cond.op == FilterOp.IN:
            clauses.append({cond.key: {"$in": cond.value}})
        elif cond.op == FilterOp.GTE:
            clauses.append({cond.key: {"$gte": cond.value}})
        elif cond.op == FilterOp.LTE:
            clauses.append({cond.key: {"$lte": cond.value}})
        elif cond.op == FilterOp.CONTAINS_ANY:
            clauses.append({"$or": _tag_clauses(cond.value)})
        elif cond.op == FilterOp.CONTAINS_ALL:
            clauses.extend(_tag_clauses(cond.value))
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _match(cond: MetadataCondition, meta: dict) -> bool:
    if cond.op in (FilterOp.CONTAINS_ANY, FilterOp.CONTAINS_ALL):
        have = set(meta.get(cond.key) or [])
        want = set(cond.value)
        if cond.op == FilterOp.CONTAINS_ANY:
            return bool(have & want)
        return want <= have
    if cond.key not in meta:
        return False
    actual = meta[cond.key]
    if cond.op == FilterOp.EQ:
        return actual == cond.value
    if cond.op == FilterOp.IN:
        return actual in cond.value
    if cond.op == FilterOp.GTE:
        return actual >= cond.value
    if cond.op == FilterOp.LTE:
        return actual <= cond.value
    return False


def make_post_filter(
    f: MetadataFilter, field_types: dict[str, FieldType]
) -> Callable[[dict], bool]:
    """构造 BM25 侧 post-filter 谓词，读候选原始 doc_metadata 判定。"""
    for cond in f.conditions:
        if cond.key not in field_types:
            raise FilterFieldError(cond.key)

    def predicate(meta: dict) -> bool:
        meta = meta or {}
        return all(_match(cond, meta) for cond in f.conditions)

    return predicate
