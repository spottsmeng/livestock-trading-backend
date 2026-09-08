import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ReferenceDataEntryInput(BaseModel):
    """`table_key` is a raw string, not the enum, so an abattoir-owned
    table name produces a precise 403 (services.reference_data_service.
    resolve_table_key) rather than a generic 422 the enum type would give
    for free — §19 wants that 403 to be testable directly."""

    table_key: str
    key1: str | None = None
    value: Decimal


class CreateVersionRequest(BaseModel):
    effective_from: datetime
    note: str | None = None
    entries: list[ReferenceDataEntryInput] = Field(min_length=1)


class ReferenceDataEntryResponse(BaseModel):
    id: uuid.UUID
    table_key: str
    key1: str | None
    value: Decimal

    model_config = {"from_attributes": True}


class ReferenceDataVersionResponse(BaseModel):
    id: uuid.UUID
    effective_from: datetime
    created_by: uuid.UUID | None
    note: str | None
    is_active: bool
    activated_at: datetime | None
    impact_previewed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReferenceDataVersionDetailResponse(ReferenceDataVersionResponse):
    entries: list[ReferenceDataEntryResponse]


class ActiveConfigResponse(BaseModel):
    """§9.8 `GET /reference-data/active` — both halves, labelled by owner
    (§11.7's framing: which panel is editable, which is read-only)."""

    ref_data_version: str
    cif_buffer_per_kg: Decimal
    dnbp_factor_by_species: dict[str, Decimal]
    standard_weight_by_species: dict[str, Decimal]
    owner: str = "EVERHEALTH"


class ImpactLineResponse(BaseModel):
    order_line_id: str
    contract_no: str | None
    species: str
    old_dnbp: Decimal | None
    new_dnbp: Decimal | None
    delta_per_kg: Decimal | None
    exposure_delta_aud: Decimal | None


class ImpactPreviewResponse(BaseModel):
    lines: list[ImpactLineResponse]
    aggregate_exposure_delta_aud: Decimal
    lines_affected: int


class SpeciesResponse(BaseModel):
    code: str
    display_name: str
    is_active: bool
    has_dnbp_factor: bool
    has_standard_weight: bool


class CreateSpeciesRequest(BaseModel):
    code: str
    display_name: str


class ProductTypeResponse(BaseModel):
    code: str
    display_name: str
    is_active: bool

    model_config = {"from_attributes": True}


class CreateProductTypeRequest(BaseModel):
    code: str
    display_name: str


class AbattoirTablesResponse(BaseModel):
    """§9.8 `GET /reference-data/abattoir` — the latest snapshot's stored
    tables, read-only (§6.1-6.3, §6.6, §11.7)."""

    snapshot_id: uuid.UUID
    source_filename: str
    pack_cost_by_product_type: dict[str, Decimal]
    offal_return_ph_by_species: dict[str, Decimal]
    skin_return_ph_by_species: dict[str, Decimal]


class DriftResponse(BaseModel):
    id: uuid.UUID
    snapshot_id: uuid.UUID
    table_key: str
    key1: str
    old_value: Decimal | None
    new_value: Decimal | None
    detected_at: datetime
    acknowledged_by: uuid.UUID | None
    acknowledged_at: datetime | None

    model_config = {"from_attributes": True}
