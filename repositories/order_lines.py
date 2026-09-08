import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.engine.workings import Lifecycle
from models.order_line import OrderLine


async def create_many(db: AsyncSession, lines: list[OrderLine]) -> list[OrderLine]:
    db.add_all(lines)
    await db.flush()
    return lines


async def get_by_id(db: AsyncSession, order_line_id: uuid.UUID) -> OrderLine | None:
    return await db.get(OrderLine, order_line_id)


async def list_by_snapshot(
    db: AsyncSession, snapshot_id: uuid.UUID, *, lifecycle: Lifecycle | None = None, species: str | None = None
) -> list[OrderLine]:
    stmt = select(OrderLine).where(OrderLine.snapshot_id == snapshot_id)
    if lifecycle is not None:
        stmt = stmt.where(OrderLine.lifecycle == lifecycle)
    if species is not None:
        stmt = stmt.where(OrderLine.species == species)
    result = await db.execute(stmt.order_by(OrderLine.line_no))
    return list(result.scalars().all())


async def find_by_identity(
    db: AsyncSession,
    snapshot_id: uuid.UUID,
    *,
    contract_no: str | None,
    species: str | None,
    product_type: str | None,
    incoterm: str | None,
) -> OrderLine | None:
    """Matches domain.ingestion.workbook.ParsedOrderLine.identity_key() —
    the same best-effort (contract_no, species, product_type, incoterm)
    tuple used for the upload-preview diff, reused here so a correction
    request's auto-resolve check (§9.3) agrees with what the diff already
    considers "the same line" across snapshots."""
    result = await db.execute(
        select(OrderLine).where(
            OrderLine.snapshot_id == snapshot_id,
            OrderLine.contract_no == contract_no,
            OrderLine.species == species,
            OrderLine.product_type == product_type,
            OrderLine.incoterm == incoterm,
        )
    )
    return result.scalars().first()
