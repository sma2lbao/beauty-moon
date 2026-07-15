"""AgentRunContext 测试。"""
from app.agent.core.context import AgentRunContext


def _make_ctx(**overrides):
    base = dict(
        run_id="r1",
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="k1",
        user_id="u1",
        conversation_id=None,
        mode="react",
        max_steps=10,
        timeout_s=120,
        max_recursion_depth=3,
        start_time=1000.0,
    )
    base.update(overrides)
    return AgentRunContext(**base)


def test_context_defaults():
    ctx = _make_ctx()
    assert ctx.memory_history == ""
    assert ctx.total_input_tokens == 0
    assert ctx.total_output_tokens == 0
    assert ctx.steps_count == 0


def test_elapsed_uses_start_time(monkeypatch):
    import app.agent.core.context as ctx_mod

    ctx = _make_ctx(start_time=1000.0)
    monkeypatch.setattr(ctx_mod.time, "time", lambda: 1002.5)
    assert ctx.elapsed_s() == 2.5
