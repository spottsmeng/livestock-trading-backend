import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.dnbp_publication import DnbpPublication, DnbpPublicationLine


async def create(db: AsyncSession, publication: DnbpPublication) -> DnbpPublication:
    db.add(publication)
    await db.flush()
    return publication


async def add_lines(db: AsyncSession, lines: list[DnbpPublicationLine]) -> list[DnbpPublicationLine]:
    db.add_all(lines)
    await db.flush()
    return lines


async def get_by_id(db: AsyncSession, publication_id: uuid.UUID) -> DnbpPublication | None:
    return await db.get(DnbpPublication, publication_id)


async def get_current_for_org(db: AsyncSession, org_id: uuid.UUID) -> DnbpPublication | None:
    """The live publication (§9.4 `GET /publications/current`) — the most
    recent one for this org that nothing has superseded yet."""
    result = await db.execute(
        select(DnbpPublication)
        .where(DnbpPublication.org_id == org_id, DnbpPublication.superseded_by.is_(None))
        .order_by(DnbpPublication.published_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_for_org(db: AsyncSession, org_id: uuid.UUID) -> list[DnbpPublication]:
    result = await db.execute(
        select(DnbpPublication).where(DnbpPublication.org_id == org_id).order_by(DnbpPublication.published_at.desc())
    )
    return list(result.scalars().all())


async def list_lines(db: AsyncSession, publication_id: uuid.UUID) -> list[DnbpPublicationLine]:
    result = await db.execute(
        select(DnbpPublicationLine).where(DnbpPublicationLine.publication_id == publication_id)
    )
    return list(result.scalars().all())


async def find_effective_as_of(db: AsyncSession, org_id: uuid.UUID, as_of: datetime) -> DnbpPublication | None:
    """§12.4's freeze rule: resolves whichever publication was live at a
    given instant, not "current" — an offline buy entry synced hours later
    must still freeze the DNBP that was actually on the buyer's screen when
    they wrote it down, even if it has since been superseded."""
    result = await db.execute(
        select(DnbpPublication)
        .where(DnbpPublication.org_id == org_id, DnbpPublication.published_at <= as_of)
        .order_by(DnbpPublication.published_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_line_for_species(
    db: AsyncSession, publication_id: uuid.UUID, species: str
) -> DnbpPublicationLine | None:
    result = await db.execute(
        select(DnbpPublicationLine).where(
            DnbpPublicationLine.publication_id == publication_id, DnbpPublicationLine.species == species
        )
    )
    return result.scalar_one_or_none()


async def recent_species_average(db: AsyncSession, org_id: uuid.UUID, species: str, *, since: datetime):
    """§5.7 `DNBP_OUTLIER` — the 30-day trailing mean this rule compares
    against (domain/engine/issues.py's `check_dnbp_outlier` stays pure; this
    is the one DB query that feeds it). Returns None when there is no
    publication history yet for this species, so the caller never invents
    a baseline to compare against."""
    result = await db.execute(
        select(func.avg(DnbpPublicationLine.dnbp_per_kg))
        .join(DnbpPublication, DnbpPublication.id == DnbpPublicationLine.publication_id)
        .where(
            DnbpPublication.org_id == org_id,
            DnbpPublicationLine.species == species,
            DnbpPublication.published_at >= since,
        )
    )
    return result.scalar_one_or_none()
