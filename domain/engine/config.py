"""Everhealth-owned reference configuration that drives the engine (PRD §6).

Plain, in-memory, effective-dated snapshot. Loading a snapshot from Postgres
(reference_data_versions/reference_data_entries, §8) is a later phase's
concern — this module only defines the shape and a JSON-loading convenience
for tests and local bootstrap scripts, which is why `from_seed_json` is the
one function here allowed to touch the filesystem.

species is a plain `str` key into these dicts, never an Enum/Literal — it is
an open, admin-managed registry (§6.9), not a closed type.
"""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any


def _to_decimal(value: Any) -> Decimal:
    """Convert via str() so a JSON float's binary imprecision is never
    imported into the Decimal — Decimal(0.3) != Decimal("0.3")."""
    return Decimal(str(value))


@dataclass(frozen=True, slots=True)
class EverhealthConfig:
    cif_buffer_per_kg: Decimal
    dnbp_factor_by_species: dict[str, Decimal] = field(default_factory=dict)
    standard_weight_by_species: dict[str, Decimal] = field(default_factory=dict)
    ref_data_version: str = "unversioned"

    @classmethod
    def from_values(
        cls,
        *,
        cif_buffer_per_kg: Any,
        dnbp_factor_by_species: dict[str, Any],
        standard_weight_by_species: dict[str, Any] | None = None,
        ref_data_version: str = "unversioned",
    ) -> "EverhealthConfig":
        return cls(
            cif_buffer_per_kg=_to_decimal(cif_buffer_per_kg),
            dnbp_factor_by_species={k: _to_decimal(v) for k, v in dnbp_factor_by_species.items()},
            standard_weight_by_species={k: _to_decimal(v) for k, v in (standard_weight_by_species or {}).items()},
            ref_data_version=ref_data_version,
        )

    @classmethod
    def from_seed_json(cls, path: str | Path) -> "EverhealthConfig":
        """Build a config from fixtures/reference-data-seed.json's shape (or
        any file matching it). The caller supplies the path explicitly —
        this module stays a pure, filesystem-agnostic dataclass loader and
        never hardcodes where the seed file lives (callers like
        core/reference_data.py and tests/engine/helpers.py own that)."""
        data = json.loads(Path(path).read_text())
        everhealth = data["everhealth"]
        return cls.from_values(
            cif_buffer_per_kg=everhealth["cif_buffer_per_kg"]["value"],
            dnbp_factor_by_species=everhealth["dnbp_factor_by_species"]["values"],
            standard_weight_by_species=everhealth["standard_weight_by_species"]["values"],
            ref_data_version=data.get("effective_from", "unversioned"),
        )
