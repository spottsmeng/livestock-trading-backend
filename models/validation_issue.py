import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from domain.engine.issues import Severity
from models.base import TimestampedBase


class ValidationIssueRecord(TimestampedBase):
    """§5.7/§5.7.1/§8. One row per issue raised against an order_line at
    calculate time. `code` reuses the string constants in
    domain/engine/issues.py (NO_DNBP_FACTOR, RECEIVED_VALUE_MISMATCH, ...)
    so a row here is always traceable back to exactly one rule in the
    engine. Acknowledgement is a Phase 3 concept tied to publication (§5.7)
    — the columns exist now so nothing needs a later migration, but no
    Phase 2 route ever sets them."""

    __tablename__ = "validation_issues"

    order_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("order_lines.id"), index=True)
    code: Mapped[str] = mapped_column(String, index=True)
    severity: Mapped[Severity] = mapped_column(Enum(Severity, name="issue_severity"))
    message: Mapped[str] = mapped_column(String)
    column_ref: Mapped[str | None] = mapped_column(String, default=None)

    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), default=None)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
