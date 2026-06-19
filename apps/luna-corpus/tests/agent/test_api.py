"""Tests for Agent API."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agent.base import AgentResponse
from app.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_agent():
    """Mock agent to avoid LLM calls."""
    mock = AsyncMock()
    mock.run.return_value = AgentResponse(
        answer="Mocked response",
        tool_calls=[],
        steps=1,
        latency_ms=100,
    )
    mock.run_stream.return_value = AsyncMock()
    mock.run_stream.return_value.__aiter__.return_value = [
        {"event": "done", "data": {"answer": "Mocked stream"}},
    ]
    return mock


def test_list_modes(client):
    """Test listing agent modes."""
    response = client.get("/api/v1/agent/modes")
    assert response.status_code == 200
    data = response.json()
    assert "modes" in data
    assert len(data["modes"]) == 4


def test_list_tools(client):
    """Test listing available tools."""
    response = client.get("/api/v1/agent/tools")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert len(data["tools"]) >= 3  # At least rag_search, calculator, current_time


def test_register_tool(client):
    """Test registering a new tool."""
    response = client.post(
        "/api/v1/agent/tools",
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


def test_invalid_mode(client):
    """Test error on invalid mode."""
    response = client.post(
        "/api/v1/agent/query",
        json={"query": "Hello", "mode": "invalid_mode"},
    )
    assert response.status_code == 400


def test_query_empty_tools_uses_default_registry(client):
    """When available_tools is omitted, default tools should be used."""
    with patch("app.api.agent_routes.AgentFactory.create") as mock_create:
        mock_agent = AsyncMock()
        mock_agent.run.return_value = AgentResponse(
            answer="ok", tool_calls=[], steps=1, latency_ms=100,
        )
        mock_create.return_value = mock_agent

        response = client.post(
            "/api/v1/agent/query",
            json={"query": "Hello", "mode": "direct"},
        )
        assert response.status_code == 200

        # Verify factory was called with the default (populated) registry
        call_args = mock_create.call_args
        registry = call_args.kwargs["tools"]
        assert len(registry) >= 3, f"Expected >=3 default tools, got {len(registry)}"


def test_query_empty_list_sends_empty_registry(client):
    """When available_tools=[], agent should receive no tools."""
    with patch("app.api.agent_routes.AgentFactory.create") as mock_create:
        mock_agent = AsyncMock()
        mock_agent.run.return_value = AgentResponse(
            answer="ok", tool_calls=[], steps=1, latency_ms=100,
        )
        mock_create.return_value = mock_agent

        response = client.post(
            "/api/v1/agent/query",
            json={"query": "Hello", "mode": "direct", "available_tools": []},
        )
        assert response.status_code == 200

        call_args = mock_create.call_args
        registry = call_args.kwargs["tools"]
        assert len(registry) == 0, f"Expected 0 tools, got {len(registry)}"


def test_stream_empty_list_sends_empty_registry(client):
    """When available_tools=[], stream should also receive no tools."""
    with patch("app.api.agent_routes.AgentFactory.create") as mock_create:
        mock_agent = AsyncMock()
        mock_agent.run_stream.return_value = AsyncMock()
        mock_agent.run_stream.return_value.__aiter__.return_value = [
            {"event": "done", "data": {"answer": "ok"}},
        ]
        mock_create.return_value = mock_agent

        response = client.post(
            "/api/v1/agent/stream",
            json={"query": "Hello", "mode": "direct", "available_tools": []},
        )
        assert response.status_code == 200

        call_args = mock_create.call_args
        registry = call_args.kwargs["tools"]
        assert len(registry) == 0, f"Expected 0 tools, got {len(registry)}"
