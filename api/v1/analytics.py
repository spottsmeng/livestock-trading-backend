import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUser, require_role
from core.db import get_db
from models.enums import Role
from schemas.analytics import (
    BuyerPerformanceResponse,
    DnbpTrendResponse,
    ExceptionsResponse,
    FulfilmentResponse,
    MarginBridgeResponse,
    OrderBookResponse,
    OverviewResponse,
)
from services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])

# §9.7 — every /analytics/* route is OWNER/ACCOUNTANT only, same pattern as
# every other trading-console surface (§2.1: Bobby and Bing are
# collaborators, neither gated ahead of the other).
_trading_console = require_role(Role.OWNER, Role.ACCOUNTANT)


@router.get("/overview", response_model=OverviewResponse)
async def overview(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> OverviewResponse:
    return await analytics_service.overview(db, current.org_id, since=from_, until=to)


@router.get("/order-book", response_model=OrderBookResponse)
async def order_book(
    current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> OrderBookResponse:
    return await analytics_service.order_book(db, current.org_id)


@router.get("/dnbp-trend", response_model=DnbpTrendResponse)
async def dnbp_trend(
    species: str,
    days: int = Query(default=30, ge=1, le=365),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> DnbpTrendResponse:
    return await analytics_service.dnbp_trend(db, current.org_id, species=species, days=days)


@router.get("/buyer-performance", response_model=BuyerPerformanceResponse)
async def buyer_performance(
    buyer_id: uuid.UUID | None = Query(default=None),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> BuyerPerformanceResponse:
    return await analytics_service.buyer_performance(db, current.org_id, buyer_id=buyer_id, since=from_, until=to)


@router.get("/margin-bridge", response_model=MarginBridgeResponse)
async def margin_bridge(
    snapshot_id: uuid.UUID | None = Query(default=None),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> MarginBridgeResponse:
    return await analytics_service.margin_bridge(db, current.org_id, snapshot_id=snapshot_id)


@router.get("/fulfilment", response_model=FulfilmentResponse)
async def fulfilment(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> FulfilmentResponse:
    return await analytics_service.fulfilment(db, current.org_id, since=from_, until=to)


@router.get("/breaches", response_model=ExceptionsResponse)
async def breaches(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    saleyard: str | None = Query(default=None),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> ExceptionsResponse:
    return await analytics_service.exceptions(db, current.org_id, since=from_, until=to, saleyard=saleyard)
