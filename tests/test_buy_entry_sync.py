"""§9.5, §12.4, §12.7 — the digital red note book's write path: idempotent
on `client_uuid` (offline replay safety), scored against the DNBP that was
actually live at `client_created_at`, and frozen so a later republish can
never retroactively change a past breach.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from models.organisation import Organisation
from tests.pipeline_helpers import accountant_headers, build_publishable_snapshot, buyer_headers


async def _publish_sheep(client, db, org) -> tuple[dict, dict]:
    headers = await accountant_headers(client, db, org, email="bing-buy1@test.com")
    snapshot = await build_publishable_snapshot(client, headers)
    publish_resp = await client.post("/api/v1/publications", json={"snapshot_id": snapshot["id"]}, headers=headers)
    assert publish_resp.status_code == 201, publish_resp.text
    return publish_resp.json(), headers


async def test_buy_entry_scores_against_published_dnbp_and_is_idempotent(
    client, db: AsyncSession, everhealth_org: Organisation
):
    publication, _accountant = await _publish_sheep(client, db, everhealth_org)
    sheep_line = next(line for line in publication["lines"] if line["species"] == "SHEEP")
    dnbp = Decimal(sheep_line["dnbp_per_kg"])

    b_headers = await buyer_headers(client, db, everhealth_org, email="buyer-buy1@test.com")

    client_uuid = "11111111-1111-4111-8111-111111111111"
    body = {
        "saleyard": "Bendigo",
        "trade_date": "2026-08-10",
        "species": "SHEEP",
        "agent": "TBW",
        "pen": "No.10",
        "head_count": 12,
        "price_per_head": "150.00",
        "weight_kg": "20.0",
        "client_uuid": client_uuid,
        "client_created_at": datetime.now(UTC).isoformat(),
    }
    resp = await client.post("/api/v1/buyer/entries", json=body, headers=b_headers)
    assert resp.status_code == 201, resp.text
    entry = resp.json()
    assert Decimal(entry["dnbp_at_entry"]) == dnbp
    expected_implied = Decimal("150.00") / Decimal("20.0")
    assert Decimal(entry["implied_price_per_kg"]) == expected_implied
    assert entry["is_breach"] == (expected_implied > dnbp)

    # Idempotent replay — same client_uuid, no duplicate row, no re-scoring.
    replay_resp = await client.post("/api/v1/buyer/entries", json=body, headers=b_headers)
    assert replay_resp.status_code == 201, replay_resp.text
    assert replay_resp.json()["id"] == entry["id"]

    list_resp = await client.get("/api/v1/buyer/entries", headers=b_headers)
    assert len(list_resp.json()) == 1


async def test_a_later_republish_never_changes_a_frozen_past_entry(
    client, db: AsyncSession, everhealth_org: Organisation
):
    publication, accountant_hdrs = await _publish_sheep(client, db, everhealth_org)
    sheep_line = next(line for line in publication["lines"] if line["species"] == "SHEEP")
    original_dnbp = Decimal(sheep_line["dnbp_per_kg"])

    b_headers = await buyer_headers(client, db, everhealth_org, email="buyer-buy2@test.com")
    body = {
        "saleyard": "Bendigo",
        "trade_date": "2026-08-10",
        "species": "SHEEP",
        "agent": "M06",
        "pen": "25",
        "head_count": 5,
        "price_per_head": "160.00",
        "weight_kg": "20.0",
        "client_uuid": "22222222-2222-4222-8222-222222222222",
        "client_created_at": datetime.now(UTC).isoformat(),
    }
    entry_resp = await client.post("/api/v1/buyer/entries", json=body, headers=b_headers)
    entry = entry_resp.json()
    assert Decimal(entry["dnbp_at_entry"]) == original_dnbp

    # Republish the same snapshot again (a no-op change in content, but a
    # brand new publication row with a fresh id) and confirm the earlier
    # entry's frozen fields are untouched.
    second_publish = await client.post(
        "/api/v1/publications", json={"snapshot_id": publication["snapshot_id"]}, headers=accountant_hdrs
    )
    assert second_publish.status_code == 201, second_publish.text
    assert second_publish.json()["id"] != publication["id"]

    list_resp = await client.get("/api/v1/buyer/entries", headers=b_headers)
    refetched = next(e for e in list_resp.json() if e["id"] == entry["id"])
    assert Decimal(refetched["dnbp_at_entry"]) == original_dnbp
    assert refetched["is_breach"] == entry["is_breach"]


async def test_buyer_entries_are_isolated_per_buyer(client, db: AsyncSession, everhealth_org: Organisation):
    publication, _accountant = await _publish_sheep(client, db, everhealth_org)
    b1 = await buyer_headers(client, db, everhealth_org, email="buyer-iso1@test.com")
    b2 = await buyer_headers(client, db, everhealth_org, email="buyer-iso2@test.com")

    body = {
        "saleyard": "Bendigo",
        "trade_date": "2026-08-10",
        "species": "SHEEP",
        "head_count": 1,
        "price_per_head": "100.00",
        "weight_kg": "20.0",
        "client_uuid": "33333333-3333-4333-8333-333333333333",
        "client_created_at": datetime.now(UTC).isoformat(),
    }
    await client.post("/api/v1/buyer/entries", json=body, headers=b1)

    b1_entries = (await client.get("/api/v1/buyer/entries", headers=b1)).json()
    b2_entries = (await client.get("/api/v1/buyer/entries", headers=b2)).json()
    assert len(b1_entries) == 1
    assert len(b2_entries) == 0
