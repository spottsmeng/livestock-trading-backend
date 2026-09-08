import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


class OrderLineResponse(BaseModel):
    """§9.3 GET /order-lines/{id} — received A-V, with per-column
    value_source (§11.3's provenance popover for a received cell)."""

    id: uuid.UUID
    snapshot_id: uuid.UUID
    line_no: int
    lifecycle: str
    contract_no: str | None
    customer_name: str | None
    species: str | None
    loadout_date: date | None
    qty_kg: Decimal | None
    avg_price_aud: Decimal | None
    amount_aud: Decimal | None
    product_type: str | None
    incoterm: str | None
    nrv_per_kg: Decimal | None
    expected_livestock_cost_per_kg: Decimal | None
    pack_cost_ph: Decimal | None
    offal_return_ph: Decimal | None
    skin_return_ph: Decimal | None
    avg_weight_kg: Decimal | None
    mom_ph: Decimal | None
    deposit_received: Decimal | None
    comments: str | None
    dnbp_benchmark: Decimal | None
    benchmark_method: str | None
    estimated_heads: Decimal | None
    total_livestock_cost: Decimal | None
    value_sources: dict[str, Any]

    model_config = {"from_attributes": True}


class OrderWorkingsResponse(BaseModel):
    """§9.3 GET /order-lines/{id}/workings — full X-AF breakdown with
    formula provenance (§11.3's provenance popover for a computed cell)."""

    order_line_id: uuid.UUID
    engine_version: str
    ref_data_version: str
    computed_at: datetime
    adjusted_price_per_kg: Decimal | None
    pack_cost_per_kg: Decimal | None
    offal_return_per_kg: Decimal | None
    skin_return_per_kg: Decimal | None
    profit_on_peter_costs: Decimal | None
    bing_dnbp: Decimal | None
    bing_dnbp_factor_used: Decimal | None
    bing_dnbp_inputs: dict[str, Any]
    profit_on_bing_dnbp: Decimal | None
    diff_vs_benchmark: Decimal | None
    diff_vs_peter: Decimal | None
    supporting_analysis_complete: bool

    model_config = {"from_attributes": True}


class DnbpProofResponse(BaseModel):
    """§9.3 GET /order-lines/{id}/dnbp-proof — the isolated AC derivation:
    `(avg_price_aud - cif_buffer) * factor = bing_dnbp`, the audit
    artefact for the Workbench's DNBP proof panel (§11.3)."""

    order_line_id: uuid.UUID
    avg_price_aud: Decimal
    cif_buffer_per_kg: Decimal
    dnbp_factor: Decimal
    bing_dnbp: Decimal
    engine_version: str
    ref_data_version: str
    computed_at: datetime
    formula: str
