import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import TimestampedBase

MONEY = Numeric(18, 10)


class OrderLineRemoval(TimestampedBase):
    """A contract present in the previous snapshot's ACTIVE/LOADED lines
    but absent from the newly committed one — moved to LOADED is tracked
    separately (SnapshotDiff.moved_to_loaded); this is everything else,
    i.e. a contract that simply vanished with no recorded reason (§7.3's
    `removed_lines`). Never surfaced as a correction (nothing to fix —
    the ingested data is exactly what the abattoir sent) and never
    inferred automatically — a human records why, same acknowledge
    discipline as reference_data_drift.

    Identity fields + a snapshot of customer_name/amount_aud are copied in
    at detection time so the row reads on its own without joining back to
    the (now-historical) order_lines row it came from."""

    __tablename__ = "order_line_removals"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("order_snapshots.id"), index=True)
    contract_no: Mapped[str | None] = mapped_column(String, default=None)
    species: Mapped[str | None] = mapped_column(String, default=None)
    product_type: Mapped[str | None] = mapped_column(String, default=None)
    incoterm: Mapped[str | None] = mapped_column(String, default=None)
    customer_name: Mapped[str | None] = mapped_column(String, default=None)
    amount_aud: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), default=None)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    reason: Mapped[str | None] = mapped_column(String, default=None)
