"""§18 demo bar, part one: "Bing receives a real file and produces the
full X-AF block without touching Excel." Exercises the actual HTTP surface
end to end — multipart upload -> preview -> commit -> calculate -> read
back the isolated AC proof for a real line — against
`Active Purchase Orders 07-08-2026 (WORKING).xlsx`, not a synthetic
fixture.
"""

import hashlib
import uuid
from decimal import Decimal
from pathlib import Path

import pyotp
from sqlalchemy.ext.asyncio import AsyncSession

from models.enums import Role
from models.organisation import Organisation
from repositories import order_workings as order_workings_repo
from tests.conftest import DEV_PASSWORD, make_active_user

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
FILE_07_08 = FIXTURES_DIR / "Active Purchase Orders 07-08-2026 (WORKING).xlsx"


async def _accountant_headers(client, db: AsyncSession, org: Organisation) -> dict:
    _user, secret = await make_active_user(db, org=org, email="bing-e2e@test.com", role=Role.ACCOUNTANT, with_mfa=True)
    code = pyotp.TOTP(secret).now()
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "bing-e2e@test.com", "password": DEV_PASSWORD, "totp_code": code}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_full_ingestion_pipeline_against_real_workbook(client, db: AsyncSession, everhealth_org: Organisation):
    headers = await _accountant_headers(client, db, everhealth_org)
    file_bytes = FILE_07_08.read_bytes()

    xlsx_content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    upload_resp = await client.post(
        "/api/v1/snapshots/upload",
        files={"file": (FILE_07_08.name, file_bytes, xlsx_content_type)},
        headers=headers,
    )
    assert upload_resp.status_code == 200, upload_resp.text
    preview = upload_resp.json()
    assert preview["active_count"] == 27
    assert preview["loaded_count"] == 16
    assert preview["diff"]["summary"]["new_count"] == 43  # first snapshot for this org: everything is "new"

    commit_resp = await client.post(
        "/api/v1/snapshots", json={"preview_id": preview["preview_id"]}, headers=headers
    )
    assert commit_resp.status_code == 201, commit_resp.text
    snapshot = commit_resp.json()
    assert snapshot["source_sha256"] == hashlib.sha256(file_bytes).hexdigest()
    assert snapshot["status"] == "PARSED"

    calc_resp = await client.post(f"/api/v1/snapshots/{snapshot['id']}/calculate", headers=headers)
    assert calc_resp.status_code == 200, calc_resp.text
    summary = calc_resp.json()
    assert summary["active_lines_computed"] == 27
    assert summary["blocked_issues"] == 0  # neither supplied file trips a BLOCK on its active lines

    lines_resp = await client.get(
        f"/api/v1/snapshots/{snapshot['id']}/lines", params={"lifecycle": "ACTIVE"}, headers=headers
    )
    assert lines_resp.status_code == 200
    ced18650 = next(line for line in lines_resp.json() if line["contract_no"] == "CED18650")

    proof_resp = await client.get(f"/api/v1/order-lines/{ced18650['id']}/dnbp-proof", headers=headers)
    assert proof_resp.status_code == 200, proof_resp.text
    proof = proof_resp.json()
    # §5.4's worked example, verbatim.
    assert abs(Decimal(proof["bing_dnbp"]) - Decimal("8.171289855072464")) < Decimal("1E-9")
    assert Decimal(proof["dnbp_factor"]) == Decimal("0.83")

    workings_resp = await client.get(f"/api/v1/order-lines/{ced18650['id']}/workings", headers=headers)
    assert workings_resp.status_code == 200
    workings = workings_resp.json()
    assert Decimal(workings["diff_vs_benchmark"]) is not None  # AE — computed, not a source of truth

    goat_line = next(line for line in lines_resp.json() if line["species"] == "GOAT")
    assert goat_line["value_sources"]["skin_return_ph"] == "HAND_SET"
    assert Decimal(goat_line["skin_return_ph"]) == Decimal("0.5")

    issues_resp = await client.get(f"/api/v1/snapshots/{snapshot['id']}/issues", headers=headers)
    assert issues_resp.status_code == 200
    codes = {issue["code"] for issue in issues_resp.json()}
    assert "HAND_SET_VALUE" in codes  # the GOAT skin-return 0.5 override, surfaced not corrected
    assert "NO_DNBP_FACTOR" not in codes  # active MUTTON never appears in this file (D1)


async def test_uploading_the_same_file_again_is_flagged_but_still_allowed(
    client, db: AsyncSession, everhealth_org: Organisation
):
    headers = await _accountant_headers(client, db, everhealth_org)
    file_bytes = FILE_07_08.read_bytes()
    xlsx_content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    first_upload = await client.post(
        "/api/v1/snapshots/upload",
        files={"file": (FILE_07_08.name, file_bytes, xlsx_content_type)},
        headers=headers,
    )
    assert first_upload.status_code == 200, first_upload.text
    assert first_upload.json()["duplicate_of_current"] is None  # nothing to be a duplicate of yet
    commit_resp = await client.post(
        "/api/v1/snapshots", json={"preview_id": first_upload.json()["preview_id"]}, headers=headers
    )
    assert commit_resp.status_code == 201, commit_resp.text
    committed_snapshot_id = commit_resp.json()["id"]

    # A re-submit of the byte-identical workbook is a real, supported case
    # (§7.3 — never blocked, PRD explicitly allows resubmission), but the
    # human reviewing the preview should be told it looks like a duplicate
    # of what's already current, since §11.2 lets either Owner or
    # Accountant upload and one may not know the other already did.
    second_upload = await client.post(
        "/api/v1/snapshots/upload",
        files={"file": (FILE_07_08.name, file_bytes, xlsx_content_type)},
        headers=headers,
    )
    assert second_upload.status_code == 200, second_upload.text
    duplicate_notice = second_upload.json()["duplicate_of_current"]
    assert duplicate_notice is not None
    assert duplicate_notice["snapshot_id"] == committed_snapshot_id
    assert duplicate_notice["uploaded_by_email"] == "bing-e2e@test.com"

    # Confirming anyway still succeeds and creates a genuinely new snapshot.
    second_commit = await client.post(
        "/api/v1/snapshots", json={"preview_id": second_upload.json()["preview_id"]}, headers=headers
    )
    assert second_commit.status_code == 201, second_commit.text
    assert second_commit.json()["id"] != committed_snapshot_id


async def test_recalculating_an_already_calculated_snapshot_stays_computable(
    client, db: AsyncSession, everhealth_org: Organisation
):
    """Regression: repositories/order_workings.py's upsert() used to copy
    every column — including the server-managed computed_at/updated_at —
    from the transient, never-flushed OrderWorkings built each calculate
    onto the existing row. That's a no-op on a line's first calculate
    (INSERT, server_default fills computed_at/updated_at in) but nulls both
    out on any recalculate (UPDATE with an explicit NULL), tripping
    computed_at's NOT NULL constraint. A read in between (dnbp-proof)
    mirrors the exact request sequence that hit this in production."""
    headers = await _accountant_headers(client, db, everhealth_org)
    file_bytes = FILE_07_08.read_bytes()
    xlsx_content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    upload_resp = await client.post(
        "/api/v1/snapshots/upload",
        files={"file": (FILE_07_08.name, file_bytes, xlsx_content_type)},
        headers=headers,
    )
    assert upload_resp.status_code == 200, upload_resp.text
    preview = upload_resp.json()

    commit_resp = await client.post(
        "/api/v1/snapshots", json={"preview_id": preview["preview_id"]}, headers=headers
    )
    assert commit_resp.status_code == 201, commit_resp.text
    snapshot = commit_resp.json()

    first_calc = await client.post(f"/api/v1/snapshots/{snapshot['id']}/calculate", headers=headers)
    assert first_calc.status_code == 200, first_calc.text

    lines_resp = await client.get(
        f"/api/v1/snapshots/{snapshot['id']}/lines", params={"lifecycle": "ACTIVE"}, headers=headers
    )
    ced18650 = next(line for line in lines_resp.json() if line["contract_no"] == "CED18650")

    first_workings = (await client.get(f"/api/v1/order-lines/{ced18650['id']}/workings", headers=headers)).json()
    assert first_workings["computed_at"] is not None

    proof_resp = await client.get(f"/api/v1/order-lines/{ced18650['id']}/dnbp-proof", headers=headers)
    assert proof_resp.status_code == 200, proof_resp.text

    second_calc = await client.post(f"/api/v1/snapshots/{snapshot['id']}/calculate", headers=headers)
    assert second_calc.status_code == 200, second_calc.text  # used to 500: NotNullViolationError on computed_at

    second_workings = (await client.get(f"/api/v1/order-lines/{ced18650['id']}/workings", headers=headers)).json()
    assert second_workings["computed_at"] is not None
    assert second_workings["computed_at"] != first_workings["computed_at"]  # recompute actually advanced it

    workings_row = await order_workings_repo.get_by_order_line_id(db, uuid.UUID(ced18650["id"]))
    assert workings_row.updated_at is not None


async def test_acknowledged_issue_carries_forward_to_an_unchanged_line_in_the_next_snapshot(
    client, db: AsyncSession, everhealth_org: Organisation
):
    """The design flaw this fixes: services/ingestion_service.py's
    commit_snapshot creates a brand-new OrderLine row for every line in the
    abattoir's cumulative file, every day — including ones that haven't
    changed at all — so an acknowledged WARN/CORRECTION issue used to come
    back unacknowledged the very next snapshot, forcing the business user to
    re-acknowledge the exact same concern on the exact same, unchanged order
    every single day it kept reappearing in the file. Re-submitting the
    byte-identical workbook (guaranteeing every line's content is unchanged)
    is the sharpest test of the fix: the GOAT line's HAND_SET_VALUE warning,
    acknowledged once against the first snapshot, must come back already
    acknowledged — and flagged as carried forward, not freshly acked — on
    the second."""
    headers = await _accountant_headers(client, db, everhealth_org)
    file_bytes = FILE_07_08.read_bytes()
    xlsx_content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    async def _upload_commit_calculate() -> dict:
        upload_resp = await client.post(
            "/api/v1/snapshots/upload",
            files={"file": (FILE_07_08.name, file_bytes, xlsx_content_type)},
            headers=headers,
        )
        assert upload_resp.status_code == 200, upload_resp.text
        commit_resp = await client.post(
            "/api/v1/snapshots", json={"preview_id": upload_resp.json()["preview_id"]}, headers=headers
        )
        assert commit_resp.status_code == 201, commit_resp.text
        snapshot = commit_resp.json()
        calc_resp = await client.post(f"/api/v1/snapshots/{snapshot['id']}/calculate", headers=headers)
        assert calc_resp.status_code == 200, calc_resp.text
        return snapshot

    async def _goat_hand_set_issue(snapshot_id: str) -> dict:
        lines_resp = await client.get(
            f"/api/v1/snapshots/{snapshot_id}/lines", params={"lifecycle": "ACTIVE"}, headers=headers
        )
        goat_line = next(line for line in lines_resp.json() if line["species"] == "GOAT")
        issues_resp = await client.get(f"/api/v1/snapshots/{snapshot_id}/issues", headers=headers)
        return next(
            issue
            for issue in issues_resp.json()
            if issue["order_line_id"] == goat_line["id"] and issue["code"] == "HAND_SET_VALUE"
        )

    first_snapshot = await _upload_commit_calculate()
    first_issue = await _goat_hand_set_issue(first_snapshot["id"])
    assert first_issue["acknowledged_at"] is None
    assert first_issue["carried_forward"] is False

    ack_resp = await client.post(
        f"/api/v1/snapshots/{first_snapshot['id']}/issues/{first_issue['id']}/acknowledge", headers=headers
    )
    assert ack_resp.status_code == 200, ack_resp.text
    acked = ack_resp.json()
    assert acked["acknowledged_at"] is not None
    assert acked["carried_forward"] is False  # a fresh, manual acknowledgment — not a carry-forward

    # A second, byte-identical submission — the abattoir's cumulative file
    # resubmitted unchanged (§7.3 explicitly allows and expects this).
    second_snapshot = await _upload_commit_calculate()
    assert second_snapshot["id"] != first_snapshot["id"]

    second_issue = await _goat_hand_set_issue(second_snapshot["id"])
    assert second_issue["id"] != first_issue["id"]  # a genuinely new row, on a genuinely new OrderLine
    assert second_issue["acknowledged_at"] is not None  # ...but carrying the same human decision forward
    assert second_issue["acknowledged_by"] == acked["acknowledged_by"]
    assert second_issue["carried_forward"] is True

    # And the publish gate agrees: this specific, previously-acknowledged
    # concern never blocks the second snapshot — other genuinely
    # unacknowledged issues on other lines in this fixture still correctly
    # do, proving the carry-forward is scoped to this exact issue, not a
    # blanket bypass of the gate.
    publish_resp = await client.post(
        "/api/v1/publications", json={"snapshot_id": second_snapshot["id"]}, headers=headers
    )
    assert publish_resp.status_code == 409, publish_resp.text
    assert second_issue["id"] not in publish_resp.json()["error"]["details"]["unacknowledged_issue_ids"]
