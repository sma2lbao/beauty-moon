"""文档处理把 doc_metadata 传播到 chunk 与向量库的测试。"""
from unittest.mock import MagicMock, patch

from app.metadata.schema import FieldType
from app.services.document_processor import DocumentProcessor


def test_chunk_metadata_and_vector_metadata_propagated():
    proc = DocumentProcessor(chunk_size=1000, chunk_overlap=0)
    document = MagicMock()
    document.id = "doc1"
    document.knowledge_base_id = "kb1"
    document.content = "一段内容。"
    document.doc_metadata = {"category": "合同", "tags": ["a"]}
    document.status = None

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = document
    db.query.return_value.filter.return_value.all.return_value = []

    field_types = {"category": FieldType.ENUM, "tags": FieldType.TAGS}

    with patch(
        "app.services.document_processor.embed_texts", return_value=[[0.1]]
    ), patch(
        "app.services.document_processor.add_chunks_to_vectorstore"
    ) as add_mock, patch(
        "app.services.document_processor.invalidate_bm25_cache"
    ), patch(
        "app.services.document_processor._field_types_for_kb",
        return_value=field_types,
    ):
        proc.process_document(db, "doc1")

    chunks_arg = add_mock.call_args.kwargs["chunks"]
    md = chunks_arg[0]["metadata"]
    assert md["category"] == "合同"
    assert md["tag__a"] is True
