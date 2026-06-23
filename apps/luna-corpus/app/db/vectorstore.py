"""Chroma vector store integration."""
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.api.models.Collection import Collection

from app.core.config import get_settings

settings = get_settings()

_COLLECTION_NAME = "document_chunks"


def get_vector_store():
    """Get the vector store (collection) instance.

    Returns:
        Chroma collection for document chunks
    """
    return get_collection()


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
        {
            "chunk_id": chunk["id"],
            "document_id": chunk["document_id"],
            "knowledge_base_id": chunk["knowledge_base_id"],
        }
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
    knowledge_base_id: str | None = None,
) -> list[dict[str, Any]]:
    """Search vector store for similar chunks.

    Args:
        query_embedding: Query embedding vector
        top_k: Number of results to return
        knowledge_base_id: Optional knowledge base ID to filter results

    Returns:
        List of matching chunks with scores
    """
    if top_k is None:
        top_k = settings.retrieval_top_k

    collection = get_collection()

    query_kwargs: dict[str, Any] = {
        "query_embeddings": [query_embedding],
        "n_results": top_k,
    }
    if knowledge_base_id is not None:
        query_kwargs["where"] = {"knowledge_base_id": knowledge_base_id}

    results = collection.query(**query_kwargs)

    output = []
    if results["ids"] and results["ids"][0]:
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        documents = results["documents"][0] if results["documents"] else []
        distances = results["distances"][0] if results["distances"] else []

        for i, chunk_id in enumerate(results["ids"][0]):
            metadata = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
            output.append(
                {
                    "chunk_id": metadata.get("chunk_id"),
                    "document_id": metadata.get("document_id"),
                    "content": documents[i] if i < len(documents) else None,
                    "score": distances[i] if i < len(distances) else 0.0,
                }
            )

    return output


def delete_chunks_from_vectorstore(chunk_ids: list[str]) -> None:
    """Delete chunks from vector store.

    Args:
        chunk_ids: List of chunk IDs to delete
    """
    collection = get_collection()
    collection.delete(ids=chunk_ids)
