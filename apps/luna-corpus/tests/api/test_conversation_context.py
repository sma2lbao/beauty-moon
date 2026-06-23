"""Tests for knowledge-base scoped conversation and QA APIs."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, KnowledgeBase, Tenant, Workspace
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


def headers(context, knowledge_base_id):
    return {
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": knowledge_base_id,
    }


def test_create_conversation_binds_current_knowledge_base(client, app_db):
    _, _, context = app_db

    response = client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"]),
        json={"title": "Chat"},
    )

    assert response.status_code == 201
    conversation = response.json()

    kb_one_response = client.get(
        f"/api/v1/conversations/{conversation['id']}",
        headers=headers(context, context["kb_one_id"]),
    )
    kb_two_response = client.get(
        f"/api/v1/conversations/{conversation['id']}",
        headers=headers(context, context["kb_two_id"]),
    )

    assert kb_one_response.status_code == 200
    assert kb_two_response.status_code == 404


def test_conversation_list_is_scoped_to_knowledge_base(client, app_db):
    _, _, context = app_db
    client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"]),
        json={"title": "Chat"},
    )

    kb_one_response = client.get(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"]),
    )
    kb_two_response = client.get(
        "/api/v1/conversations",
        headers=headers(context, context["kb_two_id"]),
    )

    assert kb_one_response.status_code == 200
    assert kb_one_response.json()["total"] == 1
    assert kb_two_response.status_code == 200
    assert kb_two_response.json()["total"] == 0


def test_qa_query_passes_current_knowledge_base(client, app_db):
    _, _, context = app_db

    with patch(
        "app.api.routes.answer_question",
        return_value={"answer": "Answer", "sources": [], "processing_time_ms": 1},
    ) as answer_question:
        response = client.post(
            "/api/v1/qa/query",
            headers=headers(context, context["kb_one_id"]),
            json={"question": "What?"},
        )

    assert response.status_code == 200
    answer_question.assert_called_once_with(
        "What?", knowledge_base_id=context["kb_one_id"]
    )


def test_multi_turn_rejects_cross_knowledge_base_conversation(client, app_db):
    _, _, context = app_db
    conversation = client.post(
        "/api/v1/conversations",
        headers=headers(context, context["kb_one_id"]),
        json={"title": "Chat"},
    ).json()

    response = client.post(
        "/api/v1/qa/multi-turn",
        headers=headers(context, context["kb_two_id"]),
        json={"question": "What?", "conversation_id": conversation["id"]},
    )

    assert response.status_code == 404
