"""Loads the Everhealth reference-data seed (§6) for Phase 2's calculate
step. This phase deliberately does NOT build the versioned
reference_data_versions/reference_data_entries tables or the editable
Reference Data screen (§11.7) — effective-dating, impact preview, and
audit-gated edits are materially separate work, scoped to a later phase.
`ref_data_version` is still recorded on every order_workings row (as the
seed file's own `effective_from`), so nothing needs backfilling once the
real versioned table lands.
"""

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from core.config import settings
from domain.engine.config import EverhealthConfig

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SEED_PATH = _BACKEND_ROOT.parent / "fixtures" / "reference-data-seed.json"


def _seed_path() -> Path:
    if settings.reference_data_seed_path:
        return Path(settings.reference_data_seed_path)
    return _DEFAULT_SEED_PATH


@lru_cache
def get_everhealth_config() -> EverhealthConfig:
    return EverhealthConfig.from_seed_json(_seed_path())


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
