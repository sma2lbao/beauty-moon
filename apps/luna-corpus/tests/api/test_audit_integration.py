"""Integration tests: audited actions produce audit rows."""
from unittest.mock import patch

from app.auth.permissions import PermissionSlug
from app.db.models import AuditLog, AuditResult
from tests.api.test_file_upload import (  # noqa: F401
    _auth_headers,
    create_user_with_permissions,
)


def test_create_document_writes_audit(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "writer",
        [PermissionSlug.DOCUMENT_WRITE, PermissionSlug.WORKSPACE_READ,
         PermissionSlug.KNOWLEDGE_BASE_READ],
    )
    headers = _auth_headers(
        context, knowledge_base_id=context["kb_one_id"], user_id=user_id
    )
    resp = client.post(
        "/api/v1/documents",
        json={"title": "T", "content": "hello", "source": "test"},
        headers=headers,
    )
    assert resp.status_code == 201
    session = Session()
    row = session.query(AuditLog).filter(AuditLog.action == "document.create").one()
    assert row.result == AuditResult.SUCCESS
    assert row.actor_user_id == user_id
    assert row.resource_id == resp.json()["id"]


@patch("app.security.audit.SessionLocal")
def test_delete_missing_document_writes_failure_audit(
    mock_session_local, client, app_db
):
    _, Session, context = app_db
    mock_session_local.return_value = Session()
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "deleter",
        [PermissionSlug.DOCUMENT_DELETE, PermissionSlug.WORKSPACE_READ,
         PermissionSlug.KNOWLEDGE_BASE_READ],
    )
    headers = _auth_headers(
        context, knowledge_base_id=context["kb_one_id"], user_id=user_id
    )
    resp = client.delete("/api/v1/documents/does-not-exist", headers=headers)
    assert resp.status_code == 404
    session = Session()
    row = session.query(AuditLog).filter(AuditLog.action == "document.delete").one()
    assert row.result == AuditResult.FAILURE
