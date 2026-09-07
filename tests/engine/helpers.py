"""Shared test-only helpers for loading fixtures/engine-test-vectors.json.
Not part of domain/engine — this filesystem/json work belongs in tests, not
in the pure engine package."""

import json
from decimal import Decimal
from pathlib import Path

from domain.engine.config import EverhealthConfig

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"
VECTORS_PATH = FIXTURES_DIR / "engine-test-vectors.json"

TOLERANCE = Decimal("1E-10")  # matches the fixture file's own "tolerance": 1e-10


def dec(value) -> Decimal:
    """Never Decimal(a_float) — that imports the float's own binary
    imprecision. Always go via str()."""
    return Decimal(str(value))


def load_vectors() -> dict:
    return json.loads(VECTORS_PATH.read_text())


def config_from_engine_config(species: str, engine_config: dict) -> EverhealthConfig:
    """Build a config from a single vector's own `engine_config` block —
    each vector pins its own inputs for §5.6 reproducibility, rather than
    all vectors sharing one mutable global config."""
    return EverhealthConfig.from_values(
        cif_buffer_per_kg=engine_config["cif_buffer"],
        dnbp_factor_by_species={species: engine_config["dnbp_factor_for_species"]},
        standard_weight_by_species={species: engine_config["standard_weight_for_species"]},
    )


def config_from_reference_tables(reference_tables: dict) -> EverhealthConfig:
    """Build a config from the fixture's top-level `reference_tables_used`
    block, covering every species in one place."""
    return EverhealthConfig.from_values(
        cif_buffer_per_kg=reference_tables["everhealth_cif_buffer"],
        dnbp_factor_by_species=reference_tables["everhealth_dnbp_factor_by_species"],
        standard_weight_by_species=reference_tables["everhealth_standard_weight_by_species"],
    )


def assert_decimal_close(actual: Decimal | None, expected_raw, *, label: str) -> None:
    """§17.3 / the fixtures' own tolerance: match to 10 decimal places, not
    'close enough' via float math.isclose."""
    assert actual is not None, f"{label}: expected a Decimal, got None"
    expected = dec(expected_raw)
    diff = abs(actual - expected)
    assert diff <= TOLERANCE, f"{label}: {actual} != {expected} (diff {diff} > tolerance {TOLERANCE})"
