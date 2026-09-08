import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import TimestampedBase
from models.enums import BuyInstructionStatus

MONEY = Numeric(18, 10)


class BuyInstruction(TimestampedBase):
    """§8, §13.1, Phase 4 — the v3 Buy Instruction. Generated wholly from a
    published snapshot (`POST /buy-instructions` validates `publication_id`
    actually belongs to `snapshot_id` — see services/buy_instruction_service.py
    for why that guarantees every line already has a valid `bing_dnbp`), never
    retyped. `note` is the only field `PATCH /buy-instructions/{id}` may touch
    while DRAFT — the line figures are always regenerated, never hand-edited."""

    __tablename__ = "buy_instructions"

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisations.id"), index=True)
    instruction_no: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("order_snapshots.id"), index=True)
    publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dnbp_publications.id"), index=True
    )

    prepared_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), default=None)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    note: Mapped[str | None] = mapped_column(String, default=None)
    status: Mapped[BuyInstructionStatus] = mapped_column(
        Enum(BuyInstructionStatus, name="buy_instruction_status"), default=BuyInstructionStatus.DRAFT
    )


class BuyInstructionLine(TimestampedBase):
    """§13.1 line items — one row per contributing ACTIVE order line.
    Every figure here is generated at instruction-creation time straight
    from that specific `order_line`/`order_workings` row (never from
    `dnbp_publication_lines`, which is species-keyed — see
    dnbp-publication-is-species-keyed) and never recomputed or hand-edited
    afterwards; a stale instruction is superseded by generating a new one,
    the same immutable-snapshot philosophy as `order_lines` itself."""

    __tablename__ = "buy_instruction_lines"

    instruction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("buy_instructions.id"), index=True
    )
    order_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("order_lines.id"))
    seq: Mapped[int] = mapped_column(Integer)

    contract_no: Mapped[str | None] = mapped_column(String, default=None)
    species: Mapped[str] = mapped_column(String)  # open registry, §6.9 — never an Enum

    schw_kg: Mapped[Decimal] = mapped_column(MONEY)
    expected_heads: Mapped[Decimal] = mapped_column(MONEY)
    weight_requirement_kg: Mapped[Decimal] = mapped_column(MONEY)
    dnbp_per_kg: Mapped[Decimal] = mapped_column(MONEY)  # order-keyed AC — see module docstring
    peters_expectation: Mapped[Decimal | None] = mapped_column(MONEY, default=None)  # L, comparison only
    expected_livestock_cost: Mapped[Decimal] = mapped_column(MONEY)  # dnbp_per_kg * weight_req * expected_heads


class BuyInstructionLineFill(TimestampedBase):
    """Beyond §8's literal diagram — same documented-deviation pattern as
    Phase 3's `dnbp_publication_deliveries`. Confirmed with Terence:
    `buy_entries` carry no order/contract reference at all, so there is no
    data path that could attribute a specific buy to a specific instruction
    line ("Buy 1/2/3 in kg" auto-computed). This is instead an open-ended,
    unbounded list of manual fills Bing enters per line while the
    instruction is ISSUED or ACKNOWLEDGED — never while DRAFT (nothing to
    reconcile yet) or RECONCILED (closed). `Balance` is always derived
    (`schw_kg - sum(fills)`), never stored here."""

    __tablename__ = "buy_instruction_line_fills"

    line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("buy_instruction_lines.id"), index=True
    )
    label: Mapped[str] = mapped_column(String)
    kg_amount: Mapped[Decimal] = mapped_column(MONEY)
    entered_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
