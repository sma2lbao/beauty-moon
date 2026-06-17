"""Tests for AgentFactory."""
import pytest
from app.agent.factory import AgentFactory
from app.agent.registry import ToolRegistry
from app.agent.tool import Tool
from app.agent.modes.direct import DirectAgent
from app.agent.modes.react import ReActAgent
from app.agent.modes.plan_execute import PlanExecuteAgent
from app.agent.modes.langgraph import LangGraphAgent
from app.core.config import AgentMode


def test_factory_create_direct():
    """Test creating DirectAgent."""
    agent = AgentFactory.create(AgentMode.DIRECT)
    assert isinstance(agent, DirectAgent)


def test_factory_create_react():
    """Test creating ReActAgent."""
    agent = AgentFactory.create(AgentMode.REACT)
    assert isinstance(agent, ReActAgent)


def test_factory_create_plan():
    """Test creating PlanExecuteAgent."""
    agent = AgentFactory.create(AgentMode.PLAN)
    assert isinstance(agent, PlanExecuteAgent)


def test_factory_create_langgraph():
    """Test creating LangGraphAgent."""
    agent = AgentFactory.create(AgentMode.LANGGRAPH)
    assert isinstance(agent, LangGraphAgent)


def test_factory_with_tools():
    """Test creating agent with tools."""
    registry = ToolRegistry()
    registry.register(Tool(name="test", description="Test tool"))

    agent = AgentFactory.create(AgentMode.DIRECT, tools=registry)
    assert len(agent.get_available_tools()) == 1


def test_factory_with_tool_list():
    """Test creating agent with tool list."""
    tools = [Tool(name="tool1", description="Tool 1")]
    agent = AgentFactory.create(AgentMode.DIRECT, tools=tools)
    assert len(agent.get_available_tools()) == 1


def test_factory_max_steps():
    """Test agent max_steps configuration."""
    agent = AgentFactory.create(AgentMode.DIRECT, max_steps=5)
    assert agent.config.max_steps == 5


def test_factory_unknown_mode():
    """Test error on unknown mode."""
    with pytest.raises(ValueError, match="Unknown agent mode"):
        AgentFactory.create("unknown")  # type: ignore
