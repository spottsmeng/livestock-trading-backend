"""Two guard exceptions that were reaching the API boundary as bare
Exceptions instead of AppError — a raw, non-JSON 500 with no error code
the frontend could act on. Both are meant to be reachable (their own
docstrings/comments say so), so both need a real, testable envelope
rather than "should never happen" being an excuse to skip it.
"""

import io

import openpyxl
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.organisation import Organisation
from models.reference_data import ReferenceDataVersion
from tests.pipeline_helpers import XLSX_CONTENT_TYPE, accountant_headers


async def test_no_active_reference_data_returns_a_clean_error_envelope(
    client, db: AsyncSession, everhealth_org: Organisation
):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-noref@test.com")

    # The autouse _seed_reference_data fixture always activates one version
    # for every test — deactivate it here to reproduce the exact state that
    # used to crash with a raw, unenveloped 500.
    await db.execute(update(ReferenceDataVersion).values(is_active=False))
    await db.commit()

    resp = await client.get("/api/v1/reference-data/active", headers=headers)
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "NO_ACTIVE_REFERENCE_DATA"


@pytest.mark.parametrize("route", ["/api/v1/reference-data/active", "/api/v1/reference-data/species"])
async def test_still_ok_when_reference_data_is_active(client, db: AsyncSession, everhealth_org: Organisation, route):
    # Sanity check the fix didn't break the normal path — the seeded
    # version is still active here (this test doesn't touch it).
    headers = await accountant_headers(client, db, everhealth_org, email="bing-refok@test.com")
    resp = await client.get(route, headers=headers)
    assert resp.status_code == 200


async def test_undetectable_layout_returns_a_clean_error_envelope(
    client, db: AsyncSession, everhealth_org: Organisation
):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-badlayout@test.com")

    # A workbook with no ACTIVE ORDERS marker anywhere — used to bubble up
    # as domain.ingestion.layout.LayoutDetectionError, an unenveloped 500.
    wb = openpyxl.Workbook()
    wb.active["A1"] = "just some unrelated data"
    buf = io.BytesIO()
    wb.save(buf)

    resp = await client.post(
        "/api/v1/snapshots/upload",
        files={"file": ("garbage.xlsx", buf.getvalue(), XLSX_CONTENT_TYPE)},
        headers=headers,
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "LAYOUT_DETECTION_FAILED"
