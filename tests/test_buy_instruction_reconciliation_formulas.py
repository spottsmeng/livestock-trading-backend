"""Phase 4, non-negotiable #7 — cross-checks the reconciliation/summary
formulas (A/B/A-B/C/D/C-D, §13.1) against the real v3 sample's own worked
numbers (`v3 Buy instruction _1108 (SAMPLE WORKING).xlsx`, rows 4-23):
CED18655/CED18653 as the two instruction lines (Ordered SCHW 47000),
Bendigo/Ballarat/Wagga reconciled under one instruction (Bought SCHW
4195.82, Actual Cost 29681.76).

This constructs the DB rows directly (not through the full upload/ingest
pipeline — `compute_reconciliation` only needs `buy_instruction_lines` and
`buy_entries`, and this is the one place in the codebase with a real,
numeric ground truth to verify formula correctness against, same spirit as
Phase 1's engine golden-vector tests) rather than reproducing the sample's
own [D6] error: `expected_livestock_cost` here is computed AC-based (the
resolved, correct formula), so — unlike the sample's own row 22 total of
394800 — this test's Expected Cost (C) deliberately does NOT reproduce that
number. See phase04-instructions.txt's explicit instruction not to
reproduce the sample's `8.4`-based figure.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from core.trading_calendar import trading_week_bounds
from domain.engine.workings import Lifecycle
from models.buy_entry import BuyEntry
from models.buy_instruction import BuyInstruction, BuyInstructionLine
from models.dnbp_publication import DnbpPublication
from models.enums import BuyInstructionStatus, Role, SnapshotStatus
from models.order_line import OrderLine
from models.order_snapshot import OrderSnapshot
from models.organisation import Organisation
from services import buy_instruction_service
from tests.conftest import make_active_user

MONEY = lambda v: Decimal(str(v))  # noqa: E731 — local shorthand, test-only


async def test_reconciliation_summary_matches_real_sample(db: AsyncSession, everhealth_org: Organisation):
    user, _secret = await make_active_user(
        db, org=everhealth_org, email="bing-recon@test.com", role=Role.ACCOUNTANT
    )
    buyer, _secret2 = await make_active_user(db, org=everhealth_org, email="buyer-recon@test.com", role=Role.BUYER)

    snapshot = OrderSnapshot(
        org_id=everhealth_org.id,
        uploaded_by=user.id,
        source_filename="test.xlsx",
        source_sha256="deadbeef",
        object_storage_key="test-key",
        detected_layout={},
        abattoir_reference_tables={},
        parser_version="test",
        status=SnapshotStatus.CALCULATED,
    )
    db.add(snapshot)
    await db.flush()

    ced18655 = OrderLine(
        snapshot_id=snapshot.id, line_no=1, lifecycle=Lifecycle.ACTIVE, contract_no="CED18655", species="SHEEP"
    )
    ced18653 = OrderLine(
        snapshot_id=snapshot.id, line_no=2, lifecycle=Lifecycle.ACTIVE, contract_no="CED18653", species="SHEEP"
    )
    db.add_all([ced18655, ced18653])
    await db.flush()

    publication = DnbpPublication(
        org_id=everhealth_org.id, snapshot_id=snapshot.id, published_by=user.id, engine_version="test"
    )
    db.add(publication)
    await db.flush()

    instruction = BuyInstruction(
        org_id=everhealth_org.id,
        instruction_no="BI-TEST",
        trade_date=date(2026, 8, 12),
        snapshot_id=snapshot.id,
        publication_id=publication.id,
        prepared_by=user.id,
        status=BuyInstructionStatus.ISSUED,
    )
    db.add(instruction)
    await db.flush()

    # §5.4/real workbook: CED18655 G=10.072463768115943, CED18653
    # G=9.710144927536232, both SHEEP (cif_buffer=0.30, factor=0.83).
    dnbp_18655 = (MONEY("10.072463768115943") - MONEY("0.30")) * MONEY("0.83")
    dnbp_18653 = (MONEY("9.710144927536232") - MONEY("0.30")) * MONEY("0.83")

    line_18655 = BuyInstructionLine(
        instruction_id=instruction.id,
        order_line_id=ced18655.id,
        seq=1,
        contract_no="CED18655",
        species="SHEEP",
        schw_kg=MONEY("24999.999999999996"),
        expected_heads=MONEY("1136.3636363636363"),
        weight_requirement_kg=MONEY("22"),
        dnbp_per_kg=dnbp_18655,
        peters_expectation=MONEY("8.4"),
        expected_livestock_cost=dnbp_18655 * MONEY("22") * MONEY("1136.3636363636363"),
    )
    line_18653 = BuyInstructionLine(
        instruction_id=instruction.id,
        order_line_id=ced18653.id,
        seq=2,
        contract_no="CED18653",
        species="SHEEP",
        schw_kg=MONEY("22000"),
        expected_heads=MONEY("785.7142857142857"),
        weight_requirement_kg=MONEY("28"),
        dnbp_per_kg=dnbp_18653,
        peters_expectation=MONEY("8.4"),
        expected_livestock_cost=dnbp_18653 * MONEY("28") * MONEY("785.7142857142857"),
    )
    db.add_all([line_18655, line_18653])
    await db.flush()

    week_start, week_end = trading_week_bounds(instruction.trade_date)

    # Reproduce the sample's own Bendigo/Ballarat/Wagga breakdown (rows
    # 10-12) as single synthetic entries per saleyard — one entry whose
    # head_count/weight_kg/price_per_head are chosen so schw and actual
    # cost land on the sample's own worked totals.
    saleyard_rows = [
        ("Bendigo", 64, MONEY("1390.72") / 64, MONEY("14875.83") / 64, week_start),
        ("Ballarat", 32, MONEY("977.92") / 32, MONEY("8923.06") / 32, week_start + (week_end - week_start) // 3),
        ("Wagga", 79, MONEY("1827.18") / 79, MONEY("5882.87") / 79, week_end),
    ]
    for saleyard, heads, weight_per_head, price_per_head, trade_date in saleyard_rows:
        db.add(
            BuyEntry(
                buyer_id=buyer.id,
                saleyard=saleyard,
                trade_date=trade_date,
                species="SHEEP",
                head_count=heads,
                price_per_head=price_per_head,
                weight_kg=weight_per_head,
                implied_price_per_kg=price_per_head / weight_per_head,
                dnbp_at_entry=dnbp_18655,
                variance_per_kg=MONEY("0"),
                is_breach=False,
                client_uuid=uuid.uuid4(),
                client_created_at=datetime.now(UTC),
            )
        )
    await db.commit()

    rows, summary = await buy_instruction_service.compute_reconciliation(db, instruction)

    # A — Ordered SCHW (sample row 18: 47000)
    assert round(summary.ordered_schw, 2) == MONEY("47000.00")
    # B — Bought SCHW (sample row 19: 4195.82)
    assert round(summary.bought_schw, 2) == MONEY("4195.82")
    # A - B (sample row 20: 42804.18)
    assert round(summary.surplus_shortfall_schw, 2) == MONEY("42804.18")
    # D — Actual Cost (sample row 21: 29681.76)
    assert round(summary.actual_cost, 2) == MONEY("29681.76")
    # Actual Heads (sample row 16: 175) / Expected Heads (row 17: 1922.08)
    assert summary.actual_heads == 175
    assert round(summary.expected_heads, 2) == MONEY("1922.08")

    # C — Expected Cost, computed AC-based (the resolved [D6] formula).
    # The sample's own row 22 (394800) is the documented ERROR — it used
    # Peter's L (8.4) instead of AC. Confirm we do NOT reproduce it, and
    # that C is exactly the sum of the two lines' own (correct) figures.
    expected_c = line_18655.expected_livestock_cost + line_18653.expected_livestock_cost
    assert summary.expected_cost == expected_c
    assert round(summary.expected_cost, 2) != MONEY("394800.00")

    # C - D — derived, not the sample's own (bug-tainted) 365118.24.
    assert summary.cost_variance == summary.expected_cost - summary.actual_cost

    # Reconciliation grouped dynamically by saleyard — three rows, not a
    # hard-coded fixed set of saleyard columns.
    assert {r.saleyard for r in rows} == {"Bendigo", "Ballarat", "Wagga"}
    bendigo = next(r for r in rows if r.saleyard == "Bendigo")
    assert bendigo.heads == 64
    assert round(bendigo.schw_kg, 2) == MONEY("1390.72")
    assert round(bendigo.actual_cost, 2) == MONEY("14875.83")
