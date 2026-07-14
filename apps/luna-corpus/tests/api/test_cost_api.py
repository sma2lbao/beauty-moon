"""成本管理 API 集成测试。"""
from datetime import datetime, timezone
from decimal import Decimal

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
    ModelPrice,
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


def _make_user(Session, workspace_id, slugs, email="u@example.com"):
    """创建一个具有指定权限的用户并绑定到工作区。"""
    session = Session()
    try:
        user = User(email=email, display_name="U", is_active=True)
        perms = []
        for slug in slugs:
            p = session.query(Permission).filter(Permission.slug == slug).first()
            if not p:
                p = Permission(name=slug, slug=slug, description=slug)
            perms.append(p)
        role = Role(
            name="admin", slug="r-" + email, is_system=True, permissions=perms
        )
        session.add(
            WorkspaceMembership(
                user=user,
                workspace_id=workspace_id,
                is_active=True,
                roles=[role],
            )
        )
        session.commit()
        return user.id
    finally:
        session.close()


def _headers(context, user_id):
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": context["kb_id"],
    }


def test_put_quota_limit_then_get_usage(client, app_db):
    """PUT /quota/limits 写入后，GET /quota/usage 应能读到限额与 0 用量。"""
    _, Session, context = app_db
    uid = _make_user(
        Session,
        context["workspace_id"],
        [PermissionSlug.COST_MANAGE, PermissionSlug.COST_READ],
    )
    put = client.put(
        "/api/v1/quota/limits",
        json={
            "scope_type": "tenant",
            "scope_id": context["tenant_id"],
            "daily_token_limit": 1000,
            "currency": "CNY",
        },
        headers=_headers(context, uid),
    )
    assert put.status_code == 200
    body = put.json()
    assert body["scope_type"] == "tenant"
    assert body["scope_id"] == context["tenant_id"]
    assert body["daily_token_limit"] == 1000
    assert body["currency"] == "CNY"

    got = client.get("/api/v1/quota/usage", headers=_headers(context, uid))
    assert got.status_code == 200
    payload = got.json()
    assert payload["tenant"]["daily_token_limit"] == 1000
    assert payload["tenant"]["token_used"] == 0
    assert payload["workspace"]["daily_token_limit"] is None
    assert payload["workspace"]["token_used"] == 0


def test_put_quota_limit_upsert_updates_existing_row(client, app_db):
    """相同 scope 的 PUT 应该是 upsert，而不是插入第二条。"""
    _, Session, context = app_db
    uid = _make_user(
        Session,
        context["workspace_id"],
        [PermissionSlug.COST_MANAGE, PermissionSlug.COST_READ],
    )
    r1 = client.put(
        "/api/v1/quota/limits",
        json={
            "scope_type": "workspace",
            "scope_id": context["workspace_id"],
            "daily_token_limit": 100,
            "currency": "CNY",
        },
        headers=_headers(context, uid),
    )
    assert r1.status_code == 200
    r2 = client.put(
        "/api/v1/quota/limits",
        json={
            "scope_type": "workspace",
            "scope_id": context["workspace_id"],
            "daily_token_limit": 500,
            "daily_cost_limit": "12.5",
            "currency": "CNY",
        },
        headers=_headers(context, uid),
    )
    assert r2.status_code == 200
    session = Session()
    try:
        rows = (
            session.query(QuotaLimit)
            .filter(
                QuotaLimit.scope_type == "workspace",
                QuotaLimit.scope_id == context["workspace_id"],
            )
            .all()
        )
        assert len(rows) == 1
        assert rows[0].daily_token_limit == 500
        assert rows[0].daily_cost_limit == Decimal("12.5")
    finally:
        session.close()


def test_get_usage_reports_current_counter(client, app_db):
    """GET /quota/usage 应正确返回当日 counter 的已用值。"""
    _, Session, context = app_db
    uid = _make_user(
        Session,
        context["workspace_id"],
        [PermissionSlug.COST_READ],
    )
    session = Session()
    try:
        session.add(
            QuotaLimit(
                scope_type="tenant",
                scope_id=context["tenant_id"],
                daily_token_limit=1000,
                daily_cost_limit=Decimal("9.99"),
                currency="CNY",
            )
        )
        session.add(
            QuotaCounter(
                scope_type="tenant",
                scope_id=context["tenant_id"],
                usage_date=datetime.now(timezone.utc).date(),
                token_used=42,
                cost_used=Decimal("1.25"),
            )
        )
        session.commit()
    finally:
        session.close()

    resp = client.get("/api/v1/quota/usage", headers=_headers(context, uid))
    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant"]["daily_token_limit"] == 1000
    assert Decimal(body["tenant"]["daily_cost_limit"]) == Decimal("9.99")
    assert body["tenant"]["token_used"] == 42
    assert Decimal(body["tenant"]["cost_used"]) == Decimal("1.25")


def test_records_endpoint_empty(client, app_db):
    """无用量记录时 total=0。"""
    _, Session, context = app_db
    uid = _make_user(
        Session,
        context["workspace_id"],
        [PermissionSlug.COST_READ],
    )
    got = client.get("/api/v1/cost/records", headers=_headers(context, uid))
    assert got.status_code == 200
    body = got.json()
    assert body["total"] == 0
    assert body["records"] == []


def test_records_endpoint_lists_tenant_scoped_rows(client, app_db):
    """/cost/records 只返回当前租户的 UsageRecord。"""
    _, Session, context = app_db
    uid = _make_user(
        Session,
        context["workspace_id"],
        [PermissionSlug.COST_READ],
    )
    session = Session()
    try:
        session.add(
            UsageRecord(
                tenant_id=context["tenant_id"],
                workspace_id=context["workspace_id"],
                knowledge_base_id=context["kb_id"],
                provider="ollama",
                model="test-model",
                input_tokens=10,
                output_tokens=20,
                total_tokens=30,
                cost_amount=Decimal("0.5"),
                currency="CNY",
            )
        )
        # 另一租户的记录不应被返回
        session.add(
            UsageRecord(
                tenant_id="00000000-0000-0000-0000-000000000000",
                workspace_id=context["workspace_id"],
                knowledge_base_id=context["kb_id"],
                provider="ollama",
                model="other",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                cost_amount=Decimal("0.01"),
                currency="CNY",
            )
        )
        session.commit()
    finally:
        session.close()

    got = client.get("/api/v1/cost/records", headers=_headers(context, uid))
    assert got.status_code == 200
    body = got.json()
    assert body["total"] == 1
    assert len(body["records"]) == 1
    row = body["records"][0]
    assert row["provider"] == "ollama"
    assert row["model"] == "test-model"
    assert row["input_tokens"] == 10
    assert row["output_tokens"] == 20
    assert row["total_tokens"] == 30
    assert row["cost_amount"] == "0.500000" or Decimal(row["cost_amount"]) == Decimal("0.5")


def test_records_endpoint_isolates_other_workspace(client, app_db):
    """/cost/records 不应返回同租户内其他工作区的用量明细。"""
    _, Session, context = app_db
    uid = _make_user(
        Session,
        context["workspace_id"],
        [PermissionSlug.COST_READ],
    )
    session = Session()
    try:
        # 同租户、当前工作区：应可见
        session.add(
            UsageRecord(
                tenant_id=context["tenant_id"],
                workspace_id=context["workspace_id"],
                knowledge_base_id=context["kb_id"],
                provider="ollama",
                model="mine",
                input_tokens=10,
                output_tokens=20,
                total_tokens=30,
                cost_amount=Decimal("0.5"),
                currency="CNY",
            )
        )
        # 同租户、其他工作区：不应可见
        session.add(
            UsageRecord(
                tenant_id=context["tenant_id"],
                workspace_id="11111111-1111-1111-1111-111111111111",
                knowledge_base_id=context["kb_id"],
                provider="ollama",
                model="other-ws",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                cost_amount=Decimal("0.01"),
                currency="CNY",
            )
        )
        session.commit()
    finally:
        session.close()

    got = client.get("/api/v1/cost/records", headers=_headers(context, uid))
    assert got.status_code == 200
    body = got.json()
    assert body["total"] == 1
    assert len(body["records"]) == 1
    assert body["records"][0]["model"] == "mine"


def test_put_price_creates_row(client, app_db):
    """PUT /cost/prices 应写入一条价格记录。"""
    _, Session, context = app_db
    uid = _make_user(
        Session,
        context["workspace_id"],
        [PermissionSlug.COST_MANAGE],
    )
    resp = client.put(
        "/api/v1/cost/prices",
        json={
            "provider": "ark",
            "model": "doubao-pro",
            "input_price_per_1k": "0.008",
            "output_price_per_1k": "0.02",
            "currency": "CNY",
            "effective_from": "2026-07-14T00:00:00",
        },
        headers=_headers(context, uid),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "id" in body

    session = Session()
    try:
        rows = session.query(ModelPrice).all()
        assert len(rows) == 1
        assert rows[0].provider == "ark"
        assert rows[0].model == "doubao-pro"
        assert rows[0].input_price_per_1k == Decimal("0.008")
        assert rows[0].output_price_per_1k == Decimal("0.02")
    finally:
        session.close()


def test_quota_limits_requires_cost_manage_permission(client, app_db):
    """仅 COST_READ 用户不能 PUT /quota/limits。"""
    _, Session, context = app_db
    uid = _make_user(
        Session,
        context["workspace_id"],
        [PermissionSlug.COST_READ],
    )
    resp = client.put(
        "/api/v1/quota/limits",
        json={
            "scope_type": "tenant",
            "scope_id": context["tenant_id"],
            "daily_token_limit": 100,
            "currency": "CNY",
        },
        headers=_headers(context, uid),
    )
    assert resp.status_code == 403


def test_quota_limits_rejects_cross_tenant_scope(client, app_db):
    """即使有 COST_MANAGE，也不能给其他租户设配额（租户隔离）。"""
    _, Session, context = app_db
    uid = _make_user(
        Session,
        context["workspace_id"],
        [PermissionSlug.COST_MANAGE],
    )
    resp = client.put(
        "/api/v1/quota/limits",
        json={
            "scope_type": "tenant",
            "scope_id": "00000000-0000-0000-0000-000000000000",
            "daily_token_limit": 100,
            "currency": "CNY",
        },
        headers=_headers(context, uid),
    )
    assert resp.status_code == 403
    assert "outside current tenant" in resp.json()["detail"]


def test_quota_limits_rejects_cross_workspace_scope(client, app_db):
    """即使有 COST_MANAGE，也不能给其他工作区设配额（工作区隔离）。"""
    _, Session, context = app_db
    uid = _make_user(
        Session,
        context["workspace_id"],
        [PermissionSlug.COST_MANAGE],
    )
    resp = client.put(
        "/api/v1/quota/limits",
        json={
            "scope_type": "workspace",
            "scope_id": "00000000-0000-0000-0000-000000000000",
            "daily_token_limit": 100,
            "currency": "CNY",
        },
        headers=_headers(context, uid),
    )
    assert resp.status_code == 403
    assert "outside current workspace" in resp.json()["detail"]
