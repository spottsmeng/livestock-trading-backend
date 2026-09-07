import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from models.enums import InviteStatus, Role


class InviteUserRequest(BaseModel):
    email: EmailStr
    role: Role


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: Role
    org_id: uuid.UUID
    invite_status: InviteStatus
    mfa_enrolled: bool
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}


class RoleChangeRequest(BaseModel):
    role: Role


class AuditEntryResponse(BaseModel):
    id: uuid.UUID
    action: str
    entity: str
    entity_id: uuid.UUID | None
    before: dict | None
    after: dict | None
    at: datetime

    model_config = {"from_attributes": True}
