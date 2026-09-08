"""Phase 3b — §6.5/§9.8/§19: reference-data versioning through the real API.
Uses the real 07-08 workbook (via pipeline_helpers) so the impact preview
runs against a genuine active book, not a synthetic fixture.
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from models.organisation import Organisation
from tests.pipeline_helpers import accountant_headers, build_calculated_snapshot


async def test_activation_refused_without_impact_preview(client, db: AsyncSession, everhealth_org: Organisation):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-refdata1@test.com")

    create_resp = await client.post(
        "/api/v1/reference-data/versions",
        json={
            "effective_from": "2026-09-08T00:00:00Z",
            "note": "test version",
            "entries": [{"table_key": "dnbp_factor_by_species", "key1": "SHEEP", "value": "0.90"}],
        },
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    version_id = create_resp.json()["id"]

    activate_resp = await client.post(f"/api/v1/reference-data/versions/{version_id}/activate", headers=headers)
    assert activate_resp.status_code == 409, activate_resp.text
    assert activate_resp.json()["error"]["code"] == "IMPACT_PREVIEW_REQUIRED"


async def test_impact_preview_then_activate_changes_active_config(
    client, db: AsyncSession, everhealth_org: Organisation
):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-refdata2@test.com")
    await build_calculated_snapshot(client, headers)

    active_before = await client.get("/api/v1/reference-data/active", headers=headers)
    assert Decimal(active_before.json()["dnbp_factor_by_species"]["SHEEP"]) == Decimal("0.83")

    create_resp = await client.post(
        "/api/v1/reference-data/versions",
        json={
            "effective_from": "2026-09-08T00:00:00Z",
            "note": "raise SHEEP factor",
            "entries": [{"table_key": "dnbp_factor_by_species", "key1": "SHEEP", "value": "0.90"}],
        },
        headers=headers,
    )
    version_id = create_resp.json()["id"]

    impact_resp = await client.post(f"/api/v1/reference-data/versions/{version_id}/impact", headers=headers)
    assert impact_resp.status_code == 200, impact_resp.text
    impact = impact_resp.json()
    assert impact["lines_affected"] >= 1
    sheep_lines = [line for line in impact["lines"] if line["species"] == "SHEEP"]
    assert sheep_lines, "expected at least one SHEEP line in the real 07-08 active book"
    for line in sheep_lines:
        assert line["new_dnbp"] is not None and line["old_dnbp"] is not None
        assert float(line["new_dnbp"]) > float(line["old_dnbp"])

    activate_resp = await client.post(f"/api/v1/reference-data/versions/{version_id}/activate", headers=headers)
    assert activate_resp.status_code == 200, activate_resp.text
    assert activate_resp.json()["is_active"] is True

    active_after = await client.get("/api/v1/reference-data/active", headers=headers)
    assert Decimal(active_after.json()["dnbp_factor_by_species"]["SHEEP"]) == Decimal("0.90")
    # Untouched species/tables carry over from the previously active version.
    assert Decimal(active_after.json()["dnbp_factor_by_species"]["GOAT"]) == Decimal("0.77")
    assert Decimal(active_after.json()["standard_weight_by_species"]["SHEEP"]) == Decimal("22")


async def test_standard_weight_change_does_not_require_impact_preview_to_be_meaningful_but_still_needs_it_to_activate(
    client, db: AsyncSession, everhealth_org: Organisation
):
    """§6.4: standard weight is Everhealth-owned and versioned, but not a
    source-of-truth input — it still goes through the same
    create->impact->activate mechanics (the backend gate is uniform), the
    difference is purely that the frontend doesn't force the friction UI in
    front of it. This test proves the mechanism still works for it."""
    headers = await accountant_headers(client, db, everhealth_org, email="bing-refdata3@test.com")

    create_resp = await client.post(
        "/api/v1/reference-data/versions",
        json={
            "effective_from": "2026-09-08T00:00:00Z",
            "note": "adjust SHEEP standard weight",
            "entries": [{"table_key": "standard_weight_by_species", "key1": "SHEEP", "value": "25"}],
        },
        headers=headers,
    )
    version_id = create_resp.json()["id"]

    impact_resp = await client.post(f"/api/v1/reference-data/versions/{version_id}/impact", headers=headers)
    assert impact_resp.status_code == 200
    # Standard weight never reaches AC — no line's dnbp should move.
    assert impact_resp.json()["aggregate_exposure_delta_aud"] == "0"

    activate_resp = await client.post(f"/api/v1/reference-data/versions/{version_id}/activate", headers=headers)
    assert activate_resp.status_code == 200, activate_resp.text


async def test_post_versions_rejects_abattoir_owned_table(client, db: AsyncSession, everhealth_org: Organisation):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-refdata4@test.com")

    resp = await client.post(
        "/api/v1/reference-data/versions",
        json={
            "effective_from": "2026-09-08T00:00:00Z",
            "entries": [{"table_key": "offal_return_ph_by_species", "key1": "SHEEP", "value": "999"}],
        },
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "ABATTOIR_OWNED_TABLE"


async def test_new_species_prices_correctly_end_to_end_through_admin_api(
    client, db: AsyncSession, everhealth_org: Organisation
):
    """§6.9/§19: add HOGGET — registry row, factor, standard weight — with
    no code change or deploy, and confirm compute_bing_dnbp would price it."""
    headers = await accountant_headers(client, db, everhealth_org, email="bing-refdata5@test.com")

    species_resp = await client.post(
        "/api/v1/reference-data/species", json={"code": "hogget", "display_name": "Hogget"}, headers=headers
    )
    assert species_resp.status_code == 201, species_resp.text
    assert species_resp.json()["code"] == "HOGGET"
    assert species_resp.json()["has_dnbp_factor"] is False

    create_resp = await client.post(
        "/api/v1/reference-data/versions",
        json={
            "effective_from": "2026-09-08T00:00:00Z",
            "entries": [
                {"table_key": "dnbp_factor_by_species", "key1": "HOGGET", "value": "0.80"},
                {"table_key": "standard_weight_by_species", "key1": "HOGGET", "value": "20"},
            ],
        },
        headers=headers,
    )
    version_id = create_resp.json()["id"]
    await client.post(f"/api/v1/reference-data/versions/{version_id}/impact", headers=headers)
    activate_resp = await client.post(f"/api/v1/reference-data/versions/{version_id}/activate", headers=headers)
    assert activate_resp.status_code == 200

    species_list = await client.get("/api/v1/reference-data/species", headers=headers)
    hogget = next(row for row in species_list.json() if row["code"] == "HOGGET")
    assert hogget["has_dnbp_factor"] is True
    assert hogget["has_standard_weight"] is True

    active = await client.get("/api/v1/reference-data/active", headers=headers)
    assert Decimal(active.json()["dnbp_factor_by_species"]["HOGGET"]) == Decimal("0.80")


async def test_duplicate_species_code_is_rejected(client, db: AsyncSession, everhealth_org: Organisation):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-refdata6@test.com")

    first = await client.post(
        "/api/v1/reference-data/species", json={"code": "HOGGET", "display_name": "Hogget"}, headers=headers
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/reference-data/species", json={"code": "hogget", "display_name": "Hogget again"}, headers=headers
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "REGISTRY_CODE_EXISTS"
