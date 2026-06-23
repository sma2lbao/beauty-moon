"""Tests for ReActAgent."""

import ast
import asyncio
import operator
from unittest.mock import MagicMock, patch

import pytest

from app.agent.base import AgentConfig
from app.agent.modes.react import ReActAgent
from app.agent.registry import ToolRegistry
from app.agent.tool import tool


def _safe_eval(expression: str) -> str:
    """Safely evaluate a simple arithmetic expression using AST.

    Only allows numeric constants and basic arithmetic operators.
    """
    _ALLOWED_OPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def _eval_node(node):
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.BinOp):
            op = _ALLOWED_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            return op(_eval_node(node.left), _eval_node(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _ALLOWED_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            return op(_eval_node(node.operand))
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported expression element: {type(node).__name__}")

    tree = ast.parse(expression, mode="eval")
    return str(_eval_node(tree))


@pytest.fixture
def empty_registry():
    """Create an empty tool registry."""
    return ToolRegistry()


@pytest.fixture
def weather_registry():
    """Create a tool registry with a weather tool."""
    registry = ToolRegistry()

    @tool(name="get_weather", description="Get weather for a city")
    def get_weather(city: str) -> str:
        return f"Weather in {city}: Sunny, 25C"

    registry.register(get_weather)
    return registry


@pytest.fixture
def calculator_registry():
    """Create a tool registry with a calculator tool."""
    registry = ToolRegistry()

    @tool(name="calculator", description="Calculate math expressions")
    def calculator(expression: str) -> str:
        return _safe_eval(expression)

    registry.register(calculator)
    return registry


@pytest.fixture
def failing_tool_registry():
    """Create a registry with a tool that raises an error."""
    registry = ToolRegistry()

    @tool(name="crash", description="A tool that always fails")
    def crash() -> str:
        raise ValueError("Intentional failure")

    registry.register(crash)
    return registry


@pytest.fixture
def multi_tool_registry():
    """Create a registry with multiple tools."""
    registry = ToolRegistry()

    @tool(name="search", description="Search the web")
    def search(query: str) -> str:
        return f"Results for {query}"

    @tool(name="translate", description="Translate text")
    def translate(text: str, target_lang: str) -> str:
        return f"[{target_lang}] {text}"

    registry.register(search)
    registry.register(translate)
    return registry


class TestReActParseResponse:
    """Tests for _parse_response method."""

    def test_parse_action_response(self):
        """Parses a response with an action."""
        agent = ReActAgent(AgentConfig())
        response = (
            '{"thought": "Need to calculate", '
            '"action": {"name": "calculator", "arguments": {"expression": "2+2"}}}'
        )
        parsed = agent._parse_response(response)
        assert parsed is not None
        assert parsed["action"]["name"] == "calculator"
        assert parsed["action"]["arguments"] == {"expression": "2+2"}
        assert parsed["thought"] == "Need to calculate"

    def test_parse_answer_response(self):
        """Parses a final answer response."""
        agent = ReActAgent(AgentConfig())
        response = (
            '{"thought": "Done", "action": null, '
            '"observation": null, "answer": "The answer is 4"}'
        )
        parsed = agent._parse_response(response)
        assert parsed is not None
        assert parsed["answer"] == "The answer is 4"
        assert parsed["action"] is None

    def test_parse_invalid_json(self):
        """Returns None for invalid JSON."""
        agent = ReActAgent(AgentConfig())
        parsed = agent._parse_response("This is not JSON")
        assert parsed is None

    def test_parse_empty_string(self):
        """Returns None for empty string."""
        agent = ReActAgent(AgentConfig())
        parsed = agent._parse_response("")
        assert parsed is None

    def test_parse_json_with_surrounding_text(self):
        """Extracts JSON from within surrounding text."""
        agent = ReActAgent(AgentConfig())
        response = (
            "Let me think about this.\n"
            '{"thought": "Need to search", '
            '"action": {"name": "search", "arguments": {"query": "python"}}}\n'
            "Executing tool..."
        )
        parsed = agent._parse_response(response)
        assert parsed is not None
        assert parsed["action"]["name"] == "search"
        assert parsed["action"]["arguments"] == {"query": "python"}

    def test_parse_malformed_json(self):
        """Returns None for malformed JSON inside text."""
        agent = ReActAgent(AgentConfig())
        parsed = agent._parse_response('{"thought": "broken"')
        assert parsed is None

    def test_parse_response_with_observation(self):
        """Parses a response that includes an observation."""
        agent = ReActAgent(AgentConfig())
        response = (
            '{"thought": "Got result", '
            '"action": null, '
            '"observation": "The weather is sunny", '
            '"answer": null}'
        )
        parsed = agent._parse_response(response)
        assert parsed is not None
        assert parsed["observation"] == "The weather is sunny"


class TestReActConfig:
    """Tests for ReActAgent configuration."""

    def test_max_iterations_from_config(self):
        """Agent respects max_steps from config as max_iterations."""
        agent = ReActAgent(AgentConfig(max_steps=5))
        assert agent.max_iterations == 5

    def test_default_max_iterations(self):
        """Agent uses default max_steps (10) from AgentConfig."""
        agent = ReActAgent(AgentConfig())
        assert agent.max_iterations == 10

    def test_name_config(self):
        """Agent respects name config."""
        agent = ReActAgent(AgentConfig(name="react-agent"))
        assert agent.config.name == "react-agent"

    def test_registry_access(self, weather_registry):
        """Agent exposes tools through registry."""
        agent = ReActAgent(AgentConfig(tools=weather_registry))
        tools = agent.get_available_tools()
        assert len(tools) == 1
        assert tools[0].name == "get_weather"

    def test_tool_schemas_from_registry(self, multi_tool_registry):
        """Agent returns tool schemas from registry."""
        agent = ReActAgent(AgentConfig(tools=multi_tool_registry))
        schemas = agent.get_tool_schemas()
        assert len(schemas) == 2
        names = [s["function"]["name"] for s in schemas]
        assert "search" in names
        assert "translate" in names


class TestReActRunNoTools:
    """Tests for run() when no tools are needed."""

    def test_direct_answer_no_tools(self):
        """Agent returns answer directly when LLM gives answer."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content=(
                    '{"thought": "No tools needed", '
                    '"action": null, '
                    '"observation": null, '
                    '"answer": "Hello! How can I help you?"}'
                )
            )
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=ToolRegistry()))
            response = asyncio.run(agent.run("Hello!"))
            assert "Hello" in response.answer
            assert len(response.tool_calls) == 0
            assert response.steps == 1
            assert response.latency_ms >= 0

    def test_empty_registry_no_tools(self):
        """Agent works with no registered tools."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content=(
                    '{"thought": "No tools available", '
                    '"action": null, '
                    '"answer": "I cannot help with that."}'
                )
            )
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=ToolRegistry()))
            response = asyncio.run(agent.run("Help"))
            assert response.answer == "I cannot help with that."
            assert len(response.tool_calls) == 0


class TestReActRunWithToolCall:
    """Tests for run() with tool call execution."""

    def test_single_tool_call_then_answer(self, calculator_registry):
        """Agent calls a tool once then returns answer."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(
                    content=(
                        '{"thought": "Need to calculate", '
                        '"action": {"name": "calculator", '
                        '"arguments": {"expression": "2+2"}}}'
                    )
                ),
                MagicMock(
                    content=(
                        '{"thought": "Got result", '
                        '"action": null, '
                        '"answer": "2 + 2 = 4"}'
                    )
                ),
            ]
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=calculator_registry))
            response = asyncio.run(agent.run("What is 2+2?"))

            assert len(response.tool_calls) == 1
            assert response.tool_calls[0]["tool"] == "calculator"
            assert response.tool_calls[0]["args"] == {"expression": "2+2"}
            assert response.tool_calls[0]["success"] is True
            assert response.tool_calls[0]["result"] == "4"
            assert "4" in response.answer
            assert response.steps == 2

    def test_multi_step_tool_calls(self, multi_tool_registry):
        """Agent makes multiple tool calls across iterations."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(
                    content=(
                        '{"thought": "Search first", '
                        '"action": {"name": "search", '
                        '"arguments": {"query": "python"}}}'
                    )
                ),
                MagicMock(
                    content=(
                        '{"thought": "Now translate", '
                        '"action": {"name": "translate", '
                        '"arguments": {"text": "hello", "target_lang": "fr"}}}'
                    )
                ),
                MagicMock(
                    content=(
                        '{"thought": "All done", '
                        '"action": null, '
                        '"answer": "Here is the translated result."}'
                    )
                ),
            ]
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=multi_tool_registry))
            response = asyncio.run(agent.run("Search and translate"))

            assert len(response.tool_calls) == 2
            assert response.tool_calls[0]["tool"] == "search"
            assert response.tool_calls[1]["tool"] == "translate"
            assert response.steps == 3

    def test_tool_not_found(self, weather_registry):
        """Agent handles tool not found gracefully."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(
                    content=(
                        '{"thought": "Try unknown tool", '
                        '"action": {"name": "nonexistent", "arguments": {}}}'
                    )
                ),
                MagicMock(
                    content=(
                        '{"thought": "Tool failed, answer directly", '
                        '"action": null, '
                        '"answer": "I could not find that tool."}'
                    )
                ),
            ]
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=weather_registry))
            response = asyncio.run(agent.run("Do something"))

            assert "I could not find that tool" in response.answer
            assert response.steps >= 1

    def test_tool_execution_failure(self, failing_tool_registry):
        """Agent handles tool execution failure gracefully."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(
                    content=(
                        '{"thought": "Try crash tool", '
                        '"action": {"name": "crash", "arguments": {}}}'
                    )
                ),
                MagicMock(
                    content=(
                        '{"thought": "Tool failed", '
                        '"action": null, '
                        '"answer": "The tool encountered an error."}'
                    )
                ),
            ]
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=failing_tool_registry))
            response = asyncio.run(agent.run("Crash test"))

            assert len(response.tool_calls) == 1
            assert response.tool_calls[0]["tool"] == "crash"
            assert response.tool_calls[0]["success"] is False


class TestReActMaxIterations:
    """Tests for max_iterations behavior."""

    def test_stops_at_max_iterations(self, calculator_registry):
        """Agent stops after max_iterations even without answer."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            # Always return an action (never an answer)
            chat.invoke.return_value = MagicMock(
                content=(
                    '{"thought": "Keep calculating", '
                    '"action": {"name": "calculator", '
                    '"arguments": {"expression": "1+1"}}}'
                )
            )
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=calculator_registry, max_steps=3))
            response = asyncio.run(agent.run("Calculate something"))

            # Should stop after 3 iterations
            assert response.steps <= 3
            assert response.tool_calls is not None
            assert response.answer is not None  # Should have some answer

    def test_exactly_max_iterations_with_answer(self, calculator_registry):
        """Agent can answer on the last allowed iteration."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            responses = []
            # First 2 iterations: tool calls
            for i in range(2):
                responses.append(
                    MagicMock(
                        content=(
                            '{"thought": "Step ' + str(i) + '", '
                            '"action": {"name": "calculator", '
                            '"arguments": {"expression": "1"}}}'
                        )
                    )
                )
            # 3rd iteration: answer
            responses.append(
                MagicMock(
                    content=(
                        '{"thought": "Final answer", '
                        '"action": null, '
                        '"answer": "Done after 3 steps."}'
                    )
                )
            )
            chat.invoke.side_effect = responses
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=calculator_registry, max_steps=3))
            response = asyncio.run(agent.run("Test"))

            assert response.answer == "Done after 3 steps."
            assert response.steps == 3
            assert len(response.tool_calls) == 2


class TestReActRunStream:
    """Tests for run_stream method."""

    @pytest.mark.asyncio
    async def test_stream_direct_answer(self):
        """Stream yields expected events for direct answer."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content=(
                    '{"thought": "Simple question", '
                    '"action": null, '
                    '"answer": "The answer is 42."}'
                )
            )
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=ToolRegistry()))
            events = []
            async for event in agent.run_stream("What is the answer?"):
                events.append(event)

            event_types = [e["event"] for e in events]
            assert "start" in event_types
            assert "thought" in event_types
            assert "done" in event_types

            done_event = next(e for e in events if e["event"] == "done")
            assert done_event["data"]["answer"] == "The answer is 42."
            assert len(done_event["data"]["tool_calls"]) == 0

    @pytest.mark.asyncio
    async def test_stream_with_tool_call(self, weather_registry):
        """Stream yields tool_call and tool_result events."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(
                    content=(
                        '{"thought": "Check weather", '
                        '"action": {"name": "get_weather", '
                        '"arguments": {"city": "Paris"}}}'
                    )
                ),
                MagicMock(
                    content=(
                        '{"thought": "Got weather", '
                        '"action": null, '
                        '"answer": "It is sunny in Paris."}'
                    )
                ),
            ]
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=weather_registry))
            events = []
            async for event in agent.run_stream("Weather in Paris?"):
                events.append(event)

            event_types = [e["event"] for e in events]
            assert "start" in event_types
            assert "thought" in event_types
            assert "tool_call" in event_types
            assert "tool_result" in event_types
            assert "done" in event_types

            tool_call_event = next(e for e in events if e["event"] == "tool_call")
            assert tool_call_event["data"]["tool"] == "get_weather"
            assert tool_call_event["data"]["args"] == {"city": "Paris"}

            tool_result_event = next(e for e in events if e["event"] == "tool_result")
            assert "Paris" in tool_result_event["data"]["result"]

            done_event = next(e for e in events if e["event"] == "done")
            assert len(done_event["data"]["tool_calls"]) == 1

    @pytest.mark.asyncio
    async def test_stream_tool_not_found(self, weather_registry):
        """Stream handles unknown tool gracefully."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(
                    content=(
                        '{"thought": "Try unknown", '
                        '"action": {"name": "no_such_tool", "arguments": {}}}'
                    )
                ),
                MagicMock(
                    content=(
                        '{"thought": "Fallback", '
                        '"action": null, '
                        '"answer": "Tool not available."}'
                    )
                ),
            ]
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=weather_registry))
            events = []
            async for event in agent.run_stream("Do something"):
                events.append(event)

            event_types = [e["event"] for e in events]
            assert "start" in event_types
            assert "done" in event_types

    @pytest.mark.asyncio
    async def test_stream_stops_at_max_iterations(self, calculator_registry):
        """Stream stops after max_iterations."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content=(
                    '{"thought": "Keep going", '
                    '"action": {"name": "calculator", '
                    '"arguments": {"expression": "1+1"}}}'
                )
            )
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=calculator_registry, max_steps=2))
            events = []
            async for event in agent.run_stream("Calculate"):
                events.append(event)

            event_types = [e["event"] for e in events]
            assert "start" in event_types
            assert "done" in event_types
            # Should not exceed 2 iterations
            thought_count = sum(1 for e in events if e["event"] == "thought")
            assert thought_count <= 2


class TestReActEdgeCases:
    """Edge case tests for ReActAgent."""

    def test_latency_is_recorded(self, empty_registry):
        """Agent records execution latency."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content=(
                    '{"thought": "Fast", "action": null, "answer": "Quick response."}'
                )
            )
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=empty_registry))
            response = asyncio.run(agent.run("Test"))
            assert response.latency_ms >= 0

    def test_response_with_no_action_no_answer(self, weather_registry):
        """Agent handles response with neither action nor answer."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content=(
                    '{"thought": "Just thinking", "action": null, "observation": null}'
                )
            )
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=weather_registry))
            response = asyncio.run(agent.run("Hello"))
            assert response.answer is not None
            assert response.steps >= 1

    def test_unparseable_response_fallback(self, weather_registry):
        """Agent falls back to raw content when response is unparseable."""
        with patch("app.agent.modes.react.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content="I think the answer is 42, but I'm not using JSON."
            )
            mock.return_value = chat

            agent = ReActAgent(AgentConfig(tools=weather_registry))
            response = asyncio.run(agent.run("What is the answer?"))
            assert response.answer is not None
            assert "42" in response.answer or response.answer != ""
