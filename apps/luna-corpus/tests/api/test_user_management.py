"""Admin creates users via API; created users can log in."""
from tests.api.test_file_upload import (
    app_db,  # noqa: F401
    client,  # noqa: F401
    create_user_with_permissions,
    _auth_headers,
)
from app.auth.permissions import PermissionSlug, RoleSlug
from app.db.models import WorkspaceMembership


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


def test_created_user_bound_to_workspace_with_role(client, app_db):
    _, Session, context = app_db
    admin_id = create_user_with_permissions(
        Session, context["workspace_id"], "admin", [PermissionSlug.WORKSPACE_MANAGE]
    )
    headers = _auth_headers(context, knowledge_base_id=context["kb_one_id"], user_id=admin_id)
    create = client.post(
        "/api/v1/users",
        json={
            "email": "reader@example.com",
            "display_name": "Reader",
            "password": "pw123456",
            "role_slug": RoleSlug.KB_READER,
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["workspace_id"] == context["workspace_id"]
    assert body["role_slug"] == RoleSlug.KB_READER

    session = Session()
    try:
        membership = (
            session.query(WorkspaceMembership)
            .filter(
                WorkspaceMembership.user_id == body["id"],
                WorkspaceMembership.workspace_id == context["workspace_id"],
            )
            .first()
        )
        assert membership is not None
        assert membership.is_active is True
        role_slugs = {role.slug for role in membership.roles}
        assert RoleSlug.KB_READER in role_slugs
        # Role must carry the expected reader permissions in DB
        permissions = {
            perm.slug
            for role in membership.roles
            for perm in role.permissions
        }
        assert PermissionSlug.KNOWLEDGE_BASE_READ in permissions
        assert PermissionSlug.DOCUMENT_READ in permissions
    finally:
        session.close()


def test_created_user_can_access_permitted_endpoint(client, app_db):
    _, Session, context = app_db
    admin_id = create_user_with_permissions(
        Session, context["workspace_id"], "admin", [PermissionSlug.WORKSPACE_MANAGE]
    )
    headers = _auth_headers(context, knowledge_base_id=context["kb_one_id"], user_id=admin_id)
    create = client.post(
        "/api/v1/users",
        json={
            "email": "reader2@example.com",
            "display_name": "Reader2",
            "password": "pw123456",
            "role_slug": RoleSlug.KB_READER,
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "reader2@example.com", "password": "pw123456"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    reader_headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": context["kb_one_id"],
    }
    resp = client.get("/api/v1/knowledge-bases", headers=reader_headers)
    assert resp.status_code != 403, resp.text
    assert resp.status_code == 200


def test_create_user_short_password_rejected(client, app_db):
    _, Session, context = app_db
    admin_id = create_user_with_permissions(
        Session, context["workspace_id"], "admin", [PermissionSlug.WORKSPACE_MANAGE]
    )
    headers = _auth_headers(context, knowledge_base_id=context["kb_one_id"], user_id=admin_id)
    resp = client.post(
        "/api/v1/users",
        json={
            "email": "shortpw@example.com",
            "display_name": "Short",
            "password": "short",
            "role_slug": RoleSlug.KB_READER,
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text

