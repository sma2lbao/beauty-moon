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
    engine.dispose()


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
    assert chunk.chunk_metadata is None


def test_chunk_with_metadata(db_session):
    """Test chunk with metadata."""
    doc = Document(title="Test", content="Code content")
    db_session.add(doc)
    db_session.commit()

    chunk = Chunk(
        document_id=doc.id,
        content="def hello(): pass",
        content_type=ContentType.CODE,
        chunk_metadata={"code_language": "python"},
        chunk_index=0,
    )
    db_session.add(chunk)
    db_session.commit()

    assert chunk.chunk_metadata == {"code_language": "python"}


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
