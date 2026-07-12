"""Integration tests for review-loop endpoints."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.permissions import PermissionSlug
from app.db.database import get_db
from app.db.models import (
    AuditLog,
    Base,
    EvaluationStatus,
    FeedbackRating,
    KnowledgeBase,
    Permission,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
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


def _user(Session, workspace_id, slugs, email="u@example.com"):
    session = Session()
    try:
        user = User(email=email, display_name="u")
        perms = []
        for slug in slugs:
            p = session.query(Permission).filter(Permission.slug == slug).first()
            if not p:
                p = Permission(name=slug, slug=slug, description=slug)
            perms.append(p)
        role = Role(name="r", slug="r-" + email, is_system=True, permissions=perms)
        session.add(
            WorkspaceMembership(user=user, workspace_id=workspace_id, roles=[role])
        )
        session.commit()
        return user.id
    finally:
        session.close()


def _headers(context, user_id, kb_key="kb_one_id"):
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": context[kb_key],
    }


def _seed_down_interaction(Session, kb_id):
    session = Session()
    try:
        it = QAInteraction(
            knowledge_base_id=kb_id, question="Q?", answer="A.", sources=[]
        )
        session.add(it)
        session.commit()
        session.add(QAFeedback(interaction_id=it.id, rating=FeedbackRating.DOWN))
        session.add(
            QAEvaluation(
                interaction_id=it.id,
                faithfulness=0.3,
                answer_relevance=0.4,
                status=EvaluationStatus.COMPLETED,
            )
        )
        session.commit()
        return it.id
    finally:
        session.close()


def test_reader_forbidden(client, app_db):
    _, Session, context = app_db
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_FEEDBACK])
    resp = client.get("/api/v1/qa/reviews", headers=_headers(context, uid))
    assert resp.status_code == 403


def test_queue_lists_triggered_interaction(client, app_db):
    _, Session, context = app_db
    iid = _seed_down_interaction(Session, context["kb_one_id"])
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_REVIEW])
    resp = client.get("/api/v1/qa/reviews", headers=_headers(context, uid))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["reviews"][0]["interaction_id"] == iid
    assert body["reviews"][0]["signals"]["thumbs_down"] is True


def test_detail_and_cross_kb_404(client, app_db):
    _, Session, context = app_db
    iid = _seed_down_interaction(Session, context["kb_one_id"])
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_REVIEW])
    ok = client.get(
        f"/api/v1/qa/reviews/{iid}", headers=_headers(context, uid)
    )
    assert ok.status_code == 200
    assert ok.json()["interaction"]["id"] == iid

    cross = client.get(
        f"/api/v1/qa/reviews/{iid}",
        headers=_headers(context, uid, kb_key="kb_two_id"),
    )
    assert cross.status_code == 404


def test_resolve_then_leaves_queue(client, app_db):
    _, Session, context = app_db
    iid = _seed_down_interaction(Session, context["kb_one_id"])
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_REVIEW])
    r = client.post(
        f"/api/v1/qa/reviews/{iid}/resolve",
        headers=_headers(context, uid),
        json={"root_cause": "knowledge_gap", "resolution_note": "补充文档"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"

    queue = client.get("/api/v1/qa/reviews", headers=_headers(context, uid))
    assert queue.json()["total"] == 0

    resolved = client.get(
        "/api/v1/qa/reviews?status=resolved", headers=_headers(context, uid)
    )
    assert resolved.json()["total"] == 1

    # 断言审计已落库：使用独立 session 查询同一个 SQLite 引擎。
    audit_session = Session()
    try:
        row = (
            audit_session.query(AuditLog)
            .filter(
                AuditLog.action == "qa.review_resolve",
                AuditLog.resource_id == iid,
            )
            .one()
        )
        assert row is not None
    finally:
        audit_session.close()


def test_dismiss_leaves_queue(client, app_db):
    _, Session, context = app_db
    iid = _seed_down_interaction(Session, context["kb_one_id"])
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_REVIEW])
    r = client.post(
        f"/api/v1/qa/reviews/{iid}/dismiss",
        headers=_headers(context, uid),
        json={"resolution_note": "误报"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "dismissed"
    queue = client.get("/api/v1/qa/reviews", headers=_headers(context, uid))
    assert queue.json()["total"] == 0


def test_resolve_cross_kb_404(client, app_db):
    _, Session, context = app_db
    iid = _seed_down_interaction(Session, context["kb_one_id"])
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_REVIEW])
    r = client.post(
        f"/api/v1/qa/reviews/{iid}/resolve",
        headers=_headers(context, uid, kb_key="kb_two_id"),
        json={"root_cause": "other", "resolution_note": "x"},
    )
    assert r.status_code == 404


def test_dismiss_cross_kb_404(client, app_db):
    _, Session, context = app_db
    iid = _seed_down_interaction(Session, context["kb_one_id"])
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_REVIEW])
    r = client.post(
        f"/api/v1/qa/reviews/{iid}/dismiss",
        headers=_headers(context, uid, kb_key="kb_two_id"),
        json={"resolution_note": "x"},
    )
    assert r.status_code == 404
