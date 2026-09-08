"""§12.6, §9.5 `GET /buyer/scorecard` — own performance only. Proves
isolation with two real buyer accounts, the same discipline
tests/test_buy_entry_sync.py::test_buyer_entries_are_isolated_per_buyer
already uses for the underlying buy_entries.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from models.organisation import Organisation
from tests.pipeline_helpers import accountant_headers, build_publishable_snapshot, buyer_headers


async def _publish(client, headers, snapshot_id: str) -> dict:
    resp = await client.post("/api/v1/publications", json={"snapshot_id": snapshot_id}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _log_entry(client, headers, *, client_uuid: str, head_count: int, price_per_head: str) -> dict:
    body = {
        "saleyard": "Bendigo",
        "trade_date": "2026-08-10",
        "species": "SHEEP",
        "head_count": head_count,
        "price_per_head": price_per_head,
        "weight_kg": "20.0",
        "client_uuid": client_uuid,
        "client_created_at": datetime.now(UTC).isoformat(),
    }
    resp = await client.post("/api/v1/buyer/entries", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_two_buyers_see_only_their_own_scorecard(client, db: AsyncSession, everhealth_org: Organisation):
    accountant_hdrs = await accountant_headers(client, db, everhealth_org, email="bing-sc1@test.com")
    snapshot = await build_publishable_snapshot(client, accountant_hdrs)
    await _publish(client, accountant_hdrs, snapshot["id"])

    b1_headers = await buyer_headers(client, db, everhealth_org, email="buyer-sc1@test.com")
    b2_headers = await buyer_headers(client, db, everhealth_org, email="buyer-sc2@test.com")

    entry1 = await _log_entry(
        client, b1_headers, client_uuid="66666666-6666-4666-8666-666666666666", head_count=6, price_per_head="150.00"
    )
    await _log_entry(
        client, b2_headers, client_uuid="77777777-7777-4777-8777-777777777777", head_count=9, price_per_head="140.00"
    )

    sc1_resp = await client.get("/api/v1/buyer/scorecard", headers=b1_headers)
    assert sc1_resp.status_code == 200, sc1_resp.text
    sc1 = sc1_resp.json()
    assert sc1["heads_bought"] == 6
    expected_headroom = Decimal(entry1["variance_per_kg"]) * Decimal("20.0") * 6
    assert Decimal(sc1["headroom_captured_aud"]) == expected_headroom
    assert sc1["spend_by_saleyard"] == [{"saleyard": "Bendigo", "spend_aud": "900.0000000000"}]

    sc2_resp = await client.get("/api/v1/buyer/scorecard", headers=b2_headers)
    assert sc2_resp.status_code == 200, sc2_resp.text
    sc2 = sc2_resp.json()
    assert sc2["heads_bought"] == 9

    # Neither buyer's scorecard reflects the other's activity.
    assert sc1["heads_bought"] != sc2["heads_bought"]


async def test_scorecard_response_has_no_forbidden_fields_for_a_buyer_with_no_entries(
    client, db: AsyncSession, everhealth_org: Organisation
):
    b_headers = await buyer_headers(client, db, everhealth_org, email="buyer-sc-empty@test.com")
    resp = await client.get("/api/v1/buyer/scorecard", headers=b_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["heads_bought"] == 0
    assert body["avg_paid_per_kg"] is None
    assert body["breach_rate"] == "0"
