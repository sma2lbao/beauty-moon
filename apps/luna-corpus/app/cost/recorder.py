"""用量明细记录与日度计数器累加（旁路容错）。

任何失败都 log + rollback + swallow，绝不影响 QA 响应。
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.cost.pricing import compute_cost, resolve_price
from app.db.models import QuotaCounter, UsageRecord
from app.observability.logging import get_logger
from app.observability.metrics import LLM_COST_TOTAL, LLM_TOKENS_TOTAL
from app.services.llm import TokenUsage

logger = get_logger("luna.cost.recorder")


def bump_counter(
    db: Session,
    *,
    scope_type: str,
    scope_id: str,
    usage_date: date,
    token_delta: int,
    cost_delta: Decimal,
) -> None:
    """可移植原子累加：先 UPDATE，命中 0 行则 INSERT，竞争 IntegrityError 时重试 UPDATE。"""
    updated = (
        db.query(QuotaCounter)
        .filter(
            QuotaCounter.scope_type == scope_type,
            QuotaCounter.scope_id == scope_id,
            QuotaCounter.usage_date == usage_date,
        )
        .update(
            {
                QuotaCounter.token_used: QuotaCounter.token_used + token_delta,
                QuotaCounter.cost_used: QuotaCounter.cost_used + cost_delta,
            },
            synchronize_session=False,
        )
    )
    if updated:
        return
    try:
        db.add(
            QuotaCounter(
                scope_type=scope_type,
                scope_id=scope_id,
                usage_date=usage_date,
                token_used=token_delta,
                cost_used=cost_delta,
            )
        )
        db.flush()
    except IntegrityError:
        db.rollback()
        db.query(QuotaCounter).filter(
            QuotaCounter.scope_type == scope_type,
            QuotaCounter.scope_id == scope_id,
            QuotaCounter.usage_date == usage_date,
        ).update(
            {
                QuotaCounter.token_used: QuotaCounter.token_used + token_delta,
                QuotaCounter.cost_used: QuotaCounter.cost_used + cost_delta,
            },
            synchronize_session=False,
        )


def record_usage(
    db: Session,
    *,
    tenant_id: str,
    workspace_id: str,
    knowledge_base_id: str,
    interaction_id: str | None,
    usage: TokenUsage | None,
) -> None:
    """折算成本、写明细、累加租户与工作区计数器、打指标。失败静默。"""
    if usage is None:
        logger.info("record_usage_skipped_no_usage", knowledge_base_id=knowledge_base_id)
        return
    try:
        now = datetime.now(timezone.utc)
        today = now.date()
        price = resolve_price(db, usage.provider, usage.model, now)
        cost, currency = compute_cost(usage.input_tokens, usage.output_tokens, price)
        total_tokens = usage.input_tokens + usage.output_tokens

        db.add(
            UsageRecord(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                knowledge_base_id=knowledge_base_id,
                interaction_id=interaction_id,
                provider=usage.provider,
                model=usage.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=total_tokens,
                cost_amount=cost,
                currency=currency,
            )
        )
        bump_counter(
            db,
            scope_type="tenant",
            scope_id=tenant_id,
            usage_date=today,
            token_delta=total_tokens,
            cost_delta=cost,
        )
        bump_counter(
            db,
            scope_type="workspace",
            scope_id=workspace_id,
            usage_date=today,
            token_delta=total_tokens,
            cost_delta=cost,
        )
        db.commit()

        LLM_TOKENS_TOTAL.labels(
            provider=usage.provider, model=usage.model, direction="input"
        ).inc(usage.input_tokens)
        LLM_TOKENS_TOTAL.labels(
            provider=usage.provider, model=usage.model, direction="output"
        ).inc(usage.output_tokens)
        LLM_COST_TOTAL.labels(
            provider=usage.provider, model=usage.model, currency=currency
        ).inc(float(cost))
    except Exception:
        logger.warning(
            "record_usage_failed",
            knowledge_base_id=knowledge_base_id,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass
