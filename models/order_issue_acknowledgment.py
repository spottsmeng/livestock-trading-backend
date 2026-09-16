import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import TimestampedBase


class OrderIssueAcknowledgment(TimestampedBase):
    """Content-addressed, cross-snapshot memory of a WARN/CORRECTION
    acknowledgment — the fix for the daily-re-acknowledge design flaw:
    every commit (services/ingestion_service.commit_snapshot) creates a
    brand-new OrderLine row for every line in the abattoir's cumulative
    file, including ones that haven't changed at all, so
    ValidationIssueRecord.acknowledged_at (scoped to that ephemeral row)
    could never survive to the next day's snapshot.

    This table instead keys the acknowledgment to the *business fact* it
    represents: identity (contract_no, species, product_type, incoterm —
    the same tuple domain.ingestion.diff already uses to match lines
    across snapshots) + issue code/column_ref + a content `fingerprint`
    (domain.ingestion.diff.line_content_fingerprint) of the exact field
    values that produced the issue. services.calculate_service looks this
    up for every WARN/CORRECTION issue it raises; a fingerprint match means
    nothing about the order has changed since a human last accepted this
    exact concern, so the new issue row is pre-stamped acknowledged rather
    than reopened. Any change to the line produces a different fingerprint
    and forces a fresh review — deliberately whole-line, not per-column,
    so an unrelated field change still prompts a fresh look at the line.

    One row per (org, identity, issue slot) — `fingerprint` is overwritten
    in place on each new manual acknowledgment (see
    services/issue_acknowledgment_service.record), so this always reflects
    only the latest human decision and the content it was made against.

    Beyond §8's literal diagram — same documented-deviation pattern as
    `dnbp_publication_deliveries` (Phase 3) and `buy_instruction_line_fills`
    (Phase 4). §5.7/§19 require every WARN/CORRECTION "individually
    acknowledged, with the acknowledger recorded" but are silent on whether
    that must be re-collected per immutable `order_lines` row or can carry
    forward by business identity — this table is the latter reading,
    directly extending §7.3's own stated principle that the real question
    is never "what's in this file" but "what changed since yesterday."
    """

    __tablename__ = "order_issue_acknowledgments"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "contract_no", "species", "product_type", "incoterm", "issue_code", "column_ref",
            name="uq_order_issue_ack_identity",
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisations.id"), index=True)

    contract_no: Mapped[str | None] = mapped_column(String, default=None)
    species: Mapped[str | None] = mapped_column(String, default=None)
    product_type: Mapped[str | None] = mapped_column(String, default=None)
    incoterm: Mapped[str | None] = mapped_column(String, default=None)

    issue_code: Mapped[str] = mapped_column(String, index=True)
    column_ref: Mapped[str | None] = mapped_column(String, default=None)
    fingerprint: Mapped[str] = mapped_column(String)

    acknowledged_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Last snapshot whose calculate run found this fingerprint still
    # matching — purely an audit/debug trail ("this waiver is still active
    # as of snapshot X"), never read by the publish gate itself.
    last_confirmed_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_snapshots.id"), default=None
    )
