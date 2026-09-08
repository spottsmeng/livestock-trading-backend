import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

# ---- Panel 1: Order book ----


class OrderBookSpeciesRow(BaseModel):
    species: str
    exposure_aud: Decimal
    heads_required: Decimal
    heads_bought: int
    days_of_cover: Decimal | None  # §3 of the approved plan — None when the trailing rate is 0


class OrderBookCustomerRow(BaseModel):
    species: str
    customer_name: str | None
    exposure_aud: Decimal


class OrderBookResponse(BaseModel):
    snapshot_id: uuid.UUID | None
    as_of_date: date | None
    total_exposure_aud: Decimal
    by_species: list[OrderBookSpeciesRow]
    by_customer: list[OrderBookCustomerRow]


# ---- Panel 2: DNBP trend ----


class DnbpTrendPoint(BaseModel):
    published_at: datetime
    dnbp_per_kg: Decimal


class ActualPaidPoint(BaseModel):
    trade_date: date
    avg_paid_per_kg: Decimal


class DnbpTrendResponse(BaseModel):
    species: str
    days: int
    dnbp_points: list[DnbpTrendPoint]
    actual_paid_points: list[ActualPaidPoint]


# ---- Panel 3: Buyer performance ----


class BuyerPerformanceRow(BaseModel):
    buyer_id: uuid.UUID
    buyer_email: str
    entry_count: int
    headroom_captured_aud: Decimal
    breach_count: int
    breach_rate: Decimal
    avg_variance_per_kg: Decimal | None


class SaleyardHeadroomRow(BaseModel):
    saleyard: str
    headroom_captured_aud: Decimal


class BuyerPerformanceResponse(BaseModel):
    from_: date | None
    to: date | None
    by_buyer: list[BuyerPerformanceRow]
    by_saleyard: list[SaleyardHeadroomRow]


# ---- Panel 4: Margin bridge ----


class MarginBridgeResponse(BaseModel):
    snapshot_id: uuid.UUID | None
    line_count: int
    avg_sell_price_aud: Decimal | None  # G
    avg_adjusted_price_per_kg: Decimal | None  # X
    avg_pack_cost_per_kg: Decimal | None  # Y
    avg_offal_return_per_kg: Decimal | None  # Z
    avg_skin_return_per_kg: Decimal | None  # AA
    avg_bing_dnbp: Decimal | None  # AC — source-of-truth path's destination
    avg_profit_on_peter_costs: Decimal | None  # AB — supporting-profit path's destination


# ---- Panel 5: Fulfilment ----


class FulfilmentRow(BaseModel):
    trade_date: date
    instructed_schw_kg: Decimal
    bought_schw_kg: Decimal
    shortfall_schw_kg: Decimal


class FulfilmentResponse(BaseModel):
    from_: date | None
    to: date | None
    rows: list[FulfilmentRow]


# ---- Panel 6: Exceptions ----


class BreachRow(BaseModel):
    id: uuid.UUID
    buyer_id: uuid.UUID
    buyer_email: str
    saleyard: str
    trade_date: date
    species: str
    variance_per_kg: Decimal
    price_per_head: Decimal
    weight_kg: Decimal


class BlockedLineRow(BaseModel):
    order_line_id: uuid.UUID
    contract_no: str | None
    species: str | None
    code: str
    message: str


class StalePublicationRow(BaseModel):
    publication_id: uuid.UUID
    published_at: datetime
    hours_stale: Decimal


class UndeliveredInstructionRow(BaseModel):
    instruction_id: uuid.UUID
    instruction_no: str
    trade_date: date
    status: str


class UndeliveredPublicationRow(BaseModel):
    publication_id: uuid.UUID
    buyer_id: uuid.UUID
    buyer_email: str
    delivered_at: datetime | None


class ExceptionsResponse(BaseModel):
    from_: date | None
    to: date | None
    breaches: list[BreachRow]
    blocked_lines: list[BlockedLineRow]
    stale_publications: list[StalePublicationRow]
    undelivered_instructions: list[UndeliveredInstructionRow]
    undelivered_publications: list[UndeliveredPublicationRow]


# ---- Overview ----


class OverviewResponse(BaseModel):
    from_: date | None
    to: date | None
    active_exposure_aud: Decimal
    heads_required_total: Decimal
    heads_bought_total: int
    open_correction_requests: int
    breach_count: int
    blocked_line_count: int
    stale_publication_count: int
    undelivered_instruction_count: int
