"""Agent 全链路集成：run/steps 落库、成本累加、熔断状态。"""
import time

import pytest

from app.agent.core.context import AgentRunContext
from app.agent.core.governance import HaltSignal
from app.agent.core.trace import TraceRecorder
from app.agent.factory import AgentFactory
from app.agent.registry import ToolRegistry
from app.agent.tool import tool
from app.core.config import AgentMode
from app.db.models import AgentRun, AgentRunStatus, AgentStep


class FakeMsg:
    """模拟 LangChain BaseMessage：暴露 content / tool_calls / usage_metadata。"""

    def __init__(self, content="", tool_calls=None, usage=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage_metadata = usage


class FakeChat:
    """按脚本回放的 LLM 客户端桩。"""

    def __init__(self, script):
        self._script = list(script)

    def bind_tools(self, schemas):
        return self

    def invoke(self, messages):
        return self._script.pop(0)

    async def ainvoke(self, messages):
        return self.invoke(messages)


def _ctx(db_ok_mode="react", max_steps=5, timeout_s=120):
    """构造一个默认的 AgentRunContext。"""
    return AgentRunContext(
        run_id="run-int-1",
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="k1",
        user_id="u1",
        conversation_id=None,
        mode=db_ok_mode,
        max_steps=max_steps,
        timeout_s=timeout_s,
        max_recursion_depth=3,
        start_time=time.time(),
        query="用工具查一下",
    )


@pytest.mark.asyncio
async def test_full_trace_persisted(db_session, monkeypatch):
    """一次成功的 ReAct 循环应把 run/steps 完整落库并累加 token。"""
    import app.agent.core.llm_loop as loop_mod
    monkeypatch.setattr(loop_mod, "check_step", lambda *a, **k: None)

    @tool(name="echo", description="回显")
    def echo(value: str) -> str:
        return f"got:{value}"

    reg = ToolRegistry()
    reg.register(echo)
    agent = AgentFactory.create(AgentMode.REACT, tools=reg)

    monkeypatch.setattr(
        "app.agent.modes.react.get_chat_model",
        lambda: FakeChat([
            FakeMsg(
                tool_calls=[{"name": "echo", "args": {"value": "x"}, "id": "c1"}],
                usage={"input_tokens": 10, "output_tokens": 5},
            ),
            FakeMsg(content="完成", usage={"input_tokens": 3, "output_tokens": 2}),
        ]),
    )

    ctx = _ctx()
    trace = TraceRecorder(db_session)
    trace.start_run(ctx, ctx.query)
    result = await agent.run(ctx, trace, db_session)
    trace.end_run(
        ctx,
        status=result.status,
        final_answer=result.answer,
        total_cost=0,
        latency_ms=100,
    )

    run = db_session.query(AgentRun).filter(AgentRun.id == "run-int-1").first()
    assert run.status == AgentRunStatus.COMPLETED
    assert run.final_answer == "完成"
    assert run.total_input_tokens == 13
    assert run.total_output_tokens == 7
    steps = db_session.query(AgentStep).filter(AgentStep.run_id == "run-int-1").all()
    # reasoning + tool_call + tool_result + final ≥ 4 步
    assert len(steps) >= 4


@pytest.mark.asyncio
async def test_quota_halt_marks_run(db_session, monkeypatch):
    """配额熔断 → run 标 halted_quota，部分步骤已落库。"""
    import app.agent.core.llm_loop as loop_mod
    from app.db.models import AgentRunStatus as S

    def halt(*a, **k):
        raise HaltSignal(S.HALTED_QUOTA, "quota exceeded")

    monkeypatch.setattr(loop_mod, "check_step", halt)

    agent = AgentFactory.create(AgentMode.REACT, tools=ToolRegistry())
    monkeypatch.setattr("app.agent.modes.react.get_chat_model", lambda: FakeChat([]))

    ctx = _ctx()
    trace = TraceRecorder(db_session)
    trace.start_run(ctx, ctx.query)
    with pytest.raises(HaltSignal) as exc:
        await agent.run(ctx, trace, db_session)
    trace.end_run(
        ctx,
        status=exc.value.status,
        final_answer="",
        total_cost=0,
        latency_ms=1,
        error_message=exc.value.reason,
    )

    run = db_session.query(AgentRun).filter(AgentRun.id == "run-int-1").first()
    assert run.status == AgentRunStatus.HALTED_QUOTA
