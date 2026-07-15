"""Tests for tenant structure API routes."""

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
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

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
    engine.dispose()


def create_user_with_role(client, workspace_id, role_slug, permission_slugs):
    db_generator = client.app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        user = User(email=f"{role_slug}@example.com", display_name=role_slug)
        permissions = []
        for slug in permission_slugs:
            permission = db.query(Permission).filter(Permission.slug == slug).first()
            if not permission:
                permission = Permission(name=slug, slug=slug, description=slug)
            permissions.append(permission)
        role = Role(
            name=role_slug, slug=role_slug, is_system=True, permissions=permissions
        )
        membership = WorkspaceMembership(
            user=user, workspace_id=workspace_id, roles=[role]
        )
        db.add(membership)
        db.commit()
        return user.id
    finally:
        db.close()


def bootstrap_tenant_and_workspace(client, tenant_name="Acme", tenant_slug="acme",
                                    workspace_name="Research", workspace_slug="research"):
    """Insert a tenant + workspace directly via DB (post-auth routes)."""
    db_generator = client.app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        tenant = Tenant(name=tenant_name, slug=tenant_slug)
        workspace = Workspace(name=workspace_name, slug=workspace_slug, tenant=tenant)
        db.add(workspace)
        db.commit()
        return {"id": tenant.id, "slug": tenant.slug, "name": tenant.name}, {
            "id": workspace.id,
            "tenant_id": workspace.tenant_id,
            "name": workspace.name,
            "slug": workspace.slug,
        }
    finally:
        db.close()


def create_knowledge_base_record(client, workspace_id, name, slug):
    db_generator = client.app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        knowledge_base = KnowledgeBase(workspace_id=workspace_id, name=name, slug=slug)
        db.add(knowledge_base)
        db.commit()
        return {
            "id": knowledge_base.id,
            "workspace_id": knowledge_base.workspace_id,
            "name": knowledge_base.name,
            "slug": knowledge_base.slug,
            "description": knowledge_base.description,
        }
    finally:
        db.close()


def context_headers(user_id, tenant_id, workspace_id, knowledge_base_id):
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-Id": tenant_id,
        "X-Workspace-Id": workspace_id,
        "X-Knowledge-Base-Id": knowledge_base_id,
    }


def test_list_tenants_requires_authenticated_user(client):
    bootstrap_tenant_and_workspace(client)

    response = client.get("/api/v1/tenants")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


def test_list_workspaces_requires_authenticated_user(client):
    tenant, _ = bootstrap_tenant_and_workspace(client)

    response = client.get(f"/api/v1/workspaces?tenant_id={tenant['id']}")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


def test_tenant_and_workspace_lists_only_return_user_memberships(client):
    tenant_one, workspace_one = bootstrap_tenant_and_workspace(
        client,
        tenant_name="Acme",
        tenant_slug="acme",
        workspace_name="Research",
        workspace_slug="research",
    )
    bootstrap_tenant_and_workspace(
        client,
        tenant_name="Other",
        tenant_slug="other",
        workspace_name="Private",
        workspace_slug="private",
    )
    user_id = create_user_with_role(
        client,
        workspace_one["id"],
        "reader",
        [PermissionSlug.WORKSPACE_READ],
    )

    auth_header = {"Authorization": f"Bearer {create_access_token(user_id)}"}
    tenants = client.get("/api/v1/tenants", headers=auth_header)
    workspaces = client.get("/api/v1/workspaces", headers=auth_header)

    assert tenants.status_code == 200
    assert tenants.json()["total"] == 1
    assert tenants.json()["tenants"][0]["id"] == tenant_one["id"]
    assert workspaces.status_code == 200
    assert workspaces.json()["total"] == 1
    assert workspaces.json()["workspaces"][0]["id"] == workspace_one["id"]


def test_create_knowledge_base_requires_manage_permission(client):
    tenant, workspace = bootstrap_tenant_and_workspace(client)
    bootstrap_kb = create_knowledge_base_record(
        client,
        workspace["id"],
        "Bootstrap",
        "bootstrap",
    )
    reader_id = create_user_with_role(
        client,
        workspace["id"],
        "reader",
        [PermissionSlug.KNOWLEDGE_BASE_READ],
    )

    response = client.post(
        "/api/v1/knowledge-bases",
        headers=context_headers(
            reader_id, tenant["id"], workspace["id"], bootstrap_kb["id"]
        ),
        json={"workspace_id": workspace["id"], "name": "Docs", "slug": "docs"},
    )

    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "Missing required permission: knowledge_base:manage"
    )


def test_workspace_admin_can_create_and_list_knowledge_bases(client):
    tenant, workspace = bootstrap_tenant_and_workspace(client)
    bootstrap_kb = create_knowledge_base_record(
        client,
        workspace["id"],
        "Bootstrap",
        "bootstrap",
    )
    admin_id = create_user_with_role(
        client,
        workspace["id"],
        "admin",
        [PermissionSlug.KNOWLEDGE_BASE_READ, PermissionSlug.KNOWLEDGE_BASE_MANAGE],
    )

    created = client.post(
        "/api/v1/knowledge-bases",
        headers=context_headers(
            admin_id, tenant["id"], workspace["id"], bootstrap_kb["id"]
        ),
        json={"workspace_id": workspace["id"], "name": "Docs", "slug": "docs"},
    )
    listed = client.get(
        f"/api/v1/knowledge-bases?workspace_id={workspace['id']}",
        headers=context_headers(
            admin_id, tenant["id"], workspace["id"], bootstrap_kb["id"]
        ),
    )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()["total"] == 2
