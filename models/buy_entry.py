import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import TimestampedBase
from models.enums import BuyEntrySyncStatus

MONEY = Numeric(18, 10)


class BuyEntry(TimestampedBase):
    """§8, §12.4 — the digital red note book. Mirrors the physical book's
    own field order (Agent/Pen/No./Price/Weight/Desc.) plus `freight_per_head`
    /`other_cost_per_kg` from its footer — see auction-buyer-red-note-book.xlsx.

    `species` has no equivalent in the physical book at all (confirmed with
    the business: the paper book carries no species or order/contract field
    — the buyer simply knows what's in the ring). It is required here
    anyway because without it `dnbp_publication_line_id` couldn't be
    resolved and no breach could ever be scored — this is the one place the
    digital version deliberately adds structure the paper process lacked.

    `dnbp_at_entry`/`variance_per_kg`/`is_breach`/`implied_price_per_kg` are
    frozen at write time via domain.buyer.bidcheck.score_bid, against
    whichever publication was effective *as of `client_created_at`* — not
    "current" — so a later republish can never retroactively change
    whether a past buy was a breach (§12.4's non-negotiable)."""

    __tablename__ = "buy_entries"

    buyer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    saleyard: Mapped[str] = mapped_column(String)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    species: Mapped[str] = mapped_column(String)  # open registry, §6.9 — never an Enum

    agent: Mapped[str | None] = mapped_column(String, default=None)
    pen: Mapped[str | None] = mapped_column(String, default=None)
    head_count: Mapped[int] = mapped_column(Integer)
    price_per_head: Mapped[Decimal] = mapped_column(MONEY)
    weight_kg: Mapped[Decimal] = mapped_column(MONEY)
    description: Mapped[str | None] = mapped_column(String, default=None)
    eid_ref: Mapped[str | None] = mapped_column(String, default=None)
    freight_per_head: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    other_cost_per_kg: Mapped[Decimal | None] = mapped_column(MONEY, default=None)

    # Derived and frozen at entry time (§12.4) — never recomputed later.
    implied_price_per_kg: Mapped[Decimal] = mapped_column(MONEY)
    dnbp_publication_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dnbp_publication_lines.id"), default=None
    )
    dnbp_at_entry: Mapped[Decimal] = mapped_column(MONEY)
    variance_per_kg: Mapped[Decimal] = mapped_column(MONEY)
    is_breach: Mapped[bool] = mapped_column(Boolean)
    breach_reason: Mapped[str | None] = mapped_column(String, default=None)

    # Offline sync (§12.7) — idempotency key generated client-side.
    client_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, index=True)
    client_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    sync_status: Mapped[BuyEntrySyncStatus] = mapped_column(
        Enum(BuyEntrySyncStatus, name="buy_entry_sync_status"), default=BuyEntrySyncStatus.SYNCED
    )

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
