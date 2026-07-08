"""Integration tests for document create/update change detection."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
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


@patch("app.api.routes._run_index_task")
def test_get_document_returns_version_and_external_id(mock_run_index, client, app_db):
    """Regression: GET /documents/{id} and GET /documents expose version and external_id."""
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"],
                [PermissionSlug.DOCUMENT_WRITE, PermissionSlug.DOCUMENT_READ])

    # Create doc with external_id and version=1
    created = client.post(
        "/api/v1/documents",
        headers=_headers(context, uid),
        json={"title": "T", "content": "v1", "external_id": "HR-9"},
    )
    assert created.status_code == 201
    doc_id = created.json()["id"]

    # PUT update to bump version to 2
    updated = client.put(
        f"/api/v1/documents/{doc_id}",
        headers=_headers(context, uid),
        json={"title": "T", "content": "v2"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    # GET single document should return version=2 and external_id="HR-9"
    get_resp = client.get(
        f"/api/v1/documents/{doc_id}",
        headers=_headers(context, uid),
    )
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["version"] == 2, f"expected version=2, got {body['version']}"
    assert body["external_id"] == "HR-9", f"expected external_id='HR-9', got {body['external_id']}"

    # GET list should also include the correct version/external_id
    list_resp = client.get(
        "/api/v1/documents",
        headers=_headers(context, uid),
    )
    assert list_resp.status_code == 200
    docs = list_resp.json()["documents"]
    assert len(docs) >= 1
    found = next(d for d in docs if d["id"] == doc_id)
    assert found["version"] == 2
    assert found["external_id"] == "HR-9"


@patch("app.api.routes._run_index_task")
def test_put_document_null_content_hash(mock_run_index, client, app_db):
    """I1: existing document with content_hash=None should be treated as updated."""
    engine, Session, context = app_db
    uid = _user(Session, context["workspace_id"],
                [PermissionSlug.DOCUMENT_WRITE, PermissionSlug.DOCUMENT_READ])

    # Directly insert a document with content_hash=None via DB session
    sess = Session()
    try:
        from app.db.models import Document
        import uuid

        doc = Document(
            id=str(uuid.uuid4()),
            title="Legacy",
            content="legacy content",
            content_hash=None,
            version=1,
            knowledge_base_id=context["kb_one_id"],
        )
        sess.add(doc)
        sess.commit()
        doc_id = doc.id
    finally:
        sess.close()

    # PUT update should detect mismatch and treat as updated
    updated = client.put(
        f"/api/v1/documents/{doc_id}",
        headers=_headers(context, uid),
        json={"title": "Legacy", "content": "new content"},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["change_type"] == "updated"
    assert body["version"] == 2


@patch("app.api.routes._run_index_task")
def test_put_document_unchanged_no_task_created(mock_run_index, client, app_db):
    """I2: unchanged PUT must not create an IngestionTask row."""
    engine, Session, context = app_db
    uid = _user(Session, context["workspace_id"], [PermissionSlug.DOCUMENT_WRITE])

    created = client.post(
        "/api/v1/documents",
        headers=_headers(context, uid),
        json={"title": "T", "content": "v1"},
    )
    assert created.status_code == 201
    doc_id = created.json()["id"]

    # Count existing IngestionTask rows
    sess = Session()
    try:
        from app.db.models import IngestionTask
        task_count_before = sess.query(IngestionTask).count()
    finally:
        sess.close()

    # Unchanged PUT
    same = client.put(
        f"/api/v1/documents/{doc_id}",
        headers=_headers(context, uid),
        json={"title": "T", "content": "v1"},
    )
    assert same.status_code == 200
    assert same.json()["change_type"] == "unchanged"

    # No new IngestionTask row should have been created
    sess = Session()
    try:
        task_count_after = sess.query(IngestionTask).count()
        assert task_count_after == task_count_before, (
            f"unchanged PUT should not create IngestionTask; "
            f"before={task_count_before}, after={task_count_after}"
        )
    finally:
        sess.close()


def test_create_document_integrity_error_returns_409(client, app_db):
    """TOCTOU: IntegrityError on commit -> 409 instead of 500."""
    from sqlalchemy.orm import Session as SASession

    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"], [PermissionSlug.DOCUMENT_WRITE])

    # First create a document with external_id="X"
    first = client.post(
        "/api/v1/documents",
        headers=_headers(context, uid),
        json={"title": "T", "content": "hello", "external_id": "X"},
    )
    assert first.status_code == 201

    # Patch sqlalchemy.orm.Session.commit to raise IntegrityError,
    # simulating a TOCTOU race where a concurrent request sneaks in.
    with patch.object(
        SASession, "commit",
        side_effect=IntegrityError("INSERT", {}, Exception("duplicate key")),
    ):
        dup = client.post(
            "/api/v1/documents",
            headers=_headers(context, uid),
            json={"title": "T2", "content": "other", "external_id": "X"},
        )
        assert dup.status_code == 409, (
            f"expected 409, got {dup.status_code}: {dup.json()}"
        )
        assert "external_id" in dup.json()["detail"].lower()


@patch("app.api.routes._run_index_task")
def test_put_document_external_id_conflict_returns_409(mock_run_index, client, app_db):
    """PUT changing external_id to one already owned by another doc -> 409."""
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"],
                [PermissionSlug.DOCUMENT_WRITE, PermissionSlug.DOCUMENT_READ])

    # Doc A with external_id="X"
    doc_a = client.post(
        "/api/v1/documents",
        headers=_headers(context, uid),
        json={"title": "A", "content": "content A", "external_id": "X"},
    )
    assert doc_a.status_code == 201

    # Doc B with different content, no external_id
    doc_b = client.post(
        "/api/v1/documents",
        headers=_headers(context, uid),
        json={"title": "B", "content": "content B"},
    )
    assert doc_b.status_code == 201
    doc_b_id = doc_b.json()["id"]

    # PUT doc B with external_id="X" + changed content -> 409
    conflict = client.put(
        f"/api/v1/documents/{doc_b_id}",
        headers=_headers(context, uid),
        json={"title": "B", "content": "content B updated", "external_id": "X"},
    )
    assert conflict.status_code == 409, (
        f"expected 409, got {conflict.status_code}: {conflict.json()}"
    )
    assert "X" in conflict.json()["detail"]


def test_put_document_cross_kb_forbidden(client, app_db):
    """M2: PUT to a document in kb_one with a different KB header must return 404."""
    engine, Session, context = app_db
    uid = _user(Session, context["workspace_id"],
                [PermissionSlug.DOCUMENT_WRITE, PermissionSlug.DOCUMENT_READ])

    # Create a document in kb_one
    created = client.post(
        "/api/v1/documents",
        headers=_headers(context, uid),
        json={"title": "T", "content": "secret"},
    )
    assert created.status_code == 201
    doc_id = created.json()["id"]

    # Use a different (non-existent) knowledge_base_id header
    wrong_headers = {
        **dict(_headers(context, uid)),
        "X-Knowledge-Base-Id": "00000000-0000-0000-0000-000000000000",
    }
    resp = client.put(
        f"/api/v1/documents/{doc_id}",
        headers=wrong_headers,
        json={"title": "T", "content": "stolen"},
    )
    # The auth layer validates the KB exists, so we expect 4xx (403 or 404)
    assert resp.status_code in (403, 404), f"unexpected status {resp.status_code}"