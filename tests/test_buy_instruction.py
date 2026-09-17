"""Phase 4 — Buy Instruction generation, approve/publish gate, and the
order-keyed-vs-species-keyed DNBP distinction (non-negotiable #2). Uses the
real 07-08 workbook, same discipline as the rest of this test suite, since
that file's own CED18653/CED18655 SHEEP lines (different sell prices) are
exactly the pair phase04-instructions.txt names as the worked example.

A `DnbpPublication` must never come into existence except as the result of
publishing an already-approved instruction (see
services/buy_instruction_service.py's `publish`) — so, unlike the old
version of this file, nothing here calls `POST /publications` directly to
set up a Buy Instruction test: generate -> approve -> publish is the only
path, same as a real trading day.
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from core.reference_data import get_active_everhealth_config
from domain.engine.dnbp import compute_bing_dnbp
from models.organisation import Organisation
from tests.pipeline_helpers import (
    accountant_headers,
    build_publishable_snapshot,
    owner_headers,
)

_MONEY_QUANT = Decimal("0.0000000001")  # NUMERIC(18,10) — same 10dp scale every stored money/rate column rounds to


async def _generate_instruction(client, headers, snapshot_id: str) -> dict:
    resp = await client.post("/api/v1/buy-instructions", json={"snapshot_id": snapshot_id}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _approve_and_publish(client, owner, trading_console_headers, instruction_id: str) -> dict:
    approve_resp = await client.post(f"/api/v1/buy-instructions/{instruction_id}/approve", headers=owner)
    assert approve_resp.status_code == 200, approve_resp.text

    publish_resp = await client.post(f"/api/v1/buy-instructions/{instruction_id}/publish", headers=trading_console_headers)
    assert publish_resp.status_code == 200, publish_resp.text
    return publish_resp.json()


async def test_instruction_lines_are_order_keyed_not_species_min(
    client, db: AsyncSession, everhealth_org: Organisation
):
    accountant = await accountant_headers(client, db, everhealth_org, email="bing-bi1@test.com")
    owner = await owner_headers(client, db, everhealth_org, email="bobby-bi1@test.com")
    snapshot = await build_publishable_snapshot(client, accountant)

    instruction = await _generate_instruction(client, accountant, snapshot["id"])
    published_instruction = await _approve_and_publish(client, owner, accountant, instruction["id"])

    publication_resp = await client.get(
        f"/api/v1/publications/{published_instruction['publication_id']}", headers=accountant
    )
    assert publication_resp.status_code == 200, publication_resp.text
    sheep_pub_line = next(line for line in publication_resp.json()["lines"] if line["species"] == "SHEEP")

    by_contract = {line["contract_no"]: line for line in published_instruction["lines"]}
    ced18653 = by_contract["CED18653"]
    ced18655 = by_contract["CED18655"]

    # §5.4/worked example: CED18653 and CED18655 are both SHEEP with
    # different sell prices, so they must produce two DIFFERENT instruction-
    # line DNBPs — never one shared MIN'd value (non-negotiable #2).
    assert ced18653["species"] == "SHEEP"
    assert ced18655["species"] == "SHEEP"
    assert ced18653["dnbp_per_kg"] != ced18655["dnbp_per_kg"]

    # CED18655 does not carry the lowest SHEEP price in this file (CED18653
    # does), so the species-keyed publication figure (MIN across all active
    # SHEEP lines) must differ from CED18655's own order-keyed DNBP — if the
    # generator were wrongly reusing dnbp_publication_lines, this would fail.
    assert Decimal(ced18655["dnbp_per_kg"]) != Decimal(sheep_pub_line["dnbp_per_kg"])

    # Cross-check both instruction-line DNBPs directly against the engine,
    # independent of whatever the publication computed.
    config = await get_active_everhealth_config(db)
    lines_resp = await client.get(
        f"/api/v1/snapshots/{snapshot['id']}/lines", params={"lifecycle": "ACTIVE"}, headers=accountant
    )
    by_contract_received = {line["contract_no"]: line for line in lines_resp.json()}
    expected_18653 = compute_bing_dnbp(Decimal(by_contract_received["CED18653"]["avg_price_aud"]), "SHEEP", config)
    expected_18655 = compute_bing_dnbp(Decimal(by_contract_received["CED18655"]["avg_price_aud"]), "SHEEP", config)
    # The DB column is NUMERIC(18,10) (§5.5) — it rounds on insert, so
    # compare at that same 10dp scale rather than at full Decimal precision.
    assert Decimal(ced18653["dnbp_per_kg"]) == expected_18653.quantize(_MONEY_QUANT)
    assert Decimal(ced18655["dnbp_per_kg"]) == expected_18655.quantize(_MONEY_QUANT)


async def test_expected_livestock_cost_uses_bing_dnbp_not_peters_expectation(
    client, db: AsyncSession, everhealth_org: Organisation
):
    """[D6] resolved — the sample's own `8.4`-based figure is a documented
    error; this must NOT be reproduced. Doesn't need a publication at all —
    generate() reads bing_dnbp straight off the calculated snapshot."""
    headers = await accountant_headers(client, db, everhealth_org, email="bing-bi2@test.com")
    snapshot = await build_publishable_snapshot(client, headers)
    instruction = await _generate_instruction(client, headers, snapshot["id"])

    for line in instruction["lines"]:
        expected = (
            Decimal(line["dnbp_per_kg"]) * Decimal(line["weight_requirement_kg"]) * Decimal(line["expected_heads"])
        )
        assert Decimal(line["expected_livestock_cost"]) == expected
        if line["peters_expectation"] is not None:
            wrong = Decimal(line["peters_expectation"]) * Decimal(line["weight_requirement_kg"]) * Decimal(
                line["expected_heads"]
            )
            if Decimal(line["dnbp_per_kg"]) != Decimal(line["peters_expectation"]):
                assert Decimal(line["expected_livestock_cost"]) != wrong


async def test_publish_refused_before_approval_then_succeeds_after(
    client, db: AsyncSession, everhealth_org: Organisation
):
    accountant = await accountant_headers(client, db, everhealth_org, email="bing-bi4@test.com")
    owner = await owner_headers(client, db, everhealth_org, email="bobby-bi4@test.com")
    snapshot = await build_publishable_snapshot(client, accountant)
    instruction = await _generate_instruction(client, accountant, snapshot["id"])
    assert instruction["publication_id"] is None

    publish_resp = await client.post(f"/api/v1/buy-instructions/{instruction['id']}/publish", headers=accountant)
    assert publish_resp.status_code == 409, publish_resp.text
    assert publish_resp.json()["error"]["code"] == "INSTRUCTION_NOT_APPROVED"

    # §9.6 — approve is OWNER only; an ACCOUNTANT attempting it is refused.
    forbidden_resp = await client.post(f"/api/v1/buy-instructions/{instruction['id']}/approve", headers=accountant)
    assert forbidden_resp.status_code == 403, forbidden_resp.text

    approve_resp = await client.post(f"/api/v1/buy-instructions/{instruction['id']}/approve", headers=owner)
    assert approve_resp.status_code == 200, approve_resp.text
    assert approve_resp.json()["approved_by"] is not None
    assert approve_resp.json()["status"] == "DRAFT"  # approve does NOT change status

    publish_resp2 = await client.post(f"/api/v1/buy-instructions/{instruction['id']}/publish", headers=accountant)
    assert publish_resp2.status_code == 200, publish_resp2.text
    assert publish_resp2.json()["status"] == "ISSUED"
    assert publish_resp2.json()["publication_id"] is not None


async def test_fills_are_open_ended_not_fixed_to_three(client, db: AsyncSession, everhealth_org: Organisation):
    accountant = await accountant_headers(client, db, everhealth_org, email="bing-bi5@test.com")
    owner = await owner_headers(client, db, everhealth_org, email="bobby-bi5@test.com")
    snapshot = await build_publishable_snapshot(client, accountant)
    instruction = await _generate_instruction(client, accountant, snapshot["id"])

    # Fills refused while still DRAFT.
    line_id = instruction["lines"][0]["id"]
    early_fill = await client.post(
        f"/api/v1/buy-instructions/{instruction['id']}/lines/{line_id}/fills",
        json={"label": "Buy 1", "kg_amount": "100.00"},
        headers=accountant,
    )
    assert early_fill.status_code == 409
    assert early_fill.json()["error"]["code"] == "FILLS_NOT_ALLOWED"

    await _approve_and_publish(client, owner, accountant, instruction["id"])

    schw_kg = Decimal(instruction["lines"][0]["schw_kg"])
    labels = ["Buy 1", "Buy 2", "Buy 3", "Buy 4", "Buy 5"]
    result = None
    for label in labels:
        result = await client.post(
            f"/api/v1/buy-instructions/{instruction['id']}/lines/{line_id}/fills",
            json={"label": label, "kg_amount": "50.00"},
            headers=accountant,
        )
        assert result.status_code == 201, result.text

    updated_line = next(line for line in result.json()["lines"] if line["id"] == line_id)
    assert len(updated_line["fills"]) == 5  # more than the old fixed "Buy 1/2/3" — proves it's unbounded
    assert Decimal(updated_line["balance_kg"]) == schw_kg - Decimal("250.00")

    # Removing one fill updates the derived balance, never a stored column.
    fill_id = updated_line["fills"][0]["id"]
    remove_resp = await client.delete(
        f"/api/v1/buy-instructions/{instruction['id']}/lines/{line_id}/fills/{fill_id}", headers=accountant
    )
    assert remove_resp.status_code == 200, remove_resp.text
    final_line = next(line for line in remove_resp.json()["lines"] if line["id"] == line_id)
    assert len(final_line["fills"]) == 4
    assert Decimal(final_line["balance_kg"]) == schw_kg - Decimal("200.00")
