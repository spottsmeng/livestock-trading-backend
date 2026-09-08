"""§12.6, §9.5 `GET /buyer/scorecard` — the buyer's own performance only.
Reuses services.analytics_service.headroom_captured_aud (non-negotiable #3)
and repositories/analytics.py's query helpers, filtered to one buyer,
rather than re-deriving either. See the approved plan's §3 for the
buyer-scorecard target-heads reading this module implements.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from repositories import analytics as analytics_repo
from schemas.buyer import SaleyardSpendRow, ScorecardResponse
from services.analytics_service import headroom_captured_aud

MONEY_ZERO = Decimal("0")


async def build_scorecard(
    db: AsyncSession, *, org_id: uuid.UUID, buyer_id: uuid.UUID, since: date | None, until: date | None
) -> ScorecardResponse:
    entries = await analytics_repo.list_org_buy_entries(db, org_id, buyer_id=buyer_id, since=since, until=until)

    heads_bought = sum(e.head_count for e in entries)
    breach_count = sum(1 for e in entries if e.is_breach)
    paid_prices = [e.implied_price_per_kg for e in entries]
    dnbp_prices = [e.dnbp_at_entry for e in entries]

    spend_by_saleyard: dict[str, Decimal] = {}
    for e in entries:
        spend_by_saleyard[e.saleyard] = spend_by_saleyard.get(e.saleyard, MONEY_ZERO) + e.price_per_head * e.head_count

    # §3 of the approved plan — target heads: sum target_heads across every
    # publication published in [since, until], restricted to the species
    # this buyer actually bought from in that same window (not every
    # species org-wide, since different buyers may cover different
    # species). since/until are inclusive calendar-date bounds; publication
    # timestamps are compared at midnight UTC on those dates for a
    # deliberately simple, documented reading — not a Melbourne-local
    # cutover, same level of rigor the rest of this phase's trailing-window
    # calculations use.
    species_bought = {e.species for e in entries}
    heads_target: Decimal | None = None
    if species_bought and since is not None:
        window_start = datetime.combine(since, datetime.min.time(), tzinfo=UTC)
        heads_target = MONEY_ZERO
        for species in species_bought:
            pub_lines = await analytics_repo.list_publication_lines_since(
                db, org_id, species=species, since=window_start
            )
            for pub, line in pub_lines:
                if until is not None and pub.published_at.date() > until:
                    continue
                if line.target_heads is not None:
                    heads_target += line.target_heads

    return ScorecardResponse(
        from_=since.isoformat() if since else None,
        to=until.isoformat() if until else None,
        heads_bought=heads_bought,
        heads_target=heads_target,
        avg_paid_per_kg=(sum(paid_prices, MONEY_ZERO) / len(paid_prices)) if paid_prices else None,
        avg_dnbp_per_kg=(sum(dnbp_prices, MONEY_ZERO) / len(dnbp_prices)) if dnbp_prices else None,
        headroom_captured_aud=headroom_captured_aud(entries),
        breach_count=breach_count,
        breach_rate=(Decimal(breach_count) / len(entries)) if entries else MONEY_ZERO,
        spend_by_saleyard=[
            SaleyardSpendRow(saleyard=saleyard, spend_aud=amount)
            for saleyard, amount in sorted(spend_by_saleyard.items())
        ],
    )
