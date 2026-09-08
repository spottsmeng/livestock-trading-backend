"""§12.5, §9.5 — the buyer's Instruction screen: buyer-safe view of the live
Buy Instruction and its acknowledgement, plus the ISSUED->ACKNOWLEDGED
transition and the OWNER/ACCOUNTANT-only reconcile-close (§8's status
machine, non-negotiable).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from models.organisation import Organisation
from tests.pipeline_helpers import accountant_headers, build_publishable_snapshot, buyer_headers, owner_headers


async def _issue_instruction(client, accountant, owner, everhealth_org) -> dict:
    snapshot = await build_publishable_snapshot(client, accountant)
    publish_resp = await client.post("/api/v1/publications", json={"snapshot_id": snapshot["id"]}, headers=accountant)
    publication = publish_resp.json()
    gen_resp = await client.post(
        "/api/v1/buy-instructions",
        json={"snapshot_id": snapshot["id"], "publication_id": publication["id"]},
        headers=accountant,
    )
    instruction = gen_resp.json()
    await client.post(f"/api/v1/buy-instructions/{instruction['id']}/approve", headers=owner)
    issue_resp = await client.post(f"/api/v1/buy-instructions/{instruction['id']}/issue", headers=accountant)
    return issue_resp.json()


async def test_buyer_sees_instruction_current_and_can_acknowledge(
    client, db: AsyncSession, everhealth_org: Organisation
):
    accountant = await accountant_headers(client, db, everhealth_org, email="bing-buyerinst1@test.com")
    owner = await owner_headers(client, db, everhealth_org, email="bobby-buyerinst1@test.com")
    buyer = await buyer_headers(client, db, everhealth_org, email="buyer-buyerinst1@test.com")

    instruction = await _issue_instruction(client, accountant, owner, everhealth_org)

    current_resp = await client.get("/api/v1/buyer/instruction/current", headers=buyer)
    assert current_resp.status_code == 200, current_resp.text
    body = current_resp.json()
    assert body["instruction_id"] == instruction["id"]
    assert body["status"] == "ISSUED"
    assert len(body["lines"]) == len(instruction["lines"])

    line = body["lines"][0]
    assert set(line.keys()) == {"contract_no", "species", "target_heads", "weight_requirement_kg", "dnbp_per_kg"}

    ack_resp = await client.post(f"/api/v1/buyer/instruction/{instruction['id']}/acknowledge", headers=buyer)
    assert ack_resp.status_code == 204, ack_resp.text

    check_resp = await client.get(f"/api/v1/buy-instructions/{instruction['id']}", headers=accountant)
    assert check_resp.json()["status"] == "ACKNOWLEDGED"


async def test_reconcile_close_requires_acknowledged_and_allows_accountant(
    client, db: AsyncSession, everhealth_org: Organisation
):
    accountant = await accountant_headers(client, db, everhealth_org, email="bing-buyerinst2@test.com")
    owner = await owner_headers(client, db, everhealth_org, email="bobby-buyerinst2@test.com")
    buyer = await buyer_headers(client, db, everhealth_org, email="buyer-buyerinst2@test.com")

    instruction = await _issue_instruction(client, accountant, owner, everhealth_org)

    too_early = await client.post(f"/api/v1/buy-instructions/{instruction['id']}/reconcile-close", headers=accountant)
    assert too_early.status_code == 409
    assert too_early.json()["error"]["code"] == "INVALID_INSTRUCTION_TRANSITION"

    await client.post(f"/api/v1/buyer/instruction/{instruction['id']}/acknowledge", headers=buyer)

    close_resp = await client.post(
        f"/api/v1/buy-instructions/{instruction['id']}/reconcile-close", headers=accountant
    )
    assert close_resp.status_code == 200, close_resp.text
    assert close_resp.json()["status"] == "RECONCILED"
