import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ARRAY, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import TimestampedBase
from models.enums import DeliveryChannel

MONEY = Numeric(18, 10)


class DnbpPublication(TimestampedBase):
    """§8, §9.4 — what the buyer actually receives. One row per publish
    action. `superseded_by` chains publications so the buyer's device can
    always be told "there is a newer one" (§10) and so a historical
    publication's figures stay exactly reproducible (§8's retention rule:
    never hard-deleted).

    Deliberately NOT the same thing as order_workings.bing_dnbp per line —
    see domain/buyer/publication.py's module docstring for why this table
    is species-keyed (MIN(AC) across that species' active lines) while the
    Buy Instruction (Phase 4) stays order-keyed."""

    __tablename__ = "dnbp_publications"

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisations.id"), index=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("order_snapshots.id"), index=True)
    published_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    engine_version: Mapped[str] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String, default=None)

    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dnbp_publications.id"), default=None
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class DnbpPublicationLine(TimestampedBase):
    """§8 — one row per species in a publication. Buyer-safe BY
    CONSTRUCTION: no customer/price/margin column exists on this table at
    all (§2.2), so there is nothing here a future column addition could
    accidentally leak to a buyer response model.

    `dnbp_per_kg` is `MIN(bing_dnbp)` across `contributing_line_ids` — the
    only aggregation that guarantees the buyer never pays more than every
    contributing active order can absorb (confirmed with the business:
    the physical red note book has no species *or* order field, so the
    buyer can only ever be given one ceiling per species at the yard)."""

    __tablename__ = "dnbp_publication_lines"

    publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dnbp_publications.id"), index=True
    )
    species: Mapped[str] = mapped_column(String)  # open registry, §6.9 — never an Enum
    dnbp_per_kg: Mapped[Decimal] = mapped_column(MONEY)
    target_heads: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    target_weight_kg_min: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    target_weight_kg_max: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    contributing_line_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)


class DnbpPublicationDelivery(TimestampedBase):
    """New beyond §8's literal diagram — added because §10 requires a
    per-buyer delivery/acknowledgement state ("Delivered ✓ 14:03 / Not yet
    seen ⚠") visible on the console, which nothing in §8's table list
    models explicitly. One row per (publication, buyer)."""

    __tablename__ = "dnbp_publication_deliveries"

    publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dnbp_publications.id"), index=True
    )
    buyer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    channel: Mapped[DeliveryChannel | None] = mapped_column(
        Enum(DeliveryChannel, name="delivery_channel"), default=None
    )  # set once first delivered
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
