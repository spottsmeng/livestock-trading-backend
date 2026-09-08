"""POST /buyer/entries(/bulk) (§9.5, §12.4, §12.7) — the digital red note
book's write path. Idempotent on `client_uuid` so the PWA's offline queue
can replay safely (§12.7's non-negotiable), and freezes `dnbp_at_entry`
against whichever publication was effective *as of* the entry's own
`client_created_at` — never "current" — so a later republish can never
retroactively change whether a past buy was a breach (§12.4).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import Conflict, NotFound
from core.reference_data import get_operational_constants
from domain.buyer.bidcheck import score_bid
from models.buy_entry import BuyEntry
from repositories import buy_entries as buy_entries_repo
from repositories import publications as publications_repo


@dataclass(slots=True)
class BuyEntryInput:
    saleyard: str
    trade_date: date
    species: str
    agent: str | None
    pen: str | None
    head_count: int
    price_per_head: Decimal
    weight_kg: Decimal
    description: str | None
    eid_ref: str | None
    freight_per_head: Decimal | None
    other_cost_per_kg: Decimal | None
    breach_reason: str | None
    client_uuid: uuid.UUID
    client_created_at: datetime


@dataclass(slots=True)
class BuyEntryResult:
    entry: BuyEntry
    is_possible_duplicate: bool


async def create_or_sync_entry(
    db: AsyncSession, *, buyer_id: uuid.UUID, org_id: uuid.UUID, payload: BuyEntryInput
) -> BuyEntryResult:
    existing = await buy_entries_repo.get_by_client_uuid(db, payload.client_uuid)
    if existing is not None:
        # Idempotent replay — the offline queue may retry a flush that
        # actually succeeded server-side but never got acknowledged back
        # to the client (§12.7). No re-scoring, no duplicate row.
        return BuyEntryResult(entry=existing, is_possible_duplicate=False)

    publication = await publications_repo.find_effective_as_of(db, org_id, payload.client_created_at)
    if publication is None:
        raise NotFound("Published DNBP as of that time")

    line = await publications_repo.find_line_for_species(db, publication.id, payload.species)
    if line is None:
        raise Conflict("SPECIES_NOT_PUBLISHED", f"No published Do Not Buy Price for {payload.species} at that time.")

    close_threshold = get_operational_constants().bid_check_close_threshold_pct
    result = score_bid(
        price_per_head=payload.price_per_head,
        weight_kg=payload.weight_kg,
        dnbp_per_kg=line.dnbp_per_kg,
        close_threshold_pct=close_threshold,
    )

    duplicate = await buy_entries_repo.find_recent_duplicate(
        db,
        buyer_id=buyer_id,
        agent=payload.agent,
        pen=payload.pen,
        price_per_head=payload.price_per_head,
        as_of=payload.client_created_at,
    )

    entry = BuyEntry(
        buyer_id=buyer_id,
        saleyard=payload.saleyard,
        trade_date=payload.trade_date,
        species=payload.species,
        agent=payload.agent,
        pen=payload.pen,
        head_count=payload.head_count,
        price_per_head=payload.price_per_head,
        weight_kg=payload.weight_kg,
        description=payload.description,
        eid_ref=payload.eid_ref,
        freight_per_head=payload.freight_per_head,
        other_cost_per_kg=payload.other_cost_per_kg,
        implied_price_per_kg=result.implied_price_per_kg,
        dnbp_publication_line_id=line.id,
        dnbp_at_entry=line.dnbp_per_kg,
        variance_per_kg=result.variance_per_kg,
        is_breach=result.is_breach,
        breach_reason=payload.breach_reason,
        client_uuid=payload.client_uuid,
        client_created_at=payload.client_created_at,
    )
    await buy_entries_repo.create(db, entry)
    entry.synced_at = datetime.now(UTC)
    await db.flush()

    return BuyEntryResult(entry=entry, is_possible_duplicate=duplicate is not None)


async def bulk_sync(
    db: AsyncSession, *, buyer_id: uuid.UUID, org_id: uuid.UUID, items: list[BuyEntryInput]
) -> list[dict]:
    """§9.5 `POST /buyer/entries/bulk` — "offline queue flush; per-item
    results". One bad item (e.g. a species that's since fallen out of
    publication) must never fail the whole batch — the PWA needs to know
    exactly which queued entries synced and which didn't, so it can retry
    only the failures."""
    results = []
    for item in items:
        try:
            outcome = await create_or_sync_entry(db, buyer_id=buyer_id, org_id=org_id, payload=item)
            results.append(
                {
                    "client_uuid": str(item.client_uuid),
                    "ok": True,
                    "entry_id": str(outcome.entry.id),
                    "is_possible_duplicate": outcome.is_possible_duplicate,
                }
            )
        except Exception as exc:  # noqa: BLE001 — deliberately broad: this is a per-item result, not a route handler
            code = getattr(exc, "code", "SYNC_FAILED")
            message = getattr(exc, "message", str(exc))
            results.append(
                {"client_uuid": str(item.client_uuid), "ok": False, "error_code": code, "error_message": message}
            )
    return results
