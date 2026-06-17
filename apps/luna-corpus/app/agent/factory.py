"""Factory for creating agents."""
from app.agent.base import Agent, AgentConfig
from app.agent.registry import ToolRegistry
from app.agent.tool import Tool
from app.agent.modes.direct import DirectAgent
from app.agent.modes.react import ReActAgent
from app.agent.modes.plan_execute import PlanExecuteAgent
from app.agent.modes.langgraph import LangGraphAgent
from app.core.config import AgentMode


class AgentFactory:
    """Factory for creating agents based on mode.

    Example:
        registry = ToolRegistry()
        registry.register(my_tool)
        agent = AgentFactory.create(
            mode=AgentMode.DIRECT,
            tools=registry,
            max_steps=10,
        )
    """

    @staticmethod
    def create(
        mode: AgentMode,
        tools: ToolRegistry | list[Tool] | None = None,
        max_steps: int = 10,
        name: str = "agent",
    ) -> Agent:
        """Create an agent instance.

        Args:
            mode: Agent execution mode
            tools: Tools to register (ToolRegistry or list of Tools)
            max_steps: Maximum execution steps
            name: Agent name

        Returns:
            Agent instance

        Raises:
            ValueError: If mode is unknown
        """
        if tools is None:
            registry = ToolRegistry()
        elif isinstance(tools, ToolRegistry):
            registry = tools
        else:
            registry = ToolRegistry()
            for t in tools:
                registry.register(t)

        config = AgentConfig(name=name, max_steps=max_steps, tools=registry)

        modes = {
            AgentMode.DIRECT: DirectAgent,
            AgentMode.REACT: ReActAgent,
            AgentMode.PLAN: PlanExecuteAgent,
            AgentMode.LANGGRAPH: LangGraphAgent,
        }

        agent_class = modes.get(mode)
        if agent_class is None:
            raise ValueError(f"Unknown agent mode: {mode}")

        return agent_class(config)
