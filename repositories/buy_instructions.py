import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.buy_entry import BuyEntry
from models.buy_instruction import BuyInstruction, BuyInstructionLine, BuyInstructionLineFill
from models.user import User


async def create(db: AsyncSession, instruction: BuyInstruction) -> BuyInstruction:
    db.add(instruction)
    await db.flush()
    return instruction


async def add_lines(db: AsyncSession, lines: list[BuyInstructionLine]) -> list[BuyInstructionLine]:
    db.add_all(lines)
    await db.flush()
    return lines


async def get_by_id(db: AsyncSession, instruction_id: uuid.UUID) -> BuyInstruction | None:
    return await db.get(BuyInstruction, instruction_id)


async def list_for_org(
    db: AsyncSession, org_id: uuid.UUID, *, trade_date: date | None = None, status: str | None = None
) -> list[BuyInstruction]:
    stmt = select(BuyInstruction).where(BuyInstruction.org_id == org_id)
    if trade_date is not None:
        stmt = stmt.where(BuyInstruction.trade_date == trade_date)
    if status is not None:
        stmt = stmt.where(BuyInstruction.status == status)
    result = await db.execute(stmt.order_by(BuyInstruction.created_at.desc()))
    return list(result.scalars().all())


async def get_current_for_org(db: AsyncSession, org_id: uuid.UUID) -> BuyInstruction | None:
    """§12.5's `GET /buyer/instruction/current` — the most recently created
    instruction that has actually reached the buyer (ISSUED or later), same
    "current means most recent, not necessarily open" reading Phase 3 used
    for `GET /publications/current`."""
    result = await db.execute(
        select(BuyInstruction)
        .where(BuyInstruction.org_id == org_id, BuyInstruction.status != "DRAFT")
        .order_by(BuyInstruction.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_lines(db: AsyncSession, instruction_id: uuid.UUID) -> list[BuyInstructionLine]:
    result = await db.execute(
        select(BuyInstructionLine).where(BuyInstructionLine.instruction_id == instruction_id).order_by(
            BuyInstructionLine.seq
        )
    )
    return list(result.scalars().all())


async def get_line(db: AsyncSession, line_id: uuid.UUID) -> BuyInstructionLine | None:
    return await db.get(BuyInstructionLine, line_id)


async def add_fill(db: AsyncSession, fill: BuyInstructionLineFill) -> BuyInstructionLineFill:
    db.add(fill)
    await db.flush()
    return fill


async def get_fill(db: AsyncSession, fill_id: uuid.UUID) -> BuyInstructionLineFill | None:
    return await db.get(BuyInstructionLineFill, fill_id)


async def delete_fill(db: AsyncSession, fill: BuyInstructionLineFill) -> None:
    await db.delete(fill)
    await db.flush()


async def list_fills_for_lines(db: AsyncSession, line_ids: list[uuid.UUID]) -> list[BuyInstructionLineFill]:
    if not line_ids:
        return []
    result = await db.execute(
        select(BuyInstructionLineFill)
        .where(BuyInstructionLineFill.line_id.in_(line_ids))
        .order_by(BuyInstructionLineFill.entered_at)
    )
    return list(result.scalars().all())


async def list_org_buy_entries_in_window(
    db: AsyncSession, org_id: uuid.UUID, *, week_start: date, week_end: date
) -> list[BuyEntry]:
    """§13.1's reconciliation/summary blocks (non-negotiable #6) — every
    buyer's entries across the whole org for the Melbourne Mon-Sun trading
    week containing the instruction's `trade_date`, not just one buyer's
    (unlike repositories/buy_entries.list_for_buyer, which is deliberately
    scoped per-buyer for §2.2's own-data-only PWA routes)."""
    result = await db.execute(
        select(BuyEntry)
        .join(User, User.id == BuyEntry.buyer_id)
        .where(
            User.org_id == org_id,
            BuyEntry.trade_date >= week_start,
            BuyEntry.trade_date <= week_end,
            BuyEntry.is_deleted.is_(False),
        )
    )
    return list(result.scalars().all())
