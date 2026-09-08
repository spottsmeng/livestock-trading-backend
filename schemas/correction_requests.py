import uuid
from datetime import datetime

from pydantic import BaseModel

from models.enums import CorrectionStatus


class CreateCorrectionRequest(BaseModel):
    column_ref: str
    issue_code: str
    detail: str | None = None


class CorrectionRequestResponse(BaseModel):
    id: uuid.UUID
    snapshot_id: uuid.UUID
    order_line_id: uuid.UUID
    raised_by: uuid.UUID
    raised_at: datetime
    column_ref: str
    issue_code: str
    detail: str | None
    status: CorrectionStatus
    resolved_by_snapshot_id: uuid.UUID | None
    resolved_at: datetime | None

    model_config = {"from_attributes": True}
