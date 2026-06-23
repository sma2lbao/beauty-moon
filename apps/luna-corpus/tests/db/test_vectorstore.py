"""Tests for Chroma vector store."""
import tempfile
from pathlib import Path

import pytest

from app.core.config import Settings


@pytest.fixture
def temp_chroma_dir():
    """Create temporary directory for Chroma data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_settings(temp_chroma_dir):
    """Create settings with temp directory."""
    return Settings(chroma_data_dir=temp_chroma_dir)


def test_add_chunks_to_vectorstore(temp_chroma_dir, monkeypatch):
    """Test adding chunks to vector store."""
    # Mock get_settings
    from app.db import vectorstore

    monkeypatch.setattr(
        vectorstore, "settings", Settings(chroma_data_dir=temp_chroma_dir)
    )

    chunks = [
        {"id": "chunk-1", "document_id": "doc-1", "knowledge_base_id": "kb-1", "content": "First chunk"},
        {"id": "chunk-2", "document_id": "doc-1", "knowledge_base_id": "kb-1", "content": "Second chunk"},
    ]
    embeddings = [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ]

    vectorstore.add_chunks_to_vectorstore(chunks, embeddings)

    # Verify by searching
    results = vectorstore.search_vectorstore([0.1, 0.2, 0.3], top_k=2)
    assert len(results) == 2


def test_search_vectorstore(temp_chroma_dir, monkeypatch):
    """Test searching vector store."""
    from app.db import vectorstore

    monkeypatch.setattr(
        vectorstore, "settings", Settings(chroma_data_dir=temp_chroma_dir)
    )

    # Add test data
    chunks = [
        {"id": "chunk-1", "document_id": "doc-1", "knowledge_base_id": "kb-1", "content": "Python code"},
        {"id": "chunk-2", "document_id": "doc-2", "knowledge_base_id": "kb-1", "content": "JavaScript code"},
    ]
    embeddings = [[0.1, 0.1, 0.1], [0.9, 0.9, 0.9]]
    vectorstore.add_chunks_to_vectorstore(chunks, embeddings)

    # Search
    results = vectorstore.search_vectorstore([0.1, 0.1, 0.1], top_k=1)

    assert len(results) == 1
    assert results[0]["content"] == "Python code"


def test_delete_chunks_from_vectorstore(temp_chroma_dir, monkeypatch):
    """Test deleting chunks from vector store."""
    from app.db import vectorstore

    monkeypatch.setattr(
        vectorstore, "settings", Settings(chroma_data_dir=temp_chroma_dir)
    )

    chunks = [
        {"id": "chunk-1", "document_id": "doc-1", "knowledge_base_id": "kb-1", "content": "To delete"},
    ]
    embeddings = [[0.1, 0.2, 0.3]]
    vectorstore.add_chunks_to_vectorstore(chunks, embeddings)

    # Verify exists
    results = vectorstore.search_vectorstore([0.1, 0.2, 0.3], top_k=1)
    assert len(results) == 1

    # Delete
    vectorstore.delete_chunks_from_vectorstore(["chunk-1"])

    # Verify deleted
    results = vectorstore.search_vectorstore([0.1, 0.2, 0.3], top_k=1)
    assert len(results) == 0


def test_search_vectorstore_filters_by_knowledge_base(temp_chroma_dir, monkeypatch):
    from app.db import vectorstore

    monkeypatch.setattr(
        vectorstore, "settings", Settings(chroma_data_dir=temp_chroma_dir)
    )

    chunks = [
        {
            "id": "chunk-1",
            "document_id": "doc-1",
            "knowledge_base_id": "kb-1",
            "content": "Python code",
        },
        {
            "id": "chunk-2",
            "document_id": "doc-2",
            "knowledge_base_id": "kb-2",
            "content": "JavaScript code",
        },
    ]
    embeddings = [[0.1, 0.1, 0.1], [0.1, 0.1, 0.1]]
    vectorstore.add_chunks_to_vectorstore(chunks, embeddings)

    results = vectorstore.search_vectorstore(
        [0.1, 0.1, 0.1],
        top_k=2,
        knowledge_base_id="kb-1",
    )

    assert len(results) == 1
    assert results[0]["document_id"] == "doc-1"
