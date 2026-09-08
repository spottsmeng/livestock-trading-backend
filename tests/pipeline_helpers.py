"""Shared helpers for Phase 3 tests that need a real, calculated, publishable
snapshot — built from the actual 07-08 workbook (not a synthetic fixture),
same discipline as tests/test_snapshot_ingestion_e2e.py.
"""

from pathlib import Path

import pyotp
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.enums import Role
from models.organisation import Organisation
from tests.conftest import DEV_PASSWORD, make_active_user

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
FILE_07_08 = FIXTURES_DIR / "Active Purchase Orders 07-08-2026 (WORKING).xlsx"
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def accountant_headers(client: AsyncClient, db: AsyncSession, org: Organisation, *, email: str) -> dict:
    _user, secret = await make_active_user(db, org=org, email=email, role=Role.ACCOUNTANT, with_mfa=True)
    code = pyotp.TOTP(secret).now()
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": DEV_PASSWORD, "totp_code": code})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def owner_headers(client: AsyncClient, db: AsyncSession, org: Organisation, *, email: str) -> dict:
    _user, secret = await make_active_user(db, org=org, email=email, role=Role.OWNER, with_mfa=True)
    code = pyotp.TOTP(secret).now()
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": DEV_PASSWORD, "totp_code": code})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def buyer_headers(client: AsyncClient, db: AsyncSession, org: Organisation, *, email: str) -> dict:
    await make_active_user(db, org=org, email=email, role=Role.BUYER)
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": DEV_PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def build_calculated_snapshot(client: AsyncClient, headers: dict) -> dict:
    """Upload -> commit -> calculate the real 07-08 file. Returns the
    committed snapshot (PARSED->CALCULATED)."""
    file_bytes = FILE_07_08.read_bytes()
    upload_resp = await client.post(
        "/api/v1/snapshots/upload", files={"file": (FILE_07_08.name, file_bytes, XLSX_CONTENT_TYPE)}, headers=headers
    )
    assert upload_resp.status_code == 200, upload_resp.text
    preview = upload_resp.json()

    commit_resp = await client.post("/api/v1/snapshots", json={"preview_id": preview["preview_id"]}, headers=headers)
    assert commit_resp.status_code == 201, commit_resp.text
    snapshot = commit_resp.json()

    calc_resp = await client.post(f"/api/v1/snapshots/{snapshot['id']}/calculate", headers=headers)
    assert calc_resp.status_code == 200, calc_resp.text

    return snapshot


async def acknowledge_all_active_issues(client: AsyncClient, snapshot_id: str, headers: dict) -> None:
    """§5.7's publication gate requires every WARN/CORRECTION issue on an
    active line to be individually acknowledged — this walks all of them so
    a test can get to a clean `POST /publications` without hand-picking
    which issues the real 07-08 file happens to raise."""
    lines_resp = await client.get(
        f"/api/v1/snapshots/{snapshot_id}/lines", params={"lifecycle": "ACTIVE"}, headers=headers
    )
    active_line_ids = {line["id"] for line in lines_resp.json()}

    issues_resp = await client.get(f"/api/v1/snapshots/{snapshot_id}/issues", headers=headers)
    for issue in issues_resp.json():
        if issue["order_line_id"] in active_line_ids and issue["severity"] in ("WARN", "CORRECTION"):
            ack_resp = await client.post(
                f"/api/v1/snapshots/{snapshot_id}/issues/{issue['id']}/acknowledge", headers=headers
            )
            assert ack_resp.status_code == 200, ack_resp.text


async def build_publishable_snapshot(client: AsyncClient, headers: dict) -> dict:
    snapshot = await build_calculated_snapshot(client, headers)
    await acknowledge_all_active_issues(client, snapshot["id"], headers)
    return snapshot
