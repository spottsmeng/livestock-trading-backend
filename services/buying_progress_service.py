"""Beyond §8/§9.4's literal spec — same documented-deviation pattern as
`buy_instruction_line_fills`/`dnbp_publication_deliveries` and, closer to
home, `domain/buyer/buying_progress.py` (read that module's docstring
first — it explains why "reset on every publish" would be wrong and why
this instead only resets when a species' `target_heads` actually changes).

One computation, two consumers: `services/delivery_service.py::buyer_safe_payload`
(the buyer's own `/buyer/dnbp/current` + WS push) and the Trading Console's
`GET /publications/current/progress` both call `compute_species_progress`
directly, so the office can never see a number that drifts from what the
buyer sees.

`heads_bought` is deliberately org-wide (every buyer, not just one) —
confirmed with Terence: the species target itself is org-wide demand, so a
per-buyer count would understate true progress whenever more than one buyer
is active (already anticipated elsewhere, e.g. services/delivery_service.py
fanning Web Push out to every active buyer)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from domain.buyer.buying_progress import PublicationSnapshot, find_progress_anchor
from models.dnbp_publication import DnbpPublication, DnbpPublicationLine
from repositories import analytics as analytics_repo

# "Old enough to see this org's entire publication history" — the same kind
# of deliberately simple sentinel scorecard_service.py's own documented
# calendar-date simplification uses, rather than tracking the org's actual
# creation date.
_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class SpeciesProgress:
    species: str
    target_heads: Decimal | None
    heads_bought: int
    anchor_effective_from: datetime


async def compute_species_progress(
    db: AsyncSession,
    org_id: uuid.UUID,
    publication: DnbpPublication,
    lines: list[DnbpPublicationLine],
    *,
    species_filter: set[str] | None = None,
) -> list[SpeciesProgress]:
    """`species_filter`, when given, restricts the (still org-wide) result to
    just those species — used after a buy_entry write to recompute only the
    species that could possibly have changed, rather than every species in
    the current publication."""
    results: list[SpeciesProgress] = []
    for line in lines:
        if species_filter is not None and line.species not in species_filter:
            continue

        history_rows = await analytics_repo.list_publication_lines_since(
            db, org_id, species=line.species, since=_EPOCH
        )
        history = [
            PublicationSnapshot(effective_from=pub.effective_from, target_heads=hist_line.target_heads)
            for pub, hist_line in history_rows
            if pub.id != publication.id
        ]
        anchor = find_progress_anchor(history, line.target_heads, publication.effective_from)

        entries = await analytics_repo.list_org_buy_entries(db, org_id, species=line.species, since=anchor.date())
        heads_bought = sum(entry.head_count for entry in entries)

        results.append(
            SpeciesProgress(
                species=line.species,
                target_heads=line.target_heads,
                heads_bought=heads_bought,
                anchor_effective_from=anchor,
            )
        )
    return results
