"""Regression: forged headers must not authenticate; only valid tokens pass."""
from tests.api.test_file_upload import (
    app_db,  # noqa: F401
    client,  # noqa: F401
    create_user_with_permissions,
)
from app.auth.permissions import PermissionSlug


def test_forged_x_user_id_is_rejected(client, app_db):
    """A raw X-User-Id header must no longer grant access."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session, context["workspace_id"], "reader", [PermissionSlug.DOCUMENT_READ]
    )
    resp = client.get(
        "/api/v1/documents",
        headers={
            "X-User-Id": user_id,  # forged legacy header, no bearer token
            "X-Tenant-Id": context["tenant_id"],
            "X-Workspace-Id": context["workspace_id"],
            "X-Knowledge-Base-Id": context["kb_one_id"],
        },
    )
    assert resp.status_code == 401


def test_valid_bearer_token_is_accepted(client, app_db):
    from app.auth.tokens import create_access_token

    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session, context["workspace_id"], "reader", [PermissionSlug.DOCUMENT_READ]
    )
    resp = client.get(
        "/api/v1/documents",
        headers={
            "Authorization": f"Bearer {create_access_token(user_id)}",
            "X-Tenant-Id": context["tenant_id"],
            "X-Workspace-Id": context["workspace_id"],
            "X-Knowledge-Base-Id": context["kb_one_id"],
        },
    )
    assert resp.status_code == 200
