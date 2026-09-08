"""§7.2 point 11 / §9.8 — abattoir lookup-table drift, wired into the real
ingestion pipeline. domain/ingestion/abattoir_drift.py's pure comparison
already has its own exhaustive unit tests (tests/ingestion/
test_abattoir_drift.py); this exercises the wiring — commit_snapshot
actually persisting rows — plus the read/acknowledge API surface.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from models.organisation import Organisation
from tests.pipeline_helpers import accountant_headers
from tests.test_snapshot_ingestion_e2e import FILE_07_08


async def _upload_and_commit(client, headers: dict) -> dict:
    file_bytes = FILE_07_08.read_bytes()
    xlsx_content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    upload_resp = await client.post(
        "/api/v1/snapshots/upload", files={"file": (FILE_07_08.name, file_bytes, xlsx_content_type)}, headers=headers
    )
    assert upload_resp.status_code == 200, upload_resp.text
    commit_resp = await client.post(
        "/api/v1/snapshots", json={"preview_id": upload_resp.json()["preview_id"]}, headers=headers
    )
    assert commit_resp.status_code == 201, commit_resp.text
    return commit_resp.json()


async def test_identical_resubmission_produces_no_drift(client, db: AsyncSession, everhealth_org: Organisation):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-drift1@test.com")

    await _upload_and_commit(client, headers)  # first ever submission — nothing to diff against
    await _upload_and_commit(client, headers)  # identical resubmission — same abattoir tables

    drift_resp = await client.get("/api/v1/reference-data/drift", headers=headers)
    assert drift_resp.status_code == 200
    assert drift_resp.json() == []


async def test_abattoir_tables_endpoint_reflects_latest_snapshot(client, db: AsyncSession, everhealth_org: Organisation):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-drift2@test.com")
    snapshot = await _upload_and_commit(client, headers)

    resp = await client.get("/api/v1/reference-data/abattoir", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["snapshot_id"] == snapshot["id"]
    assert body["skin_return_ph_by_species"]["GOAT"] == "0"  # the abattoir's table, not the hand-set 0.5 override


async def test_acknowledge_unknown_drift_is_not_found(client, db: AsyncSession, everhealth_org: Organisation):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-drift3@test.com")
    resp = await client.post(
        "/api/v1/reference-data/drift/00000000-0000-0000-0000-000000000000/acknowledge", headers=headers
    )
    assert resp.status_code == 404
