import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from models.enums import SnapshotStatus


class CommitSnapshotRequest(BaseModel):
    preview_id: str


class UploadPreviewResponse(BaseModel):
    preview_id: str
    detected_layout: dict[str, Any]
    active_count: int
    loaded_count: int
    diff: dict[str, Any]


class SnapshotResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    uploaded_by: uuid.UUID
    source_filename: str
    source_sha256: str
    detected_layout: dict[str, Any]
    parser_version: str
    status: SnapshotStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class CalculateResponse(BaseModel):
    active_lines_computed: int
    blocked_issues: int
    correction_issues: int
    warnings: int
    correction_requests_auto_resolved: int


class IssueResponse(BaseModel):
    id: uuid.UUID
    order_line_id: uuid.UUID
    code: str
    severity: str
    message: str
    column_ref: str | None
    acknowledged_by: uuid.UUID | None
    acknowledged_at: datetime | None

    model_config = {"from_attributes": True}
