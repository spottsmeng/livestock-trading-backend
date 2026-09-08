"""Orchestrates headers.py / layout.py / cells.py / benchmark.py /
lookup_sheet.py into a `ParsedSnapshot` — the one entry point the API/service
layer calls. Everything below this module is pure dataclasses in, pure
dataclasses out; this module is the sole place that touches `openpyxl` and
raw file bytes.
"""

import io
from dataclasses import dataclass, field
from decimal import Decimal

import openpyxl

from domain.engine.crosscheck import AbattoirReferenceTables
from domain.engine.workings import Lifecycle
from domain.ingestion import cells
from domain.ingestion.benchmark import classify_benchmark_header
from domain.ingestion.headers import find_header_row, normalise
from domain.ingestion.layout import DetectedLayout, detect_layout
from domain.ingestion.lookup_sheet import find_lookup_sheet_name, parse_abattoir_tables
from domain.ingestion.types import BenchmarkMethod, ValueSource

PARSER_VERSION = "ingestion-v1"

# §5.1 / §7.2 pt 4: exactly these columns arrive already computed by the
# abattoir's own formulas, so only these are checked for a hand-set literal.
_FORMULA_DRIVEN_FIELDS = frozenset(
    {
        "nrv_per_kg",
        "pack_cost_ph",
        "offal_return_ph",
        "skin_return_ph",
        "mom_ph",
        "dnbp_benchmark",
        "estimated_heads",
        "total_livestock_cost",
    }
)

_DECIMAL_FIELDS = frozenset(
    {
        "qty_kg",
        "avg_price_aud",
        "amount_aud",
        "nrv_per_kg",
        "expected_livestock_cost_per_kg",
        "pack_cost_ph",
        "offal_return_ph",
        "skin_return_ph",
        "avg_weight_kg",
        "mom_ph",
        "deposit_received",
        "dnbp_benchmark",
        "estimated_heads",
        "total_livestock_cost",
    }
)
_ENUM_FIELDS = frozenset({"species", "product_type", "incoterm"})
_TEXT_FIELDS = frozenset({"contract_no", "customer_name", "comments"})
_DATE_FIELDS = frozenset({"loadout_date"})


@dataclass(frozen=True, slots=True)
class ParsedOrderLine:
    line_no: int
    lifecycle: Lifecycle
    source_sheet: str
    source_row: int
    contract_no: str | None = None
    customer_name: str | None = None
    species: str | None = None
    loadout_date: object = None  # datetime.date | None
    qty_kg: Decimal | None = None
    avg_price_aud: Decimal | None = None
    amount_aud: Decimal | None = None
    product_type: str | None = None
    incoterm: str | None = None
    nrv_per_kg: Decimal | None = None
    expected_livestock_cost_per_kg: Decimal | None = None
    pack_cost_ph: Decimal | None = None
    offal_return_ph: Decimal | None = None
    skin_return_ph: Decimal | None = None
    avg_weight_kg: Decimal | None = None
    mom_ph: Decimal | None = None
    deposit_received: Decimal | None = None
    comments: str | None = None
    dnbp_benchmark: Decimal | None = None
    benchmark_method: BenchmarkMethod | None = None
    estimated_heads: Decimal | None = None
    total_livestock_cost: Decimal | None = None
    value_sources: dict[str, ValueSource] = field(default_factory=dict)

    def identity_key(self) -> tuple:
        """Best-effort stable identity for diffing across snapshots (§7.3).
        contract_no alone is not unique (§5.1) — one contract can split
        across species/product-type/incoterm rows in the real data."""
        return (self.contract_no, self.species, self.product_type, self.incoterm)


@dataclass(frozen=True, slots=True)
class ParsedSnapshot:
    source_filename: str
    parser_version: str
    detected_layout: DetectedLayout
    abattoir_tables: AbattoirReferenceTables
    lines: list[ParsedOrderLine]

    @property
    def active_lines(self) -> list[ParsedOrderLine]:
        return [line for line in self.lines if line.lifecycle is Lifecycle.ACTIVE]

    @property
    def loaded_lines(self) -> list[ParsedOrderLine]:
        return [line for line in self.lines if line.lifecycle is Lifecycle.LOADED]


def parse(
    file_bytes: bytes,
    *,
    filename: str,
    cif_buffer_per_kg: Decimal,
    fixed_cost_per_head_active: Decimal,
    fixed_cost_per_head_loaded: Decimal,
) -> ParsedSnapshot:
    wb_values = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    wb_formulas = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=False)

    layout = detect_layout(wb_values)

    lines: list[ParsedOrderLine] = []
    line_no = 0
    for lifecycle, section in ((Lifecycle.ACTIVE, layout.active), (Lifecycle.LOADED, layout.loaded)):
        if section is None:
            continue
        header = find_header_row(
            wb_values[section.sheet_name], start_row=section.header_row, max_scan_rows=1
        )
        if header is None:
            # Defensive — layout.py only ever returns a section whose header
            # row it already validated. Re-derive rather than trust a stale
            # index if that invariant is ever weakened later.
            header = find_header_row(wb_values[section.sheet_name])
        sheet_values = wb_values[section.sheet_name]
        sheet_formulas = wb_formulas[section.sheet_name]
        benchmark_method = _detect_benchmark_method(sheet_values, header.column_map, header.row_index)

        for row_idx in range(section.data_row_start, section.data_row_end):
            parsed_row = _parse_row(
                sheet_values,
                sheet_formulas,
                row_idx,
                header.column_map,
                benchmark_method=benchmark_method,
            )
            if parsed_row is None:
                continue
            line_no += 1
            lines.append(
                ParsedOrderLine(
                    line_no=line_no,
                    lifecycle=lifecycle,
                    source_sheet=section.sheet_name,
                    source_row=row_idx,
                    **parsed_row,
                )
            )

    lookup_sheet_name = find_lookup_sheet_name(wb_values)
    if lookup_sheet_name is not None:
        abattoir_tables = parse_abattoir_tables(
            wb_values[lookup_sheet_name],
            cif_buffer_per_kg=cif_buffer_per_kg,
            fixed_cost_per_head_active=fixed_cost_per_head_active,
            fixed_cost_per_head_loaded=fixed_cost_per_head_loaded,
        )
    else:
        abattoir_tables = AbattoirReferenceTables(
            cif_buffer_per_kg=cif_buffer_per_kg,
            fixed_cost_per_head_active=fixed_cost_per_head_active,
            fixed_cost_per_head_loaded=fixed_cost_per_head_loaded,
        )

    return ParsedSnapshot(
        source_filename=filename,
        parser_version=PARSER_VERSION,
        detected_layout=layout,
        abattoir_tables=abattoir_tables,
        lines=lines,
    )


def _detect_benchmark_method(sheet_values, column_map: dict[int, str], header_row: int) -> BenchmarkMethod | None:
    benchmark_col = next((col for col, field_name in column_map.items() if field_name == "dnbp_benchmark"), None)
    if benchmark_col is None:
        return None
    header_text = sheet_values.cell(row=header_row, column=benchmark_col).value
    return classify_benchmark_header(header_text)


def _parse_row(
    sheet_values,
    sheet_formulas,
    row_idx: int,
    column_map: dict[int, str],
    *,
    benchmark_method: BenchmarkMethod | None,
) -> dict | None:
    id_col = next((col for col, f in column_map.items() if f == "contract_no"), None)
    qty_col = next((col for col, f in column_map.items() if f == "qty_kg"), None)
    id_value = sheet_values.cell(row=row_idx, column=id_col).value if id_col else None
    qty_value = sheet_values.cell(row=row_idx, column=qty_col).value if qty_col else None
    if cells.is_grand_total_row(id_value, qty_value):
        return None
    if normalise(id_value) == "" and normalise(qty_value) == "":
        return None  # a fully blank row inside the range (spacer row)

    result: dict = {}
    value_sources: dict[str, ValueSource] = {}

    for col_idx, field_name in column_map.items():
        raw_value = sheet_values.cell(row=row_idx, column=col_idx).value
        raw_value = cells.resolve_blank(raw_value)

        if field_name in _DATE_FIELDS:
            result[field_name] = cells.to_date(raw_value)
        elif field_name in _ENUM_FIELDS:
            result[field_name] = cells.normalise_enum_value(raw_value)
        elif field_name in _TEXT_FIELDS:
            result[field_name] = cells.normalise_text(raw_value)
        elif field_name in _DECIMAL_FIELDS:
            result[field_name] = cells.to_decimal(raw_value)
        else:
            result[field_name] = raw_value

        if field_name in _FORMULA_DRIVEN_FIELDS and raw_value is not None:
            formula_value = sheet_formulas.cell(row=row_idx, column=col_idx).value
            value_sources[field_name] = (
                ValueSource.FORMULA if cells.is_formula_cell(formula_value) else ValueSource.HAND_SET
            )

    if "dnbp_benchmark" in result and result["dnbp_benchmark"] is not None:
        result["benchmark_method"] = benchmark_method

    result["value_sources"] = value_sources
    return result
