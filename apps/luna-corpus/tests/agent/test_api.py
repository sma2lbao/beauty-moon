"""Tests for Agent API."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.base import AgentResponse
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
    knowledge_base = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    session.add(knowledge_base)
    session.commit()

    context = {
        "tenant_id": tenant.id,
        "workspace_id": workspace.id,
        "knowledge_base_id": knowledge_base.id,
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


@pytest.fixture
def mock_agent():
    """Mock agent to avoid LLM calls."""

    async def stream_events(_query):
        yield {"event": "done", "data": {"answer": "Mocked stream"}}

    mock = AsyncMock()
    mock.run.return_value = AgentResponse(
        answer="Mocked response",
        tool_calls=[],
        steps=1,
        latency_ms=100,
    )
    mock.run_stream = stream_events
    return mock


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


def headers(context, user_id):
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": context["knowledge_base_id"],
    }


def test_list_modes_requires_authenticated_knowledge_base_context(client):
    """Agent modes require authenticated KB context."""
    response = client.get("/api/v1/agent/modes")

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "Missing required header: X-Tenant-Id, X-Workspace-Id, X-Knowledge-Base-Id"
    )


def test_list_tools_requires_knowledge_base_read_permission(client, app_db):
    """Listing tools requires knowledge_base:read."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "qa_only_tools",
        [PermissionSlug.QA_QUERY],
    )

    response = client.get("/api/v1/agent/tools", headers=headers(context, user_id))

    assert response.status_code == 403
    assert (
        response.json()["detail"] == "Missing required permission: knowledge_base:read"
    )


def test_register_tool_requires_knowledge_base_manage_permission(client, app_db):
    """Registering tools requires knowledge_base:manage."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "kb_reader",
        [PermissionSlug.KNOWLEDGE_BASE_READ],
    )

    response = client.post(
        "/api/v1/agent/tools",
        headers=headers(context, user_id),
        json={
            "name": "test_tool",
            "description": "A test tool",
            "parameters_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        },
    )

    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "Missing required permission: knowledge_base:manage"
    )


def test_query_requires_qa_query_permission(client, app_db):
    """Agent query requires qa:query."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "kb_reader_query",
        [PermissionSlug.KNOWLEDGE_BASE_READ],
    )

    response = client.post(
        "/api/v1/agent/query",
        headers=headers(context, user_id),
        json={"query": "Hello", "mode": "direct"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing required permission: qa:query"


def test_stream_requires_qa_query_permission(client, app_db):
    """Agent stream requires qa:query."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "kb_reader_stream",
        [PermissionSlug.KNOWLEDGE_BASE_READ],
    )

    response = client.post(
        "/api/v1/agent/stream",
        headers=headers(context, user_id),
        json={"query": "Hello", "mode": "direct"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing required permission: qa:query"


def test_list_modes(client, app_db):
    """Test listing agent modes."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "mode_reader",
        [PermissionSlug.KNOWLEDGE_BASE_READ],
    )

    response = client.get("/api/v1/agent/modes", headers=headers(context, user_id))

    assert response.status_code == 200
    data = response.json()
    assert "modes" in data
    assert len(data["modes"]) == 4


def test_list_tools(client, app_db):
    """Test listing available tools."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "tool_reader",
        [PermissionSlug.KNOWLEDGE_BASE_READ],
    )

    response = client.get("/api/v1/agent/tools", headers=headers(context, user_id))

    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert len(data["tools"]) >= 3  # At least rag_search, calculator, current_time
    rag_tool = next(tool for tool in data["tools"] if tool["name"] == "rag_search")
    assert "knowledge_base_id" not in rag_tool["parameters_schema"]["properties"]


def test_register_tool(client, app_db):
    """Test registering a new tool."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "tool_manager",
        [PermissionSlug.KNOWLEDGE_BASE_MANAGE],
    )

    response = client.post(
        "/api/v1/agent/tools",
        headers=headers(context, user_id),
        json={
            "name": "test_tool",
            "description": "A test tool",
            "parameters_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        },
    )

    assert response.status_code == 200
    assert "test_tool" in response.json()["name"]


def test_invalid_mode(client, app_db):
    """Test error on invalid mode."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "qa_invalid_mode",
        [PermissionSlug.QA_QUERY],
    )

    response = client.post(
        "/api/v1/agent/query",
        headers=headers(context, user_id),
        json={"query": "Hello", "mode": "invalid_mode"},
    )

    assert response.status_code == 400


def test_query_empty_tools_uses_scoped_default_registry(client, app_db):
    """When available_tools is omitted, default tools should be scoped to current KB."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "qa_default_tools",
        [PermissionSlug.QA_QUERY],
    )

    with patch("app.api.agent_routes.AgentFactory.create") as mock_create:
        mock_agent = AsyncMock()
        mock_agent.run.return_value = AgentResponse(
            answer="ok",
            tool_calls=[],
            steps=1,
            latency_ms=100,
        )
        mock_create.return_value = mock_agent

        response = client.post(
            "/api/v1/agent/query",
            headers=headers(context, user_id),
            json={"query": "Hello", "mode": "direct"},
        )
        assert response.status_code == 200

        registry = mock_create.call_args.kwargs["tools"]
        assert len(registry) >= 3, f"Expected >=3 default tools, got {len(registry)}"
        rag_tool = registry.get("rag_search")
        assert rag_tool is not None
        with (
            patch("app.agent.tools.rag_search.embed_text", return_value=[0.1]),
            patch(
                "app.agent.tools.rag_search.hybrid_search", return_value=[]
            ) as search,
        ):
            rag_tool.executor(query="What?")
        search.assert_called_once_with(
            "What?", [0.1], top_k=5, knowledge_base_id=context["knowledge_base_id"]
        )


def test_query_empty_list_sends_empty_registry(client, app_db):
    """When available_tools=[], agent should receive no tools."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "qa_empty_tools",
        [PermissionSlug.QA_QUERY],
    )

    with patch("app.api.agent_routes.AgentFactory.create") as mock_create:
        mock_agent = AsyncMock()
        mock_agent.run.return_value = AgentResponse(
            answer="ok",
            tool_calls=[],
            steps=1,
            latency_ms=100,
        )
        mock_create.return_value = mock_agent

        response = client.post(
            "/api/v1/agent/query",
            headers=headers(context, user_id),
            json={"query": "Hello", "mode": "direct", "available_tools": []},
        )
        assert response.status_code == 200

        registry = mock_create.call_args.kwargs["tools"]
        assert len(registry) == 0, f"Expected 0 tools, got {len(registry)}"


def test_stream_empty_list_sends_empty_registry(client, app_db):
    """When available_tools=[], stream should also receive no tools."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "qa_stream_empty_tools",
        [PermissionSlug.QA_QUERY],
    )

    with patch("app.api.agent_routes.AgentFactory.create") as mock_create:

        async def stream_events(_query):
            yield {"event": "done", "data": {"answer": "ok"}}

        mock_agent = AsyncMock()
        mock_agent.run_stream = stream_events
        mock_create.return_value = mock_agent

        response = client.post(
            "/api/v1/agent/stream",
            headers=headers(context, user_id),
            json={"query": "Hello", "mode": "direct", "available_tools": []},
        )
        assert response.status_code == 200

        registry = mock_create.call_args.kwargs["tools"]
        assert len(registry) == 0, f"Expected 0 tools, got {len(registry)}"
