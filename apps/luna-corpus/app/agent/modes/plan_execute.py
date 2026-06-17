"""Plan-then-Execute Agent."""
from app.agent.base import Agent, AgentConfig, AgentResponse


class PlanExecuteAgent(Agent):
    """Plan-then-Execute Agent.

    Full implementation will be added in a later task.
    """

    async def run(self, query: str) -> AgentResponse:
        raise NotImplementedError("PlanExecuteAgent.run not yet implemented")

    async def run_stream(self, query: str):
        raise NotImplementedError("PlanExecuteAgent.run_stream not yet implemented")
        yield  # pragma: no cover
