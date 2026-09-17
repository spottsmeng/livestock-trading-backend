"""POST /market-intel/observations(/bulk) — the market-intelligence write
path. Idempotent on `client_uuid` so the PWA's offline queue can replay
safely, same as buy_entry_service.py. Unlike a BuyEntry, there is no DNBP
publication to score against here — a competitor's purchase isn't measured
against our own Do Not Buy Price — so this only derives
`implied_price_per_kg` when a weight was actually observed.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from models.market_observation import MarketObservation
from repositories import market_observations as market_observations_repo


@dataclass(slots=True)
class MarketObservationInput:
    saleyard: str
    trade_date: date
    species: str
    competitor_name: str
    agent: str | None
    pen: str | None
    head_count: int
    price_per_head: Decimal
    weight_kg: Decimal | None
    description: str | None
    is_estimated: bool
    client_uuid: uuid.UUID
    client_created_at: datetime


@dataclass(slots=True)
class MarketObservationResult:
    observation: MarketObservation
    is_possible_duplicate: bool


def _implied_price_per_kg(price_per_head: Decimal, weight_kg: Decimal | None) -> Decimal | None:
    if weight_kg is None or weight_kg == 0:
        return None
    return price_per_head / weight_kg


async def create_or_sync_observation(
    db: AsyncSession, *, observer_id: uuid.UUID, org_id: uuid.UUID, payload: MarketObservationInput
) -> MarketObservationResult:
    existing = await market_observations_repo.get_by_client_uuid(db, payload.client_uuid)
    if existing is not None:
        # Idempotent replay, same reasoning as create_or_sync_entry.
        return MarketObservationResult(observation=existing, is_possible_duplicate=False)

    duplicate = await market_observations_repo.find_recent_duplicate(
        db,
        observer_id=observer_id,
        agent=payload.agent,
        pen=payload.pen,
        price_per_head=payload.price_per_head,
        as_of=payload.client_created_at,
    )

    observation = MarketObservation(
        org_id=org_id,
        observer_id=observer_id,
        saleyard=payload.saleyard,
        trade_date=payload.trade_date,
        species=payload.species,
        competitor_name=payload.competitor_name,
        agent=payload.agent,
        pen=payload.pen,
        head_count=payload.head_count,
        price_per_head=payload.price_per_head,
        weight_kg=payload.weight_kg,
        description=payload.description,
        implied_price_per_kg=_implied_price_per_kg(payload.price_per_head, payload.weight_kg),
        is_estimated=payload.is_estimated,
        client_uuid=payload.client_uuid,
        client_created_at=payload.client_created_at,
    )
    await market_observations_repo.create(db, observation)
    observation.synced_at = datetime.now(UTC)
    await db.flush()

    return MarketObservationResult(observation=observation, is_possible_duplicate=duplicate is not None)


async def bulk_sync(
    db: AsyncSession, *, observer_id: uuid.UUID, org_id: uuid.UUID, items: list[MarketObservationInput]
) -> list[dict]:
    """Offline queue flush — one bad item never fails the whole batch, same
    per-item-result contract as buy_entry_service.bulk_sync."""
    results = []
    for item in items:
        try:
            outcome = await create_or_sync_observation(db, observer_id=observer_id, org_id=org_id, payload=item)
            results.append(
                {
                    "client_uuid": str(item.client_uuid),
                    "ok": True,
                    "observation_id": str(outcome.observation.id),
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


@dataclass(slots=True)
class SummaryRow:
    competitor_name: str
    species: str
    entry_count: int
    heads_observed: int
    avg_price_per_kg: Decimal | None
    last_observed_at: datetime


async def summarize(db: AsyncSession, org_id: uuid.UUID, **filters) -> list[SummaryRow]:
    """The benchmarking view: every raw observation grouped by
    competitor x species. Aggregated in Python rather than SQL — this
    table is buyer-log-sized (hundreds/day at most), and doing it here
    keeps `implied_price_per_kg`'s "null when weight wasn't observed"
    handling in one place rather than duplicated in a GROUP BY."""
    rows = await market_observations_repo.list_for_org(db, org_id, **filters)
    grouped: dict[tuple[str, str], list[MarketObservation]] = {}
    for row in rows:
        grouped.setdefault((row.competitor_name, row.species), []).append(row)

    summary: list[SummaryRow] = []
    for (competitor_name, species), group in grouped.items():
        priced = [g.implied_price_per_kg for g in group if g.implied_price_per_kg is not None]
        avg = (sum(priced, Decimal(0)) / len(priced)) if priced else None
        summary.append(
            SummaryRow(
                competitor_name=competitor_name,
                species=species,
                entry_count=len(group),
                heads_observed=sum(g.head_count for g in group),
                avg_price_per_kg=avg,
                last_observed_at=max(g.client_created_at for g in group),
            )
        )
    summary.sort(key=lambda r: (r.competitor_name, r.species))
    return summary
