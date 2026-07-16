"""Base Agent class and interfaces."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from app.agent.registry import ToolRegistry
from app.agent.tool import Tool


@dataclass
class AgentConfig:
    """Agent 运行配置。

    字段说明：
    - name: agent 名称，用于日志/追踪
    - max_steps: LLM 循环最大步数（工具调用轮次上限）
    - timeout_s: 单次运行整体超时（秒），供治理层用
    - max_recursion_depth: 允许的最大递归/子任务深度，供治理层用
    - tools: 工具注册表
    """
    name: str = "agent"
    max_steps: int = 10
    timeout_s: int = 120
    max_recursion_depth: int = 3
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
    async def run(self, ctx, trace, db):
        """执行 agent 主循环。

        Args:
            ctx: AgentRunContext，携带 query/tenant/workspace/messages 等运行态
            trace: TraceRecorder，负责写入 runs/steps 轨迹
            db: 数据库会话（AsyncSession），供治理与轨迹落库

        Returns:
            LoopResult：包含最终文本、运行状态与步数
        """
        pass

    @abstractmethod
    async def run_stream(self, ctx, trace, db) -> AsyncGenerator[dict[str, Any], None]:
        """执行 agent 主循环（流式）。

        Args:
            ctx: AgentRunContext
            trace: TraceRecorder
            db: 数据库会话

        Yields:
            事件 dict（如 {"type": "delta", "content": "..."}）
        """
        pass

    def get_available_tools(self) -> list[Tool]:
        """Get list of available tools."""
        return self.registry.list_all()

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get schemas for all available tools."""
        return self.registry.get_schemas()
