"""检索层把 chunk 定位字段透传到 sources 的测试。"""
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Chunk, ContentType, Document
from app.graph.rag_graph import (
    format_sources,
    validate_retrieved_docs_for_knowledge_base,
)


def test_format_sources_includes_locator_fields():
    retrieved = [
        {
            "chunk_id": "c1",
            "document_id": "d1",
            "content": "一段被引用的原文内容。",
            "score": 0.9,
            "chunk_index": 3,
            "char_start": 100,
            "char_end": 130,
            "heading_path": "第2章 > 2.1 安装",
        }
    ]

    sources = format_sources(retrieved)

    assert sources[0]["chunk_index"] == 3
    assert sources[0]["char_start"] == 100
    assert sources[0]["char_end"] == 130
    assert sources[0]["heading_path"] == "第2章 > 2.1 安装"


def test_format_sources_defaults_missing_locator_to_none():
    # 存量 chunk 无定位字段时应优雅降级为 None
    retrieved = [
        {
            "chunk_id": "c1",
            "document_id": "d1",
            "content": "旧数据内容。",
            "score": 0.5,
        }
    ]

    sources = format_sources(retrieved)

    assert sources[0]["chunk_index"] is None
    assert sources[0]["char_start"] is None
    assert sources[0]["char_end"] is None
    assert sources[0]["heading_path"] is None


def _seed_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    doc = Document(
        id="d1", knowledge_base_id="kb1", title="T", content="正文"
    )
    db.add(doc)
    db.add(
        Chunk(
            id="c1", document_id="d1", content="正文",
            content_type=ContentType.TEXT, chunk_index=2,
            char_start=5, char_end=7, heading_path="第1章",
        )
    )
    db.commit()
    return db


def test_validate_backfills_locator_from_chunk():
    db = _seed_session()
    retrieved = [
        {"chunk_id": "c1", "document_id": "d1", "content": "正文", "score": 0.8}
    ]

    with patch("app.graph.rag_graph.get_db", return_value=iter([db])):
        result = validate_retrieved_docs_for_knowledge_base(retrieved, "kb1")

    assert len(result) == 1
    assert result[0]["chunk_index"] == 2
    assert result[0]["char_start"] == 5
    assert result[0]["heading_path"] == "第1章"


def test_validate_filters_foreign_kb():
    db = _seed_session()
    retrieved = [
        {"chunk_id": "c1", "document_id": "d1", "content": "正文", "score": 0.8}
    ]

    with patch("app.graph.rag_graph.get_db", return_value=iter([db])):
        result = validate_retrieved_docs_for_knowledge_base(retrieved, "other_kb")

    assert result == []
