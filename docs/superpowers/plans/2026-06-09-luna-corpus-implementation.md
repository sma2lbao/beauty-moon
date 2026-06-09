# Luna-Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a RAG-based Q&A system with FastAPI, LangChain, MySQL, Chroma, and Ollama

**Architecture:** Next.js frontend + FastAPI backend with separated services. RAG flow uses LangGraph for orchestration. MySQL stores documents/chunks, Chroma stores vectors, Ollama runs Llama 3.1 locally.

**Tech Stack:** FastAPI, LangChain, LangGraph, Chroma, Ollama, MySQL (mysql-connector-python), Next.js

---

## Phase 1: Project Scaffolding

### Task 1: Create Nx Python Project

**Files:**
- Create: `apps/luna-corpus/` (via Nx generator)

- [ ] **Step 1: Generate new Nx Python project using @nxlv/python plugin**

Run: `pnpm nx generate @nxlv/python:app luna-corpus --directory apps/luna-corpus`
Expected: New project created under apps/luna-corpus

- [ ] **Step 2: Verify project structure**

Run: `ls -la apps/luna-corpus/`
Expected: Contains project.json, pyproject.toml, apps/, tests/

---

### Task 2: Configure Dependencies

**Files:**
- Modify: `apps/luna-corpus/pyproject.toml`

- [ ] **Step 1: Add all required dependencies**

```toml
[project]
name = "luna-corpus"
version = "1.0.0"
description = "RAG-based Q&A knowledge base system"
requires-python = ">=3.11,<4"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    # LangChain
    "langchain>=0.3.0",
    "langchain-core>=0.3.0",
    "langchain-community>=0.3.0",
    "langgraph>=0.2.0",
    # Vector store
    "chromadb>=0.5.0",
    # Ollama
    "langchain-ollama>=0.1.0",
    # MySQL
    "mysql-connector-python>=8.0.0",
    "sqlalchemy>=2.0.0",
    # Utilities
    "python-dotenv>=1.0.0",
    "httpx>=0.27.0",
]
```

- [ ] **Step 2: Run uv lock to update dependencies**

Run: `cd apps/luna-corpus && uv lock`
Expected: `uv.lock` updated

- [ ] **Step 3: Install dependencies**

Run: `pnpm nx install luna-corpus`
Expected: Dependencies installed

- [ ] **Step 4: Commit**

Run: `git add apps/luna-corpus && git commit -m "feat(luna-corpus): scaffold new project with dependencies"`
Expected: Commit created

---

## Phase 2: Core Configuration

### Task 3: Environment Configuration

**Files:**
- Create: `apps/luna-corpus/.env.example`
- Create: `apps/luna-corpus/app/core/config.py`

- [ ] **Step 1: Create .env.example**

```env
# Database
DATABASE_URL=mysql+mysqlconnector://user:password@localhost:3306/luna_corpus

# Chroma
CHROMA_DATA_DIR=./data/chroma

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
OLLAMA_EMBED_MODEL=nomic-embed-text

# API
API_HOST=0.0.0.0
API_PORT=8000
```

- [ ] **Step 2: Create config.py**

```python
"""Core configuration for luna-corpus."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = Field(
        default="mysql+mysqlconnector://user:password@localhost:3306/luna_corpus",
        description="MySQL database connection URL",
    )

    # Chroma
    chroma_data_dir: Path = Field(
        default=Path("./data/chroma"),
        description="Directory for Chroma vector store data",
    )

    # Ollama
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API base URL",
    )
    ollama_model: str = Field(
        default="llama3.1",
        description="Ollama model name for chat",
    )
    ollama_embed_model: str = Field(
        default="nomic-embed-text",
        description="Ollama model name for embeddings",
    )

    # API
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    # RAG
    retrieval_top_k: int = Field(default=5, description="Number of chunks to retrieve")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
```

- [ ] **Step 3: Commit**

Run: `git add apps/luna-corpus/.env.example apps/luna-corpus/app/core/config.py && git commit -m "feat(luna-corpus): add environment configuration"`
Expected: Commit created

---

### Task 4: Database Models

**Files:**
- Create: `apps/luna-corpus/app/db/models.py`
- Create: `apps/luna-corpus/app/db/database.py`
- Create: `apps/luna-corpus/app/db/__init__.py`

- [ ] **Step 1: Create models.py**

```python
"""SQLAlchemy models for documents and chunks."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import CHAR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class ContentStatus(str, enum.Enum):
    """Document processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


class ContentType(str, enum.Enum):
    """Type of content in a chunk."""

    TEXT = "text"
    TABLE = "table"
    CODE = "code"


class Document(Base):
    """Document model."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    has_tables: Mapped[bool] = mapped_column(Boolean, default=False)
    has_code: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[ContentStatus] = mapped_column(
        Enum(ContentStatus), default=ContentStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    """Chunk model for document segments."""

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[ContentType] = mapped_column(
        Enum(ContentType), default=ContentType.TEXT
    )
    metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")
```

- [ ] **Step 2: Create database.py**

```python
"""Database connection and session management."""
from collections.abc import Generator
from typing import Annotated

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Get database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 3: Create __init__.py**

```python
"""Database module."""
from app.db.database import SessionLocal, get_db, init_db
from app.db.models import Base, Chunk, ContentStatus, ContentType, Document

__all__ = [
    "Base",
    "Chunk",
    "ContentStatus",
    "ContentType",
    "Document",
    "SessionLocal",
    "get_db",
    "init_db",
]
```

- [ ] **Step 4: Write tests for models**

Create: `apps/luna-corpus/tests/db/test_models.py`

```python
"""Tests for database models."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Chunk, ContentStatus, ContentType, Document


@pytest.fixture
def db_session():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_document_creation(db_session):
    """Test creating a document."""
    doc = Document(
        title="Test Document",
        content="This is test content.",
        source="test://example",
    )
    db_session.add(doc)
    db_session.commit()

    assert doc.id is not None
    assert doc.title == "Test Document"
    assert doc.status == ContentStatus.PENDING
    assert doc.created_at is not None


def test_chunk_creation(db_session):
    """Test creating a chunk."""
    doc = Document(title="Test", content="Document content")
    db_session.add(doc)
    db_session.commit()

    chunk = Chunk(
        document_id=doc.id,
        content="This is a chunk.",
        content_type=ContentType.TEXT,
        chunk_index=0,
    )
    db_session.add(chunk)
    db_session.commit()

    assert chunk.id is not None
    assert chunk.document_id == doc.id
    assert chunk.metadata is None


def test_chunk_with_metadata(db_session):
    """Test chunk with metadata."""
    doc = Document(title="Test", content="Code content")
    db_session.add(doc)
    db_session.commit()

    chunk = Chunk(
        document_id=doc.id,
        content="def hello(): pass",
        content_type=ContentType.CODE,
        metadata={"code_language": "python"},
        chunk_index=0,
    )
    db_session.add(chunk)
    db_session.commit()

    assert chunk.metadata == {"code_language": "python"}


def test_document_chunks_relationship(db_session):
    """Test document-chunk relationship."""
    doc = Document(title="Test", content="Content with chunks")
    db_session.add(doc)
    db_session.commit()

    for i in range(3):
        chunk = Chunk(
            document_id=doc.id,
            content=f"Chunk {i}",
            chunk_index=i,
        )
        db_session.add(chunk)
    db_session.commit()

    assert len(doc.chunks) == 3
    assert doc.chunks[0].chunk_index == 0
```

- [ ] **Step 5: Run tests**

Run: `pnpm nx test luna-corpus -- --filter="test_models"`
Expected: All tests pass

- [ ] **Step 6: Commit**

Run: `git add apps/luna-corpus/app/db/ tests/db/ && git commit -m "feat(luna-corpus): add database models and connection"`
Expected: Commit created

---

## Phase 3: RAG Infrastructure

### Task 5: Chroma Vector Store Setup

**Files:**
- Create: `apps/luna-corpus/app/db/vectorstore.py`
- Create: `apps/luna-corpus/tests/db/test_vectorstore.py`

- [ ] **Step 1: Create vectorstore.py**

```python
"""Chroma vector store integration."""
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_core.documents import Document as LCDocument

from app.core.config import get_settings

settings = get_settings()


def get_vector_store() -> Chroma:
    """Get Chroma vector store instance."""
    settings.chroma_data_dir.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(
        path=str(settings.chroma_data_dir),
        settings=ChromaSettings(
            anonymized_telemetry=False,
            allow_reset=True,
        ),
    )

    return Chroma(
        client=client,
        collection_name="document_chunks",
        embedding_function=None,  # We'll provide embeddings explicitly
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
    vectorstore = get_vector_store()

    ids = [chunk["id"] for chunk in chunks]
    documents = [chunk["content"] for chunk in chunks]
    metadatas = [
        {"chunk_id": chunk["id"], "document_id": chunk["document_id"]}
        for chunk in chunks
    ]

    vectorstore.add_texts(
        texts=documents,
        ids=ids,
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

    vectorstore = get_vector_store()

    results = vectorstore.similarity_search_by_vector(
        embedding=query_embedding,
        k=top_k,
    )

    return [
        {
            "chunk_id": result.metadata.get("chunk_id"),
            "document_id": result.metadata.get("document_id"),
            "content": result.page_content,
            "score": result.metadata.get("score", 0.0),
        }
        for result in results
    ]


def delete_chunks_from_vectorstore(chunk_ids: list[str]) -> None:
    """Delete chunks from vector store.

    Args:
        chunk_ids: List of chunk IDs to delete
    """
    vectorstore = get_vector_store()
    vectorstore.delete(ids=chunk_ids)
```

- [ ] **Step 2: Write tests for vectorstore**

Create: `apps/luna-corpus/tests/db/test_vectorstore.py`

```python
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
        {"id": "chunk-1", "document_id": "doc-1", "content": "First chunk"},
        {"id": "chunk-2", "document_id": "doc-1", "content": "Second chunk"},
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
        {"id": "chunk-1", "document_id": "doc-1", "content": "Python code"},
        {"id": "chunk-2", "document_id": "doc-2", "content": "JavaScript code"},
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
        {"id": "chunk-1", "document_id": "doc-1", "content": "To delete"},
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
```

- [ ] **Step 3: Run tests**

Run: `pnpm nx test luna-corpus -- --filter="test_vectorstore"`
Expected: All tests pass

- [ ] **Step 4: Commit**

Run: `git add apps/luna-corpus/app/db/vectorstore.py tests/db/test_vectorstore.py && git commit -m "feat(luna-corpus): add Chroma vector store integration"`
Expected: Commit created

---

### Task 6: Ollama Integration

**Files:**
- Create: `apps/luna-corpus/app/services/llm.py`
- Create: `apps/luna-corpus/tests/services/test_llm.py`

- [ ] **Step 1: Create llm.py**

```python
"""Ollama LLM and embeddings integration."""
from typing import Any

from langchain_ollama import ChatOllama, OllamaEmbeddings

from app.core.config import get_settings

settings = get_settings()


def get_chat_model() -> ChatOllama:
    """Get Ollama chat model instance."""
    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        temperature=0.7,
        stream=False,
    )


def get_embeddings_model() -> OllamaEmbeddings:
    """Get Ollama embeddings model instance."""
    return OllamaEmbeddings(
        base_url=settings.ollama_base_url,
        model=settings.ollama_embed_model,
    )


def embed_text(text: str) -> list[float]:
    """Generate embedding for a single text.

    Args:
        text: Text to embed

    Returns:
        Embedding vector
    """
    embeddings = get_embeddings_model()
    return embeddings.embed_query(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts.

    Args:
        texts: List of texts to embed

    Returns:
        List of embedding vectors
    """
    embeddings = get_embeddings_model()
    return embeddings.embed_documents(texts)


def generate_response(prompt: str, context: str | None = None) -> str:
    """Generate response from LLM.

    Args:
        prompt: User prompt
        context: Optional context to prepend

    Returns:
        Generated response
    """
    chat = get_chat_model()

    if context:
        full_prompt = f"""Based on the following context, answer the question.

Context:
{context}

Question: {prompt}

Answer:"""
    else:
        full_prompt = prompt

    response = chat.invoke(full_prompt)
    return response.content if hasattr(response, "content") else str(response)


def check_ollama_health() -> bool:
    """Check if Ollama service is healthy.

    Returns:
        True if Ollama is accessible
    """
    try:
        import httpx

        response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5)
        return response.status_code == 200
    except Exception:
        return False
```

- [ ] **Step 2: Write tests for llm**

Create: `apps/luna-corpus/tests/services/test_llm.py`

```python
"""Tests for Ollama integration."""
from unittest.mock import MagicMock, patch

import pytest


def test_embed_text():
    """Test embedding a single text."""
    from app.services import llm

    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

    with patch.object(llm, "get_embeddings_model", return_value=mock_embeddings):
        result = llm.embed_text("test text")
        assert result == [0.1, 0.2, 0.3]


def test_embed_texts():
    """Test embedding multiple texts."""
    from app.services import llm

    mock_embeddings = MagicMock()
    mock_embeddings.embed_documents.return_value = [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ]

    with patch.object(llm, "get_embeddings_model", return_value=mock_embeddings):
        result = llm.embed_texts(["text1", "text2"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]


def test_generate_response_with_context():
    """Test generating response with context."""
    from app.services import llm

    mock_response = MagicMock()
    mock_response.content = "Test response"

    mock_chat = MagicMock()
    mock_chat.invoke.return_value = mock_response

    with patch.object(llm, "get_chat_model", return_value=mock_chat):
        result = llm.generate_response(
            prompt="What is Python?",
            context="Python is a programming language.",
        )

        assert result == "Test response"
        # Verify the prompt includes context
        call_args = mock_chat.invoke.call_args[0][0]
        assert "Context:" in call_args
        assert "Python is a programming language" in call_args


def test_check_ollama_health_success():
    """Test Ollama health check when healthy."""
    from app.services import llm

    with patch("httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = llm.check_ollama_health()
        assert result is True


def test_check_ollama_health_failure():
    """Test Ollama health check when unreachable."""
    from app.services import llm

    with patch("httpx.get") as mock_get:
        mock_get.side_effect = Exception("Connection refused")

        result = llm.check_ollama_health()
        assert result is False
```

- [ ] **Step 3: Run tests**

Run: `pnpm nx test luna-corpus -- --filter="test_llm"`
Expected: All tests pass

- [ ] **Step 4: Commit**

Run: `git add apps/luna-corpus/app/services/llm.py tests/services/test_llm.py && git commit -m "feat(luna-corpus): add Ollama integration"`
Expected: Commit created

---

## Phase 4: RAG Flow with LangGraph

### Task 7: Document Processing Service

**Files:**
- Create: `apps/luna-corpus/app/services/document_processor.py`
- Create: `apps/luna-corpus/tests/services/test_document_processor.py`

- [ ] **Step 1: Create document_processor.py**

```python
"""Document processing service for chunking and vectorization."""
from typing import Any

from langchain_core.documents import Document as LCDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from app.db.models import Chunk, ContentStatus, ContentType, Document
from app.db.vectorstore import add_chunks_to_vectorstore, delete_chunks_from_vectorstore
from app.services.llm import embed_texts


class DocumentProcessor:
    """Processes documents: chunking and vectorization."""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        """Initialize processor.

        Args:
            chunk_size: Target size for each chunk in characters
            chunk_overlap: Overlap between chunks in characters
        """
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""],
        )

    def detect_content_type(self, content: str) -> ContentType:
        """Detect the type of content.

        Args:
            content: Text content to analyze

        Returns:
            ContentType enum value
        """
        if "```" in content or "def " in content or "class " in content:
            return ContentType.CODE
        if "|" in content and ("---" in content or "--:" in content):
            return ContentType.TABLE
        return ContentType.TEXT

    def split_document(self, document: Document) -> list[dict[str, Any]]:
        """Split document into chunks.

        Args:
            document: Document to split

        Returns:
            List of chunk dictionaries
        """
        langchain_doc = LCDocument(
            page_content=document.content,
            metadata={"document_id": document.id},
        )

        splits = self.text_splitter.split_documents([langchain_doc])

        chunks = []
        for i, split in enumerate(splits):
            chunks.append({
                "document_id": document.id,
                "content": split.page_content,
                "content_type": self.detect_content_type(split.page_content),
                "metadata": None,
                "chunk_index": i,
            })

        return chunks

    def process_document(self, db: Session, document_id: str) -> list[Chunk]:
        """Process a document: create chunks and store vectors.

        Args:
            db: Database session
            document_id: ID of document to process

        Returns:
            List of created chunks
        """
        # Get document
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise ValueError(f"Document {document_id} not found")

        # Update status
        document.status = ContentStatus.PROCESSING
        db.commit()

        try:
            # Split into chunks
            chunk_dicts = self.split_document(document)

            # Delete existing chunks if any
            existing_chunks = (
                db.query(Chunk).filter(Chunk.document_id == document_id).all()
            )
            if existing_chunks:
                delete_chunks_from_vectorstore([c.id for c in existing_chunks])
                for chunk in existing_chunks:
                    db.delete(chunk)
                db.commit()

            # Create new chunks
            chunks = []
            for chunk_dict in chunk_dicts:
                chunk = Chunk(**chunk_dict)
                db.add(chunk)
                chunks.append(chunk)
            db.commit()

            # Generate embeddings and store in vector store
            texts = [c["content"] for c in chunk_dicts]
            embeddings = embed_texts(texts)

            add_chunks_to_vectorstore(
                chunks=[
                    {"id": c.id, "document_id": c.document_id, "content": c.content}
                    for c in chunks
                ],
                embeddings=embeddings,
            )

            # Update status
            document.status = ContentStatus.COMPLETED
            db.commit()

            return chunks

        except Exception as e:
            document.status = ContentStatus.ERROR
            db.commit()
            raise e
```

- [ ] **Step 2: Write tests**

Create: `apps/luna-corpus/tests/services/test_document_processor.py`

```python
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
```

- [ ] **Step 3: Run tests**

Run: `pnpm nx test luna-corpus -- --filter="test_document_processor"`
Expected: All tests pass

- [ ] **Step 4: Commit**

Run: `git add apps/luna-corpus/app/services/document_processor.py tests/services/test_document_processor.py && git commit -m "feat(luna-corpus): add document processing service"`
Expected: Commit created

---

### Task 8: LangGraph RAG Flow

**Files:**
- Create: `apps/luna-corpus/app/graph/rag_graph.py`
- Create: `apps/luna-corpus/app/graph/state.py`
- Create: `apps/luna-corpus/tests/graph/test_rag_graph.py`

- [ ] **Step 1: Create state.py**

```python
"""LangGraph state definitions."""
from typing import Annotated

from langgraph.graph import add_messages
from typing_extensions import TypedDict


class RAGState(TypedDict):
    """State for RAG question-answering graph."""

    question: str
    retrieved_docs: Annotated[list[dict], add_messages]
    answer: str | None
    sources: list[dict]
    processing_time_ms: int | None


class DocumentProcessingState(TypedDict):
    """State for document processing graph."""

    document_id: str
    status: str
    chunks_created: int
    error: str | None
```

- [ ] **Step 2: Create rag_graph.py**

```python
"""LangGraph RAG flow for question answering."""
import time
from typing import Any

from langgraph.graph import END, StateGraph

from app.core.config import get_settings
from app.db.vectorstore import search_vectorstore
from app.graph.state import RAGState
from app.services.llm import embed_text, generate_response

settings = get_settings()


def retrieve_node(state: RAGState) -> dict[str, Any]:
    """Retrieve relevant documents from vector store.

    Args:
        state: Current RAG state

    Returns:
        Updated state with retrieved documents
    """
    question = state["question"]

    # Generate query embedding
    query_embedding = embed_text(question)

    # Search vector store
    results = search_vectorstore(
        query_embedding=query_embedding,
        top_k=settings.retrieval_top_k,
    )

    # Format retrieved docs
    retrieved_docs = []
    for result in results:
        retrieved_docs.append({
            "chunk_id": result["chunk_id"],
            "document_id": result["document_id"],
            "content": result["content"],
            "score": result.get("score", 0.0),
        })

    return {"retrieved_docs": retrieved_docs}


def generate_node(state: RAGState) -> dict[str, Any]:
    """Generate answer from retrieved documents.

    Args:
        state: Current RAG state

    Returns:
        Updated state with generated answer
    """
    question = state["question"]
    retrieved_docs = state["retrieved_docs"]

    if not retrieved_docs:
        return {
            "answer": "I couldn't find any relevant information to answer your question.",
            "sources": [],
        }

    # Build context from retrieved docs
    context_parts = []
    for i, doc in enumerate(retrieved_docs):
        context_parts.append(f"[Source {i+1}]\n{doc['content']}")

    context = "\n\n".join(context_parts)

    # Generate response
    answer = generate_response(prompt=question, context=context)

    # Format sources
    sources = [
        {
            "document_id": doc["document_id"],
            "chunk_content": doc["content"][:200] + "..."
            if len(doc["content"]) > 200
            else doc["content"],
            "relevance_score": doc["score"],
        }
        for doc in retrieved_docs
    ]

    return {"answer": answer, "sources": sources}


def create_rag_graph() -> StateGraph:
    """Create the RAG question-answering graph.

    Returns:
        Compiled LangGraph for RAG
    """
    workflow = StateGraph(RAGState)

    # Add nodes
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("generate", generate_node)

    # Set entry point
    workflow.set_entry_point("retrieve")

    # Add edges
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", END)

    return workflow.compile()


# Singleton graph instance
_rag_graph = None


def get_rag_graph() -> StateGraph:
    """Get cached RAG graph instance."""
    global _rag_graph
    if _rag_graph is None:
        _rag_graph = create_rag_graph()
    return _rag_graph


def answer_question(question: str) -> dict[str, Any]:
    """Answer a question using RAG.

    Args:
        question: User question

    Returns:
        Answer with sources and metadata
    """
    start_time = time.time()

    graph = get_rag_graph()
    result = graph.invoke({"question": question, "retrieved_docs": []})

    processing_time_ms = int((time.time() - start_time) * 1000)

    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "processing_time_ms": processing_time_ms,
    }
```

- [ ] **Step 3: Write tests**

Create: `apps/luna-corpus/tests/graph/test_rag_graph.py`

```python
"""Tests for LangGraph RAG flow."""
from unittest.mock import MagicMock, patch

import pytest


def test_retrieve_node():
    """Test retrieve node."""
    from app.graph.rag_graph import retrieve_node
    from app.graph.state import RAGState

    mock_embedding = [0.1, 0.2, 0.3]
    mock_results = [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "content": "Test content",
            "score": 0.95,
        }
    ]

    with patch("app.graph.rag_graph.embed_text", return_value=mock_embedding):
        with patch(
            "app.graph.rag_graph.search_vectorstore", return_value=mock_results
        ):
            state = RAGState(question="test question", retrieved_docs=[], answer=None, sources=[], processing_time_ms=None)
            result = retrieve_node(state)

            assert "retrieved_docs" in result
            assert len(result["retrieved_docs"]) == 1


def test_generate_node():
    """Test generate node."""
    from app.graph.rag_graph import generate_node
    from app.graph.state import RAGState

    state = RAGState(
        question="What is Python?",
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
    )

    with patch(
        "app.graph.rag_graph.generate_response", return_value="Python is great!"
    ):
        result = generate_node(state)

        assert "answer" in result
        assert result["answer"] == "Python is great!"
        assert "sources" in result


def test_answer_question():
    """Test full RAG question answering."""
    from app.graph.rag_graph import answer_question

    mock_embedding = [0.1, 0.2, 0.3]
    mock_results = [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "content": "Test content",
            "score": 0.95,
        }
    ]

    with patch("app.graph.rag_graph.embed_text", return_value=mock_embedding):
        with patch(
            "app.graph.rag_graph.search_vectorstore", return_value=mock_results
        ):
            with patch(
                "app.graph.rag_graph.generate_response",
                return_value="Test answer",
            ):
                result = answer_question("Test question")

                assert "answer" in result
                assert "sources" in result
                assert "processing_time_ms" in result


def test_answer_question_no_results():
    """Test answering when no documents found."""
    from app.graph.rag_graph import answer_question

    with patch("app.graph.rag_graph.embed_text", return_value=[0.1, 0.2]):
        with patch("app.graph.rag_graph.search_vectorstore", return_value=[]):
            result = answer_question("Test question")

            assert "I couldn't find" in result["answer"]
            assert result["sources"] == []
```

- [ ] **Step 4: Run tests**

Run: `pnpm nx test luna-corpus -- --filter="test_rag_graph"`
Expected: All tests pass

- [ ] **Step 5: Commit**

Run: `git add apps/luna-corpus/app/graph/ tests/graph/ && git commit -m "feat(luna-corpus): add LangGraph RAG flow"`
Expected: Commit created

---

## Phase 5: API Endpoints

### Task 9: FastAPI Application

**Files:**
- Create: `apps/luna-corpus/app/api/__init__.py`
- Create: `apps/luna-corpus/app/api/routes.py`
- Create: `apps/luna-corpus/app/main.py`

- [ ] **Step 1: Create routes.py**

```python
"""API routes for luna-corpus."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Chunk, ContentStatus, Document
from app.graph.rag_graph import answer_question
from app.services.document_processor import DocumentProcessor

router = APIRouter(prefix="/api/v1", tags=["qa"])


# Request/Response Models
class QuestionRequest(BaseModel):
    """Question request model."""

    question: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class SourceResponse(BaseModel):
    """Source reference model."""

    document_id: str
    document_title: str | None = None
    chunk_content: str
    relevance_score: float


class AnswerResponse(BaseModel):
    """Answer response model."""

    answer: str
    sources: list[SourceResponse]
    processing_time_ms: int


class DocumentCreate(BaseModel):
    """Document creation model."""

    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    source: str | None = None


class DocumentResponse(BaseModel):
    """Document response model."""

    id: str
    title: str
    source: str | None
    content: str
    has_tables: bool
    has_code: bool
    status: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """Document list response."""

    documents: list[DocumentResponse]
    total: int


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    mysql: str
    chroma: str
    ollama: str


class ProcessResponse(BaseModel):
    """Document processing response."""

    status: str
    chunks_created: int


# Question Answering
@router.post("/qa/query", response_model=AnswerResponse)
async def query(question_req: QuestionRequest) -> AnswerResponse:
    """Answer a question using RAG.

    Args:
        question_req: Question request

    Returns:
        Answer with sources
    """
    result = answer_question(question_req.question)

    # Enrich sources with document titles
    enriched_sources = []
    for source in result["sources"]:
        enriched_sources.append(
            SourceResponse(
                document_id=source["document_id"],
                chunk_content=source["chunk_content"],
                relevance_score=source["relevance_score"],
            )
        )

    return AnswerResponse(
        answer=result["answer"],
        sources=enriched_sources,
        processing_time_ms=result["processing_time_ms"],
    )


# Document Management
@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    doc: DocumentCreate,
    db: Annotated[Session, Depends(get_db)],
) -> DocumentResponse:
    """Create a new document.

    Args:
        doc: Document to create
        db: Database session

    Returns:
        Created document
    """
    db_doc = Document(
        title=doc.title,
        content=doc.content,
        source=doc.source,
        has_tables="|" in doc.content and "---" in doc.content,
        has_code="```" in doc.content or "def " in doc.content,
    )
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    return DocumentResponse(
        id=db_doc.id,
        title=db_doc.title,
        source=db_doc.source,
        content=db_doc.content,
        has_tables=db_doc.has_tables,
        has_code=db_doc.has_code,
        status=db_doc.status.value,
        created_at=db_doc.created_at.isoformat(),
        updated_at=db_doc.updated_at.isoformat(),
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    db: Annotated[Session, Depends(get_db)],
    status_filter: ContentStatus | None = None,
) -> DocumentListResponse:
    """List all documents.

    Args:
        db: Database session
        status_filter: Optional status filter

    Returns:
        List of documents
    """
    query = db.query(Document)

    if status_filter:
        query = query.filter(Document.status == status_filter)

    documents = query.order_by(Document.created_at.desc()).all()

    return DocumentListResponse(
        documents=[
            DocumentResponse(
                id=doc.id,
                title=doc.title,
                source=doc.source,
                content=doc.content,
                has_tables=doc.has_tables,
                has_code=doc.has_code,
                status=doc.status.value,
                created_at=doc.created_at.isoformat(),
                updated_at=doc.updated_at.isoformat(),
            )
            for doc in documents
        ],
        total=len(documents),
    )


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> DocumentResponse:
    """Get a document by ID.

    Args:
        document_id: Document ID
        db: Database session

    Returns:
        Document
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentResponse(
        id=doc.id,
        title=doc.title,
        source=doc.source,
        content=doc.content,
        has_tables=doc.has_tables,
        has_code=doc.has_code,
        status=doc.status.value,
        created_at=doc.created_at.isoformat(),
        updated_at=doc.updated_at.isoformat(),
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Delete a document.

    Args:
        document_id: Document ID
        db: Database session
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    db.delete(doc)
    db.commit()


@router.post("/documents/{document_id}/process", response_model=ProcessResponse)
async def process_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> ProcessResponse:
    """Process a document: chunk and vectorize.

    Args:
        document_id: Document ID
        db: Database session

    Returns:
        Processing result
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    processor = DocumentProcessor()
    chunks = processor.process_document(db, document_id)

    return ProcessResponse(
        status="completed",
        chunks_created=len(chunks),
    )


# Health Check
@router.get("/health", response_model=HealthResponse)
async def health_check(db: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    """Check system health.

    Args:
        db: Database session

    Returns:
        Health status
    """
    from app.db.vectorstore import get_vector_store
    from app.services.llm import check_ollama_health

    # Check MySQL
    mysql_status = "connected"
    try:
        db.execute("SELECT 1")
    except Exception:
        mysql_status = "error"

    # Check Chroma
    chroma_status = "connected"
    try:
        get_vector_store()
    except Exception:
        chroma_status = "error"

    # Check Ollama
    ollama_status = "connected" if check_ollama_health() else "disconnected"

    overall_status = "ok"
    if mysql_status != "connected" or chroma_status != "connected":
        overall_status = "degraded"

    return HealthResponse(
        status=overall_status,
        mysql=mysql_status,
        chroma=chroma_status,
        ollama=ollama_status,
    )
```

- [ ] **Step 2: Create main.py**

```python
"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.db.database import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    init_db()
    yield
    # Shutdown


app = FastAPI(
    title="Luna-Corpus API",
    description="RAG-based Q&A Knowledge Base System",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Luna-Corpus API", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
```

- [ ] **Step 3: Update __init__.py files**

Create: `apps/luna-corpus/app/__init__.py`
```python
"""Luna-Corpus application."""
```

Create: `apps/luna-corpus/app/api/__init__.py`
```python
"""API module."""
from app.api.routes import router

__all__ = ["router"]
```

Create: `apps/luna-corpus/app/services/__init__.py`
```python
"""Services module."""
```

Create: `apps/luna-corpus/app/graph/__init__.py`
```python
"""Graph module."""
```

Create: `apps/luna-corpus/app/core/__init__.py`
```python
"""Core module."""
```

- [ ] **Step 4: Add run target to project.json**

Modify: `apps/luna-corpus/project.json`

Add under targets:
```json
"serve": {
  "executor": "nx:run-commands",
  "options": {
    "command": "uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload",
    "cwd": "{projectRoot}"
  }
}
```

- [ ] **Step 5: Commit**

Run: `git add apps/luna-corpus/app/ apps/luna-corpus/project.json && git commit -m "feat(luna-corpus): add FastAPI application and routes"`
Expected: Commit created

---

## Phase 6: Final Integration

### Task 10: Update Project Configuration

**Files:**
- Modify: `apps/luna-corpus/pyproject.toml`
- Modify: `apps/luna-corpus/project.json`

- [ ] **Step 1: Update pyproject.toml with proper build config**

```toml
[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.hatch.metadata]
allow-direct-references = true
```

- [ ] **Step 2: Commit**

Run: `git add apps/luna-corpus/pyproject.toml && git commit -m "chore(luna-corpus): update project configuration"`
Expected: Commit created

---

### Task 11: End-to-End Test

**Files:**
- Create: `apps/luna-corpus/tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
"""End-to-end integration tests."""
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_all_services():
    """Mock all external services."""
    with patch("app.db.database.engine") as mock_engine, \
         patch("app.db.vectorstore.get_vector_store") as mock_chroma, \
         patch("app.services.llm.get_embeddings_model") as mock_embed, \
         patch("app.services.llm.get_chat_model") as mock_chat:

        mock_engine.return_value = MagicMock()
        mock_chroma.return_value = MagicMock()

        yield {
            "engine": mock_engine,
            "chroma": mock_chroma,
            "embed": mock_embed,
            "chat": mock_chat,
        }


def test_api_routes_import():
    """Test that API routes can be imported."""
    from app.api.routes import router

    assert router is not None
    assert len(router.routes) > 0


def test_main_app_import():
    """Test that main app can be imported."""
    from app.main import app

    assert app is not None
    assert app.title == "Luna-Corpus API"


def test_config_settings():
    """Test configuration loading."""
    from app.core.config import Settings

    settings = Settings()
    assert settings.ollama_model == "llama3.1"
    assert settings.ollama_embed_model == "nomic-embed-text"
    assert settings.retrieval_top_k == 5
```

- [ ] **Step 2: Run all tests**

Run: `pnpm nx test luna-corpus`
Expected: All tests pass

- [ ] **Step 3: Final commit**

Run: `git add apps/luna-corpus/tests/ && git commit -m "test(luna-corpus): add integration tests"`
Expected: Commit created

---

## Summary

| Task | Description |
|------|-------------|
| 1 | Create Nx Python project |
| 2 | Configure dependencies |
| 3 | Environment configuration |
| 4 | Database models |
| 5 | Chroma vector store |
| 6 | Ollama integration |
| 7 | Document processing service |
| 8 | LangGraph RAG flow |
| 9 | FastAPI routes |
| 10 | Project configuration |
| 11 | Integration tests |

---

**Next Steps After Implementation:**
1. Create `.env` file with your MySQL/Chroma/Ollama settings
2. Ensure Ollama is running with `llama3.1` and `nomic-embed-text` models
3. Create MySQL database `luna_corpus`
4. Run `pnpm nx serve luna-corpus` to start the API
5. Create Next.js frontend (separate implementation plan)

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-09-luna-corpus-implementation.md`**

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
