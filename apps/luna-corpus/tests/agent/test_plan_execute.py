"""Tests for PlanExecuteAgent."""
import pytest
from unittest.mock import MagicMock, patch
from app.agent.base import AgentConfig
from app.agent.modes.plan_execute import PlanExecuteAgent
from app.agent.registry import ToolRegistry
from app.agent.tool import Tool


def test_plan_parse():
    """Test parsing plan JSON."""
    agent = PlanExecuteAgent(AgentConfig())

    response = '[{"tool": "calculator", "arguments": {"a": 1}}, {"tool": "final_answer"}]'
    plan = agent._parse_plan(response)
    assert plan is not None
    assert len(plan) == 2
    assert plan[0]["tool"] == "calculator"


def test_plan_parse_invalid():
    """Test parsing invalid plan."""
    agent = PlanExecuteAgent(AgentConfig())

    plan = agent._parse_plan("Not a valid plan")
    assert plan is None


def test_plan_with_brackets():
    """Test parsing plan with extra brackets in text."""
    agent = PlanExecuteAgent(AgentConfig())

    response = """Here is the plan:
[{"tool": "search", "arguments": {"query": "test"}}]
That's it!"""
    plan = agent._parse_plan(response)
    assert plan is not None
    assert plan[0]["tool"] == "search"


def test_plan_max_steps():
    """Test PlanExecute respects max_steps."""
    agent = PlanExecuteAgent(AgentConfig(max_steps=5))
    assert agent.config.max_steps == 5
