import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.enums import ReferenceDataTableKey
from models.reference_data import ReferenceDataEntry, ReferenceDataVersion


async def get_active_version(db: AsyncSession) -> ReferenceDataVersion | None:
    result = await db.execute(select(ReferenceDataVersion).where(ReferenceDataVersion.is_active.is_(True)))
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, version_id: uuid.UUID) -> ReferenceDataVersion | None:
    return await db.get(ReferenceDataVersion, version_id)


async def list_versions(db: AsyncSession) -> list[ReferenceDataVersion]:
    result = await db.execute(select(ReferenceDataVersion).order_by(ReferenceDataVersion.created_at.desc()))
    return list(result.scalars().all())


async def list_entries(db: AsyncSession, version_id: uuid.UUID) -> list[ReferenceDataEntry]:
    result = await db.execute(select(ReferenceDataEntry).where(ReferenceDataEntry.version_id == version_id))
    return list(result.scalars().all())


async def create_version(
    db: AsyncSession,
    *,
    effective_from: datetime,
    created_by: uuid.UUID,
    note: str | None,
    entries: list[tuple[ReferenceDataTableKey, str | None, Decimal]],
) -> ReferenceDataVersion:
    """A version is created whole, with its entries, and never edited
    afterwards (§6.5 non-negotiable: never an in-place edit)."""
    version = ReferenceDataVersion(
        effective_from=effective_from,
        created_by=created_by,
        note=note,
        is_active=False,
    )
    db.add(version)
    await db.flush()

    for table_key, key1, value in entries:
        db.add(ReferenceDataEntry(version_id=version.id, table_key=table_key, key1=key1, value=value))
    await db.flush()
    return version


async def mark_impact_previewed(db: AsyncSession, version: ReferenceDataVersion) -> None:
    version.impact_previewed_at = datetime.now(UTC)
    await db.flush()


async def activate(db: AsyncSession, version: ReferenceDataVersion) -> None:
    """Flips exactly one version active at a time. Caller (the service
    layer) is responsible for the impact_previewed_at gate check — this
    function only performs the flip once permitted."""
    previous = await get_active_version(db)
    if previous is not None and previous.id != version.id:
        previous.is_active = False
    version.is_active = True
    version.activated_at = datetime.now(UTC)
    await db.flush()
