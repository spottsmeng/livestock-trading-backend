"""§6.4/§6.5/§6.7/§9.8/§11.7 — reference-data versioning. Fetch-then-compute
split, same discipline as calculate_service.py: this module fetches lines
from the DB and builds EverhealthConfig objects; the actual before/after
math is domain.engine.impact.compute_impact, a pure function this module
calls but never reimplements.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import AbattoirOwnedTable, AppError, ImpactPreviewRequired, NotFound
from core.reference_data import get_active_everhealth_config
from domain.engine.config import EverhealthConfig
from domain.engine.impact import ImpactLineInput, ImpactPreview, compute_impact
from domain.engine.workings import Lifecycle
from models.enums import ReferenceDataTableKey
from models.reference_data import ReferenceDataVersion
from repositories import order_lines as order_lines_repo
from repositories import order_snapshots as order_snapshots_repo
from repositories import reference_data as reference_data_repo
from services import audit_service
from services.ingestion_service import deserialize_abattoir_tables

# §6.1-6.3/§6.6 — abattoir-owned tables. Never valid on this route (§9.8).
# Named here (not just absent from ReferenceDataTableKey) so a client
# submitting one of these gets a precise 403 explaining why, rather than a
# generic "invalid table_key" 422.
_ABATTOIR_TABLE_KEYS = {
    "pack_cost_by_product_type",
    "offal_return_ph_by_species",
    "skin_return_ph_by_species",
    "reference_weight_by_species",
    "required_margin_by_species",
    "benchmark_fixed_cost_per_head",
}

# Everhealth-owned (§6.4/§6.5/§6.7) — the only writable table_keys.
_WRITABLE_TABLE_KEYS = {
    "cif_buffer_per_kg": ReferenceDataTableKey.CIF_BUFFER_PER_KG,
    "dnbp_factor_by_species": ReferenceDataTableKey.DNBP_FACTOR,
    "standard_weight_by_species": ReferenceDataTableKey.STANDARD_WEIGHT,
}

# Only these two can move `AC` — the impact-preview/second-confirmation
# friction (§6.5) applies to them and them only. Standard weight (§6.4) is
# Everhealth-owned and versioned but cannot reach AC (§5.3), so it is
# exempt from that gate.
SOURCE_OF_TRUTH_TABLE_KEYS = {ReferenceDataTableKey.CIF_BUFFER_PER_KG, ReferenceDataTableKey.DNBP_FACTOR}


def resolve_table_key(raw_table_key: str) -> ReferenceDataTableKey:
    if raw_table_key in _ABATTOIR_TABLE_KEYS:
        raise AbattoirOwnedTable(raw_table_key)
    resolved = _WRITABLE_TABLE_KEYS.get(raw_table_key)
    if resolved is None:
        raise AppError("UNKNOWN_TABLE_KEY", f"'{raw_table_key}' is not a recognised reference-data table.", 422)
    return resolved


async def list_versions(db: AsyncSession) -> list[ReferenceDataVersion]:
    return await reference_data_repo.list_versions(db)


async def get_version_with_entries(db: AsyncSession, version_id: uuid.UUID):
    version = await reference_data_repo.get_by_id(db, version_id)
    if version is None:
        raise NotFound("Reference data version")
    entries = await reference_data_repo.list_entries(db, version_id)
    return version, entries


async def get_active_config(db: AsyncSession) -> EverhealthConfig:
    return await get_active_everhealth_config(db)


async def create_version(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    effective_from: datetime,
    note: str | None,
    raw_entries: list[tuple[str, str | None, Decimal]],
) -> ReferenceDataVersion:
    """Every version is a COMPLETE, standalone snapshot of the Everhealth
    config — same philosophy as order_snapshots being a full cumulative
    snapshot, not a delta (§7.1). `raw_entries` is the caller's requested
    *change* (e.g. "just SHEEP's factor"); this clones the currently-active
    config first and overlays those changes on top, so the persisted
    version always carries a value for cif_buffer and every species that
    the active config already prices — never leaving a gap that would make
    `get_active_everhealth_config` unable to find e.g. cif_buffer once this
    version activates. Never an in-place edit: the clone is a new row, the
    active version is untouched."""
    merged: dict[tuple[ReferenceDataTableKey, str | None], Decimal] = {}

    active_version = await reference_data_repo.get_active_version(db)
    if active_version is not None:
        for entry in await reference_data_repo.list_entries(db, active_version.id):
            merged[(entry.table_key, entry.key1)] = entry.value

    for raw_table_key, key1, value in raw_entries:
        merged[(resolve_table_key(raw_table_key), key1)] = value

    resolved_entries = [(table_key, key1, value) for (table_key, key1), value in merged.items()]

    version = await reference_data_repo.create_version(
        db,
        effective_from=effective_from,
        created_by=actor_id,
        note=note,
        entries=resolved_entries,
    )

    await audit_service.write(
        db,
        actor_id=actor_id,
        action="reference_data_version.created",
        entity="reference_data_version",
        entity_id=version.id,
        after={"effective_from": effective_from.isoformat(), "note": note, "entry_count": len(resolved_entries)},
    )
    return version


async def preview_impact(db: AsyncSession, version_id: uuid.UUID, *, org_id: uuid.UUID) -> ImpactPreview:
    version, entries = await get_version_with_entries(db, version_id)

    # create_version already persisted a COMPLETE snapshot (cloned from the
    # active config with the caller's changes overlaid), so this version's
    # own entries are the whole new_config — no further merging needed here.
    cif_buffer: Decimal | None = None
    factors: dict[str, Decimal] = {}
    weights: dict[str, Decimal] = {}
    for entry in entries:
        if entry.table_key == ReferenceDataTableKey.CIF_BUFFER_PER_KG:
            cif_buffer = entry.value
        elif entry.table_key == ReferenceDataTableKey.DNBP_FACTOR:
            factors[entry.key1] = entry.value
        elif entry.table_key == ReferenceDataTableKey.STANDARD_WEIGHT:
            weights[entry.key1] = entry.value

    old_config = await get_active_everhealth_config(db)
    new_config = EverhealthConfig(
        cif_buffer_per_kg=cif_buffer if cif_buffer is not None else old_config.cif_buffer_per_kg,
        dnbp_factor_by_species=factors,
        standard_weight_by_species=weights,
    )

    latest_snapshot = await order_snapshots_repo.get_latest_for_org(db, org_id)
    lines: list[ImpactLineInput] = []
    if latest_snapshot is not None:
        active_lines = await order_lines_repo.list_by_snapshot(db, latest_snapshot.id, lifecycle=Lifecycle.ACTIVE)
        lines = [
            ImpactLineInput(
                order_line_id=str(line.id),
                contract_no=line.contract_no,
                species=line.species,
                avg_price_aud=line.avg_price_aud,
                qty_kg=line.qty_kg,
            )
            for line in active_lines
            if line.species is not None
        ]

    preview = compute_impact(lines, old_config=old_config, new_config=new_config)

    await reference_data_repo.mark_impact_previewed(db, version)
    await audit_service.write(
        db,
        actor_id=None,
        action="reference_data_version.impact_previewed",
        entity="reference_data_version",
        entity_id=version.id,
        after={
            "lines_affected": preview.lines_affected,
            "aggregate_exposure_delta_aud": str(preview.aggregate_exposure_delta_aud),
        },
    )
    return preview


async def get_latest_abattoir_tables(db: AsyncSession, *, org_id: uuid.UUID):
    """§9.8 `GET /reference-data/abattoir` — read-only, the latest
    snapshot's own stored tables (§11.7's abattoir panel). Raises NotFound
    if nothing has ever been ingested yet."""
    snapshot = await order_snapshots_repo.get_latest_for_org(db, org_id)
    if snapshot is None:
        raise NotFound("Any order snapshot")
    tables = deserialize_abattoir_tables(snapshot.abattoir_reference_tables)
    return snapshot, tables


async def activate_version(db: AsyncSession, version_id: uuid.UUID, *, actor_id: uuid.UUID) -> ReferenceDataVersion:
    version = await reference_data_repo.get_by_id(db, version_id)
    if version is None:
        raise NotFound("Reference data version")
    if version.impact_previewed_at is None:
        raise ImpactPreviewRequired()

    before_active = await reference_data_repo.get_active_version(db)
    await reference_data_repo.activate(db, version)

    await audit_service.write(
        db,
        actor_id=actor_id,
        action="reference_data_version.activated",
        entity="reference_data_version",
        entity_id=version.id,
        before={"previous_active_version_id": str(before_active.id) if before_active else None},
        after={"activated_at": datetime.now(UTC).isoformat()},
    )
    return version
