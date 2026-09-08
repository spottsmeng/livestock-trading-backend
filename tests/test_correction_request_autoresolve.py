"""§9.3, §18 demo bar — "a correction request raised on a missing cost
figure, and auto-resolved once a later snapshot supplies the missing
value." Exercises the real API surface: raise via POST .../correction-
requests, then POST /snapshots/{id}/calculate on a second snapshot that
supplies the previously-missing value, and check the request transitions
OPEN -> RESOLVED with resolved_by_snapshot_id set.
"""

import uuid
from decimal import Decimal

import pyotp
from sqlalchemy.ext.asyncio import AsyncSession

from models.enums import Incoterm, Role, SnapshotStatus
from models.order_line import OrderLine
from models.order_snapshot import OrderSnapshot
from models.organisation import Organisation
from tests.conftest import DEV_PASSWORD, make_active_user

_EMPTY_ABATTOIR_TABLES = {
    "cif_buffer_per_kg": "0.30",
    "pack_cost_by_product_type": {},
    "offal_return_ph_by_species": {},
    "skin_return_ph_by_species": {},
    "fixed_cost_per_head_active": "40",
    "fixed_cost_per_head_loaded": "34",
}


async def _accountant_token(client, db: AsyncSession, org: Organisation) -> tuple[str, uuid.UUID]:
    user, secret = await make_active_user(db, org=org, email="bing@test.com", role=Role.ACCOUNTANT, with_mfa=True)
    code = pyotp.TOTP(secret).now()
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "bing@test.com", "password": DEV_PASSWORD, "totp_code": code}
    )
    return resp.json()["access_token"], user.id


async def _make_snapshot(db: AsyncSession, *, org: Organisation, uploaded_by: uuid.UUID, sha: str) -> OrderSnapshot:
    snapshot = OrderSnapshot(
        org_id=org.id,
        uploaded_by=uploaded_by,
        source_filename="test.xlsx",
        source_sha256=sha,
        object_storage_key=f"snapshots/{sha}/test.xlsx",
        detected_layout={"strategy": "single_match"},
        abattoir_reference_tables=_EMPTY_ABATTOIR_TABLES,
        parser_version="test",
        status=SnapshotStatus.PARSED,
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


async def _make_line(
    db: AsyncSession, *, snapshot: OrderSnapshot, expected_livestock_cost_per_kg: Decimal | None
) -> OrderLine:
    line = OrderLine(
        snapshot_id=snapshot.id,
        line_no=1,
        lifecycle="ACTIVE",
        contract_no="CED-TEST",
        species="SHEEP",
        product_type="6_WAY",
        incoterm=Incoterm.CIF,
        avg_price_aud=Decimal("10.00"),
        expected_livestock_cost_per_kg=expected_livestock_cost_per_kg,
        pack_cost_ph=Decimal("4"),
        offal_return_ph=Decimal("8"),
        skin_return_ph=Decimal("10"),
        avg_weight_kg=Decimal("22"),
        value_sources={},
    )
    db.add(line)
    await db.flush()
    return line


async def test_correction_request_raised_then_auto_resolved_by_later_snapshot(
    client, db: AsyncSession, everhealth_org: Organisation
):
    token, user_id = await _accountant_token(client, db, everhealth_org)
    headers = {"Authorization": f"Bearer {token}"}

    snapshot_1 = await _make_snapshot(db, org=everhealth_org, uploaded_by=user_id, sha="sha-1")
    line_1 = await _make_line(db, snapshot=snapshot_1, expected_livestock_cost_per_kg=None)
    await db.commit()

    raise_resp = await client.post(
        f"/api/v1/order-lines/{line_1.id}/correction-requests",
        json={
            "column_ref": "expected_livestock_cost_per_kg",
            "issue_code": "MISSING_LIVESTOCK_COST",
            "detail": "Livestock cost missing on initial submission",
        },
        headers=headers,
    )
    assert raise_resp.status_code == 201, raise_resp.text
    request_id = raise_resp.json()["id"]
    assert raise_resp.json()["status"] == "OPEN"

    snapshot_2 = await _make_snapshot(db, org=everhealth_org, uploaded_by=user_id, sha="sha-2")
    await _make_line(db, snapshot=snapshot_2, expected_livestock_cost_per_kg=Decimal("8.4"))
    await db.commit()

    calc_resp = await client.post(f"/api/v1/snapshots/{snapshot_2.id}/calculate", headers=headers)
    assert calc_resp.status_code == 200, calc_resp.text
    assert calc_resp.json()["correction_requests_auto_resolved"] == 1

    list_resp = await client.get("/api/v1/correction-requests", params={"status": "RESOLVED"}, headers=headers)
    resolved_ids = {r["id"] for r in list_resp.json()}
    assert request_id in resolved_ids
    resolved = next(r for r in list_resp.json() if r["id"] == request_id)
    assert resolved["resolved_by_snapshot_id"] == str(snapshot_2.id)

    open_resp = await client.get("/api/v1/correction-requests", params={"status": "OPEN"}, headers=headers)
    assert request_id not in {r["id"] for r in open_resp.json()}
