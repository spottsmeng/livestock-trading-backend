"""§9.6 `GET /buy-instructions/{id}/export` — smoke tests that both formats
actually render valid files from a real generated instruction. Byte-level
layout fidelity isn't practical to assert in a unit test, so this checks
what a test reasonably can: correct content-type/magic-bytes, and (for
XLSX, which is easy to read back) that the real header/summary figures the
PRD calls out actually appear in the workbook.
"""

from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from models.organisation import Organisation
from tests.pipeline_helpers import accountant_headers, build_publishable_snapshot


async def _generate(client, headers, everhealth_org) -> dict:
    snapshot = await build_publishable_snapshot(client, headers)
    publish_resp = await client.post("/api/v1/publications", json={"snapshot_id": snapshot["id"]}, headers=headers)
    publication = publish_resp.json()
    gen_resp = await client.post(
        "/api/v1/buy-instructions",
        json={"snapshot_id": snapshot["id"], "publication_id": publication["id"]},
        headers=headers,
    )
    assert gen_resp.status_code == 201, gen_resp.text
    return gen_resp.json()


async def test_export_xlsx_reproduces_header_and_line_items(client, db: AsyncSession, everhealth_org: Organisation):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-export1@test.com")
    instruction = await _generate(client, headers, everhealth_org)

    resp = await client.get(
        f"/api/v1/buy-instructions/{instruction['id']}/export", params={"format": "xlsx"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml")

    wb = load_workbook(BytesIO(resp.content))
    ws = wb.active
    assert ws["B2"].value == "ACTIVE ORDER PURCHASE INSTRUCTION"
    header_row = [ws.cell(row=3, column=c).value for c in range(1, 9)]
    assert header_row[1] == "Order number"
    assert header_row[5] == "Do not buy price"

    contract_numbers = {ws.cell(row=r, column=2).value for r in range(4, 4 + len(instruction["lines"]))}
    assert contract_numbers == {line["contract_no"] for line in instruction["lines"]}


async def test_export_pdf_returns_a_valid_pdf(client, db: AsyncSession, everhealth_org: Organisation):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-export2@test.com")
    instruction = await _generate(client, headers, everhealth_org)

    resp = await client.get(
        f"/api/v1/buy-instructions/{instruction['id']}/export", params={"format": "pdf"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-")
