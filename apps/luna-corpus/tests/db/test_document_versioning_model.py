"""Tests for Document versioning columns and constraints."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Document, KnowledgeBase, Tenant, Workspace


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="Research", slug="research", tenant=tenant)
    kb = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    db.add(kb)
    db.commit()
    yield db, kb.id
    db.close()
    engine.dispose()


def test_document_defaults_version_one(session):
    db, kb_id = session
    doc = Document(knowledge_base_id=kb_id, title="a.md", content="hello")
    db.add(doc)
    db.commit()
    db.refresh(doc)
    assert doc.version == 1
    assert doc.content_hash is None
    assert doc.external_id is None


def test_document_external_id_unique_per_kb(session):
    db, kb_id = session
    db.add(Document(knowledge_base_id=kb_id, title="a", content="x", external_id="HR-1"))
    db.commit()
    db.add(Document(knowledge_base_id=kb_id, title="b", content="y", external_id="HR-1"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_document_null_external_id_allows_many(session):
    db, kb_id = session
    db.add(Document(knowledge_base_id=kb_id, title="a", content="x"))
    db.add(Document(knowledge_base_id=kb_id, title="b", content="y"))
    db.commit()  # two NULL external_id rows coexist
    assert db.query(Document).count() == 2