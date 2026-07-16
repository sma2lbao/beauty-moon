"""Governance 每步预检测试。"""
import time

import pytest

from app.agent.core.context import AgentRunContext
from app.agent.core.governance import HaltSignal, check_step
from app.db.models import AgentRunStatus


def _ctx(**ov):
    # 默认 start_time 取当前时刻，保证 elapsed_s 远小于 timeout_s；
    # 需要模拟超时的用例会显式覆盖 start_time 并 monkeypatch time.time。
    base = dict(
        run_id="r1", tenant_id="t1", workspace_id="w1", knowledge_base_id="k1",
        user_id="u1", conversation_id=None, mode="react", max_steps=3,
        timeout_s=120, max_recursion_depth=3, start_time=time.time(),
    )
    base.update(ov)
    return AgentRunContext(**base)


def test_halts_on_max_steps(monkeypatch):
    import app.agent.core.governance as gov
    monkeypatch.setattr(gov, "check_quota", lambda *a, **k: None)
    ctx = _ctx(max_steps=3)
    with pytest.raises(HaltSignal) as exc:
        check_step(db=None, ctx=ctx, step_index=3)
    assert exc.value.status == AgentRunStatus.HALTED_MAX_STEPS


def test_halts_on_timeout(monkeypatch):
    import app.agent.core.governance as gov
    import app.agent.core.context as ctx_mod
    monkeypatch.setattr(gov, "check_quota", lambda *a, **k: None)
    ctx = _ctx(timeout_s=1, start_time=1000.0)
    monkeypatch.setattr(ctx_mod.time, "time", lambda: 1002.0)
    with pytest.raises(HaltSignal) as exc:
        check_step(db=None, ctx=ctx, step_index=0)
    assert exc.value.status == AgentRunStatus.HALTED_TIMEOUT


def test_halts_on_quota(monkeypatch):
    import app.agent.core.governance as gov
    from app.cost.enforcement import QuotaExceeded

    def boom(*a, **k):
        raise QuotaExceeded("tenant", "token")

    monkeypatch.setattr(gov, "check_quota", boom)
    ctx = _ctx()
    with pytest.raises(HaltSignal) as exc:
        check_step(db=None, ctx=ctx, step_index=0)
    assert exc.value.status == AgentRunStatus.HALTED_QUOTA


def test_passes_when_all_ok(monkeypatch):
    import app.agent.core.governance as gov
    monkeypatch.setattr(gov, "check_quota", lambda *a, **k: None)
    ctx = _ctx()
    # 不抛即通过
    check_step(db=None, ctx=ctx, step_index=0)
