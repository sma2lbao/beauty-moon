"""ReAct Agent - reasoning and acting loop."""
from app.agent.base import Agent, AgentConfig, AgentResponse


class ReActAgent(Agent):
    """ReAct Agent - reasoning and acting loop.

    Full implementation will be added in a later task.
    """

    async def run(self, query: str) -> AgentResponse:
        raise NotImplementedError("ReActAgent.run not yet implemented")

    async def run_stream(self, query: str):
        raise NotImplementedError("ReActAgent.run_stream not yet implemented")
        yield  # pragma: no cover
