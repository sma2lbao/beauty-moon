"""成本管理业务逻辑：配额配置、用量查询、价格维护。"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import ModelPrice, QuotaCounter, QuotaLimit, UsageRecord


def upsert_quota_limit(
    db: Session,
    *,
    scope_type: str,
    scope_id: str,
    daily_token_limit: int | None,
    daily_cost_limit: Decimal | None,
    currency: str,
) -> QuotaLimit:
    """按 (scope_type, scope_id) upsert 配额限额行。"""
    limit = (
        db.query(QuotaLimit)
        .filter(
            QuotaLimit.scope_type == scope_type,
            QuotaLimit.scope_id == scope_id,
        )
        .first()
    )
    if limit is None:
        limit = QuotaLimit(scope_type=scope_type, scope_id=scope_id)
        db.add(limit)
    limit.daily_token_limit = daily_token_limit
    limit.daily_cost_limit = daily_cost_limit
    limit.currency = currency
    db.commit()
    db.refresh(limit)
    return limit


def _scope_usage(db: Session, scope_type: str, scope_id: str) -> dict:
    """取指定 scope 的当日限额与已用量。"""
    today = datetime.now(timezone.utc).date()
    limit = (
        db.query(QuotaLimit)
        .filter(
            QuotaLimit.scope_type == scope_type,
            QuotaLimit.scope_id == scope_id,
        )
        .first()
    )
    counter = (
        db.query(QuotaCounter)
        .filter(
            QuotaCounter.scope_type == scope_type,
            QuotaCounter.scope_id == scope_id,
            QuotaCounter.usage_date == today,
        )
        .first()
    )
    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "daily_token_limit": limit.daily_token_limit if limit else None,
        "daily_cost_limit": (
            str(limit.daily_cost_limit)
            if limit and limit.daily_cost_limit is not None
            else None
        ),
        "currency": limit.currency if limit else "CNY",
        "token_used": counter.token_used if counter else 0,
        "cost_used": str(counter.cost_used) if counter else "0",
    }


def get_current_usage(db: Session, tenant_id: str, workspace_id: str) -> dict:
    """返回租户与工作区当日的配额限额与已用量。"""
    return {
        "tenant": _scope_usage(db, "tenant", tenant_id),
        "workspace": _scope_usage(db, "workspace", workspace_id),
    }


def list_usage_records(
    db: Session,
    *,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[UsageRecord], int]:
    """分页列出本租户的 UsageRecord，返回 (行, 总数)。"""
    q = db.query(UsageRecord).filter(UsageRecord.tenant_id == tenant_id)
    total = q.count()
    rows = (
        q.order_by(UsageRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return rows, total


def upsert_model_price(
    db: Session,
    *,
    provider: str,
    model: str,
    input_price_per_1k: Decimal,
    output_price_per_1k: Decimal,
    currency: str,
    effective_from: datetime,
) -> ModelPrice:
    """新增一条价格记录（按 effective_from 作为生效点）。"""
    price = ModelPrice(
        provider=provider,
        model=model,
        input_price_per_1k=input_price_per_1k,
        output_price_per_1k=output_price_per_1k,
        currency=currency,
        effective_from=effective_from,
    )
    db.add(price)
    db.commit()
    db.refresh(price)
    return price
