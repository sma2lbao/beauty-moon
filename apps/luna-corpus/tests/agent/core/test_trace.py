"""TraceRecorder 落库与 fail-safe 测试。"""
import pytest

from app.agent.core.context import AgentRunContext
from app.agent.core.trace import TOOL_RESULT_MAX_CHARS, TraceRecorder
from app.db.models import AgentRun, AgentRunStatus, AgentStep, AgentStepType


def _ctx(run_id="r1"):
    return AgentRunContext(
        run_id=run_id, tenant_id="t1", workspace_id="w1", knowledge_base_id="k1",
        user_id="u1", conversation_id=None, mode="react", max_steps=10,
        timeout_s=120, max_recursion_depth=3, start_time=1000.0,
    )


def test_start_run_inserts_running_row(db_session):
    rec = TraceRecorder(db_session)
    ctx = _ctx()
    rec.start_run(ctx, query="hi")
    row = db_session.query(AgentRun).filter(AgentRun.id == "r1").first()
    assert row is not None
    assert row.status == AgentRunStatus.RUNNING
    assert row.query == "hi"


def test_record_step_persists(db_session):
    rec = TraceRecorder(db_session)
    ctx = _ctx()
    rec.start_run(ctx, query="hi")
    rec.record_step(ctx, step_index=0, step_type=AgentStepType.TOOL_CALL,
                    tool_name="rag_search", tool_args={"query": "x"}, latency_ms=5)
    steps = db_session.query(AgentStep).filter(AgentStep.run_id == "r1").all()
    assert len(steps) == 1
    assert steps[0].tool_name == "rag_search"
    assert steps[0].tool_args == {"query": "x"}


def test_record_step_truncates_tool_result(db_session):
    rec = TraceRecorder(db_session)
    ctx = _ctx()
    rec.start_run(ctx, query="hi")
    huge = "a" * (TOOL_RESULT_MAX_CHARS + 500)
    rec.record_step(ctx, step_index=0, step_type=AgentStepType.TOOL_RESULT,
                    tool_result=huge, tool_success=True)
    step = db_session.query(AgentStep).filter(AgentStep.run_id == "r1").first()
    assert len(step.tool_result) <= TOOL_RESULT_MAX_CHARS + len("...[truncated]")
    assert step.tool_result.endswith("...[truncated]")


def test_end_run_updates_status(db_session):
    rec = TraceRecorder(db_session)
    ctx = _ctx()
    rec.start_run(ctx, query="hi")
    rec.end_run(ctx, status=AgentRunStatus.COMPLETED, final_answer="done",
                total_cost=0, latency_ms=42)
    row = db_session.query(AgentRun).filter(AgentRun.id == "r1").first()
    assert row.status == AgentRunStatus.COMPLETED
    assert row.final_answer == "done"
    assert row.latency_ms == 42
    assert row.finished_at is not None


def test_record_step_failsafe_swallows(db_session):
    """db 抛错时 record_step 不得向上抛。"""
    class Boom:
        def add(self, *a, **k):
            raise RuntimeError("boom")
        def rollback(self):
            pass
    rec = TraceRecorder(Boom())
    ctx = _ctx()
    # 不抛即通过
    rec.record_step(ctx, step_index=0, step_type=AgentStepType.REASONING, thought="x")
