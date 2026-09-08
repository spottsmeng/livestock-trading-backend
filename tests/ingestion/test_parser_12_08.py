"""Parses the 12-08 file end to end. This file is the layout-drift
evidence case (§7.1): a different header row, a different ID-column
header, Excel serial-number loadout dates on its loaded lines, and —
critically — two sheets whose title cell both read "ACTIVE ORDERS",
resolved by the richer-candidate tiebreak in domain/ingestion/layout.py.
"""

import datetime
from decimal import Decimal

from domain.engine.workings import Lifecycle
from domain.ingestion.types import BenchmarkMethod
from tests.ingestion.helpers import FILE_12_08, parse_file


def test_layout_tiebreak_picks_the_richer_sheet():
    """Both `Orders Loaded` and `Profitability Analysis` title-match ACTIVE
    ORDERS. `Profitability Analysis` carries more real contracts (31 vs 27)
    and is the sheet PRD §7.1's own header/benchmark claims for this file
    actually describe — the tiebreak must land there, and must record both
    candidates it considered."""
    snapshot = parse_file(FILE_12_08)
    layout = snapshot.detected_layout
    assert layout.strategy == "tiebreak"
    assert layout.active.sheet_name == "Profitability Analysis"
    assert len(layout.candidates_considered) == 2
    considered_sheets = {c["sheet"] for c in layout.candidates_considered}
    assert considered_sheets == {"Orders Loaded", "Profitability Analysis"}


def test_active_and_loaded_counts():
    snapshot = parse_file(FILE_12_08)
    assert len(snapshot.active_lines) == 31
    assert len(snapshot.loaded_lines) == 17


def test_cost_column_header_has_expected_prefix():
    """§7.1: this file's cost column header is "EXPECTED Livestock Cost per
    kg (HSCW)", not "Livestock Cost per kg (HSCW)" — both map to the same
    field regardless."""
    snapshot = parse_file(FILE_12_08)
    line = next(line for line in snapshot.active_lines if line.contract_no == "CED18650")
    assert line.expected_livestock_cost_per_kg == Decimal("8.4")


def test_benchmark_column_is_financier_margin_via_column_s():
    snapshot = parse_file(FILE_12_08)
    line = next(line for line in snapshot.active_lines if line.contract_no == "CED18650")
    assert line.benchmark_method == BenchmarkMethod.FINANCIER_MARGIN
    # S = K / (1 + required_margin[SHEEP]) = 9.84492753623188 / 1.20, as
    # cached by the workbook itself (verified directly against the file).
    assert line.dnbp_benchmark == Decimal("8.20410628019324")


def test_excel_serial_loadout_dates_convert_on_loaded_lines():
    """§7.2 pt 8 — this file's loaded section stores loadout dates as bare
    Excel serial integers (e.g. 46212), not native dates."""
    snapshot = parse_file(FILE_12_08)
    line = next(line for line in snapshot.loaded_lines if line.contract_no == "CED18654")
    assert line.loadout_date == datetime.date(2026, 7, 9)


def test_mutton_is_loaded_only():
    snapshot = parse_file(FILE_12_08)
    mutton_lines = [line for line in snapshot.lines if line.species == "MUTTON"]
    assert len(mutton_lines) == 1
    assert mutton_lines[0].lifecycle is Lifecycle.LOADED
