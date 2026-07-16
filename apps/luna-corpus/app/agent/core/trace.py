"""Agent 轨迹记录器：写 agent_runs / agent_steps，全程 fail-safe。"""
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.agent.core.context import AgentRunContext
from app.db.models import AgentRun, AgentRunStatus, AgentStep, AgentStepType
from app.observability.logging import get_logger

logger = get_logger("luna.agent.trace")

TOOL_RESULT_MAX_CHARS = 8192


class TraceRecorder:
    """把 agent 执行轨迹落库；任何写库异常都 fail-safe（log + rollback + 不抛）。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def start_run(self, ctx: AgentRunContext, query: str) -> None:
        """插入一行 agent_runs（状态 RUNNING），主键取 ctx.run_id。"""
        try:
            self.db.add(
                AgentRun(
                    id=ctx.run_id,
                    tenant_id=ctx.tenant_id,
                    workspace_id=ctx.workspace_id,
                    knowledge_base_id=ctx.knowledge_base_id,
                    user_id=ctx.user_id,
                    conversation_id=ctx.conversation_id,
                    mode=ctx.mode,
                    query=query,
                    status=AgentRunStatus.RUNNING,
                )
            )
            self.db.commit()
        except Exception:
            logger.warning("agent_trace_start_run_failed", exc_info=True)
            self._safe_rollback()

    def record_step(
        self,
        ctx: AgentRunContext,
        *,
        step_index: int,
        step_type: AgentStepType,
        thought: str | None = None,
        tool_name: str | None = None,
        tool_args: dict | None = None,
        tool_result: str | None = None,
        tool_success: bool | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int = 0,
    ) -> None:
        """插入一行 agent_steps；tool_result 超长会被截断并追加 "...[truncated]"。"""
        try:
            if tool_result is not None and len(tool_result) > TOOL_RESULT_MAX_CHARS:
                tool_result = tool_result[:TOOL_RESULT_MAX_CHARS] + "...[truncated]"
            self.db.add(
                AgentStep(
                    run_id=ctx.run_id,
                    step_index=step_index,
                    step_type=step_type,
                    thought=thought,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_result=tool_result,
                    tool_success=tool_success,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                )
            )
            self.db.commit()
        except Exception:
            logger.warning("agent_trace_record_step_failed", exc_info=True)
            self._safe_rollback()

    def end_run(
        self,
        ctx: AgentRunContext,
        *,
        status: AgentRunStatus,
        final_answer: str | None,
        total_cost: Decimal | int,
        latency_ms: int,
        error_message: str | None = None,
    ) -> None:
        """更新该 run 的终态字段与聚合信息。"""
        try:
            self.db.query(AgentRun).filter(AgentRun.id == ctx.run_id).update(
                {
                    AgentRun.status: status,
                    AgentRun.final_answer: final_answer,
                    AgentRun.steps_count: ctx.steps_count,
                    AgentRun.total_input_tokens: ctx.total_input_tokens,
                    AgentRun.total_output_tokens: ctx.total_output_tokens,
                    AgentRun.total_cost: total_cost,
                    AgentRun.latency_ms: latency_ms,
                    AgentRun.error_message: error_message,
                    AgentRun.finished_at: datetime.now(UTC),
                },
                synchronize_session=False,
            )
            self.db.commit()
        except Exception:
            logger.warning("agent_trace_end_run_failed", exc_info=True)
            self._safe_rollback()

    def _safe_rollback(self) -> None:
        """尽力回滚；即使回滚本身失败也吞掉。"""
        # 刻意保留 try/except/pass：fail-safe 兜底，
        # 明确表达"任何异常都吞掉、不上抛"的意图。
        try:  # noqa: SIM105
            self.db.rollback()
        except Exception:
            pass
