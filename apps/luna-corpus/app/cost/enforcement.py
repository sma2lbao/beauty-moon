"""配额准入：事前检查 + fail-open。"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import QuotaCounter, QuotaLimit
from app.observability.logging import get_logger

settings = get_settings()
logger = get_logger("luna.cost.enforcement")


class QuotaExceeded(Exception):
    """配额超限。"""

    def __init__(self, scope_type: str, dimension: str) -> None:
        self.scope_type = scope_type
        self.dimension = dimension
        super().__init__(f"{scope_type} daily {dimension} quota exceeded")


def _check_scope(db: Session, scope_type: str, scope_id: str, usage_date) -> None:
    limit = (
        db.query(QuotaLimit)
        .filter(QuotaLimit.scope_type == scope_type, QuotaLimit.scope_id == scope_id)
        .first()
    )
    if limit is None:
        return
    if limit.daily_token_limit is None and limit.daily_cost_limit is None:
        return
    counter = (
        db.query(QuotaCounter)
        .filter(
            QuotaCounter.scope_type == scope_type,
            QuotaCounter.scope_id == scope_id,
            QuotaCounter.usage_date == usage_date,
        )
        .first()
    )
    token_used = counter.token_used if counter else 0
    cost_used = counter.cost_used if counter else 0
    if limit.daily_token_limit is not None and token_used >= limit.daily_token_limit:
        raise QuotaExceeded(scope_type, "token")
    if limit.daily_cost_limit is not None and cost_used >= limit.daily_cost_limit:
        raise QuotaExceeded(scope_type, "cost")


def check_quota(db: Session, tenant_id: str, workspace_id: str) -> None:
    """检查租户与工作区当日配额；超限抛 QuotaExceeded，读取异常时 fail-open 放行。"""
    if not settings.cost_enforcement_enabled:
        return
    usage_date = datetime.now(timezone.utc).date()
    try:
        _check_scope(db, "tenant", tenant_id, usage_date)
        _check_scope(db, "workspace", workspace_id, usage_date)
    except QuotaExceeded:
        raise
    except Exception:
        logger.warning("check_quota_failed_open", exc_info=True)
        return
