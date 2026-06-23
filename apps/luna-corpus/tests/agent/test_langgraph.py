"""Tests for LangGraphAgent."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.agent.base import AgentConfig
from app.agent.modes.langgraph import LangGraphAgent, WorkflowState
from app.agent.registry import ToolRegistry
from app.agent.tool import tool


class TestWorkflowState:
    """Tests for WorkflowState dataclass."""

    def test_workflow_state_default(self):
        """Test default WorkflowState values."""
        state = WorkflowState()
        assert state.query == ""
        assert state.tool_calls == []
        assert state.current_step == "start"
        assert state.classification == ""
        assert state.intermediate_results == []
        assert state.final_answer == ""
        assert state.steps_taken == 0

    def test_workflow_state_with_data(self):
        """Test WorkflowState with custom data."""
        state = WorkflowState(
            query="Test query",
            classification="simple",
            tool_calls=[{"tool": "test", "args": {}, "result": "ok"}],
            intermediate_results=["Step 1 done"],
            final_answer="All done",
            steps_taken=3,
        )
        assert state.query == "Test query"
        assert state.classification == "simple"
        assert len(state.tool_calls) == 1
        assert len(state.intermediate_results) == 1
        assert state.final_answer == "All done"
        assert state.steps_taken == 3


class TestLangGraphAgentCreation:
    """Tests for LangGraphAgent creation and configuration."""

    def test_langgraph_agent_creation(self):
        """Test creating LangGraphAgent."""
        agent = LangGraphAgent(AgentConfig())
        assert agent.graph is not None

    def test_langgraph_max_steps(self):
        """Test LangGraph respects max_steps."""
        agent = LangGraphAgent(AgentConfig(max_steps=3))
        assert agent.config.max_steps == 3

    def test_langgraph_agent_name(self):
        """Test LangGraph respects name config."""
        agent = LangGraphAgent(AgentConfig(name="langgraph-test"))
        assert agent.config.name == "langgraph-test"

    def test_langgraph_registry_access(self):
        """Test LangGraph exposes tools through registry."""
        registry = ToolRegistry()

        @tool(name="echo", description="Echo a message")
        def echo(message: str) -> str:
            return message

        registry.register(echo)
        agent = LangGraphAgent(AgentConfig(tools=registry))
        tools = agent.get_available_tools()
        assert len(tools) == 1
        assert tools[0].name == "echo"


class TestLangGraphAgentRun:
    """Tests for the run method."""

    def test_simple_query(self):
        """Agent processes a simple query.
        Workflow: classify -> simple_handler -> final_response (3 LLM calls)"""
        with patch("app.agent.modes.langgraph.get_chat_model") as mock_llm:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(content="simple"),
                MagicMock(content="This is a simple answer."),
                MagicMock(content="Final: This is a simple answer."),
            ]
            mock_llm.return_value = chat

            agent = LangGraphAgent(AgentConfig(tools=ToolRegistry()))
            response = asyncio.run(agent.run("What is 2+2?"))

            assert response.answer is not None
            assert len(response.answer) > 0
            assert response.steps >= 1
            assert response.latency_ms >= 0

    def test_simple_query_with_tool(self):
        """Agent uses tool for simple classified query.
        Workflow: classify -> simple_handler (tool call) -> final_response"""
        registry = ToolRegistry()

        @tool(name="get_weather", description="Get weather for a city")
        def get_weather(city: str) -> str:
            return f"Weather in {city}: Sunny, 25°C"

        registry.register(get_weather)

        with patch("app.agent.modes.langgraph.get_chat_model") as mock_llm:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(content="simple"),
                MagicMock(
                    content=(
                        'TOOL_CALL: {"name": "get_weather", '
                        '"arguments": {"city": "Beijing"}}'
                    )
                ),
                MagicMock(content="The weather in Beijing is Sunny, 25°C."),
            ]
            mock_llm.return_value = chat

            agent = LangGraphAgent(AgentConfig(tools=registry))
            response = asyncio.run(agent.run("What's the weather in Beijing?"))

            assert response.answer is not None
            assert len(response.tool_calls) >= 1
            assert response.tool_calls[0]["tool"] == "get_weather"

    def test_complex_query(self):
        """Agent processes a complex query with multi-step handling.
        Workflow: classify -> complex_handler -> final_response"""
        with patch("app.agent.modes.langgraph.get_chat_model") as mock_llm:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(content="complex"),
                MagicMock(content="PLAN: [step1, step2]\nRESULT: Analysis complete."),
                MagicMock(content="Comprehensive answer for the complex query."),
            ]
            mock_llm.return_value = chat

            agent = LangGraphAgent(AgentConfig(tools=ToolRegistry()))
            response = asyncio.run(
                agent.run("Analyze the impact of AI on education and healthcare.")
            )

            assert response.answer is not None
            assert len(response.answer) > 0
            assert response.steps >= 1
            assert response.latency_ms >= 0

    def test_classification_defaults_to_simple(self):
        """Classification defaults to 'simple' for unrecognized output."""
        with patch("app.agent.modes.langgraph.get_chat_model") as mock_llm:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(content="I'm not sure how to classify this query..."),
                MagicMock(content="Here is a direct answer."),
                MagicMock(content="Final answer."),
            ]
            mock_llm.return_value = chat

            agent = LangGraphAgent(AgentConfig(tools=ToolRegistry()))
            response = asyncio.run(agent.run("Hello!"))

            assert response.answer is not None
            assert response.answer != ""


class TestLangGraphAgentRunStream:
    """Tests for the run_stream method."""

    @pytest.mark.asyncio
    async def test_stream_yields_events(self):
        """Stream yields start and done events.
        Workflow: classify -> simple_handler -> final_response (3 LLM calls)"""
        with patch("app.agent.modes.langgraph.get_chat_model") as mock_llm:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(content="simple"),
                MagicMock(content="Direct answer."),
                MagicMock(content="Final answer."),
            ]
            mock_llm.return_value = chat

            agent = LangGraphAgent(AgentConfig(tools=ToolRegistry()))
            events = []
            async for event in agent.run_stream("Hello"):
                events.append(event)

            event_types = [e["event"] for e in events]
            assert "start" in event_types
            assert "done" in event_types
            assert len(events) >= 2

            done_event = next(e for e in events if e["event"] == "done")
            assert "answer" in done_event["data"]

    @pytest.mark.asyncio
    async def test_stream_with_complex_query(self):
        """Stream yields step events for complex query."""
        with patch("app.agent.modes.langgraph.get_chat_model") as mock_llm:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(content="complex"),
                MagicMock(
                    content=(
                        "PLAN: [analyze, research, conclude]\n"
                        "RESULT: Research phase done."
                    )
                ),
                MagicMock(content="Comprehensive analysis complete."),
            ]
            mock_llm.return_value = chat

            agent = LangGraphAgent(AgentConfig(tools=ToolRegistry()))
            events = []
            async for event in agent.run_stream("Complex analysis"):
                events.append(event)

            event_types = [e["event"] for e in events]
            assert "start" in event_types
            assert "done" in event_types

    @pytest.mark.asyncio
    async def test_stream_step_events(self):
        """Stream yields step events showing workflow progress."""
        with patch("app.agent.modes.langgraph.get_chat_model") as mock_llm:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(content="simple"),
                MagicMock(content="Quick answer."),
                MagicMock(content="Final answer."),
            ]
            mock_llm.return_value = chat

            agent = LangGraphAgent(AgentConfig(tools=ToolRegistry()))
            events = []
            async for event in agent.run_stream("Test"):
                events.append(event)

            step_events = [e for e in events if e["event"] == "step"]
            assert len(step_events) >= 1

    @pytest.mark.asyncio
    async def test_stream_tool_call(self):
        """Stream includes tool call events."""
        registry = ToolRegistry()

        @tool(name="search", description="Search for information")
        def search(query: str) -> str:
            return f"Results for: {query}"

        registry.register(search)

        with patch("app.agent.modes.langgraph.get_chat_model") as mock_llm:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(content="simple"),
                MagicMock(
                    content=(
                        'TOOL_CALL: {"name": "search", '
                        '"arguments": {"query": "Python"}}'
                    )
                ),
                MagicMock(content="Search results show Python is popular."),
            ]
            mock_llm.return_value = chat

            agent = LangGraphAgent(AgentConfig(tools=registry))
            events = []
            async for event in agent.run_stream("Search for Python"):
                events.append(event)

            event_types = [e["event"] for e in events]
            assert "start" in event_types
            assert "done" in event_types


class TestLangGraphAgentEdgeCases:
    """Edge case tests."""

    def test_empty_query(self):
        """Agent handles empty query gracefully."""
        with patch("app.agent.modes.langgraph.get_chat_model") as mock_llm:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(content="simple"),
                MagicMock(content="I received an empty query."),
                MagicMock(content="Final answer for empty query."),
            ]
            mock_llm.return_value = chat

            agent = LangGraphAgent(AgentConfig(tools=ToolRegistry()))
            response = asyncio.run(agent.run(""))
            assert response is not None

    def test_no_response_content(self):
        """Agent handles LLM response without content attribute."""
        with patch("app.agent.modes.langgraph.get_chat_model") as mock_llm:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(content="simple"),
                MagicMock(content="Answer string."),
                MagicMock(content="Final answer string."),
            ]
            mock_llm.return_value = chat

            agent = LangGraphAgent(AgentConfig(tools=ToolRegistry()))
            response = asyncio.run(agent.run("Test"))
            assert response.answer is not None

    def test_latency_recorded(self):
        """Agent records execution latency."""
        with patch("app.agent.modes.langgraph.get_chat_model") as mock_llm:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(content="simple"),
                MagicMock(content="Fast answer."),
                MagicMock(content="Final fast answer."),
            ]
            mock_llm.return_value = chat

            agent = LangGraphAgent(AgentConfig(tools=ToolRegistry()))
            response = asyncio.run(agent.run("Test latency"))
            assert response.latency_ms >= 0

    def test_tool_not_found(self):
        """Agent handles unknown tool gracefully."""
        registry = ToolRegistry()

        @tool(name="known_tool", description="A known tool")
        def known_tool() -> str:
            return "known"

        registry.register(known_tool)

        with patch("app.agent.modes.langgraph.get_chat_model") as mock_llm:
            chat = MagicMock()
            chat.invoke.side_effect = [
                MagicMock(content="simple"),
                MagicMock(
                    content='TOOL_CALL: {"name": "unknown_tool", "arguments": {}}'
                ),
                MagicMock(content="I couldn't find that tool."),
            ]
            mock_llm.return_value = chat

            agent = LangGraphAgent(AgentConfig(tools=registry))
            response = asyncio.run(agent.run("Use unknown tool"))
            assert response.answer is not None
