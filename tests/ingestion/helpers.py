"""Shared test-only helpers for parsing the two real supplied workbooks.
Path resolution mirrors tests/engine/helpers.py's own convention."""

from decimal import Decimal
from pathlib import Path

from domain.ingestion.workbook import ParsedSnapshot, parse

PROJECT_ROOT = Path(__file__).resolve().parents[3]

FILE_07_08 = PROJECT_ROOT / "Active Purchase Orders 07-08-2026 (WORKING).xlsx"
FILE_12_08 = PROJECT_ROOT / "Active Purchase Orders 12-08-2026.xlsx"

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
