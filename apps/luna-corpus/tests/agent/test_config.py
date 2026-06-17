"""Tests for agent configuration."""
from app.core.config import AgentMode, Settings, get_settings


def test_agent_mode_enum():
    """Test AgentMode enum values."""
    assert AgentMode.DIRECT.value == "direct"
    assert AgentMode.REACT.value == "react"
    assert AgentMode.PLAN.value == "plan"
    assert AgentMode.LANGGRAPH.value == "langgraph"


def test_default_agent_settings():
    """Test default agent settings."""
    settings = Settings()
    assert settings.agent_default_mode == "direct"
    assert settings.agent_max_steps == 10
    assert settings.agent_react_max_iterations == 5
    assert settings.agent_plan_max_steps == 10
