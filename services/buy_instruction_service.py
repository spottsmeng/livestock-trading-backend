"""POST /buy-instructions (§9.6, §13.1) and the full instruction lifecycle,
Phase 4.

`generate` validates that `publication_id` actually belongs to `snapshot_id`
before doing anything else. That single check is what guarantees every
resulting line has a valid `bing_dnbp`: a `DnbpPublication` can only ever be
created by `services.publication_service.publish`, which itself calls
`_assert_publishable` first and refuses (`PublicationBlocked`) if any ACTIVE
line in the snapshot holds a BLOCK issue — the only issues that can leave
`order_workings.bing_dnbp` unpopulated (§5.7). So a publication that
validates against this snapshot is proof the snapshot already passed that
gate; `generate` can safely read every ACTIVE line's own `bing_dnbp`
straight from `order_workings` without re-deriving or re-checking anything
itself, and — critically — without ever touching the species-keyed
`dnbp_publication_lines` (see dnbp-publication-is-species-keyed): the Buy
Instruction is the other, order-keyed consumer of `AC`.

Status machine (non-negotiable, confirmed with Terence before building):
  DRAFT --approve (OWNER only)--> DRAFT (stamps approved_by/approved_at only)
  DRAFT --issue (requires approved_by set)--> ISSUED
  ISSUED --buyer acknowledges--> ACKNOWLEDGED
  ACKNOWLEDGED --reconcile-close (OWNER or ACCOUNTANT)--> RECONCILED

`reconcile-close` and the fill routes are not in §9.6's literal route list —
same documented-deviation pattern as Phase 3's `dnbp_publication_deliveries`.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import (
    FillsNotAllowed,
    InstructionNotApproved,
    InvalidInstructionTransition,
    NotFound,
    NothingToInstruct,
    PublicationSnapshotMismatch,
)
from core.trading_calendar import trading_week_bounds
from models.buy_instruction import BuyInstruction, BuyInstructionLine, BuyInstructionLineFill
from models.dnbp_publication import DnbpPublication
from models.enums import BuyInstructionStatus
from models.order_snapshot import OrderSnapshot
from repositories import buy_instructions as buy_instructions_repo
from repositories import order_workings as order_workings_repo
from services import audit_service

MONEY_ZERO = Decimal("0")


async def generate(
    db: AsyncSession,
    *,
    snapshot: OrderSnapshot,
    publication: DnbpPublication,
    actor_id: uuid.UUID,
    trade_date: date | None,
    note: str | None,
) -> tuple[BuyInstruction, list[BuyInstructionLine]]:
    if publication.snapshot_id != snapshot.id:
        raise PublicationSnapshotMismatch()

    rows = await order_workings_repo.list_active_with_bing_dnbp(db, snapshot.id)
    if not rows:
        raise NothingToInstruct()

    # §13.1's header shows a single trade date for the whole instruction.
    # §9.6 doesn't list an explicit `trade_date` parameter, so — same kind
    # of documented interpretive choice Phase 3b made for the impact-preview
    # formula — this defaults to the snapshot's own `as_of_date` (the date
    # the abattoir's submission covers) unless the caller overrides it.
    effective_trade_date = trade_date or snapshot.as_of_date or date.today()

    existing_for_date = await buy_instructions_repo.list_for_org(db, snapshot.org_id, trade_date=effective_trade_date)
    version = len(existing_for_date) + 1
    instruction_no = f"BI-{effective_trade_date:%Y%m%d}"

    instruction = BuyInstruction(
        org_id=snapshot.org_id,
        instruction_no=instruction_no,
        version=version,
        trade_date=effective_trade_date,
        snapshot_id=snapshot.id,
        publication_id=publication.id,
        prepared_by=actor_id,
        note=note,
        status=BuyInstructionStatus.DRAFT,
    )
    await buy_instructions_repo.create(db, instruction)

    lines: list[BuyInstructionLine] = []
    for seq, (order_line, workings) in enumerate(
        sorted(rows, key=lambda pair: pair[0].line_no), start=1
    ):
        expected_heads = order_line.estimated_heads or MONEY_ZERO
        weight_requirement_kg = order_line.avg_weight_kg or MONEY_ZERO
        dnbp_per_kg = workings.bing_dnbp  # AC — order-keyed, never dnbp_publication_lines. See module docstring.
        schw_kg = expected_heads * weight_requirement_kg
        expected_livestock_cost = dnbp_per_kg * weight_requirement_kg * expected_heads  # [D6] resolved — AC, not L

        lines.append(
            BuyInstructionLine(
                instruction_id=instruction.id,
                order_line_id=order_line.id,
                seq=seq,
                contract_no=order_line.contract_no,
                species=order_line.species,
                schw_kg=schw_kg,
                expected_heads=expected_heads,
                weight_requirement_kg=weight_requirement_kg,
                dnbp_per_kg=dnbp_per_kg,
                peters_expectation=order_line.expected_livestock_cost_per_kg,
                expected_livestock_cost=expected_livestock_cost,
            )
        )
    await buy_instructions_repo.add_lines(db, lines)

    await audit_service.write(
        db,
        actor_id=actor_id,
        action="buy_instruction.generated",
        entity="buy_instruction",
        entity_id=instruction.id,
        after={"snapshot_id": str(snapshot.id), "publication_id": str(publication.id), "line_count": len(lines)},
    )

    return instruction, lines


async def update_note(db: AsyncSession, instruction: BuyInstruction, *, note: str | None, actor_id: uuid.UUID) -> None:
    if instruction.status != BuyInstructionStatus.DRAFT:
        raise InvalidInstructionTransition("Only a DRAFT instruction can be edited.")
    before = {"note": instruction.note}
    instruction.note = note
    await audit_service.write(
        db,
        actor_id=actor_id,
        action="buy_instruction.updated",
        entity="buy_instruction",
        entity_id=instruction.id,
        before=before,
        after={"note": note},
    )


async def approve(db: AsyncSession, instruction: BuyInstruction, *, actor_id: uuid.UUID) -> BuyInstruction:
    if instruction.status != BuyInstructionStatus.DRAFT:
        raise InvalidInstructionTransition("Only a DRAFT instruction can be approved.")
    instruction.approved_by = actor_id
    instruction.approved_at = datetime.now(UTC)
    await audit_service.write(
        db,
        actor_id=actor_id,
        action="buy_instruction.approved",
        entity="buy_instruction",
        entity_id=instruction.id,
        after={"approved_by": str(actor_id)},
    )
    return instruction


async def issue(db: AsyncSession, instruction: BuyInstruction, *, actor_id: uuid.UUID) -> BuyInstruction:
    if instruction.status != BuyInstructionStatus.DRAFT:
        raise InvalidInstructionTransition("Only a DRAFT instruction can be issued.")
    if instruction.approved_by is None:
        raise InstructionNotApproved()
    instruction.status = BuyInstructionStatus.ISSUED
    await audit_service.write(
        db, actor_id=actor_id, action="buy_instruction.issued", entity="buy_instruction", entity_id=instruction.id
    )
    return instruction


async def acknowledge(db: AsyncSession, instruction: BuyInstruction, *, buyer_id: uuid.UUID) -> BuyInstruction:
    if instruction.status != BuyInstructionStatus.ISSUED:
        raise InvalidInstructionTransition("Only an ISSUED instruction can be acknowledged.")
    instruction.status = BuyInstructionStatus.ACKNOWLEDGED
    await audit_service.write(
        db,
        actor_id=buyer_id,
        action="buy_instruction.acknowledged",
        entity="buy_instruction",
        entity_id=instruction.id,
    )
    return instruction


async def reconcile_close(db: AsyncSession, instruction: BuyInstruction, *, actor_id: uuid.UUID) -> BuyInstruction:
    if instruction.status != BuyInstructionStatus.ACKNOWLEDGED:
        raise InvalidInstructionTransition("Only an ACKNOWLEDGED instruction can be closed as reconciled.")
    instruction.status = BuyInstructionStatus.RECONCILED
    await audit_service.write(
        db,
        actor_id=actor_id,
        action="buy_instruction.reconciled",
        entity="buy_instruction",
        entity_id=instruction.id,
    )
    return instruction


async def add_fill(
    db: AsyncSession,
    instruction: BuyInstruction,
    line: BuyInstructionLine,
    *,
    label: str,
    kg_amount: Decimal,
    actor_id: uuid.UUID,
) -> BuyInstructionLineFill:
    if line.instruction_id != instruction.id:
        raise NotFound("Buy instruction line")
    if instruction.status not in (BuyInstructionStatus.ISSUED, BuyInstructionStatus.ACKNOWLEDGED):
        raise FillsNotAllowed()
    fill = BuyInstructionLineFill(
        line_id=line.id, label=label, kg_amount=kg_amount, entered_by=actor_id, entered_at=datetime.now(UTC)
    )
    await buy_instructions_repo.add_fill(db, fill)
    await audit_service.write(
        db,
        actor_id=actor_id,
        action="buy_instruction.fill_added",
        entity="buy_instruction_line",
        entity_id=line.id,
        after={"label": label, "kg_amount": str(kg_amount)},
    )
    return fill


async def remove_fill(
    db: AsyncSession, instruction: BuyInstruction, fill: BuyInstructionLineFill, *, actor_id: uuid.UUID
) -> None:
    if instruction.status not in (BuyInstructionStatus.ISSUED, BuyInstructionStatus.ACKNOWLEDGED):
        raise FillsNotAllowed()
    await audit_service.write(
        db,
        actor_id=actor_id,
        action="buy_instruction.fill_removed",
        entity="buy_instruction_line",
        entity_id=fill.line_id,
        before={"label": fill.label, "kg_amount": str(fill.kg_amount)},
    )
    await buy_instructions_repo.delete_fill(db, fill)


@dataclass(slots=True)
class SaleyardReconciliation:
    saleyard: str
    schw_kg: Decimal
    heads: int
    actual_cost: Decimal


@dataclass(slots=True)
class ReconciliationSummary:
    actual_heads: int
    expected_heads: Decimal
    ordered_schw: Decimal  # A
    bought_schw: Decimal  # B
    surplus_shortfall_schw: Decimal  # A - B
    expected_cost: Decimal  # C
    actual_cost: Decimal  # D
    cost_variance: Decimal  # C - D


async def compute_reconciliation(
    db: AsyncSession, instruction: BuyInstruction
) -> tuple[list[SaleyardReconciliation], ReconciliationSummary]:
    """§13.1's reconciliation and summary blocks, non-negotiable #6: live-
    computed on every read (never cached), scoped to the Melbourne Mon-Sun
    trading week containing `instruction.trade_date`, grouped by whichever
    saleyards actually have `buy_entries` in that window — never hard-coded
    to a fixed set of saleyard columns. "Actual Cost" is the livestock cost
    only (price_per_head x head_count), the same basis as the received `V`
    (`total_livestock_cost = L x F`, also excluding freight) — freight is
    tracked separately per entry, not folded into this figure."""
    lines = await buy_instructions_repo.list_lines(db, instruction.id)
    week_start, week_end = trading_week_bounds(instruction.trade_date)
    entries = await buy_instructions_repo.list_org_buy_entries_in_window(
        db, instruction.org_id, week_start=week_start, week_end=week_end
    )

    by_saleyard: dict[str, list] = {}
    for entry in entries:
        by_saleyard.setdefault(entry.saleyard, []).append(entry)

    saleyard_rows = [
        SaleyardReconciliation(
            saleyard=saleyard,
            schw_kg=sum((e.weight_kg * e.head_count for e in es), MONEY_ZERO),
            heads=sum(e.head_count for e in es),
            actual_cost=sum((e.price_per_head * e.head_count for e in es), MONEY_ZERO),
        )
        for saleyard, es in sorted(by_saleyard.items())
    ]

    ordered_schw = sum((line.schw_kg for line in lines), MONEY_ZERO)
    expected_heads = sum((line.expected_heads for line in lines), MONEY_ZERO)
    expected_cost = sum((line.expected_livestock_cost for line in lines), MONEY_ZERO)
    bought_schw = sum((row.schw_kg for row in saleyard_rows), MONEY_ZERO)
    actual_heads = sum(row.heads for row in saleyard_rows)
    actual_cost = sum((row.actual_cost for row in saleyard_rows), MONEY_ZERO)

    summary = ReconciliationSummary(
        actual_heads=actual_heads,
        expected_heads=expected_heads,
        ordered_schw=ordered_schw,
        bought_schw=bought_schw,
        surplus_shortfall_schw=ordered_schw - bought_schw,
        expected_cost=expected_cost,
        actual_cost=actual_cost,
        cost_variance=expected_cost - actual_cost,
    )
    return saleyard_rows, summary


def line_balance(line: BuyInstructionLine, fills: list[BuyInstructionLineFill]) -> Decimal:
    """Balance is always derived, never stored (non-negotiable #4)."""
    return line.schw_kg - sum((fill.kg_amount for fill in fills), MONEY_ZERO)
