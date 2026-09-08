import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import TimestampedBase

MONEY = Numeric(18, 10)


class OrderWorkings(TimestampedBase):
    """§8 — EVERHEALTH-OWNED, Columns X-AF. Derived only: recomputed freely
    by re-running POST /snapshots/{id}/calculate, never hand-edited. Exists
    ONLY for an ACTIVE order_line (§5.3) — enforced at the database level by
    a partial unique index plus a trigger checking the parent line's
    lifecycle (see the phase2_ingestion_tables migration), not merely
    because domain.engine.workings.compute_order_workings returns None for
    a LOADED line.

    `bing_dnbp_inputs` persists exactly what produced `bing_dnbp` (G,
    species, cif_buffer, factor) so any published price is re-derivable
    from this row alone, without joining back to reference tables that may
    since have changed (§8's explicit requirement).
    """

    __tablename__ = "order_workings"

    order_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_lines.id"), unique=True, index=True
    )
    engine_version: Mapped[str] = mapped_column(String)
    ref_data_version: Mapped[str] = mapped_column(String)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    adjusted_price_per_kg: Mapped[Decimal | None] = mapped_column(MONEY, default=None)  # X
    pack_cost_per_kg: Mapped[Decimal | None] = mapped_column(MONEY, default=None)  # Y
    offal_return_per_kg: Mapped[Decimal | None] = mapped_column(MONEY, default=None)  # Z
    skin_return_per_kg: Mapped[Decimal | None] = mapped_column(MONEY, default=None)  # AA
    profit_on_peter_costs: Mapped[Decimal | None] = mapped_column(MONEY, default=None)  # AB

    bing_dnbp: Mapped[Decimal | None] = mapped_column(MONEY, default=None)  # AC ★ SOURCE OF TRUTH
    bing_dnbp_factor_used: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    bing_dnbp_inputs: Mapped[dict] = mapped_column(JSONB, default=dict)

    profit_on_bing_dnbp: Mapped[Decimal | None] = mapped_column(MONEY, default=None)  # AD
    diff_vs_benchmark: Mapped[Decimal | None] = mapped_column(MONEY, default=None)  # AE
    diff_vs_peter: Mapped[Decimal | None] = mapped_column(MONEY, default=None)  # AF

    supporting_analysis_complete: Mapped[bool] = mapped_column(Boolean, default=False)
