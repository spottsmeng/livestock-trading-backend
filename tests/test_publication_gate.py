"""§5.7's full publication gate (the half Phase 2 didn't enforce yet):
a BLOCK issue on an active line refuses publication outright, and a WARN/
CORRECTION issue on an active line refuses it until explicitly
acknowledged — but an OPEN correction_request (the separate, manual
internal-flag table, §11.6) never gates a publication at all.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from models.organisation import Organisation
from tests.pipeline_helpers import (
    accountant_headers,
    acknowledge_all_active_issues,
    build_calculated_snapshot,
    build_publishable_snapshot,
)


async def test_publish_refused_while_active_warn_issue_unacknowledged(
    client, db: AsyncSession, everhealth_org: Organisation
):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-gate1@test.com")
    snapshot = await build_calculated_snapshot(client, headers)

    resp = await client.post("/api/v1/publications", json={"snapshot_id": snapshot["id"]}, headers=headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "ISSUES_NOT_ACKNOWLEDGED"


async def test_publish_succeeds_once_every_active_issue_is_acknowledged(
    client, db: AsyncSession, everhealth_org: Organisation
):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-gate2@test.com")
    snapshot = await build_publishable_snapshot(client, headers)

    resp = await client.post("/api/v1/publications", json={"snapshot_id": snapshot["id"]}, headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["snapshot_id"] == snapshot["id"]
    species = {line["species"] for line in body["lines"]}
    assert "SHEEP" in species  # CED18650's line, §5.4's worked example

    sheep_line = next(line for line in body["lines"] if line["species"] == "SHEEP")
    assert sheep_line["dnbp_per_kg"] is not None
    assert len(sheep_line["contributing_line_ids"]) >= 1


async def test_open_correction_request_never_gates_publication(client, db: AsyncSession, everhealth_org: Organisation):
    """§11.6 — correction_requests are a separate, manual, internal-only
    flag; the PRD is explicit that a publication may proceed with them
    still open, unlike an unacknowledged validation_issue."""
    headers = await accountant_headers(client, db, everhealth_org, email="bing-gate3@test.com")
    snapshot = await build_calculated_snapshot(client, headers)
    await acknowledge_all_active_issues(client, snapshot["id"], headers)

    lines_resp = await client.get(
        f"/api/v1/snapshots/{snapshot['id']}/lines", params={"lifecycle": "ACTIVE"}, headers=headers
    )
    a_line = lines_resp.json()[0]
    raise_resp = await client.post(
        f"/api/v1/order-lines/{a_line['id']}/correction-requests",
        json={"column_ref": "expected_livestock_cost_per_kg", "issue_code": "MISSING_LIVESTOCK_COST"},
        headers=headers,
    )
    assert raise_resp.status_code == 201, raise_resp.text

    resp = await client.post("/api/v1/publications", json={"snapshot_id": snapshot["id"]}, headers=headers)
    assert resp.status_code == 201, resp.text


async def test_get_current_publication_reflects_latest(client, db: AsyncSession, everhealth_org: Organisation):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-gate4@test.com")
    snapshot = await build_publishable_snapshot(client, headers)
    publish_resp = await client.post("/api/v1/publications", json={"snapshot_id": snapshot["id"]}, headers=headers)
    publication_id = publish_resp.json()["id"]

    current_resp = await client.get("/api/v1/publications/current", headers=headers)
    assert current_resp.status_code == 200
    assert current_resp.json()["id"] == publication_id
    assert current_resp.json()["superseded_by"] is None
