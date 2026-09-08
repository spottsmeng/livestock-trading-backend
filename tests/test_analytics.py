"""Phase 5 — §13.2's six dashboard panels plus `/analytics/overview`.
Non-negotiable #2: every /analytics/* route is OWNER/ACCOUNTANT only.
Exercises the real 07-08 workbook end to end (upload -> calculate ->
publish -> buy entries -> buy instruction), same discipline as the rest of
this suite, so the panels are proven against real engine output rather than
synthetic numbers.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from models.organisation import Organisation
from tests.pipeline_helpers import accountant_headers, build_publishable_snapshot, buyer_headers, owner_headers

ROUTES = [
    "/api/v1/analytics/overview",
    "/api/v1/analytics/order-book",
    "/api/v1/analytics/dnbp-trend?species=SHEEP",
    "/api/v1/analytics/buyer-performance",
    "/api/v1/analytics/margin-bridge",
    "/api/v1/analytics/fulfilment",
    "/api/v1/analytics/breaches",
]


async def test_buyer_is_forbidden_from_every_analytics_route(client, db: AsyncSession, everhealth_org: Organisation):
    b_headers = await buyer_headers(client, db, everhealth_org, email="buyer-analytics-rbac@test.com")
    for route in ROUTES:
        resp = await client.get(route, headers=b_headers)
        assert resp.status_code == 403, f"{route}: expected 403, got {resp.status_code}"


async def test_unauthenticated_request_is_rejected(client):
    for route in ROUTES:
        resp = await client.get(route)
        assert resp.status_code == 401, route


async def _publish(client, headers, snapshot_id: str) -> dict:
    resp = await client.post("/api/v1/publications", json={"snapshot_id": snapshot_id}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_order_book_reflects_the_latest_snapshots_active_lines(
    client, db: AsyncSession, everhealth_org: Organisation
):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-ob1@test.com")
    snapshot = await build_publishable_snapshot(client, headers)

    lines_resp = await client.get(
        f"/api/v1/snapshots/{snapshot['id']}/lines", params={"lifecycle": "ACTIVE"}, headers=headers
    )
    active_lines = lines_resp.json()
    sheep_lines = [line for line in active_lines if line["species"] == "SHEEP"]
    expected_exposure = sum(Decimal(line["amount_aud"]) for line in sheep_lines)
    expected_heads = sum(Decimal(line["estimated_heads"]) for line in sheep_lines)

    resp = await client.get("/api/v1/analytics/order-book", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["snapshot_id"] == snapshot["id"]

    sheep_row = next(row for row in body["by_species"] if row["species"] == "SHEEP")
    assert Decimal(sheep_row["exposure_aud"]) == expected_exposure
    assert Decimal(sheep_row["heads_required"]) == expected_heads
    assert sheep_row["heads_bought"] == 0
    assert sheep_row["days_of_cover"] is None  # no buy_entries yet -> trailing rate is 0 -> None, never Inf/NaN

    total_exposure = sum(Decimal(row["exposure_aud"]) for row in body["by_species"])
    assert Decimal(body["total_exposure_aud"]) == total_exposure


async def test_margin_bridge_is_a_direct_read_of_order_workings_columns(
    client, db: AsyncSession, everhealth_org: Organisation
):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-mb1@test.com")
    snapshot = await build_publishable_snapshot(client, headers)

    lines_resp = await client.get(
        f"/api/v1/snapshots/{snapshot['id']}/lines", params={"lifecycle": "ACTIVE"}, headers=headers
    )
    active_lines = lines_resp.json()
    workings = [
        (await client.get(f"/api/v1/order-lines/{line['id']}/workings", headers=headers)).json()
        for line in active_lines
    ]
    expected_avg_dnbp = sum(Decimal(w["bing_dnbp"]) for w in workings) / len(workings)

    resp = await client.get(f"/api/v1/analytics/margin-bridge?snapshot_id={snapshot['id']}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["line_count"] == len(active_lines)
    assert Decimal(body["avg_bing_dnbp"]) == expected_avg_dnbp

    # Default (no snapshot_id) resolves to the latest snapshot for the org.
    default_resp = await client.get("/api/v1/analytics/margin-bridge", headers=headers)
    assert default_resp.json()["snapshot_id"] == snapshot["id"]


async def test_buyer_performance_and_breaches_reflect_real_buy_entries(
    client, db: AsyncSession, everhealth_org: Organisation
):
    accountant_hdrs = await accountant_headers(client, db, everhealth_org, email="bing-bp1@test.com")
    snapshot = await build_publishable_snapshot(client, accountant_hdrs)
    publication = await _publish(client, accountant_hdrs, snapshot["id"])
    sheep_line = next(line for line in publication["lines"] if line["species"] == "SHEEP")
    dnbp = Decimal(sheep_line["dnbp_per_kg"])

    b_headers = await buyer_headers(client, db, everhealth_org, email="buyer-bp1@test.com")

    # A deliberate breach: price well above the published DNBP.
    breach_price_per_head = (dnbp * Decimal("2") * Decimal("20")).quantize(Decimal("0.01"))
    body = {
        "saleyard": "Bendigo",
        "trade_date": "2026-08-10",
        "species": "SHEEP",
        "agent": "TBW",
        "pen": "No.10",
        "head_count": 10,
        "price_per_head": str(breach_price_per_head),
        "weight_kg": "20.0",
        "breach_reason": "Quality premium",
        "client_uuid": "44444444-4444-4444-8444-444444444444",
        "client_created_at": datetime.now(UTC).isoformat(),
    }
    entry_resp = await client.post("/api/v1/buyer/entries", json=body, headers=b_headers)
    assert entry_resp.status_code == 201, entry_resp.text
    entry = entry_resp.json()
    assert entry["is_breach"] is True

    perf_resp = await client.get("/api/v1/analytics/buyer-performance", headers=accountant_hdrs)
    assert perf_resp.status_code == 200, perf_resp.text
    perf = perf_resp.json()
    buyer_row = next(row for row in perf["by_buyer"] if row["buyer_email"] == "buyer-bp1@test.com")
    assert buyer_row["breach_count"] == 1
    assert buyer_row["entry_count"] == 1
    assert Decimal(buyer_row["breach_rate"]) == Decimal("1")
    expected_headroom = Decimal(entry["variance_per_kg"]) * Decimal("20.0") * 10
    assert Decimal(buyer_row["headroom_captured_aud"]) == expected_headroom

    breaches_resp = await client.get("/api/v1/analytics/breaches", headers=accountant_hdrs)
    assert breaches_resp.status_code == 200, breaches_resp.text
    breach_rows = breaches_resp.json()["breaches"]
    assert any(row["id"] == entry["id"] for row in breach_rows)


async def test_fulfilment_pairs_instructed_and_bought_schw_by_trade_date(
    client, db: AsyncSession, everhealth_org: Organisation
):
    accountant_hdrs = await accountant_headers(client, db, everhealth_org, email="bing-ff1@test.com")
    owner_hdrs = await owner_headers(client, db, everhealth_org, email="bobby-ff1@test.com")
    snapshot = await build_publishable_snapshot(client, accountant_hdrs)
    publication = await _publish(client, accountant_hdrs, snapshot["id"])

    instr_resp = await client.post(
        "/api/v1/buy-instructions",
        json={"snapshot_id": snapshot["id"], "publication_id": publication["id"], "trade_date": "2026-08-10"},
        headers=accountant_hdrs,
    )
    assert instr_resp.status_code == 201, instr_resp.text
    instruction = instr_resp.json()
    expected_instructed = sum(Decimal(line["schw_kg"]) for line in instruction["lines"])

    b_headers = await buyer_headers(client, db, everhealth_org, email="buyer-ff1@test.com")
    sheep_line = next(line for line in publication["lines"] if line["species"] == "SHEEP")
    body = {
        "saleyard": "Bendigo",
        "trade_date": "2026-08-10",
        "species": "SHEEP",
        "head_count": 4,
        "price_per_head": "150.00",
        "weight_kg": "20.0",
        "client_uuid": "55555555-5555-4555-8555-555555555555",
        "client_created_at": datetime.now(UTC).isoformat(),
    }
    await client.post("/api/v1/buyer/entries", json=body, headers=b_headers)

    resp = await client.get(
        "/api/v1/analytics/fulfilment", params={"from": "2026-08-10", "to": "2026-08-10"}, headers=owner_hdrs
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["trade_date"] == "2026-08-10"
    assert Decimal(row["instructed_schw_kg"]) == expected_instructed
    assert Decimal(row["bought_schw_kg"]) == Decimal("80.0")  # 4 heads x 20.0 kg
    assert Decimal(row["shortfall_schw_kg"]) == expected_instructed - Decimal("80.0")
    assert sheep_line["species"] == "SHEEP"  # sanity: this fixture really is the SHEEP publication line
