"""元数据字段定义 Pydantic 模型与类型枚举测试。"""
import pytest
from pydantic import ValidationError

from app.metadata.schema import (
    FieldDefinitionCreate,
    FieldDefinitionUpdate,
    FieldType,
)


def test_field_type_values():
    assert FieldType.ENUM == "enum"
    assert FieldType.STRING == "string"
    assert FieldType.DATE == "date"
    assert FieldType.NUMBER == "number"
    assert FieldType.TAGS == "tags"


def test_field_definition_create_defaults():
    f = FieldDefinitionCreate(key="category", label="类别", field_type="enum")
    assert f.options is None
    assert f.required is False
    assert f.is_facetable is True


def test_field_definition_create_key_required():
    with pytest.raises(ValidationError):
        FieldDefinitionCreate(label="缺 key", field_type="string")


def test_field_definition_update_all_optional():
    u = FieldDefinitionUpdate()
    assert u.label is None
    assert u.options is None
    assert u.required is None
    assert u.is_facetable is None
