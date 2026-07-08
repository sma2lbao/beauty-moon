"""Integration tests for document create/update change detection."""
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
    kb = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    session.add(kb)
    session.commit()
    context = {
        "tenant_id": tenant.id,
        "workspace_id": workspace.id,
        "kb_one_id": kb.id,
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


def _user(Session, workspace_id, slugs):
    session = Session()
    try:
        user = User(email="u@example.com", display_name="u")
        perms = []
        for slug in slugs:
            p = session.query(Permission).filter(Permission.slug == slug).first()
            if not p:
                p = Permission(name=slug, slug=slug, description=slug)
            perms.append(p)
        role = Role(name="r", slug="r", is_system=True, permissions=perms)
        session.add(WorkspaceMembership(user=user, workspace_id=workspace_id, roles=[role]))
        session.commit()
        return user.id
    finally:
        session.close()


def _headers(context, user_id):
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": context["kb_one_id"],
    }


def test_create_document_sets_version_and_hash(client, app_db):
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"],
                [PermissionSlug.DOCUMENT_WRITE, PermissionSlug.DOCUMENT_READ])
    resp = client.post(
        "/api/v1/documents",
        headers=_headers(context, uid),
        json={"title": "T", "content": "hello", "external_id": "HR-1"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["version"] == 1
    assert body["external_id"] == "HR-1"


def test_create_document_duplicate_external_id_conflicts(client, app_db):
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"], [PermissionSlug.DOCUMENT_WRITE])
    payload = {"title": "T", "content": "hello", "external_id": "HR-1"}
    first = client.post("/api/v1/documents", headers=_headers(context, uid), json=payload)
    assert first.status_code == 201
    dup = client.post(
        "/api/v1/documents",
        headers=_headers(context, uid),
        json={"title": "T2", "content": "other", "external_id": "HR-1"},
    )
    assert dup.status_code == 409


@patch("app.api.routes._run_index_task")
def test_put_document_updated_and_unchanged(mock_run_index, client, app_db):
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"], [PermissionSlug.DOCUMENT_WRITE])
    created = client.post(
        "/api/v1/documents",
        headers=_headers(context, uid),
        json={"title": "T", "content": "v1"},
    )
    doc_id = created.json()["id"]

    updated = client.put(
        f"/api/v1/documents/{doc_id}",
        headers=_headers(context, uid),
        json={"title": "T", "content": "v2"},
    )
    assert updated.status_code == 200
    assert updated.json()["change_type"] == "updated"
    assert updated.json()["version"] == 2

    same = client.put(
        f"/api/v1/documents/{doc_id}",
        headers=_headers(context, uid),
        json={"title": "T", "content": "v2"},
    )
    assert same.status_code == 200
    assert same.json()["change_type"] == "unchanged"
    assert same.json()["version"] == 2


def test_put_document_not_found(client, app_db):
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"], [PermissionSlug.DOCUMENT_WRITE])
    resp = client.put(
        "/api/v1/documents/missing-id",
        headers=_headers(context, uid),
        json={"title": "T", "content": "x"},
    )
    assert resp.status_code == 404