"""引用富化端到端：摄取→切分→定位落库→sources 透出。"""
from unittest.mock import MagicMock

from app.graph.rag_graph import format_sources
from app.services.document_processor import DocumentProcessor


def test_ingestion_populates_locator_and_sources_expose_it():
    proc = DocumentProcessor(chunk_size=1000, chunk_overlap=0)
    document = MagicMock()
    document.id = "doc1"
    document.content = "# 第2章\n## 2.1 安装\n安装步骤内容。"

    # 摄取切分阶段：chunk dict 带定位
    chunk_dicts = proc.split_document(document, doc_metadata=None)
    first = chunk_dicts[0]
    assert first["char_start"] is not None
    assert first["heading_path"] is not None
    assert "第2章" in first["heading_path"]

    # 模拟检索结果（把 chunk_index/offset/heading 带上）走 format_sources
    retrieved = [
        {
            "chunk_id": "c1",
            "document_id": "doc1",
            "content": first["content"],
            "score": 0.9,
            "chunk_index": first["chunk_index"],
            "char_start": first["char_start"],
            "char_end": first["char_end"],
            "heading_path": first["heading_path"],
        }
    ]
    sources = format_sources(retrieved)
    assert sources[0]["char_start"] == first["char_start"]
    assert sources[0]["heading_path"] == first["heading_path"]
    assert sources[0]["chunk_index"] == first["chunk_index"]
