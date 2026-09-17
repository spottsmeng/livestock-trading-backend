import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import TimestampedBase
from models.enums import BuyEntrySyncStatus

MONEY = Numeric(18, 10)


class MarketObservation(TimestampedBase):
    """Market intelligence: another buyer's successful bid, observed
    ringside by one of our own buyers and logged for benchmarking/
    analytics/ML — never our own purchase (see BuyEntry for that). No
    DNBP/breach scoring applies here; a competitor's purchase isn't
    measured against our own Do Not Buy Price.

    Visibility is the inverse of BuyEntry's: the observing buyer is an
    external contractor and may submit observations but never read them
    back (no GET exposed to Role.BUYER at all — see api/v1/market_intel.py
    and schemas/market_intel.py, kept entirely separate from api/v1/buyer.py
    /schemas/buyer.py so the buyer-response-isolation test's scope stays
    accurate). Only OWNER/ACCOUNTANT can list or aggregate this table, so
    unlike BuyEntry it carries an explicit `org_id` for that org-scoped
    read path, rather than relying on a join through `observer_id`.

    `competitor_name` is free text, same open-registry reasoning as
    `species` (§6.9 pattern) — there's no roster of competing buyer
    companies to select from, just whatever name the observer typed
    ringside.
    """

    __tablename__ = "market_observations"

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisations.id"), index=True)
    observer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    saleyard: Mapped[str] = mapped_column(String)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    species: Mapped[str] = mapped_column(String)  # open registry, §6.9 — never an Enum

    competitor_name: Mapped[str] = mapped_column(String)
    agent: Mapped[str | None] = mapped_column(String, default=None)
    pen: Mapped[str | None] = mapped_column(String, default=None)
    head_count: Mapped[int] = mapped_column(Integer)
    price_per_head: Mapped[Decimal] = mapped_column(MONEY)
    weight_kg: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    description: Mapped[str | None] = mapped_column(String, default=None)

    # Derived at entry time when weight_kg is known; left null otherwise
    # (a competitor's lot weight is often not visible/knowable ringside).
    implied_price_per_kg: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    is_estimated: Mapped[bool] = mapped_column(Boolean, default=False)

    # Offline sync, same idempotency pattern as BuyEntry (§12.7).
    client_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, index=True)
    client_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    sync_status: Mapped[BuyEntrySyncStatus] = mapped_column(
        Enum(BuyEntrySyncStatus, name="market_observation_sync_status"), default=BuyEntrySyncStatus.SYNCED
    )

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
