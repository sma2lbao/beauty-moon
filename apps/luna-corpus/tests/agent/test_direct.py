"""Tests for DirectAgent."""
import asyncio
import pytest
from unittest.mock import MagicMock, patch

from app.agent.base import AgentConfig
from app.agent.modes.direct import DirectAgent
from app.agent.registry import ToolRegistry
from app.agent.tool import tool


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
        return f"Weather in {city}: Sunny, 25°C"

    registry.register(get_weather)
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


class TestDirectAgentNoToolCall:
    """Tests for DirectAgent when no tool call is needed."""

    def test_simple_question_no_tools(self):
        """Agent answers directly when no tool call needed."""
        with patch("app.agent.modes.direct.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(content="Hello! How can I help you?")
            mock.return_value = chat

            agent = DirectAgent(AgentConfig(tools=ToolRegistry()))
            response = asyncio.run(agent.run("Hello!"))
            assert "Hello" in response.answer
            assert len(response.tool_calls) == 0
            assert response.steps >= 1
            assert response.latency_ms >= 0

    def test_simple_question_with_tools_available(self):
        """Agent answers directly even when tools exist but aren't needed."""
        with patch("app.agent.modes.direct.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(content="2 + 2 equals 4.")
            mock.return_value = chat

            registry = ToolRegistry()

            @tool(name="search", description="Search the web")
            def search(query: str) -> str:
                return f"Results for {query}"

            registry.register(search)
            agent = DirectAgent(AgentConfig(tools=registry))
            response = asyncio.run(agent.run("What is 2 + 2?"))
            assert "4" in response.answer
            assert len(response.tool_calls) == 0


class TestDirectAgentWithToolCall:
    """Tests for DirectAgent when a tool call is made."""

    def test_tool_call_parsing_and_execution(self, weather_registry):
        """Agent parses TOOL_CALL and executes the tool."""
        with patch("app.agent.modes.direct.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content='TOOL_CALL: {"name": "get_weather", "arguments": {"city": "Beijing"}}'
            )
            mock.return_value = chat

            agent = DirectAgent(AgentConfig(tools=weather_registry))
            response = asyncio.run(agent.run("What's the weather in Beijing?"))
            assert len(response.tool_calls) == 1
            assert response.tool_calls[0]["tool"] == "get_weather"
            assert response.tool_calls[0]["args"] == {"city": "Beijing"}
            assert response.tool_calls[0]["success"] is True
            assert "Beijing" in response.tool_calls[0]["result"]
            assert response.steps == 2

    def test_tool_call_with_multiline_args(self, weather_registry):
        """Agent parses TOOL_CALL with multiline JSON arguments."""
        with patch("app.agent.modes.direct.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content=(
                    'Let me check the weather.\n'
                    'TOOL_CALL: {"name": "get_weather", "arguments": {"city": "Shanghai"}}\n'
                    'Getting weather data...'
                )
            )
            mock.return_value = chat

            agent = DirectAgent(AgentConfig(tools=weather_registry))
            response = asyncio.run(agent.run("Weather in Shanghai?"))
            assert len(response.tool_calls) == 1
            assert response.tool_calls[0]["tool"] == "get_weather"
            assert response.tool_calls[0]["args"] == {"city": "Shanghai"}

    def test_tool_not_found(self, weather_registry):
        """Agent handles tool call to unknown tool gracefully."""
        with patch("app.agent.modes.direct.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content='TOOL_CALL: {"name": "nonexistent", "arguments": {"x": 1}}'
            )
            mock.return_value = chat

            agent = DirectAgent(AgentConfig(tools=weather_registry))
            response = asyncio.run(agent.run("Do something"))
            # Tool call was parsed but not executed since tool not found
            # The original content is returned as-is by _generate_final_response
            assert "TOOL_CALL:" in response.answer or response.answer != ""
            assert response.steps >= 1

    def test_tool_execution_failure(self, failing_tool_registry):
        """Agent handles tool execution failure gracefully."""
        with patch("app.agent.modes.direct.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content='TOOL_CALL: {"name": "crash", "arguments": {}}'
            )
            mock.return_value = chat

            agent = DirectAgent(AgentConfig(tools=failing_tool_registry))
            response = asyncio.run(agent.run("Crash test"))
            assert len(response.tool_calls) == 1
            assert response.tool_calls[0]["tool"] == "crash"
            assert response.tool_calls[0]["success"] is False


class TestDirectAgentConfig:
    """Tests for DirectAgent configuration."""

    def test_max_steps_config(self):
        """Agent respects max_steps config."""
        registry = ToolRegistry()
        agent = DirectAgent(AgentConfig(tools=registry, max_steps=5))
        assert agent.config.max_steps == 5

    def test_name_config(self):
        """Agent respects name config."""
        registry = ToolRegistry()
        agent = DirectAgent(AgentConfig(tools=registry, name="custom-agent"))
        assert agent.config.name == "custom-agent"

    def test_registry_access(self, weather_registry):
        """Agent exposes tools through registry."""
        agent = DirectAgent(AgentConfig(tools=weather_registry))
        tools = agent.get_available_tools()
        assert len(tools) == 1
        assert tools[0].name == "get_weather"


class TestDirectAgentParseToolCall:
    """Tests for _parse_tool_call method."""

    def test_parse_valid_tool_call(self, empty_registry):
        """Parses a valid TOOL_CALL marker."""
        agent = DirectAgent(AgentConfig(tools=empty_registry))
        result = agent._parse_tool_call(
            'TOOL_CALL: {"name": "test", "arguments": {"a": 1}}'
        )
        assert result == {"name": "test", "arguments": {"a": 1}}

    def test_parse_no_tool_call(self, empty_registry):
        """Returns None when no TOOL_CALL marker present."""
        agent = DirectAgent(AgentConfig(tools=empty_registry))
        result = agent._parse_tool_call("This is a regular response.")
        assert result is None

    def test_parse_invalid_json(self, empty_registry):
        """Returns None for malformed JSON after TOOL_CALL marker."""
        agent = DirectAgent(AgentConfig(tools=empty_registry))
        result = agent._parse_tool_call("TOOL_CALL: {not valid json}")
        assert result is None

    def test_parse_tool_call_in_multiline(self, empty_registry):
        """Extracts TOOL_CALL from within multiline response."""
        agent = DirectAgent(AgentConfig(tools=empty_registry))
        result = agent._parse_tool_call(
            "Let me search for that.\n"
            'TOOL_CALL: {"name": "search", "arguments": {"query": "python"}}\n'
            "Searching..."
        )
        assert result == {"name": "search", "arguments": {"query": "python"}}

    def test_parse_empty_string(self, empty_registry):
        """Returns None for empty response."""
        agent = DirectAgent(AgentConfig(tools=empty_registry))
        result = agent._parse_tool_call("")
        assert result is None


class TestDirectAgentGenerateFinalResponse:
    """Tests for _generate_final_response method."""

    def test_successful_tool_result_with_explanation(self, empty_registry):
        """Generates response with explanation and tool result on success."""
        from app.agent.tool import ToolResult

        agent = DirectAgent(AgentConfig(tools=empty_registry))
        tool_result = ToolResult(success=True, output="Sunny, 25°C")
        original = "Let me check the weather for you.\nTOOL_CALL: {...}"

        result = agent._generate_final_response(original, tool_result)
        assert "Let me check the weather for you." in result
        assert "Sunny, 25°C" in result

    def test_successful_tool_result_no_explanation(self, empty_registry):
        """Returns just tool output when no explanation before TOOL_CALL."""
        from app.agent.tool import ToolResult

        agent = DirectAgent(AgentConfig(tools=empty_registry))
        tool_result = ToolResult(success=True, output="42")
        original = "TOOL_CALL: {...}"

        result = agent._generate_final_response(original, tool_result)
        assert result == "42"

    def test_failed_tool_result(self, empty_registry):
        """Returns original content when tool fails."""
        from app.agent.tool import ToolResult

        agent = DirectAgent(AgentConfig(tools=empty_registry))
        tool_result = ToolResult(success=False, output="", error="Bad")
        original = "Let me try something.\nTOOL_CALL: {...}"

        result = agent._generate_final_response(original, tool_result)
        assert result == original

    def test_no_tool_call_in_original(self, empty_registry):
        """Returns original when no TOOL_CALL marker in response."""
        from app.agent.tool import ToolResult

        agent = DirectAgent(AgentConfig(tools=empty_registry))
        tool_result = ToolResult(success=True, output="Done")
        original = "Here is a direct answer."

        result = agent._generate_final_response(original, tool_result)
        assert result == original


class TestDirectAgentRunStream:
    """Tests for the run_stream method."""

    @pytest.mark.asyncio
    async def test_stream_no_tool_call(self):
        """Stream yields expected events when no tool call is made."""
        with patch("app.agent.modes.direct.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(content="Direct answer.")
            mock.return_value = chat

            agent = DirectAgent(AgentConfig(tools=ToolRegistry()))
            events = []
            async for event in agent.run_stream("Hello"):
                events.append(event)

            assert len(events) >= 2
            event_types = [e["event"] for e in events]
            assert "start" in event_types
            assert "done" in event_types
            assert "token" in event_types

            done_event = next(e for e in events if e["event"] == "done")
            assert "answer" in done_event["data"]
            assert done_event["data"]["steps"] == 1

    @pytest.mark.asyncio
    async def test_stream_with_tool_call(self, weather_registry):
        """Stream yields tool_call and tool_result events."""
        with patch("app.agent.modes.direct.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content='TOOL_CALL: {"name": "get_weather", "arguments": {"city": "Paris"}}'
            )
            mock.return_value = chat

            agent = DirectAgent(AgentConfig(tools=weather_registry))
            events = []
            async for event in agent.run_stream("Weather in Paris?"):
                events.append(event)

            event_types = [e["event"] for e in events]
            assert "start" in event_types
            assert "tool_call" in event_types
            assert "tool_result" in event_types
            assert "token" in event_types
            assert "done" in event_types

            tool_call_event = next(e for e in events if e["event"] == "tool_call")
            assert tool_call_event["data"]["tool"] == "get_weather"

            done_event = next(e for e in events if e["event"] == "done")
            assert len(done_event["data"]["tool_calls"]) == 1
            assert done_event["data"]["steps"] == 2

    @pytest.mark.asyncio
    async def test_stream_tool_not_found(self, weather_registry):
        """Stream handles unknown tool gracefully."""
        with patch("app.agent.modes.direct.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content='TOOL_CALL: {"name": "no_such_tool", "arguments": {}}'
            )
            mock.return_value = chat

            agent = DirectAgent(AgentConfig(tools=weather_registry))
            events = []
            async for event in agent.run_stream("Do something"):
                events.append(event)

            event_types = [e["event"] for e in events]
            assert "start" in event_types
            assert "done" in event_types


class TestDirectAgentEdgeCases:
    """Edge case tests for DirectAgent."""

    def test_empty_registry(self, empty_registry):
        """Agent works with no registered tools."""
        with patch("app.agent.modes.direct.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(content="I have no tools.")
            mock.return_value = chat

            agent = DirectAgent(AgentConfig(tools=empty_registry))
            response = asyncio.run(agent.run("Help"))
            assert response.answer == "I have no tools."
            assert len(response.tool_calls) == 0

    def test_multiple_tools_schemas(self):
        """Multiple tools all appear in schema output."""
        registry = ToolRegistry()

        @tool(name="tool_a", description="Tool A")
        def tool_a() -> str:
            return "A"

        @tool(name="tool_b", description="Tool B")
        def tool_b() -> str:
            return "B"

        registry.register(tool_a)
        registry.register(tool_b)

        agent = DirectAgent(AgentConfig(tools=registry))
        schemas = agent.get_tool_schemas()
        assert len(schemas) == 2
        names = [s["function"]["name"] for s in schemas]
        assert "tool_a" in names
        assert "tool_b" in names

    def test_latency_is_recorded(self, empty_registry):
        """Agent records execution latency."""
        with patch("app.agent.modes.direct.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(content="Fast response.")
            mock.return_value = chat

            agent = DirectAgent(AgentConfig(tools=empty_registry))
            response = asyncio.run(agent.run("Test"))
            assert response.latency_ms >= 0

    def test_response_steps_count(self, weather_registry):
        """Steps count reflects tool calls + 1."""
        with patch("app.agent.modes.direct.get_chat_model") as mock:
            chat = MagicMock()
            chat.invoke.return_value = MagicMock(
                content='TOOL_CALL: {"name": "get_weather", "arguments": {"city": "Tokyo"}}'
            )
            mock.return_value = chat

            agent = DirectAgent(AgentConfig(tools=weather_registry))
            response = asyncio.run(agent.run("Tokyo weather"))
            assert response.steps == 2  # 1 LLM call + 1 tool call
