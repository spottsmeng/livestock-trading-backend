import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.order_workings import OrderWorkings


async def upsert(db: AsyncSession, workings: OrderWorkings) -> OrderWorkings:
    """order_workings is derived, freely INSERT/UPDATE (§8) — recalculation
    replaces any prior row for the same order_line rather than accumulating
    history, since only the current computation is ever meaningful."""
    existing = await get_by_order_line_id(db, workings.order_line_id)
    if existing is None:
        db.add(workings)
        await db.flush()
        return workings

    for column in OrderWorkings.__table__.columns.keys():
        if column in ("id", "order_line_id", "created_at"):
            continue
        setattr(existing, column, getattr(workings, column))
    await db.flush()
    return existing


async def get_by_order_line_id(db: AsyncSession, order_line_id: uuid.UUID) -> OrderWorkings | None:
    result = await db.execute(select(OrderWorkings).where(OrderWorkings.order_line_id == order_line_id))
    return result.scalar_one_or_none()
