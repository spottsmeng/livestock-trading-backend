"""Cell-level normalisation rules (PRD §7.2 points 4, 6, 7, 8).

Each function here handles exactly one rule so the parser's row-building
code reads as a checklist against the spec, not a wall of ad-hoc string
munging.
"""

import datetime
from decimal import Decimal, InvalidOperation

BLANK_LITERAL = "(blank)"
EXCEL_EPOCH = datetime.date(1899, 12, 30)  # Excel's day-0, including the historical leap-year bug


def normalise_text(value: object) -> str | None:
    """Strip whitespace on every text field (point 6) — real data carries a
    trailing space on "BOUNTY FOODS ". Returns None for blank/empty."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalise_enum_value(value: object) -> str | None:
    """Case-insensitive, whitespace-trimmed normalisation for open-registry
    values (species, product_type) — point 6. "6 Way" / "6 WAY" / "6way" all
    collapse to the same stored code. This does NOT reject unrecognised
    values (§6.9) — it only canonicalises casing/spacing so the same real
    value is never stored as two different registry codes."""
    text = normalise_text(value)
    if text is None:
        return None
    collapsed = "_".join(text.upper().split())
    return collapsed.replace("-", "_")


def resolve_blank(value: object) -> object:
    """The literal pivot-table artefact string "(blank)" means null
    (point 7) — checked verbatim, not folded into general text handling,
    since it's a specific artefact of these files' pivot-table origin."""
    if isinstance(value, str) and value.strip() == BLANK_LITERAL:
        return None
    return value


def to_date(value: object) -> datetime.date | None:
    """Convert a loadout-date cell. Handles three shapes seen across the two
    real files: the "(blank)" literal, a native datetime (07-08 file, where
    openpyxl recognises the cell's date format), and a bare Excel serial
    integer (12-08 file's loaded section, e.g. 46212) — point 8."""
    value = resolve_blank(value)
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, (int, float)):
        return EXCEL_EPOCH + datetime.timedelta(days=int(value))
    return None


def to_decimal(value: object) -> Decimal | None:
    """Never Decimal(a_float) directly — that imports the float's own binary
    imprecision. Always go via str(), matching domain/engine/config.py's
    own `_to_decimal` convention."""
    value = resolve_blank(value)
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def is_grand_total_row(id_cell_text: object, qty_cell_value: object) -> bool:
    """Point 5 — skip a row if its ID cell reads "Grand Total" (any casing)
    or the ID cell is blank while a numeric column is populated (the
    sub-total row pattern seen at the foot of each section)."""
    from domain.ingestion.headers import tokenize

    if {"grand", "total"} <= tokenize(id_cell_text):
        return True
    return normalise_text(id_cell_text) is None and qty_cell_value not in (None, "")


def is_formula_cell(raw_formula_value: object) -> bool:
    """True if the corresponding data_only=False read is a formula, not a
    literal. A plain string that happens to start with "=" is exceedingly
    unlikely in these numeric columns and openpyxl already distinguishes
    formula cells this way at the object level."""
    return isinstance(raw_formula_value, str) and raw_formula_value.startswith("=")
