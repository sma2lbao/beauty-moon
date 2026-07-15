"""Tenant/workspace management endpoints require authentication."""

from app.auth.permissions import PermissionSlug
from app.auth.tokens import create_access_token
from tests.api.test_file_upload import (  # noqa: F401
    app_db,
    client,
    create_user_with_permissions,
)


def test_create_tenant_requires_auth(client, app_db):
    """POST /tenants without a bearer token returns 401."""
    response = client.post(
        "/api/v1/tenants",
        json={"name": "NoAuth", "slug": "no-auth"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


def test_create_workspace_requires_auth(client, app_db):
    """POST /workspaces without a bearer token returns 401."""
    _, _, context = app_db
    response = client.post(
        "/api/v1/workspaces",
        json={
            "tenant_id": context["tenant_id"],
            "name": "NoAuth",
            "slug": "no-auth-ws",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


def test_create_workspace_forbidden_without_manage_permission(client, app_db):
    """Authenticated user without WORKSPACE_MANAGE in the target tenant → 403."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "reader",
        [PermissionSlug.WORKSPACE_READ],
    )
    headers = {"Authorization": f"Bearer {create_access_token(user_id)}"}
    response = client.post(
        "/api/v1/workspaces",
        json={
            "tenant_id": context["tenant_id"],
            "name": "Forbidden",
            "slug": "forbidden-ws",
        },
        headers=headers,
    )
    assert response.status_code == 403
    assert (
        response.json()["detail"] == "Missing required permission: workspace:manage"
    )


def test_create_workspace_allowed_with_manage_permission(client, app_db):
    """Authenticated user with WORKSPACE_MANAGE in the target tenant → 201."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "wsadmin",
        [PermissionSlug.WORKSPACE_MANAGE],
    )
    headers = {"Authorization": f"Bearer {create_access_token(user_id)}"}
    response = client.post(
        "/api/v1/workspaces",
        json={
            "tenant_id": context["tenant_id"],
            "name": "Second",
            "slug": "second-ws",
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == context["tenant_id"]
    assert body["slug"] == "second-ws"
