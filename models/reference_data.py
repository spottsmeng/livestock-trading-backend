import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base
from models.base import TimestampedBase
from models.enums import ReferenceDataTableKey

MONEY = Numeric(18, 10)


class ReferenceDataVersion(TimestampedBase):
    """§6.5, §8 — Everhealth-owned reference data (§6.4 standard weight,
    §6.5 dnbp factor, §6.7 cif_buffer) ONLY. Abattoir-owned tables
    (§6.1-6.3, §6.6) never get a row here — see §9.8's 403
    ABATTOIR_OWNED_TABLE requirement, enforced by ReferenceDataTableKey
    simply having no abattoir-table members.

    Never edited in place — a change is always a new version (same
    discipline as order_lines/order_snapshots being immutable). Exactly one
    version is `is_active` at a time; that is the version
    core.reference_data.get_active_everhealth_config loads.

    `impact_previewed_at` is the activation gate (§6.5, §19): `POST
    .../activate` refuses while this is null. Set once by `POST
    .../{id}/impact`. Versions are immutable post-creation, so once impact
    has been computed for a version it never goes stale — there is nothing
    about the version itself that could change afterwards.
    """

    __tablename__ = "reference_data_versions"

    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), default=None)
    note: Mapped[str | None] = mapped_column(String, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    impact_previewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ReferenceDataEntry(TimestampedBase):
    """§8: `(table_key, key1, key2, value)`. `key1` is a bare species code
    for DNBP_FACTOR/STANDARD_WEIGHT — never an FK to
    species_registry (§6.9: no FK constraint against species anywhere).
    `key2` exists for §8 shape-parity but is unused by every table_key this
    system has today; CIF_BUFFER_PER_KG uses neither key1 nor key2."""

    __tablename__ = "reference_data_entries"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reference_data_versions.id"), index=True
    )
    table_key: Mapped[ReferenceDataTableKey] = mapped_column(
        Enum(ReferenceDataTableKey, name="reference_data_table_key")
    )
    key1: Mapped[str | None] = mapped_column(String, default=None)
    key2: Mapped[str | None] = mapped_column(String, default=None)
    value: Mapped[Decimal] = mapped_column(MONEY)


class ReferenceDataDrift(TimestampedBase):
    """New beyond §8's literal diagram — added for §7.2 point 11 / §9.8's
    `GET /reference-data/drift`, the same way Phase 3 added
    dnbp_publication_deliveries beyond §8's diagram for a requirement §8
    itself didn't model. One row per (snapshot, table, key) where the
    abattoir's own lookup sheet disagrees with the immediately-previous
    snapshot's stored copy. Never write-capable against §6.4/§6.5 — this is
    a notice, not an input (§7.2 point 11 is explicit about this)."""

    __tablename__ = "reference_data_drift"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("order_snapshots.id"), index=True)
    table_key: Mapped[str] = mapped_column(String)  # abattoir table name, e.g. "pack_cost_by_product_type"
    key1: Mapped[str] = mapped_column(String)  # e.g. species or product_type code
    old_value: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    new_value: Mapped[Decimal | None] = mapped_column(MONEY, default=None)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), default=None)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class SpeciesRegistry(Base):
    """§6.9, §8 — open registry, rows not an enum. `code` is the primary
    key (§8's literal shape: "code PK, display_name, is_active, created_by,
    created_at") — deliberately NOT TimestampedBase's UUID `id`, since §8
    specifies `code` itself as the key. `order_lines.species` has no FK
    here by design: an unrecognised value is stored verbatim and flagged,
    never rejected (§6.9). `code` is normalised uppercase by the service
    layer before insert, never by a DB constraint."""

    __tablename__ = "species_registry"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProductTypeRegistry(Base):
    """§6.9, §8 — open registry, same shape and rules as SpeciesRegistry."""

    __tablename__ = "product_type_registry"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
