import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.engine.workings import Lifecycle
from models.order_line import OrderLine
from models.validation_issue import ValidationIssueRecord


async def replace_for_line(db: AsyncSession, order_line_id: uuid.UUID, issues: list[ValidationIssueRecord]) -> None:
    """Calculation is idempotent and re-runnable (§17.3) — a re-run must not
    accumulate duplicate issue rows, so the previous set for this line is
    cleared before inserting the freshly computed one."""
    await db.execute(delete(ValidationIssueRecord).where(ValidationIssueRecord.order_line_id == order_line_id))
    db.add_all(issues)
    await db.flush()


async def list_by_order_line(db: AsyncSession, order_line_id: uuid.UUID) -> list[ValidationIssueRecord]:
    result = await db.execute(select(ValidationIssueRecord).where(ValidationIssueRecord.order_line_id == order_line_id))
    return list(result.scalars().all())


async def list_by_snapshot(db: AsyncSession, snapshot_id: uuid.UUID) -> list[ValidationIssueRecord]:
    result = await db.execute(
        select(ValidationIssueRecord)
        .join(OrderLine, OrderLine.id == ValidationIssueRecord.order_line_id)
        .where(OrderLine.snapshot_id == snapshot_id)
    )
    return list(result.scalars().all())


async def list_active_by_snapshot(db: AsyncSession, snapshot_id: uuid.UUID) -> list[ValidationIssueRecord]:
    """Scoped to lifecycle=ACTIVE (§5.3, §5.7) — used by
    services/publication_service.py's publish gate. "No loaded-line issue
    can ever gate a publication" (§5.7) means the gate must never see a
    LOADED line's issues at all, not merely rely on their severity never
    being BLOCK."""
    result = await db.execute(
        select(ValidationIssueRecord)
        .join(OrderLine, OrderLine.id == ValidationIssueRecord.order_line_id)
        .where(OrderLine.snapshot_id == snapshot_id, OrderLine.lifecycle == Lifecycle.ACTIVE)
    )
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, issue_id: uuid.UUID) -> ValidationIssueRecord | None:
    return await db.get(ValidationIssueRecord, issue_id)
