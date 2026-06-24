"""Vector store integration with configurable Chroma backends."""
from dataclasses import dataclass
from typing import Any, Protocol

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings

from app.core.config import Settings, VectorStoreBackendType, get_settings

settings = get_settings()


class VectorStoreError(Exception):
    """Base error for vector store operations."""


class VectorStoreConfigurationError(VectorStoreError):
    """Raised when vector store configuration is invalid."""


class VectorStoreIsolationError(VectorStoreError):
    """Raised when a vector search is attempted without isolation context."""


@dataclass(frozen=True)
class VectorChunkInput:
    """Normalized chunk input for vector store writes."""

    id: str
    document_id: str
    knowledge_base_id: str
    content: str


@dataclass(frozen=True)
class VectorSearchResult:
    """Normalized vector search result."""

    chunk_id: str | None
    document_id: str | None
    content: str | None
    score: float


class VectorStoreBackend(Protocol):
    """Interface implemented by vector store backends."""

    def get_collection(self) -> Collection:
        """Get or create the backing collection."""

    def add_chunks(
        self,
        chunks: list[VectorChunkInput],
        embeddings: list[list[float]],
    ) -> None:
        """Add chunks and embeddings to the vector store."""

    def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int,
        knowledge_base_id: str,
    ) -> list[VectorSearchResult]:
        """Search chunks within one knowledge base."""

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        """Delete chunks from the vector store."""

    def health_check(self) -> None:
        """Raise if the backend is unavailable."""


class BaseChromaBackend:
    """Shared Chroma collection operations."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any | None = None
        self._collection: Collection | None = None

    def create_client(self) -> Any:
        raise NotImplementedError

    def get_client(self) -> Any:
        if self._client is None:
            self._client = self.create_client()
        return self._client

    def get_collection(self) -> Collection:
        if self._collection is None:
            self._collection = self.get_client().get_or_create_collection(
                name=self.settings.chroma_collection_name,
                metadata={"description": "Document chunks for RAG"},
            )
        return self._collection

    def add_chunks(
        self,
        chunks: list[VectorChunkInput],
        embeddings: list[list[float]],
    ) -> None:
        collection = self.get_collection()
        collection.add(
            ids=[chunk.id for chunk in chunks],
            documents=[chunk.content for chunk in chunks],
            embeddings=embeddings,
            metadatas=[
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "knowledge_base_id": chunk.knowledge_base_id,
                }
                for chunk in chunks
            ],
        )

    def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int,
        knowledge_base_id: str,
    ) -> list[VectorSearchResult]:
        _validate_knowledge_base_id(knowledge_base_id)
        collection = self.get_collection()
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"knowledge_base_id": knowledge_base_id},
        )
        return _parse_query_results(results)

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        self.get_collection().delete(ids=chunk_ids)

    def health_check(self) -> None:
        self.get_collection()


class ChromaLocalBackend(BaseChromaBackend):
    """Local persistent Chroma backend."""

    def create_client(self) -> chromadb.PersistentClient:
        self.settings.chroma_data_dir.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(
            path=str(self.settings.chroma_data_dir),
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True,
            ),
        )


class ChromaServerBackend(BaseChromaBackend):
    """Remote Chroma server backend."""

    def create_client(self) -> chromadb.HttpClient:
        headers = None
        if self.settings.chroma_auth_token:
            headers = {"Authorization": f"Bearer {self.settings.chroma_auth_token}"}
        return chromadb.HttpClient(
            host=self.settings.chroma_host,
            port=self.settings.chroma_port,
            ssl=self.settings.chroma_ssl,
            headers=headers,
        )


_backend: VectorStoreBackend | None = None


def reset_vectorstore_backend_cache() -> None:
    """Reset cached vector store backend, mainly for tests."""
    global _backend
    _backend = None


def get_vectorstore_backend() -> VectorStoreBackend:
    """Get cached vector store backend from settings."""
    global _backend
    if _backend is not None:
        return _backend

    if settings.vectorstore_backend == VectorStoreBackendType.CHROMA_LOCAL:
        _backend = ChromaLocalBackend(settings)
    elif settings.vectorstore_backend == VectorStoreBackendType.CHROMA_SERVER:
        _backend = ChromaServerBackend(settings)
    else:
        raise VectorStoreConfigurationError(
            f"Unsupported vector store backend: {settings.vectorstore_backend}"
        )
    return _backend


def get_vector_store():
    """Get the vector store collection instance."""
    return get_vectorstore_backend().get_collection()


def add_chunks_to_vectorstore(
    chunks: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> None:
    """Add chunks and their embeddings to the configured vector store."""
    normalized = [
        VectorChunkInput(
            id=chunk["id"],
            document_id=chunk["document_id"],
            knowledge_base_id=chunk["knowledge_base_id"],
            content=chunk["content"],
        )
        for chunk in chunks
    ]
    get_vectorstore_backend().add_chunks(normalized, embeddings)


def search_vectorstore(
    query_embedding: list[float],
    top_k: int | None = None,
    knowledge_base_id: str | None = None,
) -> list[dict[str, Any]]:
    """Search vector store for similar chunks within one knowledge base."""
    if top_k is None:
        top_k = settings.retrieval_top_k
    _validate_knowledge_base_id(knowledge_base_id)
    results = get_vectorstore_backend().search(
        query_embedding,
        top_k=top_k,
        knowledge_base_id=knowledge_base_id,
    )
    return [
        {
            "chunk_id": result.chunk_id,
            "document_id": result.document_id,
            "content": result.content,
            "score": result.score,
        }
        for result in results
    ]


def delete_chunks_from_vectorstore(chunk_ids: list[str]) -> None:
    """Delete chunks from vector store."""
    get_vectorstore_backend().delete_chunks(chunk_ids)


def _validate_knowledge_base_id(knowledge_base_id: str | None) -> None:
    if not knowledge_base_id:
        raise VectorStoreIsolationError("knowledge_base_id is required for vector search")


def _parse_query_results(results: dict[str, Any]) -> list[VectorSearchResult]:
    output = []
    if results["ids"] and results["ids"][0]:
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        documents = results["documents"][0] if results["documents"] else []
        distances = results["distances"][0] if results["distances"] else []

        for i, _chunk_id in enumerate(results["ids"][0]):
            metadata = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
            output.append(
                VectorSearchResult(
                    chunk_id=metadata.get("chunk_id"),
                    document_id=metadata.get("document_id"),
                    content=documents[i] if i < len(documents) else None,
                    score=distances[i] if i < len(distances) else 0.0,
                )
            )
    return output
