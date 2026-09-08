import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from domain.engine.workings import Lifecycle
from domain.ingestion.types import BenchmarkMethod
from models.base import TimestampedBase
from models.enums import Incoterm

MONEY = Numeric(18, 10)


class OrderLine(TimestampedBase):
    """§8 — ABATTOIR-OWNED, Columns A-V. IMMUTABLE once written: no
    application code path ever issues an UPDATE or DELETE against this
    table, and the database itself refuses both regardless (see the
    `phase2_ingestion_tables` migration's REVOKE + guard trigger) — a
    correction is always a new OrderSnapshot, never an edit here
    (Constraint 1, non-negotiable #1).

    `species` and `product_type` are plain `str` — open registries (§6.9),
    never an Enum or FK to a closed list. `incoterm` and `benchmark_method`
    are genuinely closed and use real enum types.
    """

    __tablename__ = "order_lines"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("order_snapshots.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    lifecycle: Mapped[Lifecycle] = mapped_column(Enum(Lifecycle, name="lifecycle"), index=True)

    contract_no: Mapped[str | None] = mapped_column(String, index=True, default=None)
    customer_name: Mapped[str | None] = mapped_column(String, default=None)
    species: Mapped[str | None] = mapped_column(String, default=None)  # open registry, §6.9 — never an Enum
    loadout_date: Mapped[date | None] = mapped_column(Date, default=None)
    qty_kg: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    avg_price_aud: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    amount_aud: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    product_type: Mapped[str | None] = mapped_column(String, default=None)  # open registry, §6.9
    incoterm: Mapped[Incoterm | None] = mapped_column(Enum(Incoterm, name="incoterm"), default=None)
    nrv_per_kg: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    expected_livestock_cost_per_kg: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    pack_cost_ph: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    offal_return_ph: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    skin_return_ph: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    avg_weight_kg: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    mom_ph: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    deposit_received: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    comments: Mapped[str | None] = mapped_column(String, default=None)
    dnbp_benchmark: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    benchmark_method: Mapped[BenchmarkMethod | None] = mapped_column(
        Enum(BenchmarkMethod, name="benchmark_method"), default=None
    )
    estimated_heads: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    total_livestock_cost: Mapped[Decimal | None] = mapped_column(MONEY, default=None)

    # Per-column FORMULA|HAND_SET provenance (§7.2 pt 4), keyed by field name
    # — only for the columns that are ever formula-driven in the source
    # (see domain/ingestion/workbook.py's _FORMULA_DRIVEN_FIELDS).
    value_sources: Mapped[dict] = mapped_column(JSONB, default=dict)
