"""Demo/dev seed for the Market Intelligence module (competitor bid
observations) — grounded in the app's own domain data rather than invented
saleyards or species: trading days come from the real saleyard_calendar
(Bendigo/Ballarat/Wagga/Griffith, fixtures/reference-data-seed.json, via
core.reference_data.get_saleyard_calendar), per-species weights start from
that same file's standard_weight_by_species, and the weight jitter uses the
seeded buyer_weight_band_tolerance_pct (15%) operational constant.

Competitor and agent names are FICTIONAL — this is illustrative demo data
for exercising the Market Intel screens, never a real market data feed, and
$/kg price bands below are illustrative approximations only.

Safe to re-run: every row this script creates carries a fixed marker at the
end of its `description` field. Re-running first deletes every row bearing
that marker, then regenerates a fresh dataset anchored to today's date —
so editing the constants below and re-running always reflects the latest
version, and a buyer's real, hand-entered observations (which never carry
the marker) are never touched.

Run with: uv run python -m scripts.seed_market_intel
"""

import asyncio
import random
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete

from core.db import async_session_factory
from core.reference_data import get_operational_constants, get_saleyard_calendar, resolve_saleyard_for_date
from models.enums import BuyEntrySyncStatus, OrgKind
from models.market_observation import MarketObservation
from repositories import organisations as org_repo
from repositories import users as user_repo

SEED_MARKER = "[seed:market-intel-demo]"
WEEKS_OF_HISTORY = 10
RANDOM_SEED = 20260917  # fixed — same distribution shape on every run, only the date window shifts with "today"

# Same species set as fixtures/reference-data-seed.json's open species
# registry. Per-head standard weight (kg) mirrors that file's
# standard_weight_by_species — MUTTON is absent there (a known data gap,
# see that file's own comment), so 24kg is used here, the value that
# file's unused Sheet1!O:P reference table suggests for it.
STANDARD_WEIGHT_KG: dict[str, Decimal] = {
    "SHEEP": Decimal("22"),
    "LAMB": Decimal("18"),
    "GOAT": Decimal("14"),
    "VEAL": Decimal("17"),
    "MUTTON": Decimal("24"),
}

# Illustrative AUD/kg liveweight bands for demo purposes only.
PRICE_PER_KG_RANGE: dict[str, tuple[float, float]] = {
    "LAMB": (7.50, 9.50),
    "SHEEP": (4.00, 5.50),
    "MUTTON": (3.50, 5.00),
    "GOAT": (5.50, 7.50),
    "VEAL": (4.50, 6.00),
}

# Fictional buyer companies and selling-agent codes — not real businesses.
COMPETITORS = [
    "Southern Cross Meats",
    "Golden Plains Livestock Co.",
    "Murray Valley Meat Co.",
    "Highland Pastoral Buyers",
    "Riverina Stock Co.",
    "Blackwood Ag Processors",
]
AGENTS = ["TBW", "M06", "EL02", "NAS1", "LMK3", "RWR7"]

# Appended to ~30% of rows, before the marker, for a bit of ringside texture.
NOTES = [
    "Sold quick, good even run",
    "Drafted the heavy end first",
    "Buyer paid up for condition",
    "Small consignment, competitive bidding",
    "Held back for a later pen",
]


def _weighted_head_count(rng: random.Random) -> int:
    return rng.choice([5, 8, 10, 12, 15, 18, 20, 25, 30])


def _build_rows(*, org_id: uuid.UUID, observer_id: uuid.UUID) -> list[MarketObservation]:
    rng = random.Random(RANDOM_SEED)
    calendar = get_saleyard_calendar()
    weight_tolerance_pct = get_operational_constants().buyer_weight_band_tolerance_pct / Decimal(100)

    rows: list[MarketObservation] = []
    today = date.today()
    d = today - timedelta(weeks=WEEKS_OF_HISTORY)
    while d <= today:
        entry = resolve_saleyard_for_date(d, calendar)
        if entry is not None:
            species_today = rng.sample(list(STANDARD_WEIGHT_KG), k=rng.randint(2, min(4, len(STANDARD_WEIGHT_KG))))
            for species in species_today:
                for _ in range(rng.randint(1, 3)):
                    base_weight = STANDARD_WEIGHT_KG[species]
                    jitter = Decimal(str(round(rng.uniform(-1, 1), 2))) * weight_tolerance_pct * base_weight
                    weight_known = rng.random() >= 0.2  # ~20% logged with no visible weight, same as ringside reality
                    weight_kg = (base_weight + jitter).quantize(Decimal("0.1")) if weight_known else None

                    price_per_kg = Decimal(str(round(rng.uniform(*PRICE_PER_KG_RANGE[species]), 2)))
                    pricing_weight = weight_kg if weight_kg is not None else base_weight
                    price_per_head = (price_per_kg * pricing_weight).quantize(Decimal("0.01"))
                    implied_price_per_kg = (price_per_head / weight_kg) if weight_kg else None

                    sale_time = time(hour=rng.randint(9, 15), minute=rng.choice([0, 15, 30, 45]))
                    logged_at = datetime.combine(d, sale_time, tzinfo=UTC)
                    description = SEED_MARKER if rng.random() >= 0.3 else f"{rng.choice(NOTES)} {SEED_MARKER}"

                    rows.append(
                        MarketObservation(
                            org_id=org_id,
                            observer_id=observer_id,
                            saleyard=entry.saleyard,
                            trade_date=d,
                            species=species,
                            competitor_name=rng.choice(COMPETITORS),
                            agent=rng.choice(AGENTS),
                            pen=str(rng.randint(1, 45)),
                            head_count=_weighted_head_count(rng),
                            price_per_head=price_per_head,
                            weight_kg=weight_kg,
                            description=description,
                            implied_price_per_kg=implied_price_per_kg,
                            is_estimated=(weight_kg is None) or rng.random() < 0.25,
                            client_uuid=uuid.uuid4(),
                            client_created_at=logged_at,
                            synced_at=logged_at,
                            sync_status=BuyEntrySyncStatus.SYNCED,
                            is_deleted=False,
                        )
                    )
        d += timedelta(days=1)
    return rows


async def main() -> None:
    async with async_session_factory() as session:
        org = await org_repo.get_by_kind(session, OrgKind.EVERHEALTH)
        if org is None:
            raise RuntimeError("No Everhealth org found — run `uv run python -m scripts.seed` first.")

        buyer = await user_repo.get_by_email(session, "buyer@example.com")
        if buyer is None:
            raise RuntimeError("No buyer@example.com user found — run `uv run python -m scripts.seed` first.")

        deleted = await session.execute(
            delete(MarketObservation).where(MarketObservation.description.like(f"%{SEED_MARKER}"))
        )
        print(f"Removed {deleted.rowcount} previously seeded market observation(s).")

        rows = _build_rows(org_id=org.id, observer_id=buyer.id)
        session.add_all(rows)
        await session.commit()

        print(f"Seeded {len(rows)} market observation(s) across the last {WEEKS_OF_HISTORY} weeks for {org.name}.")
        print("Re-run this script any time to reset to a fresh demo dataset (today-anchored).")


if __name__ == "__main__":
    asyncio.run(main())
