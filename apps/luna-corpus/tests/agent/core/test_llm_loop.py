"""run_tool_loop 循环引擎测试（mock LLM）。"""
import pytest

from app.agent.core.context import AgentRunContext
from app.agent.core.llm_loop import LoopResult, run_tool_loop
from app.agent.core.trace import TraceRecorder
from app.agent.registry import ToolRegistry
from app.agent.tool import tool
from app.db.models import AgentRunStatus


class FakeMsg:
    """假的 LLM 响应对象；提供 content / tool_calls / usage_metadata 三个属性。"""

    def __init__(self, content="", tool_calls=None, usage=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage_metadata = usage


class FakeChat:
    """按脚本依次返回 FakeMsg 的假 LLM；bind_tools 返回自身。"""

    def __init__(self, script):
        self._script = list(script)
        self.bound_schemas = None

    def bind_tools(self, schemas):
        self.bound_schemas = schemas
        return self

    def invoke(self, messages):
        return self._script.pop(0)


class NoopTrace:
    """占位 TraceRecorder，忽略所有轨迹调用。"""

    def start_run(self, *a, **k):
        pass

    def record_step(self, *a, **k):
        pass

    def end_run(self, *a, **k):
        pass


def _ctx(**ov):
    """构造一个默认的 AgentRunContext；ov 用于覆写字段。"""
    base = dict(
        run_id="r1",
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="k1",
        user_id="u1",
        conversation_id=None,
        mode="react",
        max_steps=5,
        timeout_s=120,
        max_recursion_depth=3,
        start_time=1000.0,
    )
    base.update(ov)
    return AgentRunContext(**base)


@pytest.mark.asyncio
async def test_converges_without_tools(monkeypatch):
    """LLM 首轮就给出答案（无 tool_calls）→ 立即收敛为 COMPLETED。"""
    import app.agent.core.llm_loop as loop_mod
    monkeypatch.setattr(loop_mod, "check_step", lambda *a, **k: None)
    chat = FakeChat([FakeMsg(content="直接回答")])
    reg = ToolRegistry()
    res = await run_tool_loop(
        chat=chat, registry=reg, ctx=_ctx(), trace=NoopTrace(), db=None,
        system_prompt="sys", user_query="q", provider="ark", model="m",
    )
    assert isinstance(res, LoopResult)
    assert res.answer == "直接回答"
    assert res.status == AgentRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_executes_tool_then_answers(monkeypatch):
    """LLM 先要求调用工具，工具返回后再给最终答案。"""
    import app.agent.core.llm_loop as loop_mod
    monkeypatch.setattr(loop_mod, "check_step", lambda *a, **k: None)

    @tool(name="echo", description="回显")
    def echo(value: str) -> str:
        return f"got:{value}"

    reg = ToolRegistry()
    reg.register(echo)

    chat = FakeChat([
        FakeMsg(tool_calls=[{"name": "echo", "args": {"value": "hi"}, "id": "c1"}]),
        FakeMsg(content="最终答案"),
    ])
    res = await run_tool_loop(
        chat=chat, registry=reg, ctx=_ctx(), trace=NoopTrace(), db=None,
        system_prompt="sys", user_query="q", provider="ark", model="m",
    )
    assert res.answer == "最终答案"
    assert res.status == AgentRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_halts_on_max_steps(monkeypatch):
    """LLM 一直要求调工具，撞上 max_steps 后强制收敛为 HALTED_MAX_STEPS。"""
    import app.agent.core.llm_loop as loop_mod
    monkeypatch.setattr(loop_mod, "check_step", lambda *a, **k: None)

    @tool(name="echo", description="回显")
    def echo(value: str) -> str:
        return "x"

    reg = ToolRegistry()
    reg.register(echo)

    script = [
        FakeMsg(tool_calls=[{"name": "echo", "args": {"value": "a"}, "id": "c"}])
        for _ in range(10)
    ]
    script.append(FakeMsg(content="兜底答案"))
    chat = FakeChat(script)
    res = await run_tool_loop(
        chat=chat, registry=reg, ctx=_ctx(max_steps=2), trace=NoopTrace(), db=None,
        system_prompt="sys", user_query="q", provider="ark", model="m",
    )
    assert res.status == AgentRunStatus.HALTED_MAX_STEPS


@pytest.mark.asyncio
async def test_tool_error_is_fed_back(monkeypatch):
    """工具抛异常时不崩，error 作为 observation 回灌，循环继续到最终答案。"""
    import app.agent.core.llm_loop as loop_mod
    monkeypatch.setattr(loop_mod, "check_step", lambda *a, **k: None)

    @tool(name="boom", description="炸")
    def boom(x: str) -> str:
        raise ValueError("kaboom")

    reg = ToolRegistry()
    reg.register(boom)

    chat = FakeChat([
        FakeMsg(tool_calls=[{"name": "boom", "args": {"x": "1"}, "id": "c1"}]),
        FakeMsg(content="尽管工具失败仍作答"),
    ])
    res = await run_tool_loop(
        chat=chat, registry=reg, ctx=_ctx(), trace=NoopTrace(), db=None,
        system_prompt="sys", user_query="q", provider="ark", model="m",
    )
    assert res.answer == "尽管工具失败仍作答"
    assert res.status == AgentRunStatus.COMPLETED
