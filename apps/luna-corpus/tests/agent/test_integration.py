"""Integration tests for Agent module."""
import pytest
from unittest.mock import MagicMock, patch
from app.agent.factory import AgentFactory
from app.agent.registry import ToolRegistry
from app.agent.tool import Tool, tool
from app.agent.base import AgentResponse
from app.core.config import AgentMode


def test_all_modes_can_be_created():
    """Test all agent modes can be created."""
    registry = ToolRegistry()

    for mode in AgentMode:
        agent = AgentFactory.create(mode, tools=registry)
        assert agent is not None


def test_tool_execution_flow():
    """Test complete tool execution flow."""
    registry = ToolRegistry()

    @tool(name="test", description="Test tool")
    def test_tool(value: str) -> str:
        return f"Processed: {value}"

    registry.register(test_tool)
    agent = AgentFactory.create(AgentMode.DIRECT, tools=registry)

    assert "test" in [t.name for t in agent.get_available_tools()]
    assert len(agent.get_tool_schemas()) == 1


def test_registry_tools_isolation():
    """Test tools are isolated between agents."""
    registry1 = ToolRegistry()
    registry2 = ToolRegistry()

    @tool(name="tool1", description="Tool 1")
    def tool1() -> str:
        return "tool1"

    registry1.register(tool1)

    agent1 = AgentFactory.create(AgentMode.DIRECT, tools=registry1)
    agent2 = AgentFactory.create(AgentMode.DIRECT, tools=registry2)

    assert len(agent1.get_available_tools()) == 1
    assert len(agent2.get_available_tools()) == 0


def test_agent_response_structure():
    """Test AgentResponse has correct structure."""
    response = AgentResponse(
        answer="Test answer",
        tool_calls=[{"tool": "test", "args": {}}],
        steps=1,
        latency_ms=100,
    )

    assert response.answer == "Test answer"
    assert len(response.tool_calls) == 1
    assert response.steps == 1
    assert response.latency_ms == 100
