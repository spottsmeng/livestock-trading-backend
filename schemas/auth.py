import uuid

from pydantic import BaseModel, EmailStr

from models.enums import Role


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str | None = None


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: Role
    org_id: uuid.UUID
    mfa_enrolled: bool


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AcceptInviteRequest(BaseModel):
    invite_token: str
    password: str


class AcceptInviteResponse(BaseModel):
    """accept-invite logs the user straight in (access_token + refresh
    cookie) — otherwise an OWNER/ACCOUNTANT could never reach
    /auth/mfa/confirm, since the normal login path refuses them until MFA
    is enrolled. totp_provisioning_uri is only present for OWNER/ACCOUNTANT
    (§14); the client renders it as a QR code immediately."""

    access_token: str
    mfa_required: bool
    totp_provisioning_uri: str | None = None
