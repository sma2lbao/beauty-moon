"""Tests for request knowledge-base context."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.context import get_request_context
from app.db.models import Base, KnowledgeBase, Tenant, Workspace


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def create_context_records(db_session):
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="Research", slug="research", tenant=tenant)
    knowledge_base = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    db_session.add(knowledge_base)
    db_session.commit()
    return tenant, workspace, knowledge_base


@pytest.mark.parametrize(
    ("tenant_id", "workspace_id", "knowledge_base_id", "missing"),
    [
        (None, "workspace", "kb", "X-Tenant-Id"),
        ("tenant", None, "kb", "X-Workspace-Id"),
        ("tenant", "workspace", None, "X-Knowledge-Base-Id"),
    ],
)
def test_get_request_context_rejects_missing_headers(
    db_session,
    tenant_id,
    workspace_id,
    knowledge_base_id,
    missing,
):
    with pytest.raises(HTTPException) as exc_info:
        get_request_context(db_session, tenant_id, workspace_id, knowledge_base_id)

    assert exc_info.value.status_code == 400
    assert missing in exc_info.value.detail


def test_get_request_context_rejects_unknown_context(db_session):
    with pytest.raises(HTTPException) as exc_info:
        get_request_context(db_session, "missing", "missing", "missing")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Knowledge base context not found"


def test_get_request_context_rejects_workspace_tenant_mismatch(db_session):
    tenant, workspace, knowledge_base = create_context_records(db_session)
    other_tenant = Tenant(name="Other", slug="other")
    db_session.add(other_tenant)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_request_context(
            db_session,
            other_tenant.id,
            workspace.id,
            knowledge_base.id,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Knowledge base context not found"


def test_get_request_context_rejects_knowledge_base_workspace_mismatch(db_session):
    tenant, workspace, knowledge_base = create_context_records(db_session)
    other_workspace = Workspace(name="Other", slug="other", tenant_id=tenant.id)
    db_session.add(other_workspace)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_request_context(
            db_session,
            tenant.id,
            other_workspace.id,
            knowledge_base.id,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Knowledge base context not found"


def test_get_request_context_returns_valid_context(db_session):
    tenant, workspace, knowledge_base = create_context_records(db_session)

    context = get_request_context(
        db_session,
        tenant.id,
        workspace.id,
        knowledge_base.id,
    )

    assert context.tenant == tenant
    assert context.workspace == workspace
    assert context.knowledge_base == knowledge_base
