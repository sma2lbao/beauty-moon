"""Tests for document processor."""
from unittest.mock import MagicMock, patch

import pytest

from app.db.models import ContentType, Document
from app.services.document_processor import DocumentProcessor


@pytest.fixture
def processor():
    """Create processor instance."""
    return DocumentProcessor(chunk_size=100, chunk_overlap=20)


def test_detect_content_type_code(processor):
    """Test detecting code content."""
    assert processor.detect_content_type("```python\ndef hello():\n    pass\n```") == ContentType.CODE
    assert processor.detect_content_type("def main():\n    return 0") == ContentType.CODE


def test_detect_content_type_table(processor):
    """Test detecting table content."""
    content = "| Column 1 | Column 2 |\n| --- | --- |\n| Value | Value |"
    assert processor.detect_content_type(content) == ContentType.TABLE


def test_detect_content_type_text(processor):
    """Test detecting plain text content."""
    assert processor.detect_content_type("This is plain text.") == ContentType.TEXT


def test_split_document():
    """Test splitting document into chunks."""
    processor = DocumentProcessor(chunk_size=50, chunk_overlap=10)

    doc = MagicMock(spec=Document)
    doc.id = "doc-1"
    doc.content = "This is a long document that should be split into multiple chunks."

    chunks = processor.split_document(doc)

    assert len(chunks) > 1
    assert all("document_id" in c for c in chunks)
    assert all("content" in c for c in chunks)
    assert all("chunk_index" in c for c in chunks)


@patch("app.services.document_processor.embed_texts")
@patch("app.services.document_processor.add_chunks_to_vectorstore")
def test_process_document(mock_add_vectors, mock_embed_texts):
    """Test full document processing."""
    from app.db.models import ContentStatus

    processor = DocumentProcessor(chunk_size=100, chunk_overlap=20)

    mock_db = MagicMock()
    mock_doc = MagicMock(spec=Document)
    mock_doc.id = "doc-1"
    mock_doc.content = "Short content"
    mock_doc.status = ContentStatus.PENDING

    mock_db.query.return_value.filter.return_value.first.return_value = mock_doc
    mock_db.query.return_value.filter.return_value.all.return_value = []

    mock_embed_texts.return_value = [[0.1, 0.2, 0.3]]

    chunks = processor.process_document(mock_db, "doc-1")

    assert mock_doc.status == ContentStatus.COMPLETED
    mock_db.add.assert_called()
    mock_db.commit.assert_called()
