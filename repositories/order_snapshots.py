import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.order_snapshot import OrderSnapshot


async def create(db: AsyncSession, snapshot: OrderSnapshot) -> OrderSnapshot:
    db.add(snapshot)
    await db.flush()
    return snapshot


async def get_by_id(db: AsyncSession, snapshot_id: uuid.UUID) -> OrderSnapshot | None:
    return await db.get(OrderSnapshot, snapshot_id)


async def get_latest_for_org(db: AsyncSession, org_id: uuid.UUID) -> OrderSnapshot | None:
    """The previous committed snapshot to diff a new upload against
    (§7.3) — the file is cumulative, so "what changed since yesterday" is
    always relative to the most recently committed snapshot, not any
    particular calendar date."""
    result = await db.execute(
        select(OrderSnapshot).where(OrderSnapshot.org_id == org_id).order_by(OrderSnapshot.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def list_for_org(db: AsyncSession, org_id: uuid.UUID) -> list[OrderSnapshot]:
    result = await db.execute(
        select(OrderSnapshot).where(OrderSnapshot.org_id == org_id).order_by(OrderSnapshot.created_at.desc())
    )
    return list(result.scalars().all())
