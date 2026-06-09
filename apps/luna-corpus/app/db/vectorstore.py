"""Chroma vector store integration."""
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.api.models.Collection import Collection

from app.core.config import get_settings

settings = get_settings()

_COLLECTION_NAME = "document_chunks"


def get_client() -> chromadb.PersistentClient:
    """Get Chroma persistent client instance."""
    settings.chroma_data_dir.mkdir(parents=True, exist_ok=True)

    return chromadb.PersistentClient(
        path=str(settings.chroma_data_dir),
        settings=ChromaSettings(
            anonymized_telemetry=False,
            allow_reset=True,
        ),
    )


def get_collection() -> Collection:
    """Get or create the document chunks collection."""
    client = get_client()
    return client.get_or_create_collection(
        name=_COLLECTION_NAME,
        metadata={"description": "Document chunks for RAG"},
    )


def add_chunks_to_vectorstore(
    chunks: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> None:
    """Add chunks and their embeddings to Chroma.

    Args:
        chunks: List of chunk dictionaries with 'id' and 'content'
        embeddings: List of embedding vectors
    """
    collection = get_collection()

    ids = [chunk["id"] for chunk in chunks]
    documents = [chunk["content"] for chunk in chunks]
    metadatas = [
        {"chunk_id": chunk["id"], "document_id": chunk["document_id"]}
        for chunk in chunks
    ]

    collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def search_vectorstore(
    query_embedding: list[float],
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """Search vector store for similar chunks.

    Args:
        query_embedding: Query embedding vector
        top_k: Number of results to return

    Returns:
        List of matching chunks with scores
    """
    if top_k is None:
        top_k = settings.retrieval_top_k

    collection = get_collection()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
    )

    # Flatten and format results
    output = []
    if results["ids"] and results["ids"][0]:
        for i, chunk_id in enumerate(results["ids"][0]):
            output.append({
                "chunk_id": results["metadatas"][0][i].get("chunk_id") if results["metadatas"] else None,
                "document_id": results["metadatas"][0][i].get("document_id") if results["metadatas"] else None,
                "content": results["documents"][0][i] if results["documents"] else None,
                "score": results["distances"][0][i] if results["distances"] else 0.0,
            })

    return output


def delete_chunks_from_vectorstore(chunk_ids: list[str]) -> None:
    """Delete chunks from vector store.

    Args:
        chunk_ids: List of chunk IDs to delete
    """
    collection = get_collection()
    collection.delete(ids=chunk_ids)
