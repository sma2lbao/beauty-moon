"""Tests for Agent API."""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


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
