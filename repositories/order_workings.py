import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.engine.workings import Lifecycle
from models.order_line import OrderLine
from models.order_workings import OrderWorkings


# §8's order_workings column list — the fields calculate_snapshot actually
# computes. Deliberately an allowlist, not "every column except id/
# order_line_id/created_at": computed_at and updated_at are server-managed
# (server_default / onupdate) and must never be copied from a transient,
# never-flushed OrderWorkings — doing so overwrites them with None and
# trips the NOT NULL constraint on UPDATE.
COMPUTED_COLUMNS = (
    "engine_version",
    "ref_data_version",
    "computed_at",
    "adjusted_price_per_kg",
    "pack_cost_per_kg",
    "offal_return_per_kg",
    "skin_return_per_kg",
    "profit_on_peter_costs",
    "bing_dnbp",
    "bing_dnbp_factor_used",
    "bing_dnbp_inputs",
    "profit_on_bing_dnbp",
    "diff_vs_benchmark",
    "diff_vs_peter",
    "supporting_analysis_complete",
)


async def upsert(db: AsyncSession, workings: OrderWorkings) -> OrderWorkings:
    """order_workings is derived, freely INSERT/UPDATE (§8) — recalculation
    replaces any prior row for the same order_line rather than accumulating
    history, since only the current computation is ever meaningful."""
    existing = await get_by_order_line_id(db, workings.order_line_id)
    if existing is None:
        db.add(workings)
        await db.flush()
        return workings

    for column in COMPUTED_COLUMNS:
        setattr(existing, column, getattr(workings, column))
    await db.flush()
    return existing


async def get_by_order_line_id(db: AsyncSession, order_line_id: uuid.UUID) -> OrderWorkings | None:
    result = await db.execute(select(OrderWorkings).where(OrderWorkings.order_line_id == order_line_id))
    return result.scalar_one_or_none()


async def list_by_snapshot_id(db: AsyncSession, snapshot_id: uuid.UUID) -> list[OrderWorkings]:
    """Batches what would otherwise be one GET /order-lines/{id}/workings
    call per active line (the workbench grid and benchmark-compare view
    both need every ACTIVE line's workings up front) into a single query."""
    result = await db.execute(
        select(OrderWorkings)
        .join(OrderLine, OrderWorkings.order_line_id == OrderLine.id)
        .where(OrderLine.snapshot_id == snapshot_id, OrderLine.lifecycle == Lifecycle.ACTIVE)
    )
    return list(result.scalars().all())


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
