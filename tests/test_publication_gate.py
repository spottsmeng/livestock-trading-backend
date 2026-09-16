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
    buyer_headers,
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


async def test_republishing_unchanged_prices_does_not_notify_the_buyer(
    client, db: AsyncSession, everhealth_org: Organisation
):
    """The follow-up fix to the acknowledgment-carry-forward flaw: a
    same-price republish (the abattoir resends an unchanged book) must not
    buzz the buyer's phone with another "New Do Not Buy Price" alert —
    confirmed with the business, since a daily no-news alert trains the
    buyer to ignore the real ones. The first-ever publish for an org is
    always genuinely new information; a second, byte-identical submission
    republished right after it is not."""
    headers = await accountant_headers(client, db, everhealth_org, email="bing-gate5@test.com")

    first_snapshot = await build_publishable_snapshot(client, headers)
    first_publish = await client.post(
        "/api/v1/publications", json={"snapshot_id": first_snapshot["id"]}, headers=headers
    )
    assert first_publish.status_code == 201, first_publish.text
    assert first_publish.json()["buyer_notified"] is True  # nothing published before this org's first publish

    second_snapshot = await build_publishable_snapshot(client, headers)
    second_publish = await client.post(
        "/api/v1/publications", json={"snapshot_id": second_snapshot["id"]}, headers=headers
    )
    assert second_publish.status_code == 201, second_publish.text
    assert second_publish.json()["buyer_notified"] is False  # same species, same prices as the first publish

    # §11.5's console-side "change vs the previous publication" needs the
    # same figure §12.2's buyer screen does — confirm it's on this response too.
    first_sheep = next(line for line in first_publish.json()["lines"] if line["species"] == "SHEEP")
    second_sheep = next(line for line in second_publish.json()["lines"] if line["species"] == "SHEEP")
    assert first_sheep["previous_dnbp_per_kg"] is None
    assert second_sheep["previous_dnbp_per_kg"] == first_sheep["dnbp_per_kg"]

    # And it's durable, not just the immediate response — a later read of
    # this same publication (e.g. from the console's publication history)
    # must agree.
    current_resp = await client.get("/api/v1/publications/current", headers=headers)
    assert current_resp.json()["buyer_notified"] is False


async def test_buyer_screen_carries_the_previous_publication_price_per_species(
    client, db: AsyncSession, everhealth_org: Organisation
):
    """§12.2's own mockup shows "$9.38  ▲ +0.12" next to the price — a
    change-vs-previous-publication the buyer's screen can only render if
    the API actually hands it the prior price. Nothing to compare against
    on an org's first-ever publish (no arrow in the PRD's own mockup for
    that case either); a second publish must carry the first one's price
    forward per species, so the buyer's client can compute the delta
    itself (§2.2 buyer-safe: this is the same already-safe dnbp_per_kg
    field, just the earlier value of it)."""
    owner_headers = await accountant_headers(client, db, everhealth_org, email="bing-gate6@test.com")
    buyer_creds = await buyer_headers(client, db, everhealth_org, email="buyer-gate6@test.com")

    first_snapshot = await build_publishable_snapshot(client, owner_headers)
    first_publish = await client.post(
        "/api/v1/publications", json={"snapshot_id": first_snapshot["id"]}, headers=owner_headers
    )
    assert first_publish.status_code == 201, first_publish.text

    first_buyer_view = await client.get("/api/v1/buyer/dnbp/current", headers=buyer_creds)
    assert first_buyer_view.status_code == 200, first_buyer_view.text
    first_sheep = next(line for line in first_buyer_view.json()["species"] if line["species"] == "SHEEP")
    assert first_sheep["previous_dnbp_per_kg"] is None  # nothing published before this org's first publish

    second_snapshot = await build_publishable_snapshot(client, owner_headers)
    second_publish = await client.post(
        "/api/v1/publications", json={"snapshot_id": second_snapshot["id"]}, headers=owner_headers
    )
    assert second_publish.status_code == 201, second_publish.text

    second_buyer_view = await client.get("/api/v1/buyer/dnbp/current", headers=buyer_creds)
    second_sheep = next(line for line in second_buyer_view.json()["species"] if line["species"] == "SHEEP")
    assert second_sheep["previous_dnbp_per_kg"] == first_sheep["dnbp_per_kg"]  # unchanged file -> unchanged price
    assert second_sheep["dnbp_per_kg"] == first_sheep["dnbp_per_kg"]  # so the buyer's own arrow logic shows no arrow
