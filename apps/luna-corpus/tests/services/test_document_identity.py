"""Tests for document identity resolution and content hashing."""
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Document, KnowledgeBase, Tenant, Workspace
from app.services.document_identity import (
    ChangeType,
    compute_content_hash,
    resolve_document_identity,
)


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
    workspace = Workspace(name="R", slug="r", tenant=tenant)
    kb = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    db.add(kb)
    db.commit()
    yield db, kb.id
    db.close()
    engine.dispose()


def test_compute_content_hash_stable_and_sensitive():
    assert compute_content_hash("hello") == compute_content_hash("hello")
    assert compute_content_hash("hello") != compute_content_hash("hello!")
    assert len(compute_content_hash("x")) == 64


def test_change_type_values():
    assert ChangeType.CREATED.value == "created"
    assert ChangeType.UPDATED.value == "updated"
    assert ChangeType.UNCHANGED.value == "unchanged"


def test_resolve_returns_none_when_no_match(session):
    db, kb_id = session
    assert resolve_document_identity(db, kb_id, original_name="missing.md") is None


def test_resolve_by_external_id_takes_priority(session):
    db, kb_id = session
    by_name = Document(knowledge_base_id=kb_id, title="doc.md", content="a")
    by_ext = Document(
        knowledge_base_id=kb_id, title="other.md", content="b", external_id="HR-1"
    )
    db.add_all([by_name, by_ext])
    db.commit()
    hit = resolve_document_identity(
        db, kb_id, external_id="HR-1", original_name="doc.md"
    )
    assert hit.id == by_ext.id


def test_resolve_by_original_name_when_no_external_id(session):
    db, kb_id = session
    doc = Document(knowledge_base_id=kb_id, title="doc.md", content="a")
    db.add(doc)
    db.commit()
    hit = resolve_document_identity(db, kb_id, original_name="doc.md")
    assert hit.id == doc.id


def test_resolve_by_name_picks_latest_updated(session):
    db, kb_id = session
    old = Document(knowledge_base_id=kb_id, title="dup.md", content="old")
    db.add(old)
    db.commit()
    time.sleep(1.1)  # SQLite func.now() 仅秒级精度，需确保时间戳跨秒
    new = Document(knowledge_base_id=kb_id, title="dup.md", content="new")
    db.add(new)
    db.commit()
    time.sleep(1.1)
    new.content = "touched"
    db.commit()  # bumps updated_at
    hit = resolve_document_identity(db, kb_id, original_name="dup.md")
    assert hit.id == new.id


def test_resolve_scoped_to_kb(session):
    db, kb_id = session
    other_kb = KnowledgeBase(
        name="Other", slug="other", workspace_id=db.query(KnowledgeBase).first().workspace_id
    )
    db.add(other_kb)
    db.commit()
    db.add(Document(knowledge_base_id=other_kb.id, title="doc.md", content="a"))
    db.commit()
    assert resolve_document_identity(db, kb_id, original_name="doc.md") is None