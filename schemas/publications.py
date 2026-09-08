import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


class PublishRequest(BaseModel):
    snapshot_id: uuid.UUID
    notes: str | None = None
    # §9.4 lists `species_targets[]` as an optional manual override of the
    # auto-computed target heads/weight band per species. Accepted here for
    # wire-compatibility but not yet applied — the PRD doesn't specify the
    # override's shape beyond the name, and the auto-computed values (§5.3
    # aggregation) already reproduce the worked examples correctly. A real
    # override UI is a scoped follow-up once Bing actually needs to hand-
    # adjust a target, not guessed at here.
    species_targets: list[dict[str, Any]] | None = None


class PublicationLineResponse(BaseModel):
    id: uuid.UUID
    publication_id: uuid.UUID
    species: str
    dnbp_per_kg: Decimal
    target_heads: Decimal | None
    target_weight_kg_min: Decimal | None
    target_weight_kg_max: Decimal | None
    contributing_line_ids: list[uuid.UUID]

    model_config = {"from_attributes": True}


class PublicationResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    snapshot_id: uuid.UUID
    published_by: uuid.UUID
    published_at: datetime
    effective_from: datetime
    engine_version: str
    notes: str | None
    superseded_by: uuid.UUID | None
    superseded_at: datetime | None
    lines: list[PublicationLineResponse]

    model_config = {"from_attributes": True}


class DeliveryStateResponse(BaseModel):
    buyer_id: str
    buyer_email: str
    delivered_at: str | None
    acknowledged_at: str | None
    channel: str | None
    is_overdue: bool
    escalated_at: str | None


class PublicationDetailResponse(PublicationResponse):
    deliveries: list[DeliveryStateResponse]
