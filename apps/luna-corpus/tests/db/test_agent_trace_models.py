"""AgentRun / AgentStep 模型冒烟测试。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentStepType,
    Base,
)


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_agent_run_defaults():
    session = _session()
    run = AgentRun(
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="k1",
        user_id="u1",
        mode="react",
        query="hello",
    )
    session.add(run)
    session.flush()
    assert run.id is not None
    assert run.status == AgentRunStatus.RUNNING
    assert run.steps_count == 0
    assert run.total_input_tokens == 0
    assert run.total_output_tokens == 0


def test_agent_step_defaults():
    session = _session()
    run = AgentRun(
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="k1",
        user_id="u1",
        mode="react",
        query="hello",
    )
    session.add(run)
    session.flush()
    step = AgentStep(
        run_id=run.id,
        step_index=0,
        step_type=AgentStepType.REASONING,
    )
    session.add(step)
    session.flush()
    assert step.id is not None
    assert step.step_index == 0
    assert step.step_type == AgentStepType.REASONING


def test_status_enum_values():
    assert AgentRunStatus.HALTED_QUOTA.value == "halted_quota"
    assert AgentRunStatus.HALTED_MAX_STEPS.value == "halted_max_steps"
    assert AgentRunStatus.HALTED_TIMEOUT.value == "halted_timeout"
