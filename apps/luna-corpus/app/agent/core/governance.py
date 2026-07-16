"""Agent 每步治理预检：步数 / 超时 / 配额。触发即抛 HaltSignal。"""
from sqlalchemy.orm import Session

from app.agent.core.context import AgentRunContext
from app.cost.enforcement import QuotaExceeded, check_quota
from app.db.models import AgentRunStatus


class HaltSignal(Exception):
    """治理熔断信号：由管线捕获并将 run 标记为对应 halted_* 状态。"""

    def __init__(self, status: AgentRunStatus, reason: str) -> None:
        self.status = status
        self.reason = reason
        super().__init__(reason)


def check_step(db: Session | None, ctx: AgentRunContext, step_index: int) -> None:
    """每步开始前调用；任一检查不过即抛 HaltSignal。

    顺序：步数上限 → 墙钟超时 → 配额（配额服务异常时 check_quota 内部 fail-open）。
    """
    if step_index >= ctx.max_steps:
        raise HaltSignal(AgentRunStatus.HALTED_MAX_STEPS, "max steps reached")

    if ctx.elapsed_s() > ctx.timeout_s:
        raise HaltSignal(AgentRunStatus.HALTED_TIMEOUT, "wall-clock timeout")

    try:
        check_quota(db, ctx.tenant_id, ctx.workspace_id)
    except QuotaExceeded as exc:
        raise HaltSignal(AgentRunStatus.HALTED_QUOTA, str(exc)) from exc
