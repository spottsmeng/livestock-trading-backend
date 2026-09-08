"""ACTIVE vs LOADED segmentation (PRD §7.2 point 3, §5.3).

Detected by scanning for marker text, never by assuming a fixed row range.
Two real-file wrinkles this module exists to handle:

1. The marker's word order is inconsistent between files — "LOADED ORDERS"
   in one sheet, "ORDERS LOADED" in another, purely a manual-process
   artefact (confirmed with the business). Every marker test here is a
   token-set comparison, never a fixed phrase or regex anchored to word
   order.
2. The 12-08 workbook has *two* sheets whose title cell reads "ACTIVE
   ORDERS" (`Orders Loaded` and `Profitability Analysis` — verified by
   opening the file; PRD §7.1's sheet-name table alone does not disambiguate
   this). When more than one sheet's title matches, the richer candidate
   wins — highest header-synonym match count, then highest active-row
   count — a general scoring rule, not a per-file special case. Every
   candidate considered is recorded on the result so `detected_layout`
   (§8) can show why a sheet was picked.
"""

from dataclasses import dataclass, field

from domain.ingestion import cells
from domain.ingestion.headers import HeaderRow, find_header_row, tokenize

TITLE_SCAN_ROWS = 6
ACTIVE_TOKENS = frozenset({"active", "orders"})
LOADED_TOKENS = frozenset({"loaded", "orders"})


class LayoutDetectionError(Exception):
    """No sheet in the workbook could be identified as the active-orders
    sheet. Raised, never guessed — an ingestion failure here must surface
    to the uploader, not silently parse the wrong sheet."""


@dataclass(frozen=True, slots=True)
class SectionLocation:
    sheet_name: str
    header_row: int
    data_row_start: int
    data_row_end: int  # exclusive


@dataclass(frozen=True, slots=True)
class DetectedLayout:
    strategy: str  # "single_match" | "tiebreak" (active-sheet selection)
    loaded_strategy: str  # "same_sheet_marker" | "separate_sheet" | "none"
    active: SectionLocation
    loaded: SectionLocation | None
    candidates_considered: list[dict] = field(default_factory=list)

    def as_jsonable(self) -> dict:
        """Shape persisted verbatim into order_snapshots.detected_layout
        (§8) — plain JSON-safe types only."""
        return {
            "strategy": self.strategy,
            "loaded_strategy": self.loaded_strategy,
            "active_sheet": self.active.sheet_name,
            "active_header_row": self.active.header_row,
            "loaded_sheet": self.loaded.sheet_name if self.loaded else None,
            "loaded_header_row": self.loaded.header_row if self.loaded else None,
            "candidates_considered": self.candidates_considered,
        }


def _title_cell_matches(sheet, tokens: frozenset[str], max_rows: int = TITLE_SCAN_ROWS) -> bool:
    last_row = min(max_rows, sheet.max_row)
    for row_idx in range(1, last_row + 1):
        for col_idx in range(1, sheet.max_column + 1):
            if tokens <= tokenize(sheet.cell(row=row_idx, column=col_idx).value):
                return True
    return False


def _find_marker_row(sheet, tokens: frozenset[str], id_column: int | None, start_row: int) -> int | None:
    columns = [id_column] if id_column is not None else list(range(1, sheet.max_column + 1))
    for row_idx in range(start_row, sheet.max_row + 1):
        for col_idx in columns:
            if tokens <= tokenize(sheet.cell(row=row_idx, column=col_idx).value):
                return row_idx
    return None


@dataclass(frozen=True, slots=True)
class _ActiveCandidate:
    sheet_name: str
    header: HeaderRow
    loaded_marker_row: int | None
    active_row_count: int


def _score(candidate: _ActiveCandidate) -> tuple[int, int]:
    # Row count first: a sheet actually carrying more of the business's
    # current forward book is a stronger signal of "this is the maintained
    # one" than a one-column difference in recognised headers (real files
    # show sheets that drop an incidental column like "Comments" to make
    # room for a new benchmark column, which must not count against them).
    # Header richness is still the tiebreaker when row counts agree.
    return (candidate.active_row_count, candidate.header.match_count)


def _count_real_rows(sheet, header: HeaderRow, start_row: int, end_row: int) -> int:
    """Rows in [start_row, end_row) that survive the same grand-total/blank
    filter the row-level parser applies (domain/ingestion/cells.py) — a
    sheet padded with extra blank rows before its LOADED marker must not
    outscore a denser sheet with the same real data."""
    id_col = next((col for col, f in header.column_map.items() if f == "contract_no"), None)
    qty_col = next((col for col, f in header.column_map.items() if f == "qty_kg"), None)
    count = 0
    for row_idx in range(start_row, end_row):
        id_value = sheet.cell(row=row_idx, column=id_col).value if id_col else None
        qty_value = sheet.cell(row=row_idx, column=qty_col).value if qty_col else None
        if cells.is_grand_total_row(id_value, qty_value):
            continue
        if cells.normalise_text(id_value) is None and cells.normalise_text(qty_value) is None:
            continue
        count += 1
    return count


def detect_layout(workbook_values) -> DetectedLayout:
    """`workbook_values` is an openpyxl Workbook opened with
    data_only=True. Marker/title text is never a formula, so only the
    values view is needed here."""
    candidates: list[_ActiveCandidate] = []
    for sheet_name in workbook_values.sheetnames:
        sheet = workbook_values[sheet_name]
        if not _title_cell_matches(sheet, ACTIVE_TOKENS):
            continue
        header = find_header_row(sheet)
        if header is None:
            continue
        id_column = next((col for col, field_name in header.column_map.items() if field_name == "contract_no"), None)
        loaded_marker_row = _find_marker_row(sheet, LOADED_TOKENS, id_column, header.row_index + 1)
        active_end = loaded_marker_row if loaded_marker_row is not None else sheet.max_row + 1
        active_row_count = _count_real_rows(sheet, header, header.row_index + 1, active_end)
        candidates.append(
            _ActiveCandidate(
                sheet_name=sheet_name,
                header=header,
                loaded_marker_row=loaded_marker_row,
                active_row_count=active_row_count,
            )
        )

    if not candidates:
        raise LayoutDetectionError(
            "No sheet's title cell matched an ACTIVE ORDERS marker — cannot locate the active-orders section."
        )

    candidates_considered = [
        {
            "sheet": c.sheet_name,
            "header_row": c.header.row_index,
            "header_match_count": c.header.match_count,
            "active_row_count": c.active_row_count,
        }
        for c in candidates
    ]

    if len(candidates) == 1:
        winner = candidates[0]
        strategy = "single_match"
    else:
        winner = max(candidates, key=_score)
        strategy = "tiebreak"

    active_end = winner.loaded_marker_row if winner.loaded_marker_row is not None else (
        workbook_values[winner.sheet_name].max_row + 1
    )
    active = SectionLocation(
        sheet_name=winner.sheet_name,
        header_row=winner.header.row_index,
        data_row_start=winner.header.row_index + 1,
        data_row_end=active_end,
    )

    loaded, loaded_strategy = _locate_loaded_section(workbook_values, winner)

    return DetectedLayout(
        strategy=strategy,
        loaded_strategy=loaded_strategy,
        active=active,
        loaded=loaded,
        candidates_considered=candidates_considered,
    )


def _locate_loaded_section(
    workbook_values, winner: _ActiveCandidate
) -> tuple[SectionLocation | None, str]:
    if winner.loaded_marker_row is not None:
        sheet = workbook_values[winner.sheet_name]
        # The LOADED section re-declares its own header row directly below
        # the marker — real files do this and it is not assumed identical
        # to the ACTIVE header (e.g. the 07-08 file's loaded header omits
        # the "Deposit Received" column present in the active header).
        loaded_header = find_header_row(sheet, start_row=winner.loaded_marker_row + 1, max_scan_rows=5)
        header_row = loaded_header.row_index if loaded_header else winner.loaded_marker_row
        data_start = (loaded_header.row_index + 1) if loaded_header else winner.loaded_marker_row + 1
        return (
            SectionLocation(
                sheet_name=winner.sheet_name,
                header_row=header_row,
                data_row_start=data_start,
                data_row_end=sheet.max_row + 1,
            ),
            "same_sheet_marker",
        )

    # Fallback per §7.2 pt 3: the workbook separates ACTIVE/LOADED by sheet
    # instead of a marker row within one sheet. Not exercised by either
    # supplied file (both use a same-sheet marker) but required behaviour
    # for a future file that genuinely does this.
    for sheet_name in workbook_values.sheetnames:
        if sheet_name == winner.sheet_name:
            continue
        sheet = workbook_values[sheet_name]
        if not _title_cell_matches(sheet, LOADED_TOKENS):
            continue
        header = find_header_row(sheet)
        if header is None:
            continue
        return (
            SectionLocation(
                sheet_name=sheet_name,
                header_row=header.row_index,
                data_row_start=header.row_index + 1,
                data_row_end=sheet.max_row + 1,
            ),
            "separate_sheet",
        )

    return None, "none"
