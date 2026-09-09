"""§7.3's removed_lines, persisted and acknowledgeable rather than shown
once in the upload preview and discarded. Uses the real 07-08 workbook,
lightly mutated in-memory to force one specific contract to genuinely
disappear (not move to LOADED) between two commits — see
_mutate_one_line_identity's docstring for why a single in-place cell edit
is used instead of deleting a row.
"""

import io

import openpyxl
from sqlalchemy.ext.asyncio import AsyncSession

from models.organisation import Organisation
from tests.pipeline_helpers import FILE_07_08, XLSX_CONTENT_TYPE, accountant_headers


def _mutate_one_line_identity(row: int, new_species: str) -> bytes:
    """Deleting a row shifts every row below it, which also shifts the
    LOADED section further down the same sheet — confirmed empirically to
    silently drop unrelated rows out of the parser's detected section
    bounds. Editing one cell's value in place changes that row's identity
    key (contract_no, species, product_type, incoterm) with zero effect on
    any other row's position, which is what actually isolates the test to
    a single genuine removal."""
    wb = openpyxl.load_workbook(FILE_07_08)
    ws = wb["Profitability Analysis"]
    ws.cell(row=row, column=4, value=new_species)  # column D = species/"Type"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _upload_and_commit(client, headers: dict, file_bytes: bytes) -> dict:
    upload_resp = await client.post(
        "/api/v1/snapshots/upload", files={"file": (FILE_07_08.name, file_bytes, XLSX_CONTENT_TYPE)}, headers=headers
    )
    assert upload_resp.status_code == 200, upload_resp.text
    commit_resp = await client.post(
        "/api/v1/snapshots", json={"preview_id": upload_resp.json()["preview_id"]}, headers=headers
    )
    assert commit_resp.status_code == 201, commit_resp.text
    return commit_resp.json()


async def test_a_contract_that_disappears_is_recorded_and_acknowledgeable(
    client, db: AsyncSession, everhealth_org: Organisation
):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-removals@test.com")

    # Snapshot 1: the real file, untouched — CED18650/SHEEP is a genuine
    # active line in it.
    await _upload_and_commit(client, headers, FILE_07_08.read_bytes())

    # Snapshot 2: identical except row 8's species is renamed — from the
    # diff's perspective, (CED18650, SHEEP, ...) simply vanished.
    mutated_bytes = _mutate_one_line_identity(row=8, new_species="ZZZTESTSPECIES")
    await _upload_and_commit(client, headers, mutated_bytes)

    list_resp = await client.get("/api/v1/order-line-removals", params={"unacknowledged": True}, headers=headers)
    assert list_resp.status_code == 200, list_resp.text
    removals = list_resp.json()
    assert len(removals) == 1
    removal = removals[0]
    assert removal["contract_no"] == "CED18650"
    assert removal["species"] == "SHEEP"  # the line's last known identity, not the mutated one
    assert removal["customer_name"] == "SHANGHAI NEW SOURCE"
    assert removal["amount_aud"] is not None
    assert removal["acknowledged_at"] is None

    ack_resp = await client.post(
        f"/api/v1/order-line-removals/{removal['id']}/acknowledge",
        json={"reason": "Customer cancelled this contract"},
        headers=headers,
    )
    assert ack_resp.status_code == 200, ack_resp.text
    acknowledged = ack_resp.json()
    assert acknowledged["acknowledged_at"] is not None
    assert acknowledged["reason"] == "Customer cancelled this contract"

    # Acknowledged rows drop out of the unacknowledged-only view.
    list_after = await client.get("/api/v1/order-line-removals", params={"unacknowledged": True}, headers=headers)
    assert list_after.json() == []

    # But remain visible in the full list.
    list_all = await client.get("/api/v1/order-line-removals", headers=headers)
    assert len(list_all.json()) == 1


async def test_acknowledging_an_unknown_removal_is_404(client, db: AsyncSession, everhealth_org: Organisation):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-removals2@test.com")
    resp = await client.post(
        "/api/v1/order-line-removals/00000000-0000-0000-0000-000000000000/acknowledge",
        json={},
        headers=headers,
    )
    assert resp.status_code == 404
