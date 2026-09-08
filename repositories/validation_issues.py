import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

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
