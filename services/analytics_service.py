"""§13.2's six owner's-dashboard panels plus `/analytics/overview` (§9.7).
Every figure here is a read-time aggregation over tables domain/engine/,
domain/ingestion/ and the publication/Buy Instruction pipelines already
write — this module computes no new DNBP-shaped number and never calls
anything in domain/engine/ directly (phase05-instructions.txt's non-
negotiables #1, #5-#7). Aggregation is plain Python Decimal arithmetic over
fetched rows, the same convention services/buy_instruction_service
.compute_reconciliation already uses, rather than SQL-side func.sum/avg.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from core.reference_data import get_operational_constants
from domain.engine.issues import Severity
from domain.engine.workings import Lifecycle
from repositories import analytics as analytics_repo
from repositories import order_lines as order_lines_repo
from repositories import order_snapshots as order_snapshots_repo
from repositories import order_workings as order_workings_repo
from repositories import publication_deliveries as publication_deliveries_repo
from repositories import publications as publications_repo
from repositories import users as users_repo
from repositories import validation_issues as validation_issues_repo
from repositories.correction_requests import list_open_for_org
from schemas.analytics import (
    ActualPaidPoint,
    BlockedLineRow,
    BreachRow,
    BuyerPerformanceResponse,
    BuyerPerformanceRow,
    DnbpTrendPoint,
    DnbpTrendResponse,
    ExceptionsResponse,
    FulfilmentResponse,
    FulfilmentRow,
    MarginBridgeResponse,
    OrderBookCustomerRow,
    OrderBookResponse,
    OrderBookSpeciesRow,
    OverviewResponse,
    SaleyardHeadroomRow,
    StalePublicationRow,
    UndeliveredInstructionRow,
    UndeliveredPublicationRow,
)
from services.buy_instruction_service import schw_kg_for_entries

MONEY_ZERO = Decimal("0")
TRAILING_DAYS_FOR_RATE = 7  # §3 of the approved plan — the buyer's rhythm is inherently weekly (§6.8)


def headroom_captured_aud(entries: list) -> Decimal:
    """Non-negotiable #3 — the one already-grounded formula, shared by the
    buyer-performance panel and the buyer scorecard (services/scorecard_
    service.py) so it's computed exactly once. `variance_per_kg` is frozen
    on every buy_entry by domain.buyer.bidcheck.score_bid at write time —
    this never re-derives it."""
    return sum((e.variance_per_kg * e.weight_kg * e.head_count for e in entries), MONEY_ZERO)


def _avg(values: list[Decimal | None]) -> Decimal | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present, MONEY_ZERO) / len(present)


async def _buyer_email_lookup(db: AsyncSession, buyer_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    emails: dict[uuid.UUID, str] = {}
    for buyer_id in buyer_ids:
        user = await users_repo.get_by_id(db, buyer_id)
        emails[buyer_id] = user.email if user is not None else "unknown"
    return emails


@dataclass(slots=True)
class DateWindow:
    since: date | None
    until: date | None


async def order_book(db: AsyncSession, org_id: uuid.UUID) -> OrderBookResponse:
    """Panel 1 (§13.2 item 1). Scoped to the latest snapshot for the org —
    order snapshots are cumulative (§7.1), so the current book is always the
    latest one's ACTIVE lines, never a union across snapshots (which would
    double-count the same contract on two different days)."""
    snapshot = await order_snapshots_repo.get_latest_for_org(db, org_id)
    if snapshot is None:
        return OrderBookResponse(
            snapshot_id=None, as_of_date=None, total_exposure_aud=MONEY_ZERO, by_species=[], by_customer=[]
        )

    active_lines = await order_lines_repo.list_by_snapshot(db, snapshot.id, lifecycle=Lifecycle.ACTIVE)

    exposure_by_species: dict[str, Decimal] = {}
    exposure_by_species_customer: dict[tuple[str, str | None], Decimal] = {}
    required_by_species: dict[str, Decimal] = {}
    for line in active_lines:
        species = line.species or "UNKNOWN"
        amount = line.amount_aud or MONEY_ZERO
        exposure_by_species[species] = exposure_by_species.get(species, MONEY_ZERO) + amount
        key = (species, line.customer_name)
        exposure_by_species_customer[key] = exposure_by_species_customer.get(key, MONEY_ZERO) + amount
        required = line.estimated_heads or MONEY_ZERO
        required_by_species[species] = required_by_species.get(species, MONEY_ZERO) + required

    all_time_bought_entries = await analytics_repo.list_org_buy_entries(db, org_id)
    bought_by_species: dict[str, int] = {}
    for entry in all_time_bought_entries:
        bought_by_species[entry.species] = bought_by_species.get(entry.species, 0) + entry.head_count

    since_trailing = date.today() - timedelta(days=TRAILING_DAYS_FOR_RATE)
    trailing_entries = await analytics_repo.list_org_buy_entries(db, org_id, since=since_trailing)
    trailing_bought_by_species: dict[str, int] = {}
    for entry in trailing_entries:
        trailing_bought_by_species[entry.species] = trailing_bought_by_species.get(entry.species, 0) + entry.head_count

    species_rows = []
    for species in sorted(set(exposure_by_species) | set(required_by_species) | set(bought_by_species)):
        required = required_by_species.get(species, MONEY_ZERO)
        bought = Decimal(bought_by_species.get(species, 0))
        remaining = max(required - bought, MONEY_ZERO)
        trailing_rate = Decimal(trailing_bought_by_species.get(species, 0)) / TRAILING_DAYS_FOR_RATE
        days_of_cover = (remaining / trailing_rate) if trailing_rate > 0 else None
        species_rows.append(
            OrderBookSpeciesRow(
                species=species,
                exposure_aud=exposure_by_species.get(species, MONEY_ZERO),
                heads_required=required,
                heads_bought=bought_by_species.get(species, 0),
                days_of_cover=days_of_cover,
            )
        )

    customer_rows = [
        OrderBookCustomerRow(species=species, customer_name=customer, exposure_aud=amount)
        for (species, customer), amount in sorted(exposure_by_species_customer.items(), key=lambda kv: kv[0])
    ]

    return OrderBookResponse(
        snapshot_id=snapshot.id,
        as_of_date=snapshot.as_of_date,
        total_exposure_aud=sum(exposure_by_species.values(), MONEY_ZERO),
        by_species=species_rows,
        by_customer=customer_rows,
    )


async def dnbp_trend(db: AsyncSession, org_id: uuid.UUID, *, species: str, days: int) -> DnbpTrendResponse:
    """Panel 2 (§13.2 item 2)."""
    since = datetime.now(UTC) - timedelta(days=days)
    pub_lines = await analytics_repo.list_publication_lines_since(db, org_id, species=species, since=since)
    dnbp_points = [
        DnbpTrendPoint(published_at=pub.published_at, dnbp_per_kg=line.dnbp_per_kg) for pub, line in pub_lines
    ]

    entries = await analytics_repo.list_org_buy_entries(db, org_id, species=species, since=since.date())
    by_day: dict[date, list[Decimal]] = {}
    for entry in entries:
        by_day.setdefault(entry.trade_date, []).append(entry.implied_price_per_kg)
    actual_points = [
        ActualPaidPoint(trade_date=day, avg_paid_per_kg=sum(prices, MONEY_ZERO) / len(prices))
        for day, prices in sorted(by_day.items())
    ]

    return DnbpTrendResponse(species=species, days=days, dnbp_points=dnbp_points, actual_paid_points=actual_points)


async def buyer_performance(
    db: AsyncSession, org_id: uuid.UUID, *, buyer_id: uuid.UUID | None, since: date | None, until: date | None
) -> BuyerPerformanceResponse:
    """Panel 3 (§13.2 item 3)."""
    entries = await analytics_repo.list_org_buy_entries(db, org_id, buyer_id=buyer_id, since=since, until=until)

    by_buyer: dict[uuid.UUID, list] = {}
    by_saleyard: dict[str, list] = {}
    for entry in entries:
        by_buyer.setdefault(entry.buyer_id, []).append(entry)
        by_saleyard.setdefault(entry.saleyard, []).append(entry)

    emails = await _buyer_email_lookup(db, set(by_buyer))
    buyer_rows = []
    for buyer, es in sorted(by_buyer.items(), key=lambda kv: emails.get(kv[0], "")):
        breach_count = sum(1 for e in es if e.is_breach)
        variances = [e.variance_per_kg for e in es]
        buyer_rows.append(
            BuyerPerformanceRow(
                buyer_id=buyer,
                buyer_email=emails.get(buyer, "unknown"),
                entry_count=len(es),
                headroom_captured_aud=headroom_captured_aud(es),
                breach_count=breach_count,
                breach_rate=(Decimal(breach_count) / len(es)) if es else MONEY_ZERO,
                avg_variance_per_kg=_avg(variances),
            )
        )

    saleyard_rows = [
        SaleyardHeadroomRow(saleyard=saleyard, headroom_captured_aud=headroom_captured_aud(es))
        for saleyard, es in sorted(by_saleyard.items())
    ]

    return BuyerPerformanceResponse(from_=since, to=until, by_buyer=buyer_rows, by_saleyard=saleyard_rows)


async def margin_bridge(db: AsyncSession, org_id: uuid.UUID, *, snapshot_id: uuid.UUID | None) -> MarginBridgeResponse:
    """Panel 4 (§13.2 item 4), non-negotiable #5 — direct reads of
    order_workings' own columns, no new computation. See this plan's own
    note on why the response deliberately keeps the source-of-truth path
    (G -> X -> AC) visually distinct from the supporting-profit path
    (X -> Y/Z/AA -> AB): AC = X * factor never subtracts Y/Z/AA."""
    if snapshot_id is None:
        snapshot = await order_snapshots_repo.get_latest_for_org(db, org_id)
        snapshot_id = snapshot.id if snapshot is not None else None

    if snapshot_id is None:
        return MarginBridgeResponse(
            snapshot_id=None,
            line_count=0,
            avg_sell_price_aud=None,
            avg_adjusted_price_per_kg=None,
            avg_pack_cost_per_kg=None,
            avg_offal_return_per_kg=None,
            avg_skin_return_per_kg=None,
            avg_bing_dnbp=None,
            avg_profit_on_peter_costs=None,
        )

    rows = await order_workings_repo.list_active_with_bing_dnbp(db, snapshot_id)
    return MarginBridgeResponse(
        snapshot_id=snapshot_id,
        line_count=len(rows),
        avg_sell_price_aud=_avg([line.avg_price_aud for line, _ in rows]),
        avg_adjusted_price_per_kg=_avg([w.adjusted_price_per_kg for _, w in rows]),
        avg_pack_cost_per_kg=_avg([w.pack_cost_per_kg for _, w in rows]),
        avg_offal_return_per_kg=_avg([w.offal_return_per_kg for _, w in rows]),
        avg_skin_return_per_kg=_avg([w.skin_return_per_kg for _, w in rows]),
        avg_bing_dnbp=_avg([w.bing_dnbp for _, w in rows]),
        avg_profit_on_peter_costs=_avg([w.profit_on_peter_costs for _, w in rows]),
    )


async def fulfilment(
    db: AsyncSession, org_id: uuid.UUID, *, since: date | None, until: date | None
) -> FulfilmentResponse:
    """Panel 5 (§13.2 item 5), non-negotiable #6 — instructed vs bought vs
    shortfall grouped by trade date across ALL instructions, reusing
    services.buy_instruction_service.schw_kg_for_entries' exact SCHW math
    rather than re-deriving it."""
    instructed_lines = await analytics_repo.list_org_buy_instruction_lines_by_trade_date(
        db, org_id, since=since, until=until
    )
    instructed_by_date: dict[date, Decimal] = {}
    for trade_date, line in instructed_lines:
        instructed_by_date[trade_date] = instructed_by_date.get(trade_date, MONEY_ZERO) + line.schw_kg

    entries = await analytics_repo.list_org_buy_entries(db, org_id, since=since, until=until)
    entries_by_date: dict[date, list] = {}
    for entry in entries:
        entries_by_date.setdefault(entry.trade_date, []).append(entry)
    bought_by_date = {d: schw_kg_for_entries(es) for d, es in entries_by_date.items()}

    all_dates = sorted(set(instructed_by_date) | set(bought_by_date))
    rows = [
        FulfilmentRow(
            trade_date=d,
            instructed_schw_kg=instructed_by_date.get(d, MONEY_ZERO),
            bought_schw_kg=bought_by_date.get(d, MONEY_ZERO),
            shortfall_schw_kg=instructed_by_date.get(d, MONEY_ZERO) - bought_by_date.get(d, MONEY_ZERO),
        )
        for d in all_dates
    ]
    return FulfilmentResponse(from_=since, to=until, rows=rows)


async def exceptions(
    db: AsyncSession, org_id: uuid.UUID, *, since: date | None, until: date | None, saleyard: str | None
) -> ExceptionsResponse:
    """Panel 6 (§13.2 item 6) and `GET /analytics/breaches` (§9.7),
    non-negotiable #7 — pure reads over the four named sources."""
    breach_entries = await analytics_repo.list_org_buy_entries(db, org_id, since=since, until=until, saleyard=saleyard)
    breach_entries = [e for e in breach_entries if e.is_breach]
    emails = await _buyer_email_lookup(db, {e.buyer_id for e in breach_entries})
    breach_rows = [
        BreachRow(
            id=e.id,
            buyer_id=e.buyer_id,
            buyer_email=emails.get(e.buyer_id, "unknown"),
            saleyard=e.saleyard,
            trade_date=e.trade_date,
            species=e.species,
            variance_per_kg=e.variance_per_kg,
            price_per_head=e.price_per_head,
            weight_kg=e.weight_kg,
        )
        for e in breach_entries
    ]

    snapshot = await order_snapshots_repo.get_latest_for_org(db, org_id)
    blocked_rows: list[BlockedLineRow] = []
    if snapshot is not None:
        active_lines = await order_lines_repo.list_by_snapshot(db, snapshot.id, lifecycle=Lifecycle.ACTIVE)
        lines_by_id = {line.id: line for line in active_lines}
        issues = await validation_issues_repo.list_active_by_snapshot(db, snapshot.id)
        for issue in issues:
            if issue.severity != Severity.BLOCK:
                continue
            line = lines_by_id.get(issue.order_line_id)
            blocked_rows.append(
                BlockedLineRow(
                    order_line_id=issue.order_line_id,
                    contract_no=line.contract_no if line else None,
                    species=line.species if line else None,
                    code=issue.code,
                    message=issue.message,
                )
            )

    constants = get_operational_constants()
    cutoff = datetime.now(UTC) - timedelta(hours=constants.stale_instruction_hours)
    stale_pubs = await analytics_repo.list_stale_publications(db, org_id, cutoff=cutoff)
    stale_rows = [
        StalePublicationRow(
            publication_id=pub.id,
            published_at=pub.published_at,
            hours_stale=Decimal((datetime.now(UTC) - pub.published_at).total_seconds()) / Decimal(3600),
        )
        for pub in stale_pubs
    ]

    undelivered_instructions = await analytics_repo.list_issued_without_acknowledgement(db, org_id)
    instruction_rows = [
        UndeliveredInstructionRow(
            instruction_id=i.id, instruction_no=i.instruction_no, trade_date=i.trade_date, status=i.status.value
        )
        for i in undelivered_instructions
    ]

    current_publication = await publications_repo.get_current_for_org(db, org_id)
    undelivered_pub_rows: list[UndeliveredPublicationRow] = []
    if current_publication is not None:
        deliveries = await publication_deliveries_repo.list_for_publication(db, current_publication.id)
        pending = [d for d in deliveries if d.acknowledged_at is None]
        pending_emails = await _buyer_email_lookup(db, {d.buyer_id for d in pending})
        undelivered_pub_rows = [
            UndeliveredPublicationRow(
                publication_id=d.publication_id,
                buyer_id=d.buyer_id,
                buyer_email=pending_emails.get(d.buyer_id, "unknown"),
                delivered_at=d.delivered_at,
            )
            for d in pending
        ]

    return ExceptionsResponse(
        from_=since,
        to=until,
        breaches=breach_rows,
        blocked_lines=blocked_rows,
        stale_publications=stale_rows,
        undelivered_instructions=instruction_rows,
        undelivered_publications=undelivered_pub_rows,
    )


async def overview(db: AsyncSession, org_id: uuid.UUID, *, since: date | None, until: date | None) -> OverviewResponse:
    """`GET /analytics/overview` (§9.7) — a compact top-line rollup reusing
    the other panels' own repository calls, not a new computation."""
    book = await order_book(db, org_id)
    exc = await exceptions(db, org_id, since=since, until=until, saleyard=None)
    open_corrections = await list_open_for_org(db, org_id)

    return OverviewResponse(
        from_=since,
        to=until,
        active_exposure_aud=book.total_exposure_aud,
        heads_required_total=sum((row.heads_required for row in book.by_species), MONEY_ZERO),
        heads_bought_total=sum(row.heads_bought for row in book.by_species),
        open_correction_requests=len(open_corrections),
        breach_count=len(exc.breaches),
        blocked_line_count=len(exc.blocked_lines),
        stale_publication_count=len(exc.stale_publications),
        undelivered_instruction_count=len(exc.undelivered_instructions),
    )
