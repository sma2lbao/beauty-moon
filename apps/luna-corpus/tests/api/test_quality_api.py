"""Integration tests for quality endpoints."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.permissions import PermissionSlug
from app.auth.tokens import create_access_token
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
    kb2 = KnowledgeBase(name="Other", slug="other", workspace=workspace)
    session.add_all([kb, kb2])
    session.commit()
    context = {
        "tenant_id": tenant.id,
        "workspace_id": workspace.id,
        "kb_one_id": kb.id,
        "kb_two_id": kb2.id,
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
        session.add(
            WorkspaceMembership(user=user, workspace_id=workspace_id, roles=[role])
        )
        session.commit()
        return user.id
    finally:
        session.close()


def _headers(context, user_id, kb_key="kb_one_id"):
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": context[kb_key],
    }


@patch("app.api.routes.answer_question")
def test_query_records_interaction_and_returns_answer_id(mock_answer, client, app_db):
    _, Session, context = app_db
    mock_answer.return_value = {
        "answer": "A.",
        "sources": [
            {"document_id": "d1", "chunk_content": "c", "relevance_score": 0.9}
        ],
        "processing_time_ms": 42,
        "retrieval_mode": "vector",
    }
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_QUERY])
    resp = client.post(
        "/api/v1/qa/query",
        headers=_headers(context, uid),
        json={"question": "Q?"},
    )
    assert resp.status_code == 200
    assert resp.json()["answer_id"] is not None


@patch("app.api.routes.answer_question")
def test_feedback_roundtrip_and_cross_kb_404(mock_answer, client, app_db):
    _, Session, context = app_db
    mock_answer.return_value = {
        "answer": "A.",
        "sources": [],
        "processing_time_ms": 10,
        "retrieval_mode": "vector",
    }
    uid = _user(
        Session,
        context["workspace_id"],
        [PermissionSlug.QA_QUERY, PermissionSlug.QA_FEEDBACK],
    )
    q = client.post(
        "/api/v1/qa/query", headers=_headers(context, uid), json={"question": "Q?"}
    )
    answer_id = q.json()["answer_id"]

    ok = client.post(
        f"/api/v1/qa/interactions/{answer_id}/feedback",
        headers=_headers(context, uid),
        json={"rating": "down", "error_type": "hallucination", "comment": "bad"},
    )
    assert ok.status_code == 201

    cross = client.post(
        f"/api/v1/qa/interactions/{answer_id}/feedback",
        headers=_headers(context, uid, kb_key="kb_two_id"),
        json={"rating": "up"},
    )
    assert cross.status_code == 404


def test_quality_summary_empty(client, app_db):
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_QUERY])
    resp = client.get(
        "/api/v1/qa/quality/summary?days=7", headers=_headers(context, uid)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_interactions"] == 0
    assert body["thumbs_up_rate"] is None
