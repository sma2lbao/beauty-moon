"""按知识库 schema 校验并归一化上传元数据。"""
from datetime import date

from sqlalchemy.orm import Session

from app.metadata.models import MetadataFieldDefinition
from app.metadata.schema import FieldType


class MetadataValidationError(Exception):
    """元数据校验失败，聚合逐字段错误信息。"""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def load_field_definitions(
    db: Session, kb_id: str
) -> list[MetadataFieldDefinition]:
    """加载知识库的全部字段定义。"""
    return (
        db.query(MetadataFieldDefinition)
        .filter(MetadataFieldDefinition.knowledge_base_id == kb_id)
        .all()
    )


def _normalize_value(
    field: MetadataFieldDefinition, value: object, errors: list[str]
) -> object | None:
    """按字段类型归一化单个值；出错时追加到 errors 并返回 None。"""
    key = field.key
    if field.field_type == FieldType.ENUM:
        v = str(value).strip()
        if field.options and v not in field.options:
            errors.append(f"字段 {key} 的值 '{v}' 不在候选项内")
            return None
        return v
    if field.field_type == FieldType.STRING:
        return str(value).strip()
    if field.field_type == FieldType.DATE:
        try:
            return date.fromisoformat(str(value).strip()).isoformat()
        except ValueError:
            errors.append(f"字段 {key} 不是合法日期(YYYY-MM-DD): '{value}'")
            return None
    if field.field_type == FieldType.NUMBER:
        try:
            return float(value)
        except (TypeError, ValueError):
            errors.append(f"字段 {key} 不是合法数值: '{value}'")
            return None
    if field.field_type == FieldType.TAGS:
        if not isinstance(value, list):
            errors.append(f"字段 {key} 必须是标签数组")
            return None
        seen: list[str] = []
        for item in value:
            t = str(item).strip()
            if not t or t in seen:
                continue
            if field.options and t not in field.options:
                errors.append(f"字段 {key} 的标签 '{t}' 不在候选项内")
                continue
            seen.append(t)
        return seen
    errors.append(f"字段 {key} 类型未知")
    return None


def validate_and_normalize(
    db: Session, kb_id: str, raw: dict | None
) -> dict:
    """按 schema 校验并归一化上传元数据，成功返回归一化字典。"""
    raw = raw or {}
    fields = {f.key: f for f in load_field_definitions(db, kb_id)}
    errors: list[str] = []

    # 未知字段（严格模式）
    for key in raw:
        if key not in fields:
            errors.append(f"未定义的元数据字段: {key}")

    normalized: dict = {}
    for key, field in fields.items():
        if key not in raw or raw[key] is None:
            if field.required:
                errors.append(f"缺少必填字段: {key}")
            continue
        result = _normalize_value(field, raw[key], errors)
        if result is not None:
            normalized[key] = result

    if errors:
        raise MetadataValidationError(errors)
    return normalized
