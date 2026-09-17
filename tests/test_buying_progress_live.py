"""End-to-end coverage for the live buying-progress counter (see
domain/buyer/buying_progress.py and services/buying_progress_service.py):
a buy_entry write is immediately reflected in both the buyer's own
GET /buyer/dnbp/current and the Trading Console's
GET /publications/current/progress (same computation, no drift), and an
unchanged republish does NOT reset accumulated progress — the specific
correction Terence confirmed after the pure-unit-test level already proved
the anchor algorithm, but this is the first check that the real publish/
buy_entry pipeline actually wires it up end to end.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from models.organisation import Organisation
from tests.pipeline_helpers import accountant_headers, build_publishable_snapshot, buyer_headers


async def _publish(client, headers) -> dict:
    snapshot = await build_publishable_snapshot(client, headers)
    resp = await client.post("/api/v1/publications", json={"snapshot_id": snapshot["id"]}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _post_buy(client, headers, *, species: str, head_count: int, client_uuid: str) -> None:
    # trade_date must be "today" (real wall-clock), not a fixed past date —
    # heads_bought is compared against the anchor's date (derived from the
    # live publication's real effective_from), same convention
    # scorecard_service.py's own documented calendar-date simplification
    # already uses for buy_entries.
    body = {
        "saleyard": "Bendigo",
        "trade_date": datetime.now(UTC).date().isoformat(),
        "species": species,
        "head_count": head_count,
        "price_per_head": "150.00",
        "weight_kg": "20.0",
        "client_uuid": client_uuid,
        "client_created_at": datetime.now(UTC).isoformat(),
    }
    resp = await client.post("/api/v1/buyer/entries", json=body, headers=headers)
    assert resp.status_code == 201, resp.text


def _sheep_heads_bought(payload: dict) -> str:
    line = next(s for s in payload["species"] if s["species"] == "SHEEP")
    return line["heads_bought"]


async def test_buy_entry_updates_both_buyer_and_console_progress_identically(
    client, db: AsyncSession, everhealth_org: Organisation
):
    accountant = await accountant_headers(client, db, everhealth_org, email="bing-progress1@test.com")
    buyer = await buyer_headers(client, db, everhealth_org, email="buyer-progress1@test.com")

    await _publish(client, accountant)

    before = await client.get("/api/v1/buyer/dnbp/current", headers=buyer)
    assert before.status_code == 200, before.text
    sheep_before = next(s for s in before.json()["species"] if s["species"] == "SHEEP")
    assert sheep_before["heads_bought"] == "0"

    await _post_buy(client, buyer, species="SHEEP", head_count=12, client_uuid="22222222-2222-4222-8222-222222222222")

    buyer_after = await client.get("/api/v1/buyer/dnbp/current", headers=buyer)
    assert _sheep_heads_bought(buyer_after.json()) == "12"

    console_after = await client.get("/api/v1/publications/current/progress", headers=accountant)
    assert console_after.status_code == 200, console_after.text
    console_line = next(s for s in console_after.json()["species"] if s["species"] == "SHEEP")
    assert console_line["heads_bought"] == 12
    assert Decimal(str(console_line["target_heads"])) == Decimal(sheep_before["target_heads"])


async def test_unchanged_republish_does_not_reset_progress(client, db: AsyncSession, everhealth_org: Organisation):
    accountant = await accountant_headers(client, db, everhealth_org, email="bing-progress2@test.com")
    buyer = await buyer_headers(client, db, everhealth_org, email="buyer-progress2@test.com")

    await _publish(client, accountant)
    await _post_buy(client, buyer, species="SHEEP", head_count=15, client_uuid="33333333-3333-4333-8333-333333333333")

    first_check = await client.get("/api/v1/buyer/dnbp/current", headers=buyer)
    assert _sheep_heads_bought(first_check.json()) == "15"

    # Republish the SAME order book (target_heads per species is unchanged)
    # — this must NOT reset the counter back to zero, per the confirmed
    # anchor-reset rule (see domain/buyer/buying_progress.py's docstring).
    await _publish(client, accountant)

    after_republish = await client.get("/api/v1/buyer/dnbp/current", headers=buyer)
    assert _sheep_heads_bought(after_republish.json()) == "15"
