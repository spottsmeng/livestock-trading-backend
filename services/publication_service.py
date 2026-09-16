"""POST /publications (§9.4) — the core value of Phase 3. Two responsibilities
kept deliberately separate:

1. `compute_publication_lines` — the species-level aggregation. Per-species
   `dnbp_per_kg` is `MIN(bing_dnbp)` across that species' active order lines,
   confirmed with the business as the only aggregation that guarantees the
   buyer never overpays relative to any contributing order (the physical red
   note book has no species *or* order field at all, so a per-order figure
   like the Buy Instruction's is not something the buyer can act on at the
   ring — see the resolved design note in this phase's plan). This never
   touches `domain.engine.dnbp` directly — it only ever aggregates an
   already-computed `order_workings.bing_dnbp`.
2. `publish` — the full §5.7 gate (BLOCK issues refuse publication; every
   WARN/CORRECTION issue on an ACTIVE line must be individually
   acknowledged first) plus the supersession bookkeeping.

`publish` also decides whether this publication carries genuinely new
information for the buyer (`_prices_changed`, against whichever publication
it supersedes) — a per-species price move, or a species appearing/dropping
out of the active book. That flag (`DnbpPublication.buyer_notified`) is the
only thing services/delivery_service.py's `fan_out` uses to decide whether
to interrupt the buyer with a Web Push; every publish still happens, still
supersedes the previous one, and still refreshes the buyer's on-screen
"updated X min ago" status regardless — confirmed with the business that a
same-price republish should stay silent on the buyer's phone rather than
retrain them to ignore "New Do Not Buy Price" alerts.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import IssuesNotAcknowledged, NothingToPublish, PublicationBlocked
from core.reference_data import get_active_everhealth_config, get_operational_constants
from domain.engine.issues import Severity
from models.dnbp_publication import DnbpPublication, DnbpPublicationLine
from models.enums import SnapshotStatus
from models.order_snapshot import OrderSnapshot
from repositories import order_workings as order_workings_repo
from repositories import publications as publications_repo
from repositories import validation_issues as validation_issues_repo
from services import audit_service
from services.calculate_service import ENGINE_VERSION


class PublicationLineDraft:
    __slots__ = (
        "species",
        "dnbp_per_kg",
        "target_heads",
        "target_weight_kg_min",
        "target_weight_kg_max",
        "contributing_line_ids",
    )

    def __init__(
        self,
        *,
        species: str,
        dnbp_per_kg: Decimal,
        target_heads: Decimal | None,
        target_weight_kg_min: Decimal | None,
        target_weight_kg_max: Decimal | None,
        contributing_line_ids: list[uuid.UUID],
    ) -> None:
        self.species = species
        self.dnbp_per_kg = dnbp_per_kg
        self.target_heads = target_heads
        self.target_weight_kg_min = target_weight_kg_min
        self.target_weight_kg_max = target_weight_kg_max
        self.contributing_line_ids = contributing_line_ids


async def compute_publication_lines(db: AsyncSession, snapshot_id: uuid.UUID) -> list[PublicationLineDraft]:
    config = await get_active_everhealth_config(db)
    tolerance_pct = get_operational_constants().buyer_weight_band_tolerance_pct

    by_species: dict[str, list] = {}
    for line, workings in await order_workings_repo.list_active_with_bing_dnbp(db, snapshot_id):
        by_species.setdefault(line.species, []).append((line, workings))

    drafts: list[PublicationLineDraft] = []
    for species, rows in sorted(by_species.items()):
        dnbp_per_kg = min(workings.bing_dnbp for _line, workings in rows)
        heads = [line.estimated_heads for line, _w in rows if line.estimated_heads is not None]
        target_heads = sum(heads) if heads else None

        standard_weight = config.standard_weight_by_species.get(species)
        weight_min = weight_max = None
        if standard_weight:
            tolerance = standard_weight * tolerance_pct / Decimal("100")
            weight_min = standard_weight - tolerance
            weight_max = standard_weight + tolerance

        drafts.append(
            PublicationLineDraft(
                species=species,
                dnbp_per_kg=dnbp_per_kg,
                target_heads=target_heads,
                target_weight_kg_min=weight_min,
                target_weight_kg_max=weight_max,
                contributing_line_ids=[line.id for line, _w in rows],
            )
        )
    return drafts


def _prices_changed(previous_lines: list[DnbpPublicationLine], drafts: list[PublicationLineDraft]) -> bool:
    """Whole-species-list-and-price comparison, not per-line — a species
    appearing or dropping out of the active book entirely is exactly as
    real a change to the buyer as its $/kg moving (confirmed with the
    business); target_heads/weight_band shifting on their own, with the
    same species list and the same prices, is deliberately not enough on
    its own to interrupt the buyer."""
    if not previous_lines:
        return True  # nothing published before — always genuinely new
    previous_by_species = {line.species: line.dnbp_per_kg for line in previous_lines}
    current_by_species = {draft.species: draft.dnbp_per_kg for draft in drafts}
    return previous_by_species != current_by_species


async def _assert_publishable(db: AsyncSession, snapshot_id: uuid.UUID) -> None:
    active_issues = await validation_issues_repo.list_active_by_snapshot(db, snapshot_id)

    blocked = [str(issue.order_line_id) for issue in active_issues if issue.severity is Severity.BLOCK]
    if blocked:
        raise PublicationBlocked(blocked)

    unacknowledged = [
        str(issue.id)
        for issue in active_issues
        if issue.severity in (Severity.WARN, Severity.CORRECTION) and issue.acknowledged_at is None
    ]
    if unacknowledged:
        raise IssuesNotAcknowledged(unacknowledged)


async def publish(
    db: AsyncSession, snapshot: OrderSnapshot, *, actor_id: uuid.UUID, notes: str | None
) -> tuple[DnbpPublication, list[DnbpPublicationLine]]:
    await _assert_publishable(db, snapshot.id)

    drafts = await compute_publication_lines(db, snapshot.id)
    if not drafts:
        raise NothingToPublish()

    previous_current = await publications_repo.get_current_for_org(db, snapshot.org_id)
    previous_lines = await publications_repo.list_lines(db, previous_current.id) if previous_current else []
    buyer_notified = _prices_changed(previous_lines, drafts)

    now = datetime.now(UTC)
    publication = DnbpPublication(
        org_id=snapshot.org_id,
        snapshot_id=snapshot.id,
        published_by=actor_id,
        effective_from=now,
        engine_version=ENGINE_VERSION,
        notes=notes,
        buyer_notified=buyer_notified,
    )
    await publications_repo.create(db, publication)

    lines = [
        DnbpPublicationLine(
            publication_id=publication.id,
            species=draft.species,
            dnbp_per_kg=draft.dnbp_per_kg,
            target_heads=draft.target_heads,
            target_weight_kg_min=draft.target_weight_kg_min,
            target_weight_kg_max=draft.target_weight_kg_max,
            contributing_line_ids=draft.contributing_line_ids,
        )
        for draft in drafts
    ]
    await publications_repo.add_lines(db, lines)

    if previous_current is not None:
        previous_current.superseded_by = publication.id
        previous_current.superseded_at = now
        previous_snapshot = await db.get(OrderSnapshot, previous_current.snapshot_id)
        if previous_snapshot is not None and previous_snapshot.status is SnapshotStatus.PUBLISHED:
            previous_snapshot.status = SnapshotStatus.SUPERSEDED

    snapshot.status = SnapshotStatus.PUBLISHED

    await audit_service.write(
        db,
        actor_id=actor_id,
        action="publication.published",
        entity="dnbp_publication",
        entity_id=publication.id,
        after={
            "snapshot_id": str(snapshot.id),
            "species": [{"species": d.species, "dnbp_per_kg": str(d.dnbp_per_kg)} for d in drafts],
            "buyer_notified": buyer_notified,
        },
    )

    return publication, lines
