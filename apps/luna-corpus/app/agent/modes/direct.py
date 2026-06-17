"""Direct Agent - single tool call execution."""
from app.agent.base import Agent, AgentConfig, AgentResponse


class DirectAgent(Agent):
    """Direct Agent - executes tools in a single step.

    Full implementation will be added in a later task.
    """

    async def run(self, query: str) -> AgentResponse:
        raise NotImplementedError("DirectAgent.run not yet implemented")

    async def run_stream(self, query: str):
        raise NotImplementedError("DirectAgent.run_stream not yet implemented")
        yield  # pragma: no cover
