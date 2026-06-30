"""Tests for knowledge-base scoped document APIs."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
    engine, Session, _ = app_db

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
            permission = (
                session.query(Permission).filter(Permission.slug == slug).first()
            )
            if not permission:
                permission = Permission(name=slug, slug=slug, description=slug)
            permissions.append(permission)
        role = Role(name=label, slug=label, is_system=True, permissions=permissions)
        membership = WorkspaceMembership(
            user=user, workspace_id=workspace_id, roles=[role]
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


def test_create_document_requires_user_context(client):
    response = client.post(
        "/api/v1/documents",
        json={"title": "Doc", "content": "Content"},
    )

    assert response.status_code == 400
    assert "X-Tenant-Id" in response.json()["detail"]


def test_document_create_and_list_are_scoped_to_knowledge_base(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "document_editor",
        [
            PermissionSlug.DOCUMENT_READ,
            PermissionSlug.DOCUMENT_WRITE,
            PermissionSlug.DOCUMENT_DELETE,
        ],
    )

    created = client.post(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"], user_id),
        json={"title": "Doc One", "content": "Content one"},
    )

    assert created.status_code == 201
    document = created.json()
    assert document["title"] == "Doc One"

    kb_one_list = client.get(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"], user_id),
    )
    kb_two_list = client.get(
        "/api/v1/documents",
        headers=headers(context, context["kb_two_id"], user_id),
    )

    assert kb_one_list.status_code == 200
    assert kb_one_list.json()["total"] == 1
    assert kb_one_list.json()["documents"][0]["id"] == document["id"]
    assert kb_two_list.status_code == 200
    assert kb_two_list.json()["total"] == 0


def test_document_reader_cannot_create_or_delete_documents(client, app_db):
    _, Session, context = app_db
    reader_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "document_reader",
        [PermissionSlug.DOCUMENT_READ],
    )
    editor_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "document_editor_for_reader_test",
        [
            PermissionSlug.DOCUMENT_READ,
            PermissionSlug.DOCUMENT_WRITE,
            PermissionSlug.DOCUMENT_DELETE,
        ],
    )
    created = client.post(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"], editor_id),
        json={"title": "Doc One", "content": "Content one"},
    ).json()

    create_response = client.post(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"], reader_id),
        json={"title": "Forbidden", "content": "Nope"},
    )
    delete_response = client.delete(
        f"/api/v1/documents/{created['id']}",
        headers=headers(context, context["kb_one_id"], reader_id),
    )

    assert create_response.status_code == 403
    assert (
        create_response.json()["detail"]
        == "Missing required permission: document:write"
    )
    assert delete_response.status_code == 403
    assert (
        delete_response.json()["detail"]
        == "Missing required permission: document:delete"
    )


@patch("app.services.document_processor.DocumentProcessor")
@patch("app.api.routes.SessionLocal")
def test_document_write_permission_allows_processing(
    mock_session_local, mock_processor, client, app_db
):
    _, Session, context = app_db
    # Make the background indexing task inert: it opens a real SessionLocal and
    # runs DocumentProcessor, neither of which is wired to the SQLite test DB.
    mock_processor.return_value.process_document.return_value = None

    editor_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "document_processor",
        [PermissionSlug.DOCUMENT_READ, PermissionSlug.DOCUMENT_WRITE],
    )
    created = client.post(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"], editor_id),
        json={"title": "Doc One", "content": "Content one"},
    ).json()

    response = client.post(
        f"/api/v1/documents/{created['id']}/process",
        headers=headers(context, context["kb_one_id"], editor_id),
    )

    assert response.status_code == 200


def test_document_detail_delete_and_process_reject_cross_knowledge_base(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "document_admin",
        [
            PermissionSlug.DOCUMENT_READ,
            PermissionSlug.DOCUMENT_WRITE,
            PermissionSlug.DOCUMENT_DELETE,
        ],
    )
    created = client.post(
        "/api/v1/documents",
        headers=headers(context, context["kb_one_id"], user_id),
        json={"title": "Doc One", "content": "Content one"},
    ).json()

    detail = client.get(
        f"/api/v1/documents/{created['id']}",
        headers=headers(context, context["kb_two_id"], user_id),
    )
    delete = client.delete(
        f"/api/v1/documents/{created['id']}",
        headers=headers(context, context["kb_two_id"], user_id),
    )
    process = client.post(
        f"/api/v1/documents/{created['id']}/process",
        headers=headers(context, context["kb_two_id"], user_id),
    )

    assert detail.status_code == 404
    assert delete.status_code == 404
    assert process.status_code == 404
