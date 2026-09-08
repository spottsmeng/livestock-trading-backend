import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.reference_data import ReferenceDataDrift


async def create_many(db: AsyncSession, rows: list[ReferenceDataDrift]) -> list[ReferenceDataDrift]:
    db.add_all(rows)
    await db.flush()
    return rows


async def list_all(db: AsyncSession, *, unacknowledged_only: bool = False) -> list[ReferenceDataDrift]:
    query = select(ReferenceDataDrift).order_by(ReferenceDataDrift.detected_at.desc())
    if unacknowledged_only:
        query = query.where(ReferenceDataDrift.acknowledged_at.is_(None))
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, drift_id: uuid.UUID) -> ReferenceDataDrift | None:
    return await db.get(ReferenceDataDrift, drift_id)


async def acknowledge(db: AsyncSession, drift: ReferenceDataDrift, *, acknowledged_by: uuid.UUID) -> None:
    drift.acknowledged_by = acknowledged_by
    drift.acknowledged_at = datetime.now(UTC)
    await db.flush()
