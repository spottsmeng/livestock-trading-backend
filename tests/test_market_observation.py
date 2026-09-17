"""Market intelligence — competitor bid observations. Idempotent on
`client_uuid` like BuyEntry, but visibility is inverted: a BUYER may submit
and correct their own observations but never list them back; only
OWNER/ACCOUNTANT can list or aggregate this org's observations.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from models.enums import OrgKind
from models.organisation import Organisation
from tests.pipeline_helpers import accountant_headers, buyer_headers, owner_headers


def _body(**overrides) -> dict:
    body = {
        "saleyard": "Bendigo",
        "trade_date": "2026-08-10",
        "species": "SHEEP",
        "competitor_name": "Rival Meats Co",
        "agent": "TBW",
        "pen": "No.10",
        "head_count": 12,
        "price_per_head": "150.00",
        "weight_kg": "20.0",
        "client_uuid": "44444444-4444-4444-8444-444444444444",
        "client_created_at": datetime.now(UTC).isoformat(),
    }
    body.update(overrides)
    return body


async def test_create_observation_is_idempotent_and_derives_implied_price(
    client, db: AsyncSession, everhealth_org: Organisation
):
    b_headers = await buyer_headers(client, db, everhealth_org, email="buyer-mi1@test.com")

    body = _body()
    resp = await client.post("/api/v1/market-intel/observations", json=body, headers=b_headers)
    assert resp.status_code == 201, resp.text
    observation = resp.json()
    assert Decimal(observation["implied_price_per_kg"]) == Decimal("150.00") / Decimal("20.0")
    assert observation["is_possible_duplicate"] is False

    # Idempotent replay — same client_uuid, no duplicate row.
    replay = await client.post("/api/v1/market-intel/observations", json=body, headers=b_headers)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == observation["id"]

    o_headers = await owner_headers(client, db, everhealth_org, email="owner-mi1@test.com")
    list_resp = await client.get("/api/v1/market-intel/observations", headers=o_headers)
    assert list_resp.status_code == 200, list_resp.text
    assert len(list_resp.json()) == 1


async def test_observation_without_weight_has_no_implied_price(
    client, db: AsyncSession, everhealth_org: Organisation
):
    b_headers = await buyer_headers(client, db, everhealth_org, email="buyer-mi2@test.com")
    body = _body(weight_kg=None, client_uuid="55555555-5555-4555-8555-555555555555")
    resp = await client.post("/api/v1/market-intel/observations", json=body, headers=b_headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["implied_price_per_kg"] is None


async def test_buyer_cannot_list_or_read_back_observations(
    client, db: AsyncSession, everhealth_org: Organisation
):
    b_headers = await buyer_headers(client, db, everhealth_org, email="buyer-mi3@test.com")
    body = _body(client_uuid="66666666-6666-4666-8666-666666666666")
    await client.post("/api/v1/market-intel/observations", json=body, headers=b_headers)

    list_resp = await client.get("/api/v1/market-intel/observations", headers=b_headers)
    assert list_resp.status_code == 403

    summary_resp = await client.get("/api/v1/market-intel/summary", headers=b_headers)
    assert summary_resp.status_code == 403


async def test_owner_and_accountant_cannot_submit_observations(
    client, db: AsyncSession, everhealth_org: Organisation
):
    o_headers = await owner_headers(client, db, everhealth_org, email="owner-mi2@test.com")
    a_headers = await accountant_headers(client, db, everhealth_org, email="accountant-mi1@test.com")

    resp_owner = await client.post(
        "/api/v1/market-intel/observations",
        json=_body(client_uuid="77777777-7777-4777-8777-777777777777"),
        headers=o_headers,
    )
    assert resp_owner.status_code == 403

    resp_accountant = await client.post(
        "/api/v1/market-intel/observations",
        json=_body(client_uuid="88888888-8888-4888-8888-888888888888"),
        headers=a_headers,
    )
    assert resp_accountant.status_code == 403


async def test_summary_groups_by_competitor_and_species(client, db: AsyncSession, everhealth_org: Organisation):
    b_headers = await buyer_headers(client, db, everhealth_org, email="buyer-mi4@test.com")
    await client.post(
        "/api/v1/market-intel/observations",
        json=_body(client_uuid="99999999-9999-4999-8999-999999999991", price_per_head="150.00", weight_kg="20.0"),
        headers=b_headers,
    )
    await client.post(
        "/api/v1/market-intel/observations",
        json=_body(client_uuid="99999999-9999-4999-8999-999999999992", price_per_head="170.00", weight_kg="20.0"),
        headers=b_headers,
    )

    a_headers = await accountant_headers(client, db, everhealth_org, email="accountant-mi2@test.com")
    resp = await client.get("/api/v1/market-intel/summary", headers=a_headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    row = next(r for r in rows if r["competitor_name"] == "Rival Meats Co" and r["species"] == "SHEEP")
    assert row["entry_count"] == 2
    assert row["heads_observed"] == 24
    assert Decimal(row["avg_price_per_kg"]) == Decimal("8.0")


async def test_observations_are_org_scoped(client, db: AsyncSession, everhealth_org: Organisation):
    b_headers = await buyer_headers(client, db, everhealth_org, email="buyer-mi5@test.com")
    await client.post(
        "/api/v1/market-intel/observations",
        json=_body(client_uuid="10101010-1010-4101-8101-101010101010"),
        headers=b_headers,
    )

    other_org = Organisation(name="Rival Buyer Co.", kind=OrgKind.BUYER_CO)
    db.add(other_org)
    await db.commit()
    await db.refresh(other_org)

    other_owner = await owner_headers(client, db, other_org, email="owner-mi-other@test.com")
    list_resp = await client.get("/api/v1/market-intel/observations", headers=other_owner)
    assert list_resp.status_code == 200
    assert list_resp.json() == []
