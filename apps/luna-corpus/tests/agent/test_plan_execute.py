"""Tests for PlanExecuteAgent."""
import json
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


@pytest.mark.asyncio
async def test_plan_max_steps():
    """Test PlanExecute enforces max_steps during execution."""
    # Register tools that return simple results
    registry = ToolRegistry()
    registry.register(Tool(
        name="step_tool",
        description="A test step tool",
        parameters_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
        },
        executor=lambda value: f"result:{value}",
    ))

    agent = PlanExecuteAgent(AgentConfig(max_steps=2, tools=registry))
    assert agent.config.max_steps == 2

    # Mock LLM: plan with 5 steps, none are final_answer
    mock_plan = MagicMock()
    mock_plan.content = json.dumps([
        {"tool": "step_tool", "arguments": {"value": "a"}, "reasoning": "step 1"},
        {"tool": "step_tool", "arguments": {"value": "b"}, "reasoning": "step 2"},
        {"tool": "step_tool", "arguments": {"value": "c"}, "reasoning": "step 3"},
        {"tool": "step_tool", "arguments": {"value": "d"}, "reasoning": "step 4"},
        {"tool": "step_tool", "arguments": {"value": "e"}, "reasoning": "step 5"},
    ])
    mock_final = MagicMock()
    mock_final.content = "All done"

    mock_chat = MagicMock()
    mock_chat.invoke.side_effect = [mock_plan, mock_final]

    with patch("app.agent.modes.plan_execute.get_chat_model", return_value=mock_chat):
        result = await agent.run("do many things")

    assert result.answer == "All done"
    # Only 2 steps should have been executed, not all 5
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0]["tool"] == "step_tool"
    assert result.tool_calls[1]["tool"] == "step_tool"
