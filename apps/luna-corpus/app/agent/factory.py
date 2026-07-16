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
        timeout_s: int = 120,
        max_recursion_depth: int = 3,
        name: str = "agent",
    ) -> Agent:
        """创建 agent 实例。

        Args:
            mode: agent 执行模式
            tools: 工具（ToolRegistry 或 Tool 列表）
            max_steps: LLM 循环最大步数
            timeout_s: 单次运行超时（秒），供治理层
            max_recursion_depth: 最大递归深度，供治理层
            name: agent 名称

        Returns:
            Agent 实例

        Raises:
            ValueError: mode 未知
        """
        if tools is None:
            registry = ToolRegistry()
        elif isinstance(tools, ToolRegistry):
            registry = tools
        else:
            registry = ToolRegistry()
            for t in tools:
                registry.register(t)

        config = AgentConfig(
            name=name,
            max_steps=max_steps,
            timeout_s=timeout_s,
            max_recursion_depth=max_recursion_depth,
            tools=registry,
        )

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
