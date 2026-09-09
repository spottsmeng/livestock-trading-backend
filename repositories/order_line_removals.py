import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.order_line_removal import OrderLineRemoval


async def create_many(db: AsyncSession, rows: list[OrderLineRemoval]) -> list[OrderLineRemoval]:
    db.add_all(rows)
    await db.flush()
    return rows


async def list_all(db: AsyncSession, *, unacknowledged_only: bool = False) -> list[OrderLineRemoval]:
    query = select(OrderLineRemoval).order_by(OrderLineRemoval.detected_at.desc())
    if unacknowledged_only:
        query = query.where(OrderLineRemoval.acknowledged_at.is_(None))
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, removal_id: uuid.UUID) -> OrderLineRemoval | None:
    return await db.get(OrderLineRemoval, removal_id)


async def acknowledge(
    db: AsyncSession, removal: OrderLineRemoval, *, acknowledged_by: uuid.UUID, reason: str | None
) -> None:
    removal.acknowledged_by = acknowledged_by
    removal.acknowledged_at = datetime.now(UTC)
    removal.reason = reason
    await db.flush()
