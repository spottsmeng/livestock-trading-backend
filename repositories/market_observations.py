import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.market_observation import MarketObservation

DUPLICATE_WINDOW = timedelta(minutes=2)  # same non-blocking flag as BuyEntry's — see repositories/buy_entries.py


async def create(db: AsyncSession, observation: MarketObservation) -> MarketObservation:
    db.add(observation)
    await db.flush()
    return observation


async def get_by_client_uuid(db: AsyncSession, client_uuid: uuid.UUID) -> MarketObservation | None:
    result = await db.execute(select(MarketObservation).where(MarketObservation.client_uuid == client_uuid))
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, observation_id: uuid.UUID) -> MarketObservation | None:
    return await db.get(MarketObservation, observation_id)


async def list_for_org(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    trade_date_from: date | None = None,
    trade_date_to: date | None = None,
    saleyard: str | None = None,
    species: str | None = None,
    competitor_name: str | None = None,
) -> list[MarketObservation]:
    """OWNER/ACCOUNTANT read path (§ market intelligence) — every buyer in
    the org's observations, never scoped to a single observer the way
    BuyEntry's list_for_buyer is."""
    stmt = select(MarketObservation).where(MarketObservation.org_id == org_id, MarketObservation.is_deleted.is_(False))
    if trade_date_from is not None:
        stmt = stmt.where(MarketObservation.trade_date >= trade_date_from)
    if trade_date_to is not None:
        stmt = stmt.where(MarketObservation.trade_date <= trade_date_to)
    if saleyard is not None:
        stmt = stmt.where(MarketObservation.saleyard == saleyard)
    if species is not None:
        stmt = stmt.where(MarketObservation.species == species)
    if competitor_name is not None:
        stmt = stmt.where(MarketObservation.competitor_name == competitor_name)
    result = await db.execute(stmt.order_by(MarketObservation.client_created_at.desc()))
    return list(result.scalars().all())


async def find_recent_duplicate(
    db: AsyncSession,
    *,
    observer_id: uuid.UUID,
    agent: str | None,
    pen: str | None,
    price_per_head,
    as_of: datetime,
) -> MarketObservation | None:
    result = await db.execute(
        select(MarketObservation)
        .where(
            MarketObservation.observer_id == observer_id,
            MarketObservation.agent == agent,
            MarketObservation.pen == pen,
            MarketObservation.price_per_head == price_per_head,
            MarketObservation.client_created_at >= as_of - DUPLICATE_WINDOW,
            MarketObservation.client_created_at <= as_of + DUPLICATE_WINDOW,
            MarketObservation.is_deleted.is_(False),
        )
        .order_by(MarketObservation.client_created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
