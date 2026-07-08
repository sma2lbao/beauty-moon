"""向量库元数据写入与 where 合并测试（mock Chroma collection）。"""
from unittest.mock import MagicMock

from app.db.vectorstore import BaseChromaBackend, VectorChunkInput
from app.core.config import get_settings


def _backend_with_mock_collection():
    backend = BaseChromaBackend(get_settings())
    collection = MagicMock()
    backend._collection = collection
    return backend, collection


def test_add_chunks_writes_metadata():
    backend, collection = _backend_with_mock_collection()
    backend.add_chunks(
        [VectorChunkInput(
            id="c1", document_id="d1", knowledge_base_id="kb1",
            content="hello", metadata={"category": "合同", "tag__a": True},
        )],
        [[0.1, 0.2]],
    )
    _, kwargs = collection.add.call_args
    md = kwargs["metadatas"][0]
    assert md["knowledge_base_id"] == "kb1"
    assert md["category"] == "合同"
    assert md["tag__a"] is True


def test_search_without_where_uses_kb_isolation_only():
    backend, collection = _backend_with_mock_collection()
    collection.query.return_value = {"ids": [[]]}
    backend.search([0.1], top_k=5, knowledge_base_id="kb1")
    _, kwargs = collection.query.call_args
    assert kwargs["where"] == {"knowledge_base_id": "kb1"}


def test_search_with_where_merges_and():
    backend, collection = _backend_with_mock_collection()
    collection.query.return_value = {"ids": [[]]}
    backend.search(
        [0.1], top_k=5, knowledge_base_id="kb1",
        where={"category": "合同"},
    )
    _, kwargs = collection.query.call_args
    assert kwargs["where"] == {
        "$and": [{"knowledge_base_id": "kb1"}, {"category": "合同"}]
    }
