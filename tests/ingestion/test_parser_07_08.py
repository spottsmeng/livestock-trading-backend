"""Parses the 07-08 file end to end and checks every real-data fixture
case PRD §7.1/§7.2 calls out for it: single-sheet ACTIVE/LOADED marker
segmentation, the GOAT hand-set skin-return override, the Gayan `T`
benchmark, and the MUTTON-is-LOADED-only case (D1)."""

from decimal import Decimal

from domain.engine.workings import Lifecycle
from domain.ingestion.types import BenchmarkMethod, ValueSource
from tests.ingestion.helpers import FILE_07_08, parse_file


def test_active_and_loaded_counts():
    snapshot = parse_file(FILE_07_08)
    assert len(snapshot.active_lines) == 27
    assert len(snapshot.loaded_lines) == 16


def test_layout_detected_same_sheet_marker():
    snapshot = parse_file(FILE_07_08)
    layout = snapshot.detected_layout
    assert layout.strategy == "single_match"
    assert layout.loaded_strategy == "same_sheet_marker"
    assert layout.active.sheet_name == "Profitability Analysis"
    assert layout.loaded.sheet_name == "Profitability Analysis"


def test_ced18650_matches_prd_worked_example():
    """§5.4's worked example, verbatim."""
    snapshot = parse_file(FILE_07_08)
    line = next(line for line in snapshot.active_lines if line.contract_no == "CED18650")
    assert line.species == "SHEEP"
    assert line.product_type == "6_WAY"
    assert line.incoterm == "CIF"
    assert line.qty_kg == Decimal("25000")
    assert line.avg_price_aud == Decimal("10.144927536231885")
    assert line.skin_return_ph == Decimal("10")
    assert line.avg_weight_kg == Decimal("22")


def test_goat_hand_set_skin_return_flagged():
    """§5.2, §7.2 pt 4, D3 — every active GOAT line carries a hand-set 0.5
    where the abattoir's own table says 0. Must be used, not corrected."""
    snapshot = parse_file(FILE_07_08)
    goat_lines = [line for line in snapshot.active_lines if line.species == "GOAT"]
    assert len(goat_lines) == 11
    for line in goat_lines:
        assert line.skin_return_ph == Decimal("0.5")
        assert line.value_sources["skin_return_ph"] is ValueSource.HAND_SET


def test_benchmark_column_is_gayan_fixed_cost_via_column_t():
    snapshot = parse_file(FILE_07_08)
    for line in snapshot.active_lines:
        assert line.benchmark_method == BenchmarkMethod.GAYAN_FIXED_COST
        assert line.dnbp_benchmark is not None


def test_mutton_is_loaded_only():
    """D1 — MUTTON appears exactly once, and it is LOADED in every
    instance. No active MUTTON line exists in either supplied file."""
    snapshot = parse_file(FILE_07_08)
    mutton_lines = [line for line in snapshot.lines if line.species == "MUTTON"]
    assert len(mutton_lines) == 1
    assert mutton_lines[0].lifecycle is Lifecycle.LOADED
    assert mutton_lines[0].contract_no == "CED18656"


def test_bounty_foods_trailing_space_stripped():
    """§7.2 pt 6 — real data carries a trailing space on "BOUNTY FOODS "."""
    snapshot = parse_file(FILE_07_08)
    line = next(line for line in snapshot.lines if line.contract_no == "CEDD7085")
    assert line.customer_name == "BOUNTY FOODS"


def test_blank_loadout_date_is_none_on_active_lines():
    """§7.2 pt 7 — the literal "(blank)" pivot-table artefact means null."""
    snapshot = parse_file(FILE_07_08)
    assert all(line.loadout_date is None for line in snapshot.active_lines)


def test_abattoir_lookup_tables_parsed():
    snapshot = parse_file(FILE_07_08)
    tables = snapshot.abattoir_tables
    assert tables.pack_cost_by_product_type == {"CCS": Decimal(2), "6_WAY": Decimal(4), "FULL_BONE": Decimal(7)}
    assert tables.offal_return_ph_by_species["GOAT"] == Decimal(6)
    assert tables.skin_return_ph_by_species["GOAT"] == Decimal(0)  # the table's own value, not the hand-set 0.5
