"""Tests for knowledge-base scoped conversation and QA APIs."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.permissions import PermissionSlug
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


def create_user_with_permissions(Session, workspace_id, label, permission_slugs):
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


def headers(context, knowledge_base_id, user_id):
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": knowledge_base_id,
    }


def test_create_conversation_binds_current_knowledge_base(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "conversation_writer",
        [PermissionSlug.CONVERSATION_READ, PermissionSlug.CONVERSATION_WRITE],
    )

    response = client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"], user_id),
        json={"title": "Chat"},
    )

    assert response.status_code == 201
    conversation = response.json()

    kb_one_response = client.get(
        f"/api/v1/conversations/{conversation['id']}",
        headers=headers(context, context["kb_one_id"], user_id),
    )
    kb_two_response = client.get(
        f"/api/v1/conversations/{conversation['id']}",
        headers=headers(context, context["kb_two_id"], user_id),
    )

    assert kb_one_response.status_code == 200
    assert kb_two_response.status_code == 404


def test_conversation_list_is_scoped_to_knowledge_base(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "conversation_lister",
        [PermissionSlug.CONVERSATION_READ, PermissionSlug.CONVERSATION_WRITE],
    )
    client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"], user_id),
        json={"title": "Chat"},
    )

    kb_one_response = client.get(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"], user_id),
    )
    kb_two_response = client.get(
        "/api/v1/conversations",
        headers=headers(context, context["kb_two_id"], user_id),
    )

    assert kb_one_response.status_code == 200
    assert kb_one_response.json()["total"] == 1
    assert kb_two_response.status_code == 200
    assert kb_two_response.json()["total"] == 0


def test_qa_query_passes_current_knowledge_base(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "qa_reader",
        [PermissionSlug.QA_QUERY],
    )

    with patch(
        "app.api.routes.answer_question",
        return_value={"answer": "Answer", "sources": [], "processing_time_ms": 1},
    ) as answer_question:
        response = client.post(
            "/api/v1/qa/query",
            headers=headers(context, context["kb_one_id"], user_id),
            json={"question": "What?"},
        )

    assert response.status_code == 200
    answer_question.assert_called_once_with(
        "What?",
        knowledge_base_id=context["kb_one_id"],
        filters=None,
        field_types=None,
    )


def test_conversation_reader_cannot_create_clear_or_delete_conversation(client, app_db):
    _, Session, context = app_db
    reader_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "conversation_reader",
        [PermissionSlug.CONVERSATION_READ],
    )
    writer_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "conversation_writer_for_reader_test",
        [
            PermissionSlug.CONVERSATION_READ,
            PermissionSlug.CONVERSATION_WRITE,
            PermissionSlug.CONVERSATION_DELETE,
        ],
    )
    conversation = client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"], writer_id),
        json={"title": "Chat"},
    ).json()

    create_response = client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"], reader_id),
        json={"title": "Forbidden"},
    )
    clear_response = client.post(
        f"/api/v1/conversations/{conversation['id']}/clear",
        headers=headers(context, context["kb_one_id"], reader_id),
    )
    delete_response = client.delete(
        f"/api/v1/conversations/{conversation['id']}",
        headers=headers(context, context["kb_one_id"], reader_id),
    )

    assert create_response.status_code == 403
    assert (
        create_response.json()["detail"]
        == "Missing required permission: conversation:write"
    )
    assert clear_response.status_code == 403
    assert (
        clear_response.json()["detail"]
        == "Missing required permission: conversation:write"
    )
    assert delete_response.status_code == 403
    assert (
        delete_response.json()["detail"]
        == "Missing required permission: conversation:delete"
    )


def test_multi_turn_requires_qa_and_conversation_write_permissions(client, app_db):
    _, Session, context = app_db
    qa_only_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "qa_only",
        [PermissionSlug.QA_QUERY],
    )

    response = client.post(
        "/api/v1/qa/multi-turn",
        headers=headers(context, context["kb_one_id"], qa_only_id),
        json={"question": "What?"},
    )

    assert response.status_code == 403
    assert (
        response.json()["detail"] == "Missing required permission: conversation:write"
    )


def test_multi_turn_rejects_cross_knowledge_base_conversation(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "multi_turn_user",
        [
            PermissionSlug.QA_QUERY,
            PermissionSlug.CONVERSATION_READ,
            PermissionSlug.CONVERSATION_WRITE,
        ],
    )
    conversation = client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"], user_id),
        json={"title": "Chat"},
    ).json()

    response = client.post(
        "/api/v1/qa/multi-turn",
        headers=headers(context, context["kb_two_id"], user_id),
        json={"question": "What?", "conversation_id": conversation["id"]},
    )

    assert response.status_code == 404
