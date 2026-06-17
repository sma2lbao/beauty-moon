"""Base Agent class and interfaces."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from app.agent.registry import ToolRegistry
from app.agent.tool import Tool


@dataclass
class AgentConfig:
    """Configuration for an Agent."""
    name: str = "agent"
    max_steps: int = 10
    tools: ToolRegistry = field(default_factory=ToolRegistry)


@dataclass
class AgentResponse:
    """Response from an Agent execution."""
    answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    latency_ms: int = 0


class Agent(ABC):
    """Abstract base class for agents.

    All agents must implement the run method.
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self.registry = config.tools

    @abstractmethod
    async def run(self, query: str) -> AgentResponse:
        """Run the agent with a query.

        Args:
            query: User query

        Returns:
            Agent response
        """
        pass

    @abstractmethod
    async def run_stream(self, query: str) -> AsyncGenerator[dict[str, Any], None]:
        """Run the agent with streaming output.

        Args:
            query: User query

        Yields:
            Stream events
        """
        pass

    def get_available_tools(self) -> list[Tool]:
        """Get list of available tools."""
        return self.registry.list_all()

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get schemas for all available tools."""
        return self.registry.get_schemas()
