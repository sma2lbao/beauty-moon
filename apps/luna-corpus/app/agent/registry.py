"""Tool registry for managing available tools."""
from typing import Any

from app.agent.tool import Tool


class ToolRegistry:
    """Registry for managing tools.

    Example:
        registry = ToolRegistry()
        registry.register(my_tool)
        schema = registry.get_schemas()
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool.

        Args:
            tool: Tool to register
        """
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """Unregister a tool.

        Args:
            name: Tool name

        Returns:
            True if tool was removed, False if not found
        """
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> Tool | None:
        """Get a tool by name.

        Args:
            name: Tool name

        Returns:
            Tool or None if not found
        """
        return self._tools.get(name)

    def list_all(self) -> list[Tool]:
        """List all registered tools.

        Returns:
            List of all tools
        """
        return list(self._tools.values())

    def get_schemas(self) -> list[dict[str, Any]]:
        """Get schemas for all tools.

        Returns:
            List of tool schemas for LLM consumption
        """
        return [tool.get_schema() for tool in self._tools.values()]

    def get_schema_by_names(self, names: list[str]) -> list[dict[str, Any]]:
        """Get schemas for specific tools.

        Args:
            names: List of tool names

        Returns:
            List of tool schemas
        """
        schemas = []
        for name in names:
            tool = self._tools.get(name)
            if tool:
                schemas.append(tool.get_schema())
        return schemas

    def clear(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()

    def __len__(self) -> int:
        """Get number of registered tools."""
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools
