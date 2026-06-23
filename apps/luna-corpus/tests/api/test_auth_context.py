"""Tests for authenticated request context and RBAC checks."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.auth import get_authenticated_context
from app.auth.permissions import PermissionSlug
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


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def create_auth_records(db_session, *, user_active=True, membership_active=True, permission_slugs=None):
    permission_slugs = permission_slugs or [PermissionSlug.DOCUMENT_READ]
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="Research", slug="research", tenant=tenant)
    knowledge_base = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    user = User(
        email="reader@example.com",
        display_name="Reader",
        is_active=user_active,
    )
    permissions = [
        Permission(name=slug, slug=slug, description=slug)
        for slug in permission_slugs
    ]
    role = Role(name="Role", slug="test_role", is_system=True, permissions=permissions)
    membership = WorkspaceMembership(
        user=user,
        workspace=workspace,
        is_active=membership_active,
        roles=[role],
    )
    db_session.add_all([knowledge_base, membership])
    db_session.commit()
    return tenant, workspace, knowledge_base, user, membership


def test_get_authenticated_context_rejects_missing_user_header(db_session):
    tenant, workspace, knowledge_base, _, _ = create_auth_records(db_session)

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            None,
            tenant.id,
            workspace.id,
            knowledge_base.id,
            [PermissionSlug.DOCUMENT_READ],
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Missing required header: X-User-Id"


def test_get_authenticated_context_rejects_unknown_user(db_session):
    tenant, workspace, knowledge_base, _, _ = create_auth_records(db_session)

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            "missing-user",
            tenant.id,
            workspace.id,
            knowledge_base.id,
            [PermissionSlug.DOCUMENT_READ],
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "User not found"


def test_get_authenticated_context_rejects_inactive_user(db_session):
    tenant, workspace, knowledge_base, user, _ = create_auth_records(
        db_session, user_active=False
    )

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            user.id,
            tenant.id,
            workspace.id,
            knowledge_base.id,
            [PermissionSlug.DOCUMENT_READ],
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "User is inactive"


def test_get_authenticated_context_rejects_missing_workspace_membership(db_session):
    tenant, workspace, knowledge_base, _, _ = create_auth_records(db_session)
    other_user = User(email="other@example.com", display_name="Other")
    db_session.add(other_user)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            other_user.id,
            tenant.id,
            workspace.id,
            knowledge_base.id,
            [PermissionSlug.DOCUMENT_READ],
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Workspace membership required"


def test_get_authenticated_context_rejects_inactive_membership(db_session):
    tenant, workspace, knowledge_base, user, _ = create_auth_records(
        db_session, membership_active=False
    )

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            user.id,
            tenant.id,
            workspace.id,
            knowledge_base.id,
            [PermissionSlug.DOCUMENT_READ],
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Workspace membership is inactive"


def test_get_authenticated_context_rejects_missing_permission(db_session):
    tenant, workspace, knowledge_base, user, _ = create_auth_records(
        db_session, permission_slugs=[PermissionSlug.DOCUMENT_READ]
    )

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            user.id,
            tenant.id,
            workspace.id,
            knowledge_base.id,
            [PermissionSlug.DOCUMENT_WRITE],
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Missing required permission: document:write"


def test_get_authenticated_context_returns_effective_permissions(db_session):
    tenant, workspace, knowledge_base, user, membership = create_auth_records(
        db_session,
        permission_slugs=[PermissionSlug.DOCUMENT_READ, PermissionSlug.QA_QUERY],
    )

    context = get_authenticated_context(
        db_session,
        user.id,
        tenant.id,
        workspace.id,
        knowledge_base.id,
        [PermissionSlug.DOCUMENT_READ],
    )

    assert context.user == user
    assert context.tenant == tenant
    assert context.workspace == workspace
    assert context.knowledge_base == knowledge_base
    assert context.membership == membership
    assert context.permissions == frozenset({PermissionSlug.DOCUMENT_READ, PermissionSlug.QA_QUERY})


def test_get_authenticated_context_rejects_cross_workspace_access(db_session):
    tenant, workspace, knowledge_base, user, _ = create_auth_records(db_session)
    other_workspace = Workspace(name="Other", slug="other", tenant=tenant)
    other_knowledge_base = KnowledgeBase(name="Other Docs", slug="other-docs", workspace=other_workspace)
    db_session.add(other_knowledge_base)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_authenticated_context(
            db_session,
            user.id,
            tenant.id,
            other_workspace.id,
            other_knowledge_base.id,
            [PermissionSlug.DOCUMENT_READ],
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Workspace membership required"
