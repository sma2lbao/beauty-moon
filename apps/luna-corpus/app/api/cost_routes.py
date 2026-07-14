"""成本与配额管理 API 路由。"""
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
from app.cost import service
from app.db.database import get_db

router = APIRouter(prefix="/api/v1", tags=["cost"])


class QuotaLimitRequest(BaseModel):
    """PUT /quota/limits 请求体。"""

    scope_type: str = Field(..., pattern="^(tenant|workspace)$")
    scope_id: str
    daily_token_limit: int | None = None
    daily_cost_limit: Decimal | None = None
    currency: str = "CNY"


class QuotaLimitResponse(BaseModel):
    """PUT /quota/limits 响应体。"""

    scope_type: str
    scope_id: str
    daily_token_limit: int | None
    daily_cost_limit: Decimal | None
    currency: str

    model_config = ConfigDict(from_attributes=True)


class UsageRecordResponse(BaseModel):
    """UsageRecord 序列化视图。"""

    id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_amount: Decimal
    currency: str

    model_config = ConfigDict(from_attributes=True)


class UsageRecordListResponse(BaseModel):
    """GET /cost/records 响应体。"""

    records: list[UsageRecordResponse]
    total: int


class ModelPriceRequest(BaseModel):
    """PUT /cost/prices 请求体。"""

    provider: str
    model: str
    input_price_per_1k: Decimal
    output_price_per_1k: Decimal
    currency: str = "CNY"
    effective_from: datetime


class ModelPriceResponse(BaseModel):
    """PUT /cost/prices 响应体。"""

    id: str


@router.put("/quota/limits", response_model=QuotaLimitResponse)
async def put_quota_limit(
    req: QuotaLimitRequest,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.COST_MANAGE)),
    ],
) -> QuotaLimitResponse:
    """按 (scope_type, scope_id) upsert 配额限额。"""
    _ = context
    limit = service.upsert_quota_limit(
        db,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        daily_token_limit=req.daily_token_limit,
        daily_cost_limit=req.daily_cost_limit,
        currency=req.currency,
    )
    return QuotaLimitResponse.model_validate(limit)


@router.get("/quota/usage")
async def get_quota_usage(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.COST_READ)),
    ],
) -> dict:
    """返回当前租户与工作区的当日配额与已用量。"""
    return service.get_current_usage(
        db, context.tenant.id, context.workspace.id
    )


@router.get("/cost/records", response_model=UsageRecordListResponse)
async def get_cost_records(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.COST_READ)),
    ],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> UsageRecordListResponse:
    """分页列出当前租户的 UsageRecord。"""
    rows, total = service.list_usage_records(
        db, tenant_id=context.tenant.id, limit=limit, offset=offset
    )
    return UsageRecordListResponse(
        records=[UsageRecordResponse.model_validate(r) for r in rows],
        total=total,
    )


@router.put("/cost/prices", response_model=ModelPriceResponse)
async def put_model_price(
    req: ModelPriceRequest,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.COST_MANAGE)),
    ],
) -> ModelPriceResponse:
    """新增一条价格记录。"""
    _ = context
    price = service.upsert_model_price(
        db,
        provider=req.provider,
        model=req.model,
        input_price_per_1k=req.input_price_per_1k,
        output_price_per_1k=req.output_price_per_1k,
        currency=req.currency,
        effective_from=req.effective_from,
    )
    return ModelPriceResponse(id=price.id)
