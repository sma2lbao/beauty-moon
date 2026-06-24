"""Tests for Chroma vector store with mandatory knowledge_base_id filtering."""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import chromadb
import pytest

from app.core.config import Settings, VectorStoreBackendType


@pytest.fixture
def temp_chroma_dir():
    """Create temporary directory for Chroma data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def configure_vectorstore(monkeypatch, temp_chroma_dir, **overrides):
    from app.db import vectorstore

    settings = Settings(chroma_data_dir=temp_chroma_dir, **overrides)
    monkeypatch.setattr(vectorstore, "settings", settings)
    vectorstore.reset_vectorstore_backend_cache()
    return vectorstore


def test_add_chunks_to_vectorstore(temp_chroma_dir, monkeypatch):
    vectorstore = configure_vectorstore(monkeypatch, temp_chroma_dir)

    chunks = [
        {
            "id": "chunk-1",
            "document_id": "doc-1",
            "knowledge_base_id": "kb-1",
            "content": "First chunk",
        },
        {
            "id": "chunk-2",
            "document_id": "doc-1",
            "knowledge_base_id": "kb-1",
            "content": "Second chunk",
        },
    ]
    embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

    vectorstore.add_chunks_to_vectorstore(chunks, embeddings)

    results = vectorstore.search_vectorstore(
        [0.1, 0.2, 0.3], top_k=2, knowledge_base_id="kb-1"
    )
    assert len(results) == 2


def test_search_vectorstore_requires_knowledge_base(temp_chroma_dir, monkeypatch):
    vectorstore = configure_vectorstore(monkeypatch, temp_chroma_dir)

    with pytest.raises(vectorstore.VectorStoreIsolationError):
        vectorstore.search_vectorstore([0.1, 0.2, 0.3], top_k=1)

    with pytest.raises(vectorstore.VectorStoreIsolationError):
        vectorstore.search_vectorstore([0.1, 0.2, 0.3], top_k=1, knowledge_base_id="")


def test_search_vectorstore(temp_chroma_dir, monkeypatch):
    vectorstore = configure_vectorstore(monkeypatch, temp_chroma_dir)

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
            "knowledge_base_id": "kb-1",
            "content": "JavaScript code",
        },
    ]
    embeddings = [[0.1, 0.1, 0.1], [0.9, 0.9, 0.9]]
    vectorstore.add_chunks_to_vectorstore(chunks, embeddings)

    results = vectorstore.search_vectorstore(
        [0.1, 0.1, 0.1], top_k=1, knowledge_base_id="kb-1"
    )

    assert len(results) == 1
    assert results[0]["content"] == "Python code"


def test_delete_chunks_from_vectorstore(temp_chroma_dir, monkeypatch):
    vectorstore = configure_vectorstore(monkeypatch, temp_chroma_dir)

    chunks = [
        {
            "id": "chunk-1",
            "document_id": "doc-1",
            "knowledge_base_id": "kb-1",
            "content": "To delete",
        },
    ]
    embeddings = [[0.1, 0.2, 0.3]]
    vectorstore.add_chunks_to_vectorstore(chunks, embeddings)

    results = vectorstore.search_vectorstore(
        [0.1, 0.2, 0.3], top_k=1, knowledge_base_id="kb-1"
    )
    assert len(results) == 1

    vectorstore.delete_chunks_from_vectorstore(["chunk-1"])

    results = vectorstore.search_vectorstore(
        [0.1, 0.2, 0.3], top_k=1, knowledge_base_id="kb-1"
    )
    assert len(results) == 0


def test_search_vectorstore_handles_missing_metadata(monkeypatch, temp_chroma_dir):
    from app.db import vectorstore

    class Backend:
        def search(self, query_embedding, *, top_k, knowledge_base_id):
            return [
                vectorstore.VectorSearchResult(
                    chunk_id=None,
                    document_id=None,
                    content="Content",
                    score=0.1,
                )
            ]

    monkeypatch.setattr(vectorstore, "get_vectorstore_backend", lambda: Backend())

    results = vectorstore.search_vectorstore([0.1], top_k=1, knowledge_base_id="kb-1")

    assert results == [
        {
            "chunk_id": None,
            "document_id": None,
            "content": "Content",
            "score": 0.1,
        }
    ]


def test_search_vectorstore_filters_by_knowledge_base(temp_chroma_dir, monkeypatch):
    vectorstore = configure_vectorstore(monkeypatch, temp_chroma_dir)

    chunks = [
        {
            "id": "chunk-1",
            "document_id": "doc-1",
            "knowledge_base_id": "kb-1",
            "content": "Shared content",
        },
        {
            "id": "chunk-2",
            "document_id": "doc-2",
            "knowledge_base_id": "kb-2",
            "content": "Shared content",
        },
    ]
    embeddings = [[0.1, 0.1, 0.1], [0.1, 0.1, 0.1]]
    vectorstore.add_chunks_to_vectorstore(chunks, embeddings)

    results = vectorstore.search_vectorstore(
        [0.1, 0.1, 0.1], top_k=2, knowledge_base_id="kb-1"
    )

    assert len(results) == 1
    assert results[0]["document_id"] == "doc-1"


def test_chroma_backend_sends_knowledge_base_where_filter(monkeypatch, temp_chroma_dir):
    from app.db import vectorstore

    collection = Mock()
    collection.query.return_value = {
        "ids": [["chunk-1"]],
        "metadatas": [[{"chunk_id": "chunk-1", "document_id": "doc-1"}]],
        "documents": [["Content"]],
        "distances": [[0.2]],
    }
    backend = vectorstore.ChromaLocalBackend(Settings(chroma_data_dir=temp_chroma_dir))
    monkeypatch.setattr(backend, "get_collection", lambda: collection)

    results = backend.search([0.1], top_k=3, knowledge_base_id="kb-1")

    collection.query.assert_called_once_with(
        query_embeddings=[[0.1]],
        n_results=3,
        where={"knowledge_base_id": "kb-1"},
    )
    assert results[0].document_id == "doc-1"


def test_factory_selects_local_chroma_backend(temp_chroma_dir, monkeypatch):
    vectorstore = configure_vectorstore(
        monkeypatch,
        temp_chroma_dir,
        vectorstore_backend=VectorStoreBackendType.CHROMA_LOCAL,
    )

    backend = vectorstore.get_vectorstore_backend()

    assert isinstance(backend, vectorstore.ChromaLocalBackend)


def test_factory_selects_server_chroma_backend(temp_chroma_dir, monkeypatch):
    vectorstore = configure_vectorstore(
        monkeypatch,
        temp_chroma_dir,
        vectorstore_backend=VectorStoreBackendType.CHROMA_SERVER,
        chroma_host="chroma.example.com",
        chroma_port=8443,
        chroma_ssl=True,
    )

    backend = vectorstore.get_vectorstore_backend()

    assert isinstance(backend, vectorstore.ChromaServerBackend)


def test_local_backend_uses_persistent_client(monkeypatch, temp_chroma_dir):
    from app.db import vectorstore

    client = Mock()
    collection = Mock()
    client.get_or_create_collection.return_value = collection
    persistent_client = Mock(return_value=client)
    monkeypatch.setattr(chromadb, "PersistentClient", persistent_client)

    backend = vectorstore.ChromaLocalBackend(
        Settings(chroma_data_dir=temp_chroma_dir, chroma_collection_name="test_chunks")
    )

    assert backend.get_collection() is collection
    persistent_client.assert_called_once()
    assert persistent_client.call_args.kwargs["path"] == str(temp_chroma_dir)
    client.get_or_create_collection.assert_called_once_with(
        name="test_chunks",
        metadata={"description": "Document chunks for RAG"},
    )


def test_server_backend_uses_http_client(monkeypatch, temp_chroma_dir):
    from app.db import vectorstore

    client = Mock()
    collection = Mock()
    client.get_or_create_collection.return_value = collection
    http_client = Mock(return_value=client)
    monkeypatch.setattr(chromadb, "HttpClient", http_client)

    backend = vectorstore.ChromaServerBackend(
        Settings(
            chroma_data_dir=temp_chroma_dir,
            chroma_collection_name="server_chunks",
            chroma_host="chroma.example.com",
            chroma_port=8443,
            chroma_ssl=True,
            chroma_auth_token="secret-token",
        )
    )

    assert backend.get_collection() is collection
    http_client.assert_called_once_with(
        host="chroma.example.com",
        port=8443,
        ssl=True,
        headers={"Authorization": "Bearer secret-token"},
    )
    client.get_or_create_collection.assert_called_once_with(
        name="server_chunks",
        metadata={"description": "Document chunks for RAG"},
    )
