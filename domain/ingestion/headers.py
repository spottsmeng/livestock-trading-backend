"""Header-text column mapping (PRD §7.2 points 1-2).

Never map by column letter or fixed cell address. A sheet's header row is
located by scanning for known header tokens, and each column is mapped to a
field name by normalising its header text and matching it against a synonym
registry — verified against both real workbooks, where the same field lands
on different letters (the benchmark column is `T` in one file, `S` in the
other) and even the header row index differs (7 vs 4).
"""

import re
from dataclasses import dataclass

MAX_HEADER_SCAN_ROWS = 20
MIN_HEADER_MATCHES = 6

# field name -> set of normalised header texts that map to it. Extended
# beyond PRD §7.2's sketch with every header actually observed in the two
# supplied workbooks (see domain/ingestion — verified by opening both files
# with openpyxl in both data_only modes).
SYNONYMS: dict[str, frozenset[str]] = {
    "contract_no": frozenset({"row labels", "contract no", "contract no.", "order number"}),
    "customer_name": frozenset({"customer name"}),
    "species": frozenset({"type", "species"}),
    "loadout_date": frozenset({"loadout date"}),
    "qty_kg": frozenset({"sum of total qty", "total qty", "qty"}),
    "avg_price_aud": frozenset({"average of price aud", "avg price aud", "price aud"}),
    "amount_aud": frozenset({"sum of amount aud", "amount aud"}),
    "product_type": frozenset({"product type"}),
    "incoterm": frozenset({"cif or fas ?", "cif or fas", "incoterm"}),
    "nrv_per_kg": frozenset({"nrv per kg", "nrv (per kg)"}),
    "expected_livestock_cost_per_kg": frozenset(
        {
            "livestock cost per kg hscw",
            "expected livestock cost per kg hscw",
        }
    ),
    "pack_cost_ph": frozenset({"pack cost"}),
    "offal_return_ph": frozenset({"offal return ph"}),
    "skin_return_ph": frozenset({"avg skin return", "skin return"}),
    "avg_weight_kg": frozenset({"avg weight", "average weight"}),
    "mom_ph": frozenset({"mom ph"}),
    "deposit_received": frozenset({"deposit received"}),
    "comments": frozenset({"comments"}),
    # Both benchmark spellings map to the same field; benchmark.py decides
    # GAYAN_FIXED_COST vs FINANCIER_MARGIN from the header text separately.
    "dnbp_benchmark": frozenset(
        {
            "do not buy price",
            # normalise() strips punctuation (including "%") from real
            # header text before comparison, so this entry must already be
            # in that stripped form or it can never match.
            "do not buy price using method instructed by the financier",
        }
    ),
    "estimated_heads": frozenset({"estimated number of heads required"}),
    "total_livestock_cost": frozenset({"total livestock cost"}),
}

_PUNCTUATION_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalise(text: object) -> str:
    """Lowercase, strip punctuation, collapse whitespace. The one function
    every header/enum comparison in this package goes through."""
    if text is None:
        return ""
    s = str(text).strip().lower()
    s = s.replace("_", " ")  # real headers use "_" as a stray word separator (e.g. "Price_Using")
    s = _PUNCTUATION_RE.sub("", s)
    s = _WHITESPACE_RE.sub(" ", s)
    return s.strip()


def tokenize(text: object) -> frozenset[str]:
    """Word-set of a normalised string, order-independent. Used for the
    marker-row / title-cell tests below — real data writes "LOADED ORDERS"
    in one sheet and "ORDERS LOADED" in another, purely from manual
    inconsistency, so word order must never matter."""
    return frozenset(normalise(text).split())


_HEADER_LOOKUP: dict[str, str] = {synonym: field for field, synonyms in SYNONYMS.items() for synonym in synonyms}


def map_header_cell(text: object) -> str | None:
    """Field name for one header cell's text, or None if unrecognised. An
    unrecognised header is not an error — it's a column this system doesn't
    need (or a future column); the row can still be a valid header row via
    the other cells."""
    return _HEADER_LOOKUP.get(normalise(text))


@dataclass(frozen=True, slots=True)
class HeaderRow:
    row_index: int  # 1-based, openpyxl convention
    column_map: dict[int, str]  # 1-based column index -> field name
    match_count: int


def find_header_row(
    sheet, *, start_row: int = 1, max_scan_rows: int = MAX_HEADER_SCAN_ROWS
) -> HeaderRow | None:
    """Scan up to `max_scan_rows` rows of `sheet` starting at `start_row`
    (an openpyxl worksheet opened with data_only=True — header text is never
    a formula) for a row whose cells match >= MIN_HEADER_MATCHES
    synonym-registry entries. Returns the best-matching row in that window,
    or None if no row qualifies. `start_row` lets a caller re-scan for a
    second, re-declared header row below a LOADED-section marker, which the
    real files do (§7.2 pt 3) rather than repeating the ACTIVE header."""
    best: HeaderRow | None = None
    last_row = min(start_row + max_scan_rows - 1, sheet.max_row)
    for row_idx in range(start_row, last_row + 1):
        column_map: dict[int, str] = {}
        seen_fields: set[str] = set()
        for col_idx in range(1, sheet.max_column + 1):
            field = map_header_cell(sheet.cell(row=row_idx, column=col_idx).value)
            # First occurrence wins. The 07-08 file's own X-AF "workings
            # echo" block re-uses identical header text for several columns
            # ("Average of Price AUD" appears at both G and X, "Pack Cost"
            # at both M and Y, ...) — the received A-V column always comes
            # first (§1.2's ownership boundary is A-V *then* X-AF), so a
            # later duplicate is the workings echo, never the source value,
            # and must not overwrite the real mapping.
            if field is not None and field not in seen_fields:
                column_map[col_idx] = field
                seen_fields.add(field)
        if len(column_map) >= MIN_HEADER_MATCHES and (best is None or len(column_map) > best.match_count):
            best = HeaderRow(row_index=row_idx, column_map=column_map, match_count=len(column_map))
    return best
