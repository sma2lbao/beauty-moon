"""Tests for database models."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    Chunk,
    ContentStatus,
    ContentType,
    Conversation,
    Document,
    KnowledgeBase,
    Permission,
    Role,
    Tenant,
    User,
    Workspace,
    WorkspaceMembership,
)


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
    _, _, knowledge_base = create_knowledge_base(db_session)
    doc = Document(
        title="Test Document",
        content="This is test content.",
        source="test://example",
        knowledge_base_id=knowledge_base.id,
    )
    db_session.add(doc)
    db_session.commit()

    assert doc.id is not None
    assert doc.title == "Test Document"
    assert doc.status == ContentStatus.PENDING
    assert doc.created_at is not None


def test_chunk_creation(db_session):
    """Test creating a chunk."""
    _, _, knowledge_base = create_knowledge_base(db_session)
    doc = Document(
        title="Test", content="Document content", knowledge_base_id=knowledge_base.id
    )
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
    _, _, knowledge_base = create_knowledge_base(db_session)
    doc = Document(
        title="Test", content="Code content", knowledge_base_id=knowledge_base.id
    )
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
    _, _, knowledge_base = create_knowledge_base(db_session)
    doc = Document(
        title="Test", content="Content with chunks", knowledge_base_id=knowledge_base.id
    )
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


def create_knowledge_base(db_session):
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="Research", slug="research", tenant=tenant)
    knowledge_base = KnowledgeBase(
        name="Docs",
        slug="docs",
        description="Product documentation",
        workspace=workspace,
    )
    db_session.add(knowledge_base)
    db_session.commit()
    return tenant, workspace, knowledge_base


def test_tenant_workspace_knowledge_base_hierarchy(db_session):
    tenant, workspace, knowledge_base = create_knowledge_base(db_session)

    assert tenant.id is not None
    assert workspace.tenant_id == tenant.id
    assert knowledge_base.workspace_id == workspace.id
    assert tenant.workspaces == [workspace]
    assert workspace.knowledge_bases == [knowledge_base]


def test_workspace_slug_unique_per_tenant(db_session):
    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()

    db_session.add_all(
        [
            Workspace(name="One", slug="docs", tenant_id=tenant.id),
            Workspace(name="Two", slug="docs", tenant_id=tenant.id),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_knowledge_base_slug_unique_per_workspace(db_session):
    tenant, workspace, _ = create_knowledge_base(db_session)

    db_session.add_all(
        [
            KnowledgeBase(name="One", slug="duplicate", workspace_id=workspace.id),
            KnowledgeBase(name="Two", slug="duplicate", workspace_id=workspace.id),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_document_belongs_to_knowledge_base(db_session):
    _, _, knowledge_base = create_knowledge_base(db_session)

    doc = Document(
        title="Scoped Document",
        content="Scoped content",
        knowledge_base_id=knowledge_base.id,
    )
    db_session.add(doc)
    db_session.commit()

    assert doc.knowledge_base_id == knowledge_base.id
    assert doc.knowledge_base == knowledge_base
    assert knowledge_base.documents == [doc]


def test_conversation_belongs_to_knowledge_base(db_session):
    _, _, knowledge_base = create_knowledge_base(db_session)

    conversation = Conversation(
        title="Scoped Conversation",
        knowledge_base_id=knowledge_base.id,
    )
    db_session.add(conversation)
    db_session.commit()

    assert conversation.knowledge_base_id == knowledge_base.id
    assert conversation.knowledge_base == knowledge_base
    assert knowledge_base.conversations == [conversation]


def test_user_email_is_unique(db_session):
    db_session.add_all([
        User(email="owner@example.com", display_name="Owner"),
        User(email="owner@example.com", display_name="Duplicate"),
    ])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_workspace_membership_is_unique_per_user_and_workspace(db_session):
    _, workspace, _ = create_knowledge_base(db_session)
    user = User(email="member@example.com", display_name="Member")
    db_session.add(user)
    db_session.commit()

    db_session.add_all([
        WorkspaceMembership(user_id=user.id, workspace_id=workspace.id),
        WorkspaceMembership(user_id=user.id, workspace_id=workspace.id),
    ])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_workspace_membership_relationships(db_session):
    _, workspace, _ = create_knowledge_base(db_session)
    user = User(email="member@example.com", display_name="Member")
    membership = WorkspaceMembership(user=user, workspace=workspace)
    db_session.add(membership)
    db_session.commit()

    assert membership.id is not None
    assert membership.is_active is True
    assert membership.user == user
    assert membership.workspace == workspace
    assert user.workspace_memberships == [membership]
    assert workspace.memberships == [membership]


def test_role_slug_is_unique(db_session):
    db_session.add_all([
        Role(name="Reader", slug="kb_reader", is_system=True),
        Role(name="Duplicate Reader", slug="kb_reader", is_system=True),
    ])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_permission_slug_is_unique(db_session):
    db_session.add_all([
        Permission(name="Document Read", slug="document:read"),
        Permission(name="Duplicate Document Read", slug="document:read"),
    ])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_role_permission_relationship(db_session):
    permission = Permission(name="Document Read", slug="document:read")
    role = Role(
        name="Knowledge Base Reader",
        slug="kb_reader",
        description="Read knowledge-base content",
        is_system=True,
        permissions=[permission],
    )
    db_session.add(role)
    db_session.commit()

    assert role.id is not None
    assert role.permissions == [permission]
    assert permission.roles == [role]


def test_workspace_membership_role_relationship(db_session):
    _, workspace, _ = create_knowledge_base(db_session)
    user = User(email="member@example.com", display_name="Member")
    role = Role(name="Editor", slug="kb_editor", is_system=True)
    membership = WorkspaceMembership(user=user, workspace=workspace, roles=[role])
    db_session.add(membership)
    db_session.commit()

    assert membership.roles == [role]
    assert role.workspace_memberships == [membership]
