import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.engine.workings import Lifecycle
from models.order_line import OrderLine
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


async def list_active_with_bing_dnbp(db: AsyncSession, snapshot_id: uuid.UUID) -> list[tuple[OrderLine, OrderWorkings]]:
    """services/publication_service.py's `compute_publication_lines` input:
    every ACTIVE line in a snapshot that has a computed, non-null `AC`
    (§5.3 — a species missing a factor never reaches here at all, since it
    never got a workings row's `bing_dnbp` populated in the first place)."""
    result = await db.execute(
        select(OrderLine, OrderWorkings)
        .join(OrderWorkings, OrderWorkings.order_line_id == OrderLine.id)
        .where(
            OrderLine.snapshot_id == snapshot_id,
            OrderLine.lifecycle == Lifecycle.ACTIVE,
            OrderWorkings.bing_dnbp.is_not(None),
        )
    )
    return [(line, workings) for line, workings in result.all()]
