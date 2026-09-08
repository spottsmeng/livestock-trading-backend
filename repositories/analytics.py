"""Phase 5 (§13.2, §12.6) — new org-scoped list queries the dashboard and
buyer scorecard need that no existing repository already provides. Every
function here returns rows (entries/lines), never a pre-aggregated number —
aggregation happens in services/analytics_service.py using plain Python
Decimal arithmetic, the same convention services/buy_instruction_service
.compute_reconciliation already uses, rather than mixing SQL-side
func.sum/avg with Python Decimal math in different places.

Deliberately reuses existing repositories wherever one already answers the
question (repositories/order_lines.py, repositories/order_workings.py,
repositories/buy_entries.py, repositories/publications.py,
repositories/buy_instructions.py, repositories/validation_issues.py,
repositories/correction_requests.py, repositories/publication_deliveries.py)
— this module only adds the queries those don't cover: flexible-filter
org-wide buy_entries (existing ones are either per-buyer or one fixed trading
week), publication lines over an arbitrary trailing window, and stale-
publication detection.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.buy_entry import BuyEntry
from models.buy_instruction import BuyInstruction, BuyInstructionLine
from models.dnbp_publication import DnbpPublication, DnbpPublicationLine
from models.user import User
from repositories import buy_instructions as buy_instructions_repo


async def list_org_buy_entries(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    buyer_id: uuid.UUID | None = None,
    species: str | None = None,
    saleyard: str | None = None,
    since: date | None = None,
    until: date | None = None,
) -> list[BuyEntry]:
    """Every OWNER/ACCOUNTANT-facing analytics query over buy_entries
    funnels through here — a generalisation of
    repositories.buy_instructions.list_org_buy_entries_in_window (fixed to
    one instruction's trading week) and repositories.buy_entries.
    list_for_buyer (always scoped to a single buyer) for the org-wide,
    open-ended-window case those two don't cover."""
    stmt = select(BuyEntry).join(User, User.id == BuyEntry.buyer_id).where(
        User.org_id == org_id, BuyEntry.is_deleted.is_(False)
    )
    if buyer_id is not None:
        stmt = stmt.where(BuyEntry.buyer_id == buyer_id)
    if species is not None:
        stmt = stmt.where(BuyEntry.species == species)
    if saleyard is not None:
        stmt = stmt.where(BuyEntry.saleyard == saleyard)
    if since is not None:
        stmt = stmt.where(BuyEntry.trade_date >= since)
    if until is not None:
        stmt = stmt.where(BuyEntry.trade_date <= until)
    result = await db.execute(stmt.order_by(BuyEntry.trade_date))
    return list(result.scalars().all())


async def list_publication_lines_since(
    db: AsyncSession, org_id: uuid.UUID, *, species: str | None = None, since: datetime
) -> list[tuple[DnbpPublication, DnbpPublicationLine]]:
    """Panel 2 (DNBP trend) and the buyer scorecard's target-heads reading
    (§3 of the approved plan) both need "every publication line published
    in a trailing window" — repositories.publications has no such query,
    only get_current_for_org / find_effective_as_of (single point in time)."""
    stmt = (
        select(DnbpPublication, DnbpPublicationLine)
        .join(DnbpPublicationLine, DnbpPublicationLine.publication_id == DnbpPublication.id)
        .where(DnbpPublication.org_id == org_id, DnbpPublication.published_at >= since)
    )
    if species is not None:
        stmt = stmt.where(DnbpPublicationLine.species == species)
    result = await db.execute(stmt.order_by(DnbpPublication.published_at))
    return [(pub, line) for pub, line in result.all()]


async def list_stale_publications(
    db: AsyncSession, org_id: uuid.UUID, *, cutoff: datetime
) -> list[DnbpPublication]:
    """Exceptions panel (§13.2 item 6, non-negotiable #7): a publication
    that is still "live" (nothing has superseded it) but was published
    before `cutoff` (now - OperationalConstants.stale_instruction_hours)."""
    result = await db.execute(
        select(DnbpPublication).where(
            DnbpPublication.org_id == org_id,
            DnbpPublication.superseded_by.is_(None),
            DnbpPublication.published_at < cutoff,
        )
    )
    return list(result.scalars().all())


async def list_org_buy_instruction_lines_by_trade_date(
    db: AsyncSession, org_id: uuid.UUID, *, since: date | None = None, until: date | None = None
) -> list[tuple[date, BuyInstructionLine]]:
    """Panel 5 (fulfilment): every buy_instruction_line across every
    instruction for this org, paired with its parent instruction's
    trade_date — the "instructed" side of "instructed vs bought vs
    shortfall, by trade date" (non-negotiable #6)."""
    stmt = (
        select(BuyInstruction.trade_date, BuyInstructionLine)
        .join(BuyInstructionLine, BuyInstructionLine.instruction_id == BuyInstruction.id)
        .where(BuyInstruction.org_id == org_id)
    )
    if since is not None:
        stmt = stmt.where(BuyInstruction.trade_date >= since)
    if until is not None:
        stmt = stmt.where(BuyInstruction.trade_date <= until)
    result = await db.execute(stmt)
    return [(trade_date, line) for trade_date, line in result.all()]


async def list_issued_without_acknowledgement(db: AsyncSession, org_id: uuid.UUID) -> list[BuyInstruction]:
    """Exceptions panel: an instruction the buyer has never acknowledged
    (status frozen at ISSUED — repositories.buy_instructions has no
    status-filtered org-wide query, only list_for_org's optional filter,
    which this reuses)."""
    return await buy_instructions_repo.list_for_org(db, org_id, status="ISSUED")
