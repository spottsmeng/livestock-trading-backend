"""Shared test-only helpers for parsing the two real supplied workbooks.
Path resolution mirrors tests/engine/helpers.py's own convention — both
workbooks are vendored into backend/fixtures/ (see that directory's
README.md)."""

from decimal import Decimal
from pathlib import Path

from domain.ingestion.workbook import ParsedSnapshot, parse

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"

FILE_07_08 = FIXTURES_DIR / "Active Purchase Orders 07-08-2026 (WORKING).xlsx"
FILE_12_08 = FIXTURES_DIR / "Active Purchase Orders 12-08-2026.xlsx"

DEFAULT_CIF_BUFFER = Decimal("0.30")
DEFAULT_FIXED_COST_ACTIVE = Decimal(40)
DEFAULT_FIXED_COST_LOADED = Decimal(34)


def parse_file(path: Path) -> ParsedSnapshot:
    return parse(
        path.read_bytes(),
        filename=path.name,
        cif_buffer_per_kg=DEFAULT_CIF_BUFFER,
        fixed_cost_per_head_active=DEFAULT_FIXED_COST_ACTIVE,
        fixed_cost_per_head_loaded=DEFAULT_FIXED_COST_LOADED,
    )
