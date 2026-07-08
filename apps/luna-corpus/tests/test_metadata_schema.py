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


def test_reserved_key_rejected():
    """业务字段 key 不得占用向量库保留标识键。"""
    import pytest
    from pydantic import ValidationError

    from app.metadata.schema import FieldDefinitionCreate

    for reserved in ("chunk_id", "document_id", "knowledge_base_id"):
        with pytest.raises(ValidationError):
            FieldDefinitionCreate(key=reserved, label="x", field_type="string")


def test_add_chunks_fixed_keys_win_over_business_metadata():
    """业务 metadata 携带保留键时，固定标识键仍胜出（防 kb 隔离污染）。"""
    from unittest.mock import MagicMock

    from app.core.config import get_settings
    from app.db.vectorstore import BaseChromaBackend, VectorChunkInput

    backend = BaseChromaBackend(get_settings())
    collection = MagicMock()
    backend._collection = collection
    backend.add_chunks(
        [VectorChunkInput(
            id="c1", document_id="d1", knowledge_base_id="kb1",
            content="x", metadata={"knowledge_base_id": "EVIL", "category": "合同"},
        )],
        [[0.1]],
    )
    md = collection.add.call_args.kwargs["metadatas"][0]
    assert md["knowledge_base_id"] == "kb1"
    assert md["category"] == "合同"
