"""价格解析与成本折算。

缺价不阻断计量：折算返回 0 成本，token 照常记录。
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import ModelPrice
from app.observability.logging import get_logger

logger = get_logger("luna.cost.pricing")

_THOUSAND = Decimal(1000)


def resolve_price(
    db: Session, provider: str, model: str, at: datetime
) -> ModelPrice | None:
    """取 (provider, model) 下 effective_from <= at 的最新一条价格。"""
    return (
        db.query(ModelPrice)
        .filter(
            ModelPrice.provider == provider,
            ModelPrice.model == model,
            ModelPrice.effective_from <= at,
        )
        .order_by(ModelPrice.effective_from.desc())
        .first()
    )


def compute_cost(
    input_tokens: int, output_tokens: int, price: ModelPrice | None
) -> tuple[Decimal, str]:
    """按单价折算成本；无价格时返回 (0, 'CNY') 并 log warning。"""
    if price is None:
        logger.warning("compute_cost_no_price")
        return Decimal("0"), "CNY"
    cost = (
        Decimal(input_tokens) / _THOUSAND * price.input_price_per_1k
        + Decimal(output_tokens) / _THOUSAND * price.output_price_per_1k
    )
    return cost, price.currency
