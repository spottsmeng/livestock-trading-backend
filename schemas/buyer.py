"""§2.2, §14 — every response model in this module is buyer-safe BY
CONSTRUCTION: none of them define `customer_name`, `avg_price_aud`,
`nrv_per_kg`, `amount_aud`, `mom_ph`, any `profit_on_*`/`diff_vs_*`, or
`dnbp_benchmark` — not because a serializer was careful to omit them, but
because the underlying tables (`dnbp_publication_lines`, `buy_entries`)
never carry those columns at all (§8). tests/test_buyer_response_isolation.py
introspects every model here and fails if any of those field names ever
appear.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class WeightBand(BaseModel):
    min: str
    max: str


class DnbpSpeciesLine(BaseModel):
    species: str
    dnbp_per_kg: str
    target_heads: str | None
    weight_band: WeightBand | None


class DnbpCurrentResponse(BaseModel):
    publication_id: str
    published_at: str
    effective_from: str
    engine_version: str
    species: list[DnbpSpeciesLine]


class AckRequest(BaseModel):
    publication_id: uuid.UUID


class PushSubscriptionRequest(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    ua: str | None = None


class BuyEntryCreateRequest(BaseModel):
    saleyard: str
    trade_date: date
    species: str
    agent: str | None = None
    pen: str | None = None
    head_count: int
    price_per_head: Decimal
    weight_kg: Decimal
    description: str | None = None
    eid_ref: str | None = None
    freight_per_head: Decimal | None = None
    other_cost_per_kg: Decimal | None = None
    breach_reason: str | None = None
    client_uuid: uuid.UUID
    client_created_at: datetime


class BuyEntryBulkRequest(BaseModel):
    entries: list[BuyEntryCreateRequest]


class BuyEntryPatchRequest(BaseModel):
    pen: str | None = None
    description: str | None = None
    breach_reason: str | None = None
    head_count: int | None = None
    price_per_head: Decimal | None = None
    weight_kg: Decimal | None = None


class BuyEntryResponse(BaseModel):
    id: uuid.UUID
    saleyard: str
    trade_date: date
    species: str
    agent: str | None
    pen: str | None
    head_count: int
    price_per_head: Decimal
    weight_kg: Decimal
    description: str | None
    eid_ref: str | None
    freight_per_head: Decimal | None
    other_cost_per_kg: Decimal | None
    implied_price_per_kg: Decimal
    dnbp_at_entry: Decimal
    variance_per_kg: Decimal
    is_breach: bool
    breach_reason: str | None
    client_uuid: uuid.UUID
    client_created_at: datetime
    synced_at: datetime | None
    is_possible_duplicate: bool = False

    model_config = {"from_attributes": True}


class InstructionLineResponse(BaseModel):
    """§12.5, §2.2 — deliberately excludes `peters_expectation` and
    `expected_livestock_cost` (cost/margin-adjacent, same forbidden category
    as `mom_ph`/`profit_on_*`), and every fill/reconciliation field — none
    of those exist on this model at all, so a future field addition to
    `BuyInstructionLine` cannot silently leak here (same buyer-safe-by-
    construction discipline as every other model in this module)."""

    contract_no: str | None
    species: str
    target_heads: str
    weight_requirement_kg: str
    dnbp_per_kg: str


class InstructionResponse(BaseModel):
    instruction_id: str
    instruction_no: str
    trade_date: str
    status: str
    saleyard: str | None
    prepayment_note: str | None
    lines: list[InstructionLineResponse]


class BulkSyncItemResult(BaseModel):
    client_uuid: str
    ok: bool
    entry_id: str | None = None
    is_possible_duplicate: bool | None = None
    error_code: str | None = None
    error_message: str | None = None
