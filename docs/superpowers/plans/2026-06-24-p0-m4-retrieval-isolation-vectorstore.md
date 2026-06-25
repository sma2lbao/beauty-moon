# P0-M4 Retrieval Isolation and Vector Store Productionization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement P0-M4 so every QA and agent retrieval path is knowledge-base scoped, source-validated, and backed by a configurable local/server Chroma vector store abstraction.

**Architecture:** Keep the single Chroma collection strategy and make unscoped vector search invalid. Add a vector backend protocol/factory with local and server Chroma implementations, create agent RAG tools per request with the current `knowledge_base_id`, and validate retrieved source documents against SQL before prompt construction or response output.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic Settings, ChromaDB, LangGraph, pytest, Nx `luna-corpus:test` target.

## Global Constraints

- Do not implement pgvector, Qdrant, Milvus, Weaviate, Pinecone, or multi-backend storage.
- Do not implement collection-per-tenant or collection-per-knowledge-base migration.
- Do not implement rebuild-index API endpoints, background jobs, or CLI commands.
- Production authentication remains the existing temporary `X-User-Id` header model.
- Keep one logical Chroma collection; default collection name is `document_chunks`.
- Vector records must include `chunk_id`, `document_id`, and `knowledge_base_id` metadata.
- `knowledge_base_id` is mandatory for vector search.
- Agent tool schemas must not expose `knowledge_base_id` to the LLM.
- Final verification must run through Nx: `npx nx run luna-corpus:test`.

---

## File Structure

Create or modify these files:

- Modify `apps/luna-corpus/app/core/config.py`
  - Add `VectorStoreBackendType` enum and Chroma server/local settings.
- Modify `apps/luna-corpus/app/db/vectorstore.py`
  - Replace direct Chroma module functions with dataclasses, backend protocol, local/server Chroma backends, factory/cache, explicit errors, and compatibility façade functions.
- Modify `apps/luna-corpus/app/graph/rag_graph.py`
  - Add source validation helper and use it in non-streaming, streaming, multi-turn, and multi-turn streaming retrieval flows.
- Modify `apps/luna-corpus/app/agent/tools/rag_search.py`
  - Add `create_rag_search_tool(knowledge_base_id: str)` and remove default use of unscoped search.
- Modify `apps/luna-corpus/app/agent/tools/__init__.py`
  - Export `create_rag_search_tool` instead of only the static `rag_search_tool`.
- Modify `apps/luna-corpus/app/api/agent_routes.py`
  - Add RBAC dependencies to every endpoint and build request-scoped registries.
- Modify `apps/luna-corpus/tests/core/test_config.py`
  - Add config tests for backend defaults and enum parsing.
- Modify `apps/luna-corpus/tests/db/test_vectorstore.py`
  - Add backend, isolation, and filter tests; update existing searches to pass `knowledge_base_id`.
- Modify `apps/luna-corpus/tests/graph/test_knowledge_base_filter.py`
  - Add source validation tests.
- Modify `apps/luna-corpus/tests/graph/test_rag_graph.py`
  - Update existing tests to include `knowledge_base_id`; add streaming/multi-turn validation tests.
- Modify `apps/luna-corpus/tests/agent/test_tools.py`
  - Add scoped RAG tool tests.
- Modify `apps/luna-corpus/tests/agent/test_api.py`
  - Replace anonymous-agent assumptions with authenticated/RBAC coverage.

No database migration is required.

---

### Task 1: Add vector store configuration

**Files:**
- Modify: `apps/luna-corpus/app/core/config.py`
- Test: `apps/luna-corpus/tests/core/test_config.py`

**Interfaces:**
- Produces: `VectorStoreBackendType` enum with values `CHROMA_LOCAL = "chroma_local"` and `CHROMA_SERVER = "chroma_server"`.
- Produces settings fields: `vectorstore_backend`, `chroma_collection_name`, `chroma_host`, `chroma_port`, `chroma_ssl`, `chroma_auth_token`.
- Consumed by Task 2: `get_settings().vectorstore_backend` and related Chroma settings.

- [ ] **Step 1: Write failing config tests**

Add these imports and tests to `apps/luna-corpus/tests/core/test_config.py`:

```python
from app.core.config import AppEnv, Settings, VectorStoreBackendType
```

Replace the existing import line:

```python
from app.core.config import AppEnv, Settings
```

with the import above.

Append these tests at the end of the file:

```python
def test_vectorstore_defaults_to_local_chroma():
    settings = Settings()

    assert settings.vectorstore_backend == VectorStoreBackendType.CHROMA_LOCAL
    assert settings.chroma_collection_name == "document_chunks"
    assert settings.chroma_host == "localhost"
    assert settings.chroma_port == 8000
    assert settings.chroma_ssl is False
    assert settings.chroma_auth_token == ""


def test_vectorstore_backend_accepts_chroma_server():
    settings = Settings(
        vectorstore_backend="chroma_server",
        chroma_host="chroma.example.com",
        chroma_port=8443,
        chroma_ssl=True,
        chroma_auth_token="secret-token",
    )

    assert settings.vectorstore_backend == VectorStoreBackendType.CHROMA_SERVER
    assert settings.chroma_host == "chroma.example.com"
    assert settings.chroma_port == 8443
    assert settings.chroma_ssl is True
    assert settings.chroma_auth_token == "secret-token"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
npx nx run luna-corpus:test
```

Expected: FAIL with an import error similar to `cannot import name 'VectorStoreBackendType'` or an attribute error for `vectorstore_backend`.

- [ ] **Step 3: Implement configuration**

In `apps/luna-corpus/app/core/config.py`, add this enum after `AppEnv`:

```python
class VectorStoreBackendType(StrEnum):
    """Available vector store backends."""

    CHROMA_LOCAL = "chroma_local"
    CHROMA_SERVER = "chroma_server"
```

In the `Settings` class, replace the current Chroma section:

```python
    # Chroma
    chroma_data_dir: Path = Field(
        default=Path("./data/chroma"),
        description="Directory for Chroma vector store data",
    )
```

with:

```python
    # Vector Store / Chroma
    vectorstore_backend: VectorStoreBackendType = Field(
        default=VectorStoreBackendType.CHROMA_LOCAL,
        description="Vector store backend to use",
    )
    chroma_collection_name: str = Field(
        default="document_chunks",
        description="Chroma collection name for document chunks",
    )
    chroma_data_dir: Path = Field(
        default=Path("./data/chroma"),
        description="Directory for local Chroma vector store data",
    )
    chroma_host: str = Field(
        default="localhost",
        description="Chroma server host",
    )
    chroma_port: int = Field(
        default=8000,
        description="Chroma server port",
    )
    chroma_ssl: bool = Field(
        default=False,
        description="Use SSL when connecting to Chroma server",
    )
    chroma_auth_token: str = Field(
        default="",
        description="Optional bearer token for Chroma server",
    )
```

- [ ] **Step 4: Run tests to verify config passes**

Run:

```bash
npx nx run luna-corpus:test
```

Expected: config tests pass. Other tests may fail later because vectorstore behavior has not changed yet.

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/core/config.py apps/luna-corpus/tests/core/test_config.py
git commit -m "feat(corpus): add vectorstore backend settings"
```

---

### Task 2: Build vector store backend abstraction and mandatory KB filtering

**Files:**
- Modify: `apps/luna-corpus/app/db/vectorstore.py`
- Modify: `apps/luna-corpus/tests/db/test_vectorstore.py`

**Interfaces:**
- Consumes from Task 1: `VectorStoreBackendType`, `Settings.vectorstore_backend`, `Settings.chroma_collection_name`, Chroma local/server settings.
- Produces exceptions: `VectorStoreError`, `VectorStoreConfigurationError`, `VectorStoreIsolationError`.
- Produces dataclasses: `VectorChunkInput`, `VectorSearchResult`.
- Produces protocol: `VectorStoreBackend` with `get_collection`, `add_chunks`, `search`, `delete_chunks`, `health_check`.
- Produces façade functions: `get_vectorstore_backend()`, `reset_vectorstore_backend_cache()`, `get_vector_store()`, `add_chunks_to_vectorstore()`, `search_vectorstore()`, `delete_chunks_from_vectorstore()`.
- Consumed by Tasks 3 and 4: `search_vectorstore(query_embedding, top_k, knowledge_base_id)` raises `VectorStoreIsolationError` when `knowledge_base_id` is missing.

- [ ] **Step 1: Replace vectorstore tests with expected P0-M4 behavior**

Edit `apps/luna-corpus/tests/db/test_vectorstore.py`.

Keep the existing `temp_chroma_dir` fixture. Replace `mock_settings` fixture and all tests with this content below the imports and `temp_chroma_dir` fixture:

```python
from unittest.mock import Mock

import chromadb

from app.core.config import Settings, VectorStoreBackendType


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
npx nx run luna-corpus:test
```

Expected: FAIL with missing names such as `reset_vectorstore_backend_cache`, `VectorStoreIsolationError`, `ChromaLocalBackend`, or because old `search_vectorstore` permits missing `knowledge_base_id`.

- [ ] **Step 3: Replace vectorstore implementation**

Replace all content in `apps/luna-corpus/app/db/vectorstore.py` with:

```python
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
            metadata = metadatas[i] if i < len(metatas) and metadatas[i] else {}
            output.append(
                VectorSearchResult(
                    chunk_id=metadata.get("chunk_id"),
                    document_id=metadata.get("document_id"),
                    content=documents[i] if i < len(documents) else None,
                    score=distances[i] if i < len(distances) else 0.0,
                )
            )
    return output
```

Note: the code block above contains a typo `metatas`; correct it to `metadatas` during implementation:

```python
metadata = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
```

- [ ] **Step 4: Run tests to verify vectorstore passes**

Run:

```bash
npx nx run luna-corpus:test
```

Expected: vectorstore tests pass. Graph tests may fail where they still call `search_vectorstore` without `knowledge_base_id` or lack source validation.

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/db/vectorstore.py apps/luna-corpus/tests/db/test_vectorstore.py
git commit -m "feat(corpus): add vectorstore backend abstraction"
```

---

### Task 3: Add RAG source validation before prompt and sources

**Files:**
- Modify: `apps/luna-corpus/app/graph/rag_graph.py`
- Modify: `apps/luna-corpus/tests/graph/test_knowledge_base_filter.py`
- Modify: `apps/luna-corpus/tests/graph/test_rag_graph.py`

**Interfaces:**
- Consumes from Task 2: `search_vectorstore(..., knowledge_base_id: str)`.
- Produces helper: `validate_retrieved_docs_for_knowledge_base(retrieved_docs: list[dict[str, Any]], knowledge_base_id: str) -> list[dict[str, Any]]`.
- Produces behavior: every RAG path builds prompt context and response sources only from validated docs.

- [ ] **Step 1: Add failing source validation tests**

Append these tests to `apps/luna-corpus/tests/graph/test_knowledge_base_filter.py`:

```python
def test_validate_retrieved_docs_filters_documents_outside_knowledge_base():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.database import get_db
    from app.db.models import Base, Document, KnowledgeBase, Tenant, Workspace
    from app.graph import rag_graph

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="Research", slug="research", tenant=tenant)
    kb_one = KnowledgeBase(id="kb-1", name="Docs", slug="docs", workspace=workspace)
    kb_two = KnowledgeBase(id="kb-2", name="Notes", slug="notes", workspace=workspace)
    doc_one = Document(id="doc-1", title="Allowed", content="A", knowledge_base=kb_one)
    doc_two = Document(id="doc-2", title="Blocked", content="B", knowledge_base=kb_two)
    session.add_all([doc_one, doc_two])
    session.commit()
    session.close()

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    docs = [
        {"chunk_id": "chunk-1", "document_id": "doc-1", "content": "Allowed", "score": 0.1},
        {"chunk_id": "chunk-2", "document_id": "doc-2", "content": "Blocked", "score": 0.2},
        {"chunk_id": "chunk-3", "document_id": None, "content": "No doc", "score": 0.3},
    ]

    with patch("app.graph.rag_graph.get_db", override_get_db):
        filtered = rag_graph.validate_retrieved_docs_for_knowledge_base(docs, "kb-1")

    assert filtered == [
        {"chunk_id": "chunk-1", "document_id": "doc-1", "content": "Allowed", "score": 0.1}
    ]
    engine.dispose()


def test_retrieve_node_validates_sources_before_returning_docs():
    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1]),
        patch(
            "app.graph.rag_graph.search_vectorstore",
            return_value=[
                {"chunk_id": "chunk-1", "document_id": "doc-1", "content": "Allowed", "score": 0.1},
                {"chunk_id": "chunk-2", "document_id": "doc-2", "content": "Blocked", "score": 0.2},
            ],
        ),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=[
                {"chunk_id": "chunk-1", "document_id": "doc-1", "content": "Allowed", "score": 0.1}
            ],
        ) as validate,
    ):
        result = rag_graph.retrieve_node({"question": "What?", "knowledge_base_id": "kb-1"})

    validate.assert_called_once()
    assert result["retrieved_docs"] == [
        {"chunk_id": "chunk-1", "document_id": "doc-1", "content": "Allowed", "score": 0.1}
    ]
```

Modify `test_retrieve_node_passes_knowledge_base_filter` in the same file so the patch block includes validation:

```python
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=[],
        ),
```

- [ ] **Step 2: Update failing graph tests for mandatory KB context**

In `apps/luna-corpus/tests/graph/test_rag_graph.py`, update `test_retrieve_node` state to include KB context:

```python
        state = RAGState(
            question="test question",
            knowledge_base_id="kb-1",
            conversation_id=None,
            conversation_history=[],
            retrieved_docs=[],
            answer=None,
            sources=[],
            processing_time_ms=None,
            needs_summarization=False,
        )
```

Update the patch block in `test_retrieve_node` to include:

```python
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=mock_results,
        ),
```

Update `test_generate_node` state to include required keys:

```python
    state = RAGState(
        question="What is Python?",
        knowledge_base_id="kb-1",
        conversation_id=None,
        conversation_history=[],
        retrieved_docs=[
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "content": "Python is a programming language.",
                "score": 0.95,
            }
        ],
        answer=None,
        sources=[],
        processing_time_ms=None,
        needs_summarization=False,
    )
```

Update `test_answer_question` patch block to include:

```python
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=mock_results,
        ),
```

Append these tests to `apps/luna-corpus/tests/graph/test_rag_graph.py`:

```python
def test_answer_question_uses_validated_sources_for_prompt():
    from app.graph.rag_graph import answer_question

    raw_results = [
        {"chunk_id": "chunk-1", "document_id": "doc-1", "content": "Allowed", "score": 0.1},
        {"chunk_id": "chunk-2", "document_id": "doc-2", "content": "Blocked", "score": 0.2},
    ]
    validated_results = [raw_results[0]]

    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1]),
        patch("app.graph.rag_graph.search_vectorstore", return_value=raw_results),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=validated_results,
        ),
        patch("app.graph.rag_graph.generate_response", return_value="Answer") as generate,
    ):
        result = answer_question("Test question", "kb-1")

    prompt = generate.call_args.kwargs["prompt"]
    assert "Allowed" in prompt
    assert "Blocked" not in prompt
    assert result["sources"] == [
        {"document_id": "doc-1", "chunk_content": "Allowed", "relevance_score": 0.1}
    ]


def test_answer_question_returns_no_results_when_validation_filters_everything():
    from app.graph.rag_graph import answer_question

    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1]),
        patch(
            "app.graph.rag_graph.search_vectorstore",
            return_value=[
                {"chunk_id": "chunk-2", "document_id": "doc-2", "content": "Blocked", "score": 0.2}
            ],
        ),
        patch("app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base", return_value=[]),
    ):
        result = answer_question("Test question", "kb-1")

    assert "I couldn't find" in result["answer"]
    assert result["sources"] == []


async def collect_stream(async_iterable):
    events = []
    async for event in async_iterable:
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_answer_question_stream_uses_validated_sources():
    from app.graph.rag_graph import answer_question_stream

    raw_results = [
        {"chunk_id": "chunk-1", "document_id": "doc-1", "content": "Allowed", "score": 0.1},
        {"chunk_id": "chunk-2", "document_id": "doc-2", "content": "Blocked", "score": 0.2},
    ]
    validated_results = [raw_results[0]]

    async def fake_streaming_response(prompt, context):
        yield "Answer"

    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1]),
        patch("app.graph.rag_graph.search_vectorstore", return_value=raw_results),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=validated_results,
        ),
        patch("app.graph.rag_graph.generate_streaming_response", fake_streaming_response),
    ):
        events = await collect_stream(answer_question_stream("Test question", "kb-1"))

    done = [event for event in events if event["event"] == "done"][0]
    assert done["data"]["sources"] == [
        {"document_id": "doc-1", "chunk_content": "Allowed", "relevance_score": 0.1}
    ]


def test_answer_question_multi_turn_uses_validated_sources():
    from app.graph.rag_graph import answer_question_multi_turn

    raw_results = [
        {"chunk_id": "chunk-1", "document_id": "doc-1", "content": "Allowed", "score": 0.1}
    ]

    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1]),
        patch("app.graph.rag_graph.search_vectorstore", return_value=raw_results),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=raw_results,
        ),
        patch("app.graph.rag_graph.generate_response", return_value="Answer"),
    ):
        result = answer_question_multi_turn("Test question", "kb-1")

    assert result["sources"] == [
        {"document_id": "doc-1", "chunk_content": "Allowed", "relevance_score": 0.1}
    ]


@pytest.mark.asyncio
async def test_answer_question_multi_turn_stream_uses_validated_sources():
    from app.graph.rag_graph import answer_question_multi_turn_stream

    raw_results = [
        {"chunk_id": "chunk-1", "document_id": "doc-1", "content": "Allowed", "score": 0.1}
    ]

    async def fake_streaming_response(prompt, context):
        yield "Answer"

    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1]),
        patch("app.graph.rag_graph.search_vectorstore", return_value=raw_results),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=raw_results,
        ),
        patch("app.graph.rag_graph.generate_streaming_response", fake_streaming_response),
    ):
        events = await collect_stream(answer_question_multi_turn_stream("Test question", "kb-1"))

    done = [event for event in events if event["event"] == "done"][0]
    assert done["data"]["sources"] == [
        {"document_id": "doc-1", "chunk_content": "Allowed", "relevance_score": 0.1}
    ]
```

Also add imports at the top of `test_rag_graph.py`:

```python
import pytest
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
npx nx run luna-corpus:test
```

Expected: FAIL because `validate_retrieved_docs_for_knowledge_base` does not exist or retrieval paths do not call it.

- [ ] **Step 4: Implement source validation helper and wire retrieve node**

In `apps/luna-corpus/app/graph/rag_graph.py`, add this import:

```python
from app.db.database import SessionLocal, get_db
from app.db.models import Document
```

Replace the existing import:

```python
from app.db.database import SessionLocal
```

with the two imports above.

Add these helpers after `settings = get_settings()`:

```python
def validate_retrieved_docs_for_knowledge_base(
    retrieved_docs: list[dict[str, Any]],
    knowledge_base_id: str,
) -> list[dict[str, Any]]:
    """Keep only retrieved docs whose SQL document belongs to the knowledge base."""
    document_ids = {
        doc.get("document_id") for doc in retrieved_docs if doc.get("document_id")
    }
    if not document_ids:
        return []

    db = next(get_db())
    try:
        allowed_document_ids = {
            document.id
            for document in db.query(Document.id)
            .filter(
                Document.id.in_(document_ids),
                Document.knowledge_base_id == knowledge_base_id,
            )
            .all()
        }
    finally:
        db.close()

    return [
        doc
        for doc in retrieved_docs
        if doc.get("document_id") in allowed_document_ids
    ]


def format_sources(retrieved_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format validated retrieved docs as API sources."""
    return [
        {
            "document_id": doc["document_id"],
            "chunk_content": doc["content"][:200] + "..."
            if len(doc["content"]) > 200
            else doc["content"],
            "relevance_score": doc["score"],
        }
        for doc in retrieved_docs
    ]
```

In `retrieve_node`, after the `retrieved_docs` list is built, add validation and return the validated list:

```python
    retrieved_docs = validate_retrieved_docs_for_knowledge_base(
        retrieved_docs,
        knowledge_base_id,
    )

    return {"retrieved_docs": retrieved_docs}
```

Replace the existing final line:

```python
    return {"retrieved_docs": retrieved_docs}
```

with the block above.

- [ ] **Step 5: Wire helper into source formatting**

In `generate_node`, replace the current `sources = [...]` list comprehension with:

```python
    sources = format_sources(retrieved_docs)
```

In `answer_question_stream`, after building `retrieved_docs`, add:

```python
    retrieved_docs = validate_retrieved_docs_for_knowledge_base(
        retrieved_docs,
        knowledge_base_id,
    )
```

before the `yield` that reports `检索到 {len(retrieved_docs)} 个相关文档`.

In `answer_question_stream`, replace the current `sources = [...]` list comprehension with:

```python
    sources = format_sources(retrieved_docs)
```

In `answer_question_multi_turn_stream`, after building `retrieved_docs`, add:

```python
    retrieved_docs = validate_retrieved_docs_for_knowledge_base(
        retrieved_docs,
        knowledge_base_id,
    )
```

before the `yield` that reports retrieved doc count.

In `answer_question_multi_turn_stream`, replace the current `sources = [...]` list comprehension with:

```python
    sources = format_sources(retrieved_docs)
```

`answer_question` and `answer_question_multi_turn` use `retrieve_node` through the graph, so they inherit validation from `retrieve_node`.

- [ ] **Step 6: Run tests to verify graph behavior passes**

Run:

```bash
npx nx run luna-corpus:test
```

Expected: graph tests pass. If `validate_retrieved_docs_for_knowledge_base` returns rows as SQLAlchemy `Row` objects and `document.id` fails, use `row[0]` in the set comprehension:

```python
allowed_document_ids = {row[0] for row in db.query(Document.id).filter(...).all()}
```

Then rerun the same Nx command.

- [ ] **Step 7: Commit**

```bash
git add apps/luna-corpus/app/graph/rag_graph.py apps/luna-corpus/tests/graph/test_knowledge_base_filter.py apps/luna-corpus/tests/graph/test_rag_graph.py
git commit -m "feat(corpus): validate rag sources by knowledge base"
```

---

### Task 4: Scope the agent RAG tool by knowledge base

**Files:**
- Modify: `apps/luna-corpus/app/agent/tools/rag_search.py`
- Modify: `apps/luna-corpus/app/agent/tools/__init__.py`
- Modify: `apps/luna-corpus/tests/agent/test_tools.py`

**Interfaces:**
- Consumes from Task 2: mandatory `search_vectorstore(..., knowledge_base_id=...)`.
- Produces: `create_rag_search_tool(knowledge_base_id: str) -> Tool`.
- Consumed by Task 5: request-scoped agent registry uses `create_rag_search_tool(context.knowledge_base.id)`.

- [ ] **Step 1: Write failing scoped tool tests**

Append these tests to `apps/luna-corpus/tests/agent/test_tools.py`:

```python
from unittest.mock import patch

from app.agent.tools.rag_search import create_rag_search_tool


def test_create_rag_search_tool_passes_knowledge_base_filter():
    rag_tool = create_rag_search_tool("kb-1")

    with (
        patch("app.agent.tools.rag_search.embed_text", return_value=[0.1]),
        patch(
            "app.agent.tools.rag_search.search_vectorstore",
            return_value=[
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "content": "Relevant content",
                    "score": 0.2,
                }
            ],
        ) as search,
    ):
        result = rag_tool.executor(query="What?", top_k=3)

    search.assert_called_once_with([0.1], top_k=3, knowledge_base_id="kb-1")
    assert "Relevant content" in result


def test_rag_search_tool_schema_does_not_expose_knowledge_base_id():
    rag_tool = create_rag_search_tool("kb-1")

    properties = rag_tool.parameters_schema["properties"]

    assert "query" in properties
    assert "top_k" in properties
    assert "knowledge_base_id" not in properties


def test_rag_search_tool_handles_empty_results():
    rag_tool = create_rag_search_tool("kb-1")

    with (
        patch("app.agent.tools.rag_search.embed_text", return_value=[0.1]),
        patch("app.agent.tools.rag_search.search_vectorstore", return_value=[]),
    ):
        result = rag_tool.executor(query="What?")

    assert result == "No relevant documents found in the knowledge base."


def test_rag_search_tool_handles_vectorstore_error():
    rag_tool = create_rag_search_tool("kb-1")

    with (
        patch("app.agent.tools.rag_search.embed_text", return_value=[0.1]),
        patch(
            "app.agent.tools.rag_search.search_vectorstore",
            side_effect=RuntimeError("backend unavailable"),
        ),
    ):
        result = rag_tool.executor(query="What?")

    assert result == "Error searching knowledge base: backend unavailable"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
npx nx run luna-corpus:test
```

Expected: FAIL because `create_rag_search_tool` does not exist and existing static RAG tool does not pass `knowledge_base_id`.

- [ ] **Step 3: Implement scoped RAG tool factory**

Replace `apps/luna-corpus/app/agent/tools/rag_search.py` with:

```python
"""Knowledge-base scoped RAG search tool."""
from app.agent.tool import Tool, tool
from app.db.vectorstore import search_vectorstore
from app.services.llm import embed_text


_RAG_SEARCH_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The search query to find relevant documents",
        },
        "top_k": {
            "type": "integer",
            "description": "Maximum number of documents to return",
            "default": 5,
        },
    },
    "required": ["query"],
}


def _format_rag_results(query: str, knowledge_base_id: str, top_k: int = 5) -> str:
    """Execute scoped RAG search and format results."""
    try:
        query_embedding = embed_text(query)
        results = search_vectorstore(
            query_embedding,
            top_k=top_k,
            knowledge_base_id=knowledge_base_id,
        )

        if not results:
            return "No relevant documents found in the knowledge base."

        formatted = []
        for i, result in enumerate(results, 1):
            content = result.get("content", "") or ""
            score = result.get("score", 0.0)
            doc_id = result.get("document_id", "unknown")
            formatted.append(
                f"[Document {i}] (ID: {doc_id}, Relevance: {score:.3f})\n"
                f"{content[:500]}{'...' if len(content) > 500 else ''}"
            )

        return "\n\n".join(formatted)

    except Exception as e:
        return f"Error searching knowledge base: {str(e)}"


def create_rag_search_tool(knowledge_base_id: str) -> Tool:
    """Create a RAG search tool scoped to one knowledge base."""

    def _get_rag_results(query: str, top_k: int = 5) -> str:
        return _format_rag_results(
            query=query,
            top_k=top_k,
            knowledge_base_id=knowledge_base_id,
        )

    return tool(
        name="rag_search",
        description=(
            "Search the current knowledge base for relevant documents. "
            "Use this when the user asks about information that might be "
            "in the current documents."
        ),
        parameters_schema=_RAG_SEARCH_PARAMETERS,
    )(_get_rag_results)
```

Replace `apps/luna-corpus/app/agent/tools/__init__.py` with:

```python
"""Built-in tools for the agent."""
from app.agent.tools.rag_search import create_rag_search_tool
from app.agent.tools.calculator import calculator_tool
from app.agent.tools.time_tool import current_time_tool

__all__ = [
    "create_rag_search_tool",
    "calculator_tool",
    "current_time_tool",
]
```

- [ ] **Step 4: Run tests to verify scoped tool passes**

Run:

```bash
npx nx run luna-corpus:test
```

Expected: scoped tool tests pass. Agent API tests may fail because `agent_routes.py` still imports `rag_search_tool`.

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/agent/tools/rag_search.py apps/luna-corpus/app/agent/tools/__init__.py apps/luna-corpus/tests/agent/test_tools.py
git commit -m "feat(corpus): scope agent rag tool to knowledge base"
```

---

### Task 5: Protect all agent endpoints and use request-scoped registries

**Files:**
- Modify: `apps/luna-corpus/app/api/agent_routes.py`
- Modify: `apps/luna-corpus/tests/agent/test_api.py`

**Interfaces:**
- Consumes from Task 4: `create_rag_search_tool(knowledge_base_id: str)`.
- Consumes existing auth: `AuthenticatedRequestContext`, `require_permission`, `PermissionSlug`.
- Produces helper: `get_default_registry(knowledge_base_id: str) -> ToolRegistry`.
- Produces helper: `filter_registry(registry: ToolRegistry, available_tools: list[str] | None) -> ToolRegistry`.
- Produces behavior: all `/api/v1/agent/*` endpoints require authenticated KB context.

- [ ] **Step 1: Replace agent API tests with authenticated/RBAC coverage**

Replace `apps/luna-corpus/tests/agent/test_api.py` with:

```python
"""Tests for Agent API."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.base import AgentResponse
from app.auth.permissions import PermissionSlug
from app.db.database import get_db
from app.db.models import (
    Base,
    KnowledgeBase,
    Permission,
    Role,
    Tenant,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.main import create_app


@pytest.fixture
def app_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="Research", slug="research", tenant=tenant)
    kb_one = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    kb_two = KnowledgeBase(name="Notes", slug="notes", workspace=workspace)
    session.add_all([kb_one, kb_two])
    session.commit()

    context = {
        "tenant_id": tenant.id,
        "workspace_id": workspace.id,
        "kb_one_id": kb_one.id,
        "kb_two_id": kb_two.id,
    }
    session.close()

    yield engine, Session, context
    engine.dispose()


@pytest.fixture
def client(app_db):
    _, Session, _ = app_db

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def create_user_with_permissions(Session, workspace_id, label, permission_slugs):
    session = Session()
    try:
        user = User(email=f"{label}@example.com", display_name=label)
        permissions = []
        for slug in permission_slugs:
            permission = session.query(Permission).filter(Permission.slug == slug).first()
            if not permission:
                permission = Permission(name=slug, slug=slug, description=slug)
            permissions.append(permission)
        role = Role(name=label, slug=label, is_system=True, permissions=permissions)
        membership = WorkspaceMembership(
            user=user,
            workspace_id=workspace_id,
            roles=[role],
        )
        session.add(membership)
        session.commit()
        return user.id
    finally:
        session.close()


def headers(context, knowledge_base_id, user_id):
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": knowledge_base_id,
    }


@pytest.mark.parametrize(
    "method,path,json_body",
    [
        ("post", "/api/v1/agent/query", {"query": "Hello", "mode": "direct"}),
        ("post", "/api/v1/agent/stream", {"query": "Hello", "mode": "direct"}),
        ("get", "/api/v1/agent/tools", None),
        ("get", "/api/v1/agent/modes", None),
        (
            "post",
            "/api/v1/agent/tools",
            {"name": "test_tool", "description": "A test tool", "parameters_schema": {"type": "object"}},
        ),
    ],
)
def test_agent_endpoints_reject_anonymous_requests(client, method, path, json_body):
    request = getattr(client, method)

    if json_body is None:
        response = request(path)
    else:
        response = request(path, json=json_body)

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing required header: X-Tenant-Id"


def test_list_modes_requires_knowledge_base_read(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "mode_reader",
        [PermissionSlug.KNOWLEDGE_BASE_READ],
    )

    response = client.get(
        "/api/v1/agent/modes",
        headers=headers(context, context["kb_one_id"], user_id),
    )

    assert response.status_code == 200
    data = response.json()
    assert "modes" in data
    assert len(data["modes"]) == 4


def test_list_tools_requires_knowledge_base_read(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "tool_reader",
        [PermissionSlug.KNOWLEDGE_BASE_READ],
    )

    response = client.get(
        "/api/v1/agent/tools",
        headers=headers(context, context["kb_one_id"], user_id),
    )

    assert response.status_code == 200
    data = response.json()
    tool_names = {tool["name"] for tool in data["tools"]}
    assert {"rag_search", "calculator", "current_time"}.issubset(tool_names)


def test_register_tool_requires_knowledge_base_manage(client, app_db):
    _, Session, context = app_db
    reader_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "tool_register_reader",
        [PermissionSlug.KNOWLEDGE_BASE_READ],
    )

    response = client.post(
        "/api/v1/agent/tools",
        headers=headers(context, context["kb_one_id"], reader_id),
        json={
            "name": "test_tool",
            "description": "A test tool",
            "parameters_schema": {"type": "object"},
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing required permission: knowledge_base:manage"


def test_admin_can_register_tool(client, app_db):
    _, Session, context = app_db
    admin_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "tool_register_admin",
        [PermissionSlug.KNOWLEDGE_BASE_READ, PermissionSlug.KNOWLEDGE_BASE_MANAGE],
    )

    response = client.post(
        "/api/v1/agent/tools",
        headers=headers(context, context["kb_one_id"], admin_id),
        json={
            "name": "test_tool",
            "description": "A test tool",
            "parameters_schema": {"type": "object"},
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "test_tool"


def test_invalid_mode_requires_qa_permission(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "invalid_mode_reader",
        [PermissionSlug.QA_QUERY],
    )

    response = client.post(
        "/api/v1/agent/query",
        headers=headers(context, context["kb_one_id"], user_id),
        json={"query": "Hello", "mode": "invalid_mode"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid mode: invalid_mode"


def test_query_requires_qa_permission(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "agent_qa_reader",
        [PermissionSlug.QA_QUERY],
    )

    with patch("app.api.agent_routes.AgentFactory.create") as mock_create:
        mock_agent = AsyncMock()
        mock_agent.run.return_value = AgentResponse(
            answer="ok",
            tool_calls=[],
            steps=1,
            latency_ms=100,
        )
        mock_create.return_value = mock_agent

        response = client.post(
            "/api/v1/agent/query",
            headers=headers(context, context["kb_one_id"], user_id),
            json={"query": "Hello", "mode": "direct"},
        )

    assert response.status_code == 200
    assert response.json()["answer"] == "ok"


def test_query_without_qa_permission_is_forbidden(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "agent_no_qa_reader",
        [PermissionSlug.KNOWLEDGE_BASE_READ],
    )

    response = client.post(
        "/api/v1/agent/query",
        headers=headers(context, context["kb_one_id"], user_id),
        json={"query": "Hello", "mode": "direct"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing required permission: qa:query"


def test_query_default_registry_uses_scoped_rag_tool(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "agent_registry_reader",
        [PermissionSlug.QA_QUERY],
    )

    with patch("app.api.agent_routes.AgentFactory.create") as mock_create:
        mock_agent = AsyncMock()
        mock_agent.run.return_value = AgentResponse(
            answer="ok",
            tool_calls=[],
            steps=1,
            latency_ms=100,
        )
        mock_create.return_value = mock_agent

        response = client.post(
            "/api/v1/agent/query",
            headers=headers(context, context["kb_one_id"], user_id),
            json={"query": "Hello", "mode": "direct"},
        )

    assert response.status_code == 200
    registry = mock_create.call_args.kwargs["tools"]
    rag_tool = registry.get("rag_search")
    assert rag_tool is not None
    assert "knowledge_base_id" not in rag_tool.parameters_schema["properties"]
    assert len(registry) >= 3


def test_query_empty_list_sends_empty_registry(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "agent_empty_registry_reader",
        [PermissionSlug.QA_QUERY],
    )

    with patch("app.api.agent_routes.AgentFactory.create") as mock_create:
        mock_agent = AsyncMock()
        mock_agent.run.return_value = AgentResponse(
            answer="ok",
            tool_calls=[],
            steps=1,
            latency_ms=100,
        )
        mock_create.return_value = mock_agent

        response = client.post(
            "/api/v1/agent/query",
            headers=headers(context, context["kb_one_id"], user_id),
            json={"query": "Hello", "mode": "direct", "available_tools": []},
        )

    assert response.status_code == 200
    registry = mock_create.call_args.kwargs["tools"]
    assert len(registry) == 0


def test_stream_empty_list_sends_empty_registry(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "agent_stream_reader",
        [PermissionSlug.QA_QUERY],
    )

    with patch("app.api.agent_routes.AgentFactory.create") as mock_create:
        mock_agent = AsyncMock()
        mock_agent.run_stream.return_value = AsyncMock()
        mock_agent.run_stream.return_value.__aiter__.return_value = [
            {"event": "done", "data": {"answer": "ok"}},
        ]
        mock_create.return_value = mock_agent

        response = client.post(
            "/api/v1/agent/stream",
            headers=headers(context, context["kb_one_id"], user_id),
            json={"query": "Hello", "mode": "direct", "available_tools": []},
        )

    assert response.status_code == 200
    registry = mock_create.call_args.kwargs["tools"]
    assert len(registry) == 0


def test_agent_cross_knowledge_base_header_is_rejected(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "agent_cross_kb_reader",
        [PermissionSlug.QA_QUERY],
    )
    bad_headers = headers(context, context["kb_one_id"], user_id)
    bad_headers["X-Workspace-Id"] = "missing-workspace"

    response = client.post(
        "/api/v1/agent/query",
        headers=bad_headers,
        json={"query": "Hello", "mode": "direct"},
    )

    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
npx nx run luna-corpus:test
```

Expected: FAIL because `agent_routes.py` still has anonymous endpoints and imports `rag_search_tool`.

- [ ] **Step 3: Update agent routes imports and registry helpers**

In `apps/luna-corpus/app/api/agent_routes.py`, replace imports:

```python
from fastapi import APIRouter, HTTPException
```

with:

```python
from typing import Annotated, Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
```

Remove the existing `from typing import Any, AsyncGenerator` line because the new line includes it.

Replace:

```python
from app.agent.tools import rag_search_tool, calculator_tool, current_time_tool
```

with:

```python
from app.agent.tools import create_rag_search_tool, calculator_tool, current_time_tool
```

Add these imports:

```python
from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
```

Replace `get_default_registry()` with:

```python
def get_default_registry(knowledge_base_id: str) -> ToolRegistry:
    """Get default tool registry scoped to the current knowledge base."""
    registry = ToolRegistry()
    registry.register(create_rag_search_tool(knowledge_base_id))
    registry.register(calculator_tool)
    registry.register(current_time_tool)
    for tool in _registered_tools.values():
        registry.register(tool)
    return registry


def filter_registry(
    registry: ToolRegistry,
    available_tools: list[str] | None,
) -> ToolRegistry:
    """Filter a registry by requested tool names."""
    if available_tools is None:
        return registry

    filtered_registry = ToolRegistry()
    for tool_name in available_tools:
        tool = registry.get(tool_name)
        if tool:
            filtered_registry.register(tool)
    return filtered_registry
```

- [ ] **Step 4: Add dependencies to query and stream endpoints**

Change `query` signature to:

```python
async def query(
    request: AgentQueryRequest,
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_QUERY)),
    ],
) -> AgentQueryResponse:
```

Inside `query`, replace registry construction/filtering:

```python
    registry = get_default_registry()

    # Filter by available_tools if specified
    if request.available_tools is not None:
        filtered_registry = ToolRegistry()
        for tool_name in request.available_tools:
            tool = registry.get(tool_name)
            if tool:
                filtered_registry.register(tool)
        registry = filtered_registry
```

with:

```python
    registry = filter_registry(
        get_default_registry(context.knowledge_base.id),
        request.available_tools,
    )
```

Change `agent_stream_generator` signature to:

```python
async def agent_stream_generator(
    query: str,
    mode: AgentMode,
    registry: ToolRegistry,
) -> AsyncGenerator[str, None]:
```

This signature is already correct; do not add context here because the registry is built before streaming begins.

Change `stream_query` signature to:

```python
async def stream_query(
    request: AgentQueryRequest,
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_QUERY)),
    ],
):
```

Inside `stream_query`, replace registry construction/filtering with:

```python
    registry = filter_registry(
        get_default_registry(context.knowledge_base.id),
        request.available_tools,
    )
```

- [ ] **Step 5: Add dependencies to tools and modes endpoints**

Change `list_tools` signature to:

```python
async def list_tools(
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
) -> ToolListResponse:
```

Inside `list_tools`, replace:

```python
    registry = get_default_registry()
```

with:

```python
    registry = get_default_registry(context.knowledge_base.id)
```

Change `register_tool` signature to:

```python
async def register_tool(
    request: ToolRegisterRequest,
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_MANAGE)),
    ],
):
```

The function body does not need to use `context`.

Change `list_modes` signature to:

```python
async def list_modes(
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
):
```

The function body does not need to use `context`.

- [ ] **Step 6: Run tests to verify agent API passes**

Run:

```bash
npx nx run luna-corpus:test
```

Expected: agent API tests pass. If ruff complains about unused `context` in `register_tool` or `list_modes`, add this as the first line in each function body:

```python
    _ = context
```

Then rerun the Nx command.

- [ ] **Step 7: Commit**

```bash
git add apps/luna-corpus/app/api/agent_routes.py apps/luna-corpus/tests/agent/test_api.py
git commit -m "feat(corpus): protect agent endpoints with rbac"
```

---

### Task 6: Final integration cleanup and verification

**Files:**
- Modify if needed: `apps/luna-corpus/app/api/agent_routes.py`
- Modify if needed: `apps/luna-corpus/app/db/vectorstore.py`
- Modify if needed: `apps/luna-corpus/app/graph/rag_graph.py`
- Modify if needed: tests touched by earlier tasks

**Interfaces:**
- Consumes all previous tasks.
- Produces a green `luna-corpus:test` Nx target and a clean git working tree.

- [ ] **Step 1: Run full test suite through Nx**

Run:

```bash
npx nx run luna-corpus:test
```

Expected: PASS.

- [ ] **Step 2: If tests fail, inspect the first failure only**

Run the same Nx command again only after fixing the first root cause. Do not batch speculative fixes.

Common expected fixes:

1. If old tests call `search_vectorstore(...)` without `knowledge_base_id`, update the test or production call to pass the current KB.
2. If `rag_graph.validate_retrieved_docs_for_knowledge_base` has trouble with SQLAlchemy row shape, use `row[0]` instead of `document.id` in the set comprehension.
3. If agent endpoint tests receive `Missing required header: X-Tenant-Id` instead of `Missing required header: X-User-Id`, keep the assertion from this plan: the context layer validates tenant/workspace/KB before user identity.
4. If Chroma `HttpClient` does not accept `headers=None`, build kwargs conditionally:

```python
    def create_client(self) -> chromadb.HttpClient:
        kwargs = {
            "host": self.settings.chroma_host,
            "port": self.settings.chroma_port,
            "ssl": self.settings.chroma_ssl,
        }
        if self.settings.chroma_auth_token:
            kwargs["headers"] = {
                "Authorization": f"Bearer {self.settings.chroma_auth_token}"
            }
        return chromadb.HttpClient(**kwargs)
```

- [ ] **Step 3: Check for unscoped vector search call sites**

Run:

```bash
grep -R "search_vectorstore(" -n apps/luna-corpus/app apps/luna-corpus/tests
```

Expected: every app call either passes `knowledge_base_id=...` or is inside `vectorstore.py` itself. Test calls without a KB should only exist in tests that assert `VectorStoreIsolationError`.

- [ ] **Step 4: Check agent routes no longer import unscoped RAG tool**

Run:

```bash
grep -R "rag_search_tool" -n apps/luna-corpus/app apps/luna-corpus/tests || true
```

Expected: no app usage of `rag_search_tool`. If the term appears only in historical comments, remove the comment or rewrite it to `create_rag_search_tool`.

- [ ] **Step 5: Run final full test suite**

Run:

```bash
npx nx run luna-corpus:test
```

Expected: PASS.

- [ ] **Step 6: Commit final cleanup if any files changed**

If Step 2, 3, or 4 required fixes, commit them:

```bash
git add apps/luna-corpus/app apps/luna-corpus/tests
git commit -m "fix(corpus): satisfy p0-m4 verification"
```

If no files changed after the previous task commit, skip this commit.

---

## Self-Review

Spec coverage:

- All `/api/v1/agent/*` endpoints protected: Task 5.
- RAG graph retrieval for non-streaming, streaming, multi-turn, multi-turn streaming: Task 3.
- Agent `rag_search` scoped retrieval: Task 4 and Task 5.
- Local/server Chroma backend initialization: Task 1 and Task 2.
- Source validation before prompt construction and response sources: Task 3.
- Operations documentation: already completed in `apps/luna-corpus/docs/vectorstore-operations.md` with the approved spec commit.
- No pgvector/Qdrant/Milvus, no collection-per-KB migration, no rebuild API/CLI: preserved in Global Constraints and task scope.

Placeholder scan: no `TBD`, `TODO`, placeholder function names, or unspecified edge handling remain in this plan.

Type consistency:

- `VectorStoreBackendType` values match config tests and factory usage.
- `create_rag_search_tool(knowledge_base_id: str) -> Tool` is produced in Task 4 and consumed in Task 5.
- `validate_retrieved_docs_for_knowledge_base(retrieved_docs, knowledge_base_id)` is produced and used within Task 3.
- `search_vectorstore(query_embedding, top_k=None, knowledge_base_id=None)` retains the compatibility signature while enforcing non-empty KB at runtime.
