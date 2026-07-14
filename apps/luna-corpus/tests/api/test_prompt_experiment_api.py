"""End-to-end tests for prompt version & experiment management endpoints."""
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


def _user(Session, workspace_id, slugs, email="u@example.com"):
    session = Session()
    try:
        user = User(email=email, display_name=email.split("@")[0])
        perms = []
        for slug in slugs:
            p = session.query(Permission).filter(Permission.slug == slug).first()
            if not p:
                p = Permission(name=slug, slug=slug, description=slug)
            perms.append(p)
        role = Role(name=f"r-{email}", slug=f"r-{email}", is_system=True, permissions=perms)
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


def test_prompt_experiment_flow(client, app_db):
    _, Session, context = app_db
    uid = _user(
        Session,
        context["workspace_id"],
        [PermissionSlug.PROMPT_MANAGE, PermissionSlug.QA_QUERY],
    )
    headers = _headers(context, uid)

    # 1. create a DB version
    r = client.post(
        "/api/v1/qa/prompt-versions",
        headers=headers,
        json={
            "prompt_key": "rag_qa",
            "version_label": "v2-concise",
            "lang": "zh",
            "template_text": "简洁版 {body}",
            "status": "active",
        },
    )
    assert r.status_code == 200, r.text
    version_id = r.json()["id"]
    assert r.json()["status"] == "active"
    assert r.json()["prompt_key"] == "rag_qa"

    # 2. create experiment: file-default vs new version
    r = client.post(
        "/api/v1/qa/experiments",
        headers=headers,
        json={
            "prompt_key": "rag_qa",
            "variants": [
                {"version_id": "file::rag_qa::zh", "weight": 50},
                {"version_id": version_id, "weight": 50},
            ],
        },
    )
    assert r.status_code == 200, r.text
    exp_id = r.json()["id"]
    assert r.json()["status"] == "running"

    # 3. report is reachable and well-formed
    r = client.get("/api/v1/qa/experiments/rag_qa/report", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prompt_key"] == "rag_qa"
    assert {v["version_id"] for v in body["variants"]} == {
        "file::rag_qa::zh",
        version_id,
    }

    # 4. stop the experiment
    r = client.patch(
        f"/api/v1/qa/experiments/{exp_id}",
        headers=headers,
        json={"status": "stopped"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "stopped"


def test_patch_experiment_not_found(client, app_db):
    _, Session, context = app_db
    uid = _user(
        Session,
        context["workspace_id"],
        [PermissionSlug.PROMPT_MANAGE],
    )
    r = client.patch(
        "/api/v1/qa/experiments/does-not-exist",
        headers=_headers(context, uid),
        json={"status": "stopped"},
    )
    assert r.status_code == 404


def test_create_version_without_permission_returns_403(client, app_db):
    _, Session, context = app_db
    uid = _user(
        Session,
        context["workspace_id"],
        [PermissionSlug.QA_QUERY],
        email="reader@example.com",
    )
    r = client.post(
        "/api/v1/qa/prompt-versions",
        headers=_headers(context, uid),
        json={
            "prompt_key": "rag_qa",
            "version_label": "vX",
            "lang": "zh",
            "template_text": "x {body}",
        },
    )
    assert r.status_code == 403
