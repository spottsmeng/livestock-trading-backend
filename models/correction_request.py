import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import TimestampedBase
from models.enums import CorrectionStatus


class CorrectionRequest(TimestampedBase):
    """§2.1.1, §8, §9.3 — INTERNAL ONLY. A flag on a defect in received
    A-V data, visible to OWNER/ACCOUNTANT. There is no send/notify path
    anywhere in this codebase for this table — resolving it with the
    abattoir happens by phone or email, entirely outside this product.

    Auto-resolves when a later snapshot supplies a valid value for the same
    flagged line (matched by `domain.ingestion.workbook.ParsedOrderLine
    .identity_key()`) and column — see services/calculate_service.py.
    """

    __tablename__ = "correction_requests"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("order_snapshots.id"), index=True)
    order_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("order_lines.id"), index=True)
    raised_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    column_ref: Mapped[str] = mapped_column(String)
    issue_code: Mapped[str] = mapped_column(String)
    detail: Mapped[str | None] = mapped_column(String, default=None)

    status: Mapped[CorrectionStatus] = mapped_column(
        Enum(CorrectionStatus, name="correction_status"), default=CorrectionStatus.OPEN, index=True
    )
    resolved_by_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_snapshots.id"), default=None
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
