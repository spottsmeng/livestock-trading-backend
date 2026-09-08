import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class GenerateBuyInstructionRequest(BaseModel):
    snapshot_id: uuid.UUID
    publication_id: uuid.UUID
    trade_date: date | None = None
    note: str | None = None


class PatchBuyInstructionRequest(BaseModel):
    note: str | None = None


class AddFillRequest(BaseModel):
    label: str
    kg_amount: Decimal


class FillResponse(BaseModel):
    id: uuid.UUID
    label: str
    kg_amount: Decimal
    entered_by: uuid.UUID
    entered_at: datetime

    model_config = {"from_attributes": True}


class BuyInstructionLineResponse(BaseModel):
    id: uuid.UUID
    seq: int
    order_line_id: uuid.UUID
    contract_no: str | None
    species: str
    schw_kg: Decimal
    expected_heads: Decimal
    weight_requirement_kg: Decimal
    dnbp_per_kg: Decimal
    peters_expectation: Decimal | None
    expected_livestock_cost: Decimal
    fills: list[FillResponse]
    balance_kg: Decimal


class BuyInstructionResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    instruction_no: str
    version: int
    trade_date: date
    snapshot_id: uuid.UUID
    publication_id: uuid.UUID
    prepared_by: uuid.UUID
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    note: str | None
    status: str
    lines: list[BuyInstructionLineResponse]

    model_config = {"from_attributes": True}


class SaleyardReconciliationResponse(BaseModel):
    saleyard: str
    schw_kg: Decimal
    heads: int
    actual_cost: Decimal


class ReconciliationSummaryResponse(BaseModel):
    actual_heads: int
    expected_heads: Decimal
    ordered_schw: Decimal
    bought_schw: Decimal
    surplus_shortfall_schw: Decimal
    expected_cost: Decimal
    actual_cost: Decimal
    cost_variance: Decimal


class ReconciliationResponse(BaseModel):
    week_start: date
    week_end: date
    by_saleyard: list[SaleyardReconciliationResponse]
    summary: ReconciliationSummaryResponse
