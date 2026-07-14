"""QA 路由：配额准入（429）与用量记录集成测试。"""
from datetime import datetime, timezone
from decimal import Decimal
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
    QuotaCounter,
    QuotaLimit,
    Role,
    Tenant,
    UsageRecord,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.main import create_app
from app.services.llm import TokenUsage


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
        "kb_id": kb.id,
    }
    session.close()
    yield engine, Session, context
    engine.dispose()


@pytest.fixture
def client(app_db):
    _engine, Session, _ = app_db

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


def _headers(context, user_id):
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": context["kb_id"],
    }


def _seed_over_tenant_quota(Session, tenant_id):
    """租户 token 日限=1，当日已用 5 → 已超。"""
    session = Session()
    try:
        session.add(
            QuotaLimit(
                scope_type="tenant",
                scope_id=tenant_id,
                daily_token_limit=1,
                currency="CNY",
            )
        )
        session.add(
            QuotaCounter(
                scope_type="tenant",
                scope_id=tenant_id,
                usage_date=datetime.now(timezone.utc).date(),
                token_used=5,
                cost_used=Decimal("0"),
            )
        )
        session.commit()
    finally:
        session.close()


def test_qa_query_rejected_when_over_quota(client, app_db):
    _, Session, context = app_db
    _seed_over_tenant_quota(Session, context["tenant_id"])
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_QUERY])
    resp = client.post(
        "/api/v1/qa/query",
        headers=_headers(context, uid),
        json={"question": "hi"},
    )
    assert resp.status_code == 429
    assert "quota exceeded" in resp.json()["detail"]


@patch("app.api.routes.answer_question")
def test_qa_query_records_usage_on_success(mock_answer, client, app_db):
    """成功路径：路由必须调用 record_usage 并落一条 UsageRecord。"""
    _, Session, context = app_db
    mock_answer.return_value = {
        "answer": "A.",
        "sources": [],
        "processing_time_ms": 42,
        "retrieval_mode": "vector",
        "usage": TokenUsage(
            input_tokens=10, output_tokens=20, model="test-model", provider="ollama"
        ),
    }
    uid = _user(Session, context["workspace_id"], [PermissionSlug.QA_QUERY])
    resp = client.post(
        "/api/v1/qa/query",
        headers=_headers(context, uid),
        json={"question": "Q?"},
    )
    assert resp.status_code == 200

    audit_session = Session()
    try:
        row = (
            audit_session.query(UsageRecord)
            .filter(UsageRecord.tenant_id == context["tenant_id"])
            .one()
        )
        assert row.workspace_id == context["workspace_id"]
        assert row.knowledge_base_id == context["kb_id"]
        assert row.input_tokens == 10
        assert row.output_tokens == 20
        assert row.total_tokens == 30
    finally:
        audit_session.close()
