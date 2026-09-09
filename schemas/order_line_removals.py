import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class OrderLineRemovalResponse(BaseModel):
    id: uuid.UUID
    snapshot_id: uuid.UUID
    contract_no: str | None
    species: str | None
    product_type: str | None
    incoterm: str | None
    customer_name: str | None
    amount_aud: Decimal | None
    detected_at: datetime
    acknowledged_by: uuid.UUID | None
    acknowledged_at: datetime | None
    reason: str | None

    model_config = {"from_attributes": True}


class AcknowledgeRemovalRequest(BaseModel):
    reason: str | None = None
