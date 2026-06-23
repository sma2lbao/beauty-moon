"""Tests for ToolRegistry."""

from app.agent.registry import ToolRegistry
from app.agent.tool import Tool


def test_registry_register():
    """Test registering a tool."""
    registry = ToolRegistry()
    tool = Tool(name="test", description="Test tool")
    registry.register(tool)
    assert "test" in registry


def test_registry_get():
    """Test getting a tool."""
    registry = ToolRegistry()
    tool = Tool(name="my_tool", description="My tool")
    registry.register(tool)
    retrieved = registry.get("my_tool")
    assert retrieved is not None
    assert retrieved.name == "my_tool"


def test_registry_get_not_found():
    """Test getting non-existent tool."""
    registry = ToolRegistry()
    assert registry.get("nonexistent") is None


def test_registry_list_all():
    """Test listing all tools."""
    registry = ToolRegistry()
    registry.register(Tool(name="tool1", description="Tool 1"))
    registry.register(Tool(name="tool2", description="Tool 2"))
    tools = registry.list_all()
    assert len(tools) == 2


def test_registry_get_schemas():
    """Test getting tool schemas."""
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="search",
            description="Search",
            parameters_schema={"type": "object"},
        )
    )
    schemas = registry.get_schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "search"


def test_registry_get_schema_by_names():
    """Test getting schemas for specific tools."""
    registry = ToolRegistry()
    registry.register(Tool(name="tool1", description="Tool 1"))
    registry.register(Tool(name="tool2", description="Tool 2"))
    schemas = registry.get_schema_by_names(["tool1"])
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "tool1"


def test_registry_unregister():
    """Test unregistering a tool."""
    registry = ToolRegistry()
    registry.register(Tool(name="test", description="Test"))
    assert registry.unregister("test") is True
    assert "test" not in registry


def test_registry_unregister_not_found():
    """Test unregistering non-existent tool."""
    registry = ToolRegistry()
    assert registry.unregister("nonexistent") is False


def test_registry_clear():
    """Test clearing all tools."""
    registry = ToolRegistry()
    registry.register(Tool(name="tool1", description="Tool 1"))
    registry.register(Tool(name="tool2", description="Tool 2"))
    registry.clear()
    assert len(registry) == 0


def test_registry_len():
    """Test registry length."""
    registry = ToolRegistry()
    assert len(registry) == 0
    registry.register(Tool(name="tool1", description="Tool 1"))
    assert len(registry) == 1
