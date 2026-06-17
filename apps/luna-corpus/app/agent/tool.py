"""Tool definitions and decorator for tool creation."""
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Union
import inspect

CallableExecutor = Union[Callable[..., str], Callable[..., Awaitable[str]]]


@dataclass
class ToolResult:
    """Result from tool execution."""
    success: bool
    output: str
    error: str | None = None


@dataclass
class Tool:
    """Tool definition with schema and executor."""
    name: str
    description: str
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    executor: CallableExecutor | None = None
    is_async: bool = False

    def __post_init__(self):
        if self.executor is not None:
            self.is_async = inspect.iscoroutinefunction(self.executor)

    def get_schema(self) -> dict[str, Any]:
        """Get JSON schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given arguments."""
        if self.executor is None:
            return ToolResult(
                success=False,
                output="",
                error="No executor configured for this tool",
            )

        try:
            if self.is_async:
                output = await self.executor(**kwargs)
            else:
                output = self.executor(**kwargs)
            return ToolResult(success=True, output=output)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def execute_sync(self, **kwargs) -> ToolResult:
        """Execute the tool synchronously (blocking wrapper).

        For sync executors, calls directly. For async executors,
        this will raise an error as async code cannot run sync.
        """
        if self.executor is None:
            return ToolResult(
                success=False,
                output="",
                error="No executor configured for this tool",
            )

        try:
            if self.is_async:
                return ToolResult(
                    success=False,
                    output="",
                    error="Cannot call async executor synchronously. Use await tool.execute() instead.",
                )
            output = self.executor(**kwargs)
            return ToolResult(success=True, output=output)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


def tool(
    name: str,
    description: str,
    parameters_schema: dict[str, Any] | None = None,
) -> Callable[[CallableExecutor], Tool]:
    """Decorator to create a Tool from a function.

    Args:
        name: Tool name
        description: Tool description
        parameters_schema: JSON Schema for parameters

    Returns:
        Decorator function

    Example:
        @tool(name="calculator", description="Calculate math")
        def calculate(expression: str) -> str:
            return str(eval(expression))
    """
    def decorator(func: CallableExecutor) -> Tool:
        schema = parameters_schema
        if schema is None:
            schema = _infer_schema(func)

        return Tool(
            name=name,
            description=description,
            parameters_schema=schema,
            executor=func,
            is_async=inspect.iscoroutinefunction(func),
        )
    return decorator


def _infer_schema(func: Callable) -> dict[str, Any]:
    """Infer JSON Schema from function signature."""
    sig = inspect.signature(func)
    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        param_type = "string"
        if param.annotation is not inspect.Parameter.empty:
            if param.annotation is int:
                param_type = "integer"
            elif param.annotation is float:
                param_type = "number"
            elif param.annotation is bool:
                param_type = "boolean"
            elif param.annotation is str:
                param_type = "string"

        properties[param_name] = {
            "type": param_type,
            "description": f"Parameter {param_name}",
        }

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required if required else None,
    }
