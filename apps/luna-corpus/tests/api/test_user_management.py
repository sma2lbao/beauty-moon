"""Admin creates users via API; created users can log in."""
from tests.api.test_file_upload import (
    app_db,  # noqa: F401
    client,  # noqa: F401
    create_user_with_permissions,
    _auth_headers,
)
from app.auth.permissions import PermissionSlug


def test_create_user_requires_permission(client, app_db):
    _, _, context = app_db
    resp = client.post(
        "/api/v1/users",
        json={"email": "new@example.com", "display_name": "New", "password": "pw123456"},
        headers={
            "X-Tenant-Id": context["tenant_id"],
            "X-Workspace-Id": context["workspace_id"],
            "X-Knowledge-Base-Id": context["kb_one_id"],
        },
    )
    assert resp.status_code == 401


def test_admin_creates_user_then_login(client, app_db):
    _, Session, context = app_db
    admin_id = create_user_with_permissions(
        Session, context["workspace_id"], "admin", [PermissionSlug.WORKSPACE_MANAGE]
    )
    headers = _auth_headers(context, knowledge_base_id=context["kb_one_id"], user_id=admin_id)
    create = client.post(
        "/api/v1/users",
        json={"email": "new@example.com", "display_name": "New", "password": "pw123456"},
        headers=headers,
    )
    assert create.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "new@example.com", "password": "pw123456"},
    )
    assert login.status_code == 200
