"""元数据 Schema 与分面 API 集成测试。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.permissions import PermissionSlug
from app.db.database import get_db
from app.db.models import (
    Base,
    ContentStatus,
    Document,
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
    _, Session, _ = app_db

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


def _create_user_with_permissions(Session, workspace_id, label, permission_slugs):
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


def _headers(context, knowledge_base_id, user_id):
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": knowledge_base_id,
    }


_KB_ADMIN_PERMS = [
    PermissionSlug.KNOWLEDGE_BASE_MANAGE,
    PermissionSlug.KNOWLEDGE_BASE_READ,
]

_KB_READER_PERMS = [PermissionSlug.KNOWLEDGE_BASE_READ]


def test_create_and_list_metadata_field(client, app_db):
    _, Session, context = app_db
    user_id = _create_user_with_permissions(
        Session, context["workspace_id"], "kb_admin", _KB_ADMIN_PERMS
    )
    kb_id = context["kb_one_id"]
    headers = _headers(context, kb_id, user_id)

    resp = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/metadata-fields",
        json={
            "key": "category",
            "label": "类别",
            "field_type": "enum",
            "options": ["合同", "发票"],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["key"] == "category"
    assert body["label"] == "类别"
    assert body["field_type"] == "enum"
    assert body["options"] == ["合同", "发票"]
    assert body["knowledge_base_id"] == kb_id

    dup = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/metadata-fields",
        json={"key": "category", "label": "重复", "field_type": "string"},
        headers=headers,
    )
    assert dup.status_code == 409

    listed = client.get(
        f"/api/v1/knowledge-bases/{kb_id}/metadata-fields", headers=headers
    )
    assert listed.status_code == 200
    payload = listed.json()
    assert isinstance(payload, list)
    assert any(f["key"] == "category" for f in payload)


def test_create_metadata_field_requires_manage(client, app_db):
    _, Session, context = app_db
    reader_id = _create_user_with_permissions(
        Session, context["workspace_id"], "kb_reader", _KB_READER_PERMS
    )
    kb_id = context["kb_one_id"]
    resp = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/metadata-fields",
        json={"key": "topic", "label": "Topic", "field_type": "string"},
        headers=_headers(context, kb_id, reader_id),
    )
    assert resp.status_code == 403


def test_update_and_delete_metadata_field(client, app_db):
    _, Session, context = app_db
    admin_id = _create_user_with_permissions(
        Session, context["workspace_id"], "kb_admin", _KB_ADMIN_PERMS
    )
    kb_id = context["kb_one_id"]
    headers = _headers(context, kb_id, admin_id)

    created = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/metadata-fields",
        json={"key": "priority", "label": "优先级", "field_type": "string"},
        headers=headers,
    )
    assert created.status_code == 201
    field_id = created.json()["id"]

    patched = client.patch(
        f"/api/v1/metadata-fields/{field_id}",
        json={"label": "重要程度", "is_facetable": False},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["label"] == "重要程度"
    assert patched.json()["is_facetable"] is False

    deleted = client.delete(
        f"/api/v1/metadata-fields/{field_id}", headers=headers
    )
    assert deleted.status_code == 204

    listed = client.get(
        f"/api/v1/knowledge-bases/{kb_id}/metadata-fields", headers=headers
    )
    assert all(f["id"] != field_id for f in listed.json())


def test_cross_kb_access_returns_404(client, app_db):
    _, Session, context = app_db
    admin_id = _create_user_with_permissions(
        Session, context["workspace_id"], "kb_admin", _KB_ADMIN_PERMS
    )
    kb_id = context["kb_one_id"]
    other_kb_id = context["kb_two_id"]

    # header 声明 kb_two，但路径写 kb_one -> 应 404
    resp = client.get(
        f"/api/v1/knowledge-bases/{kb_id}/metadata-fields",
        headers=_headers(context, other_kb_id, admin_id),
    )
    assert resp.status_code == 404

    # PATCH / DELETE 使用另一个 kb 下的字段 id 时也应 404
    created = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/metadata-fields",
        json={"key": "category", "label": "类别", "field_type": "string"},
        headers=_headers(context, kb_id, admin_id),
    )
    assert created.status_code == 201
    field_id = created.json()["id"]

    patched = client.patch(
        f"/api/v1/metadata-fields/{field_id}",
        json={"label": "跨 kb"},
        headers=_headers(context, other_kb_id, admin_id),
    )
    assert patched.status_code == 404

    deleted = client.delete(
        f"/api/v1/metadata-fields/{field_id}",
        headers=_headers(context, other_kb_id, admin_id),
    )
    assert deleted.status_code == 404


def test_facets_endpoint(client, app_db):
    _, Session, context = app_db
    admin_id = _create_user_with_permissions(
        Session, context["workspace_id"], "kb_admin", _KB_ADMIN_PERMS
    )
    kb_id = context["kb_one_id"]
    headers = _headers(context, kb_id, admin_id)

    resp = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/metadata-fields",
        json={"key": "category", "label": "类别", "field_type": "enum"},
        headers=headers,
    )
    assert resp.status_code == 201

    # 塞一条 COMPLETED 文档，让 facet 有数据
    session = Session()
    try:
        doc = Document(
            title="d1",
            content="hello",
            knowledge_base_id=kb_id,
            status=ContentStatus.COMPLETED,
            doc_metadata={"category": "合同"},
        )
        session.add(doc)
        session.commit()
    finally:
        session.close()

    facets = client.get(
        f"/api/v1/knowledge-bases/{kb_id}/facets", headers=headers
    )
    assert facets.status_code == 200
    body = facets.json()
    assert "facets" in body
    assert isinstance(body["facets"], list)
    assert any(f["key"] == "category" for f in body["facets"])


def test_facets_endpoint_requires_read(client, app_db):
    _, Session, context = app_db
    # 用户不含 KB_READ
    user_id = _create_user_with_permissions(
        Session,
        context["workspace_id"],
        "no_perm",
        [PermissionSlug.QA_QUERY],
    )
    kb_id = context["kb_one_id"]
    resp = client.get(
        f"/api/v1/knowledge-bases/{kb_id}/facets",
        headers=_headers(context, kb_id, user_id),
    )
    assert resp.status_code == 403
