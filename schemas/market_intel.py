"""Market intelligence — competitor bid observations. Deliberately its own
module, separate from schemas/buyer.py: that file's isolation discipline
(tests/test_buyer_response_isolation.py) assumes every response model
reachable from api/v1/buyer.py is safe for a BUYER to read, and the OWNER/
ACCOUNTANT-only response models here (MarketObservationResponse,
MarketIntelSummaryResponse) are the opposite — they carry the org-wide
aggregate view a buyer must never see. Keeping them out of schemas/buyer.py
means that test's scope stays accurate without having to special-case
anything.

MarketObservationAck is the one response model a BUYER does see (the
create/patch endpoints' response) — it only echoes back the fields the
buyer themselves just submitted, never another observation or an
aggregate, so it carries no forbidden information despite living in the
same module as the trading-console models.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class MarketObservationCreateRequest(BaseModel):
    saleyard: str
    trade_date: date
    species: str
    competitor_name: str
    agent: str | None = None
    pen: str | None = None
    head_count: int
    price_per_head: Decimal
    weight_kg: Decimal | None = None
    description: str | None = None
    is_estimated: bool = False
    client_uuid: uuid.UUID
    client_created_at: datetime


class MarketObservationBulkRequest(BaseModel):
    observations: list[MarketObservationCreateRequest]


class MarketObservationPatchRequest(BaseModel):
    competitor_name: str | None = None
    pen: str | None = None
    description: str | None = None
    head_count: int | None = None
    price_per_head: Decimal | None = None
    weight_kg: Decimal | None = None
    is_estimated: bool | None = None


class MarketObservationAck(BaseModel):
    id: uuid.UUID
    saleyard: str
    trade_date: date
    species: str
    competitor_name: str
    agent: str | None
    pen: str | None
    head_count: int
    price_per_head: Decimal
    weight_kg: Decimal | None
    description: str | None
    implied_price_per_kg: Decimal | None
    is_estimated: bool
    client_uuid: uuid.UUID
    client_created_at: datetime
    synced_at: datetime | None
    is_possible_duplicate: bool = False

    model_config = {"from_attributes": True}


class BulkObservationSyncItemResult(BaseModel):
    client_uuid: str
    ok: bool
    observation_id: str | None = None
    is_possible_duplicate: bool | None = None
    error_code: str | None = None
    error_message: str | None = None


class MarketObservationResponse(BaseModel):
    """OWNER/ACCOUNTANT only — the raw feed, for drill-down/export/ML."""

    id: uuid.UUID
    observer_id: uuid.UUID
    observer_email: str
    saleyard: str
    trade_date: date
    species: str
    competitor_name: str
    agent: str | None
    pen: str | None
    head_count: int
    price_per_head: Decimal
    weight_kg: Decimal | None
    description: str | None
    implied_price_per_kg: Decimal | None
    is_estimated: bool
    client_created_at: datetime

    model_config = {"from_attributes": True}


class MarketIntelSummaryRow(BaseModel):
    competitor_name: str
    species: str
    entry_count: int
    heads_observed: int
    avg_price_per_kg: Decimal | None
    last_observed_at: datetime


class MarketIntelSummaryResponse(BaseModel):
    from_: str | None
    to: str | None
    rows: list[MarketIntelSummaryRow]
