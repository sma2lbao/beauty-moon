"""四模式均通过 run_tool_loop 执行（mock LLM + mock loop）。"""
import pytest

from app.agent.core.context import AgentRunContext
from app.agent.core.llm_loop import LoopResult
from app.agent.factory import AgentFactory
from app.agent.registry import ToolRegistry
from app.core.config import AgentMode
from app.db.models import AgentRunStatus


class NoopTrace:
    """空实现的 TraceRecorder 替身，便于单元测试。"""

    def start_run(self, *a, **k):
        pass

    def record_step(self, *a, **k):
        pass

    def end_run(self, *a, **k):
        pass


def _ctx(mode):
    """构造一个最小可用的运行上下文。"""
    return AgentRunContext(
        run_id="r1",
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="k1",
        user_id="u1",
        conversation_id=None,
        mode=mode,
        max_steps=5,
        timeout_s=120,
        max_recursion_depth=3,
        start_time=1000.0,
        query="hello",
    )


@pytest.mark.parametrize("mode", list(AgentMode))
@pytest.mark.asyncio
async def test_mode_delegates_to_loop(mode, monkeypatch):
    """四种模式的 run 都应转发到 run_tool_loop；direct 传 single_shot=True，其余 False。"""
    called = {}

    async def fake_loop(**kwargs):
        called["single_shot"] = kwargs.get("single_shot", False)
        called["provider"] = kwargs["provider"]
        return LoopResult("答案", AgentRunStatus.COMPLETED, 1)

    # patch 每个模式模块内引用的 run_tool_loop 与 get_chat_model
    import app.agent.modes.direct as m_direct
    import app.agent.modes.langgraph as m_lg
    import app.agent.modes.plan_execute as m_plan
    import app.agent.modes.react as m_react

    for m in (m_direct, m_react, m_plan, m_lg):
        monkeypatch.setattr(m, "run_tool_loop", fake_loop)
        monkeypatch.setattr(m, "get_chat_model", lambda: object())

    agent = AgentFactory.create(mode, tools=ToolRegistry())
    res = await agent.run(_ctx(mode.value), NoopTrace(), db=None)
    assert res.answer == "答案"
    if mode == AgentMode.DIRECT:
        assert called["single_shot"] is True
    else:
        assert called["single_shot"] is False
