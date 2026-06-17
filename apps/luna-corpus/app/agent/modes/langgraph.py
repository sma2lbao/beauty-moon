"""LangGraph Agent - state machine workflow."""
from app.agent.base import Agent, AgentConfig, AgentResponse


class LangGraphAgent(Agent):
    """LangGraph Agent - state machine workflow.

    Full implementation will be added in a later task.
    """

    async def run(self, query: str) -> AgentResponse:
        raise NotImplementedError("LangGraphAgent.run not yet implemented")

    async def run_stream(self, query: str):
        raise NotImplementedError("LangGraphAgent.run_stream not yet implemented")
        yield  # pragma: no cover
