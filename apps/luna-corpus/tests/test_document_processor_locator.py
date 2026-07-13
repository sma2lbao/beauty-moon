"""摄取切分把定位信息并入 chunk dict 的测试。"""
from unittest.mock import MagicMock

from app.services.document_processor import DocumentProcessor


def test_split_document_attaches_locator_fields():
    proc = DocumentProcessor(chunk_size=1000, chunk_overlap=0)
    document = MagicMock()
    document.id = "doc1"
    document.content = "# 标题A\n第一段内容。\n## 标题B\n第二段内容。"

    chunks = proc.split_document(document, doc_metadata=None)

    assert len(chunks) >= 1
    first = chunks[0]
    # 定位字段存在
    assert "char_start" in first
    assert "char_end" in first
    assert "heading_path" in first
    # char_start 指向该 chunk 内容在原文中的位置
    assert first["char_start"] == document.content.find(first["content"])
    assert first["char_end"] == first["char_start"] + len(first["content"])
    # 内容落在某个标题下
    assert first["heading_path"] is not None
    assert "标题A" in first["heading_path"]
