"""Tests for tool definitions."""

import pytest

from app.agent.tool import Tool, ToolResult, tool


def test_tool_result_success():
    """Test successful ToolResult."""
    result = ToolResult(success=True, output="result")
    assert result.success is True
    assert result.output == "result"
    assert result.error is None


def test_tool_result_failure():
    """Test failed ToolResult."""
    result = ToolResult(success=False, output="", error="something went wrong")
    assert result.success is False
    assert result.output == ""
    assert result.error == "something went wrong"


def test_tool_creation():
    """Test creating a Tool manually."""
    tool_obj = Tool(
        name="test_tool",
        description="A test tool",
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        executor=lambda query: f"Searching for: {query}",
    )
    assert tool_obj.name == "test_tool"
    assert tool_obj.is_async is False


def test_tool_get_schema():
    """Test getting tool schema."""
    tool_obj = Tool(
        name="search",
        description="Search the web",
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    )
    schema = tool_obj.get_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "search"
    assert "query" in schema["function"]["parameters"]["properties"]


def test_tool_decorator_sync():
    """Test @tool decorator for sync function."""

    @tool(name="calculator", description="Calculate math")
    def calculate(expression: str) -> str:
        return str(eval(expression))

    assert calculate.name == "calculator"
    assert calculate.is_async is False
    assert "expression" in calculate.parameters_schema["properties"]


def test_tool_decorator_async():
    """Test @tool decorator for async function."""

    @tool(name="async_tool", description="An async tool")
    async def async_tool(query: str) -> str:
        return f"Async result: {query}"

    assert async_tool.name == "async_tool"
    assert async_tool.is_async is True


def test_tool_execute_sync():
    """Test executing a sync tool."""

    @tool(name="greet", description="Greet someone")
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    tool_instance = greet
    result = tool_instance.execute_sync(name="World")
    assert result.success is True
    assert result.output == "Hello, World!"


@pytest.mark.asyncio
async def test_tool_execute_async():
    """Test executing an async tool."""

    @tool(name="async_greet", description="Async greet")
    async def async_greet(name: str) -> str:
        return f"Hello, {name}!"

    tool_instance = async_greet
    result = await tool_instance.execute(name="World")
    assert result.success is True
    assert result.output == "Hello, World!"


@pytest.mark.asyncio
async def test_tool_execute_error():
    """Test tool execution error handling."""

    @tool(name="failing", description="A failing tool")
    def failing_tool() -> str:
        raise ValueError("Intentional error")

    result = await failing_tool.execute()
    assert result.success is False
    assert "Intentional error" in result.error
