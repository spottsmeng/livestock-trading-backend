"""Loads reference configuration for the engine (§6).

`get_active_everhealth_config` (Phase 3b) is the one this system's
money-moving config — §6.4 standard weight, §6.5 dnbp factor, §6.7
cif_buffer — comes from: the currently-active `reference_data_versions` row
in Postgres, editable through the Reference Data screen (§11.7) with
effective-dating, an impact-preview gate, and audit (§6.5). No caching: the
whole point of admin-editable config is that activating a new version takes
effect on the very next calculation, not after a process restart.

`get_abattoir_fixed_costs` and `get_operational_constants` stay exactly as
Phase 2/3 built them, seed-file-backed. Neither is a §6.5-style
source-of-truth input — the abattoir fixed costs only reproduce the
abattoir's own benchmark formula for cross-checking (§5.2), and the
operational constants (bid-check threshold, weight-band tolerance, stale-
instruction hours) tune supporting UX, not `AC` — so neither needs the
versioning/impact-preview/audit machinery this phase adds. `EverhealthConfig`
itself (domain/engine/config.py) and its `from_seed_json` loader are
untouched; `from_values` is what the DB-backed path uses now.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from domain.engine.config import EverhealthConfig
from models.enums import ReferenceDataTableKey
from repositories import reference_data as reference_data_repo

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SEED_PATH = _BACKEND_ROOT.parent / "fixtures" / "reference-data-seed.json"


def _seed_path() -> Path:
    if settings.reference_data_seed_path:
        return Path(settings.reference_data_seed_path)
    return _DEFAULT_SEED_PATH


class NoActiveReferenceDataError(Exception):
    """Raised if reference_data_versions has no active row — should never
    happen past the Phase 3b migration, which seeds and activates one, but
    the engine must never silently fall back to the seed file once the DB
    is the source of truth: that would let a stale file value outlive an
    admin's deliberate change."""


async def get_active_everhealth_config(db: AsyncSession) -> EverhealthConfig:
    version = await reference_data_repo.get_active_version(db)
    if version is None:
        raise NoActiveReferenceDataError()

    entries = await reference_data_repo.list_entries(db, version.id)

    cif_buffer_per_kg: Decimal | None = None
    dnbp_factor_by_species: dict[str, Decimal] = {}
    standard_weight_by_species: dict[str, Decimal] = {}

    for entry in entries:
        if entry.table_key == ReferenceDataTableKey.CIF_BUFFER_PER_KG:
            cif_buffer_per_kg = entry.value
        elif entry.table_key == ReferenceDataTableKey.DNBP_FACTOR:
            dnbp_factor_by_species[entry.key1] = entry.value
        elif entry.table_key == ReferenceDataTableKey.STANDARD_WEIGHT:
            standard_weight_by_species[entry.key1] = entry.value

    if cif_buffer_per_kg is None:
        raise NoActiveReferenceDataError()

    return EverhealthConfig(
        cif_buffer_per_kg=cif_buffer_per_kg,
        dnbp_factor_by_species=dnbp_factor_by_species,
        standard_weight_by_species=standard_weight_by_species,
        ref_data_version=version.effective_from.date().isoformat(),
    )


@lru_cache
def get_abattoir_fixed_costs() -> tuple[Decimal, Decimal]:
    """(fixed_cost_per_head_active, fixed_cost_per_head_loaded) — §6.7's
    40/34 constants used only to reproduce the abattoir's own Gayan `T`
    formula for the §5.2 cross-check. Not a workbook table (see
    domain/ingestion/lookup_sheet.py's module docstring) — sourced from the
    seed file, same as Everhealth's own constants."""
    data = json.loads(_seed_path().read_text())
    values = data["abattoir"]["benchmark_fixed_cost_per_head"]["values"]
    return Decimal(str(values["ACTIVE"])), Decimal(str(values["LOADED"]))


@dataclass(frozen=True, slots=True)
class OperationalConstants:
    """§6.7's operational tunables that Phase 3 needs and Phase 1/2 had no
    use for yet: Bid Check's PASS/CLOSE threshold (§12.3), the buyer's
    displayed weight band tolerance around a species' standard weight
    (§12.2, D10), and the "instruction is stale" banner threshold (§3,
    §12.2). None of these are source-of-truth inputs (§6.5) — they tune
    supporting UX, not `AC` — so they carry none of the impact-preview/
    audit machinery reserved for the DNBP factor table and cif_buffer."""

    bid_check_close_threshold_pct: Decimal
    buyer_weight_band_tolerance_pct: Decimal
    stale_instruction_hours: int


@lru_cache
def get_operational_constants() -> OperationalConstants:
    data = json.loads(_seed_path().read_text())
    values = data["everhealth"]["operational_constants"]
    return OperationalConstants(
        bid_check_close_threshold_pct=Decimal(str(values["bid_check_close_threshold_pct"])),
        buyer_weight_band_tolerance_pct=Decimal(str(values["buyer_weight_band_tolerance_pct"])),
        stale_instruction_hours=int(values["stale_instruction_hours"]),
    )
