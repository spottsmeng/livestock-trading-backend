"""Parse the abattoir's own lookup sheet (`Sheet1` in the 07-08 file,
`Inputs` in the 12-08 file — PRD §7.2 point 11) into an
`AbattoirReferenceTables` (the dataclass domain/engine/crosscheck.py already
defines and consumes — reused here, not redefined, so the cross-check at
calculate time and this parser agree on shape by construction).

Detected by content, never by the literal sheet name — a third file could
rename it again. Both real lookup sheets share one structural signature:
two anchor header cells whose text reads exactly "Offal" and "Skins",
each followed immediately below by a two-column (species, value) block.
The pack-cost-by-product-type block carries no such anchor in either real
file, so it is located instead as the left-most unclaimed two-column
(text, small positive number) block in the sheet's first ten rows.

Only pack cost, offal return and skin return are read from the workbook —
these are the tables that actually vary submission to submission and feed
§5.2's cross-check (§6.1-6.3). The two `fixed_cost_per_head_*` constants
used inside the abattoir's own Gayan formula (§6.7) are not a workbook
table at all — they come from the reference-data seed, passed in by the
caller, same as `cif_buffer_per_kg`.
"""

from decimal import Decimal

from domain.engine.crosscheck import AbattoirReferenceTables
from domain.ingestion.headers import normalise

MAX_SCAN_ROW = 12
MAX_SCAN_COL = 24


def _cell(sheet, row: int, col: int) -> object:
    if row < 1 or col < 1 or row > sheet.max_row or col > sheet.max_column:
        return None
    return sheet.cell(row=row, column=col).value


def _read_label_value_block(sheet, *, start_row: int, label_col: int, value_col: int) -> dict[str, Decimal]:
    """Read (label, value) pairs downward from `start_row` until the label
    cell is empty. Labels are normalised to the same uppercase registry-code
    form the parser uses for species/product_type elsewhere, so lookups
    against a `dict[str, Decimal]` built from parsed order lines line up."""
    result: dict[str, Decimal] = {}
    row = start_row
    while row <= sheet.max_row:
        label = _cell(sheet, row, label_col)
        if label is None or str(label).strip() == "":
            break
        value = _cell(sheet, row, value_col)
        if isinstance(value, (int, float, Decimal)):
            code = "_".join(str(label).strip().upper().split())
            result[code] = Decimal(str(value))
        row += 1
    return result


def _find_anchored_block(sheet, anchor_text: str) -> dict[str, Decimal]:
    """Find a cell whose normalised text equals `anchor_text` exactly, then
    read the (label, value) block starting one row below it — the label in
    the anchor's own column, the value one column to the right."""
    target = normalise(anchor_text)
    for row in range(1, min(MAX_SCAN_ROW, sheet.max_row) + 1):
        for col in range(1, min(MAX_SCAN_COL, sheet.max_column) + 1):
            if normalise(_cell(sheet, row, col)) == target:
                return _read_label_value_block(sheet, start_row=row + 1, label_col=col, value_col=col + 1)
    return {}


def _find_unanchored_numeric_block(sheet, *, claimed_columns: set[int]) -> dict[str, Decimal]:
    """The pack-cost-by-product-type block carries no header text in either
    real file. Located instead as the left-most two-column run, in the
    first ten rows, of (non-empty text, small positive number) pairs whose
    columns were not already claimed by an anchored block."""
    for col in range(1, min(MAX_SCAN_COL, sheet.max_column)):
        if col in claimed_columns or (col + 1) in claimed_columns:
            continue
        block = _read_label_value_block(sheet, start_row=1, label_col=col, value_col=col + 1)
        # A real label/value run starts somewhere in the first few rows and
        # has at least two entries — a single stray (label, number) pair
        # elsewhere in the sheet is not this table.
        if len(block) >= 2:
            return block
        for start_row in range(2, MAX_SCAN_ROW + 1):
            block = _read_label_value_block(sheet, start_row=start_row, label_col=col, value_col=col + 1)
            if len(block) >= 2:
                return block
    return {}


def is_lookup_sheet(sheet) -> bool:
    """Structural signature shared by both real lookup sheets: an "Offal"
    header cell and a "Skins" header cell, both within the first
    MAX_SCAN_ROW rows."""
    found_offal = found_skins = False
    for row in range(1, min(MAX_SCAN_ROW, sheet.max_row) + 1):
        for col in range(1, min(MAX_SCAN_COL, sheet.max_column) + 1):
            text = normalise(_cell(sheet, row, col))
            if text == "offal":
                found_offal = True
            elif text == "skins":
                found_skins = True
    return found_offal and found_skins


def find_lookup_sheet_name(workbook_values) -> str | None:
    for sheet_name in workbook_values.sheetnames:
        if is_lookup_sheet(workbook_values[sheet_name]):
            return sheet_name
    return None


def parse_abattoir_tables(
    sheet, *, cif_buffer_per_kg: Decimal, fixed_cost_per_head_active: Decimal, fixed_cost_per_head_loaded: Decimal
) -> AbattoirReferenceTables:
    offal = _find_anchored_block(sheet, "Offal")
    skins = _find_anchored_block(sheet, "Skins")

    claimed_columns: set[int] = set()
    for anchor_text in ("Offal", "Skins"):
        for row in range(1, min(MAX_SCAN_ROW, sheet.max_row) + 1):
            for col in range(1, min(MAX_SCAN_COL, sheet.max_column) + 1):
                if normalise(_cell(sheet, row, col)) == normalise(anchor_text):
                    claimed_columns.update({col, col + 1})

    pack_cost = _find_unanchored_numeric_block(sheet, claimed_columns=claimed_columns)

    return AbattoirReferenceTables(
        cif_buffer_per_kg=cif_buffer_per_kg,
        pack_cost_by_product_type=pack_cost,
        offal_return_ph_by_species=offal,
        skin_return_ph_by_species=skins,
        fixed_cost_per_head_active=fixed_cost_per_head_active,
        fixed_cost_per_head_loaded=fixed_cost_per_head_loaded,
    )
