import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.buy_entry import BuyEntry

DUPLICATE_WINDOW = timedelta(minutes=2)  # §12.4 — same agent+pen+price within this window is flagged, not blocked


async def create(db: AsyncSession, entry: BuyEntry) -> BuyEntry:
    db.add(entry)
    await db.flush()
    return entry


async def get_by_client_uuid(db: AsyncSession, client_uuid: uuid.UUID) -> BuyEntry | None:
    """The idempotency check §12.7 requires — POST /buyer/entries(/bulk)
    upserts on this, so a replayed offline queue item is always safe."""
    result = await db.execute(select(BuyEntry).where(BuyEntry.client_uuid == client_uuid))
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, entry_id: uuid.UUID) -> BuyEntry | None:
    return await db.get(BuyEntry, entry_id)


async def list_for_buyer(
    db: AsyncSession, buyer_id: uuid.UUID, *, trade_date: date | None = None, saleyard: str | None = None
) -> list[BuyEntry]:
    stmt = select(BuyEntry).where(BuyEntry.buyer_id == buyer_id, BuyEntry.is_deleted.is_(False))
    if trade_date is not None:
        stmt = stmt.where(BuyEntry.trade_date == trade_date)
    if saleyard is not None:
        stmt = stmt.where(BuyEntry.saleyard == saleyard)
    result = await db.execute(stmt.order_by(BuyEntry.client_created_at.desc()))
    return list(result.scalars().all())


async def find_recent_duplicate(
    db: AsyncSession, *, buyer_id: uuid.UUID, agent: str | None, pen: str | None, price_per_head, as_of: datetime
) -> BuyEntry | None:
    """§12.4 — "warn if agent + pen + price repeat within 2 minutes".
    Non-blocking: the caller surfaces this as a flag on the response, never
    a rejection, since a buyer sometimes genuinely does buy the same pen
    twice in a row."""
    result = await db.execute(
        select(BuyEntry)
        .where(
            BuyEntry.buyer_id == buyer_id,
            BuyEntry.agent == agent,
            BuyEntry.pen == pen,
            BuyEntry.price_per_head == price_per_head,
            BuyEntry.client_created_at >= as_of - DUPLICATE_WINDOW,
            BuyEntry.client_created_at <= as_of + DUPLICATE_WINDOW,
            BuyEntry.is_deleted.is_(False),
        )
        .order_by(BuyEntry.client_created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
