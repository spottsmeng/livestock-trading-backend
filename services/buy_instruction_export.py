"""GET /buy-instructions/{id}/export?format=pdf|xlsx (§9.6, §13.1).

Both formats render from the same `BuyInstructionExportData` bundle
(`build_export_data`, below) so the two can never drift out of layout sync
with each other. Both reproduce the real v3 sample's structure verbatim:
header, line items, prepayment block (§6.8, with the Southern Central
footnotes), reconciliation block, summary block, signature block.

XLSX uses `openpyxl` (already a dependency, write-capable — no new library).
PDF uses `reportlab` (BSD-3-Clause, FOSS, pure-Python — no system Pango/
Cairo dependency the way WeasyPrint would need, which matters for a Railway
deployment) — added as a dependency for this phase.
"""

import io
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.reference_data import SaleyardCalendarEntry
from models.buy_instruction import BuyInstruction, BuyInstructionLine, BuyInstructionLineFill
from services.buy_instruction_service import ReconciliationSummary, SaleyardReconciliation, line_balance


@dataclass(slots=True)
class ExportLine:
    line: BuyInstructionLine
    fills: list[BuyInstructionLineFill]
    balance_kg: Decimal


@dataclass(slots=True)
class BuyInstructionExportData:
    instruction: BuyInstruction
    lines: list[ExportLine]
    saleyard_calendar: tuple[SaleyardCalendarEntry, ...]
    week_start: date
    week_end: date
    reconciliation: list[SaleyardReconciliation]
    summary: ReconciliationSummary
    prepared_by_name: str
    approved_by_name: str | None


def build_export_data(
    *,
    instruction: BuyInstruction,
    lines: list[BuyInstructionLine],
    fills_by_line: dict[uuid.UUID, list[BuyInstructionLineFill]],
    saleyard_calendar: tuple[SaleyardCalendarEntry, ...],
    week_start: date,
    week_end: date,
    reconciliation: list[SaleyardReconciliation],
    summary: ReconciliationSummary,
    prepared_by_name: str,
    approved_by_name: str | None,
) -> BuyInstructionExportData:
    export_lines = [
        ExportLine(
            line=line,
            fills=fills_by_line.get(line.id, []),
            balance_kg=line_balance(line, fills_by_line.get(line.id, [])),
        )
        for line in lines
    ]
    return BuyInstructionExportData(
        instruction=instruction,
        lines=export_lines,
        saleyard_calendar=saleyard_calendar,
        week_start=week_start,
        week_end=week_end,
        reconciliation=reconciliation,
        summary=summary,
        prepared_by_name=prepared_by_name,
        approved_by_name=approved_by_name,
    )


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:,.2f}"


def render_xlsx(data: BuyInstructionExportData) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Buy Instruction"

    bold = Font(bold=True)
    ws["A1"] = "Date"
    ws["B1"] = data.instruction.trade_date.isoformat()
    ws["B2"] = "ACTIVE ORDER PURCHASE INSTRUCTION"
    ws["B2"].font = Font(bold=True, size=14)
    ws["D2"] = f"{data.instruction.instruction_no} v{data.instruction.version}"

    headers = [
        "#",
        "Order number",
        "SCHW",
        "Expected no of head",
        "weight Requirement",
        "Do not buy price",
        "Peter's expectation",
        "Expected Livestock Cost",
        "Fills (kg)",
        "Balance",
    ]
    header_row = 3
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.font = bold

    row = header_row + 1
    for export_line in data.lines:
        line = export_line.line
        fills_text = "; ".join(f"{f.label}: {f.kg_amount:,.2f}kg" for f in export_line.fills)
        ws.cell(row=row, column=1, value=line.seq)
        ws.cell(row=row, column=2, value=line.contract_no)
        ws.cell(row=row, column=3, value=float(line.schw_kg))
        ws.cell(row=row, column=4, value=float(line.expected_heads))
        ws.cell(row=row, column=5, value=float(line.weight_requirement_kg))
        ws.cell(row=row, column=6, value=float(line.dnbp_per_kg))
        peters_expectation = float(line.peters_expectation) if line.peters_expectation is not None else None
        ws.cell(row=row, column=7, value=peters_expectation)
        ws.cell(row=row, column=8, value=float(line.expected_livestock_cost))
        ws.cell(row=row, column=9, value=fills_text)
        ws.cell(row=row, column=10, value=float(export_line.balance_kg))
        row += 1

    # Prepayment block (§6.8)
    row += 2
    ws.cell(row=row, column=2, value="Prepayment Requirements").font = bold
    row += 1
    ws.cell(row=row, column=2, value="Saleyard").font = bold
    ws.cell(row=row, column=3, value="Day").font = bold
    ws.cell(row=row, column=4, value="Amount (AUD)").font = bold
    row += 1
    for entry in data.saleyard_calendar:
        ws.cell(row=row, column=2, value=entry.saleyard)
        ws.cell(row=row, column=3, value=entry.day.title())
        ws.cell(row=row, column=4, value=float(entry.prepayment_aud))
        row += 1
    for entry in data.saleyard_calendar:
        if entry.note:
            ws.cell(row=row, column=2, value=f"* {entry.note}").alignment = Alignment(wrap_text=True)
            row += 1

    # Reconciliation block, grouped by whichever saleyards actually traded
    row += 2
    recon_title = f"Reconciliation ({data.week_start.isoformat()} - {data.week_end.isoformat()})"
    ws.cell(row=row, column=2, value=recon_title).font = bold
    row += 1
    ws.cell(row=row, column=2, value="Saleyard").font = bold
    ws.cell(row=row, column=3, value="SCHW").font = bold
    ws.cell(row=row, column=4, value="Heads").font = bold
    ws.cell(row=row, column=5, value="Actual Cost").font = bold
    row += 1
    for r in data.reconciliation:
        ws.cell(row=row, column=2, value=r.saleyard)
        ws.cell(row=row, column=3, value=float(r.schw_kg))
        ws.cell(row=row, column=4, value=r.heads)
        ws.cell(row=row, column=5, value=float(r.actual_cost))
        row += 1

    # Summary block
    row += 2
    ws.cell(row=row, column=2, value="Summary").font = bold
    row += 1
    summary_rows = [
        ("Actual Heads", data.summary.actual_heads, None),
        ("Expected Heads", data.summary.expected_heads, None),
        ("Ordered SCHW", data.summary.ordered_schw, "A"),
        ("Bought SCHW", data.summary.bought_schw, "B"),
        ("Surplus/shortfall SCHW", data.summary.surplus_shortfall_schw, "A - B"),
        ("Expected Cost", data.summary.expected_cost, "C"),
        ("Actual Cost", data.summary.actual_cost, "D"),
        ("Cost Variance", data.summary.cost_variance, "C - D"),
    ]
    for label, value, code in summary_rows:
        ws.cell(row=row, column=2, value=label)
        ws.cell(row=row, column=4, value=float(value))
        if code:
            ws.cell(row=row, column=5, value=code)
        row += 1

    # Signature block — real accounts, never a hard-coded/free-text stand-in
    row += 2
    ws.cell(row=row, column=2, value=f"Prepared by: {data.prepared_by_name}")
    ws.cell(row=row, column=6, value=f"Approved by: {data.approved_by_name or '(not yet approved)'}")

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def render_pdf(data: BuyInstructionExportData) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Heading1"], alignment=1)
    elements: list = []

    elements.append(Paragraph(f"Date: {data.instruction.trade_date.isoformat()}", styles["Normal"]))
    elements.append(Paragraph("ACTIVE ORDER PURCHASE INSTRUCTION", title_style))
    elements.append(Paragraph(f"{data.instruction.instruction_no} · v{data.instruction.version}", styles["Normal"]))
    elements.append(Spacer(1, 8))

    line_headers = [
        "#",
        "Order number",
        "SCHW",
        "Exp. heads",
        "Wt req.",
        "Do not buy price",
        "Peter's exp.",
        "Exp. Livestock Cost",
        "Balance",
    ]
    line_rows = [line_headers]
    for export_line in data.lines:
        line = export_line.line
        line_rows.append(
            [
                str(line.seq),
                line.contract_no or "",
                f"{line.schw_kg:,.2f}",
                f"{line.expected_heads:,.2f}",
                f"{line.weight_requirement_kg:,.2f}",
                f"{line.dnbp_per_kg:,.4f}",
                _money(line.peters_expectation),
                _money(line.expected_livestock_cost),
                f"{export_line.balance_kg:,.2f}",
            ]
        )
    line_table = Table(line_rows, repeatRows=1)
    line_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ]
        )
    )
    elements.append(line_table)
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("Prepayment Requirements", styles["Heading3"]))
    prepay_rows = [["Saleyard", "Day", "Amount (AUD)"]]
    for entry in data.saleyard_calendar:
        prepay_rows.append([entry.saleyard, entry.day.title(), f"{entry.prepayment_aud:,.0f}"])
    prepay_table = Table(prepay_rows, repeatRows=1)
    prepay_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    elements.append(prepay_table)
    for entry in data.saleyard_calendar:
        if entry.note:
            elements.append(Paragraph(f"* {entry.note}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    elements.append(
        Paragraph(f"Reconciliation ({data.week_start.isoformat()} to {data.week_end.isoformat()})", styles["Heading3"])
    )
    recon_rows = [["Saleyard", "SCHW", "Heads", "Actual Cost"]]
    for r in data.reconciliation:
        recon_rows.append([r.saleyard, f"{r.schw_kg:,.2f}", str(r.heads), f"{r.actual_cost:,.2f}"])
    recon_table = Table(recon_rows, repeatRows=1)
    recon_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    elements.append(recon_table)
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("Summary", styles["Heading3"]))
    summary_rows = [
        ["Actual Heads", str(data.summary.actual_heads), ""],
        ["Expected Heads", f"{data.summary.expected_heads:,.2f}", ""],
        ["Ordered SCHW", f"{data.summary.ordered_schw:,.2f}", "A"],
        ["Bought SCHW", f"{data.summary.bought_schw:,.2f}", "B"],
        ["Surplus/shortfall SCHW", f"{data.summary.surplus_shortfall_schw:,.2f}", "A - B"],
        ["Expected Cost", f"{data.summary.expected_cost:,.2f}", "C"],
        ["Actual Cost", f"{data.summary.actual_cost:,.2f}", "D"],
        ["Cost Variance", f"{data.summary.cost_variance:,.2f}", "C - D"],
    ]
    summary_table = Table(summary_rows)
    summary_table.setStyle(
        TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8)])
    )
    elements.append(summary_table)
    elements.append(Spacer(1, 24))

    approved_by_text = f"Approved by: {data.approved_by_name or '(not yet approved)'}"
    signature_rows = [[f"Prepared by: {data.prepared_by_name}", approved_by_text]]
    signature_table = Table(signature_rows, colWidths=[90 * mm, 90 * mm])
    signature_table.setStyle(
        TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 24)])
    )
    elements.append(signature_table)

    doc.build(elements)
    return buffer.getvalue()
