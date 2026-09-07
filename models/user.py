import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import TimestampedBase
from models.enums import InviteStatus


class User(TimestampedBase):
    """§2.1.2, §8. A user is created PENDING by an OWNER-only invite and
    becomes ACTIVE only by completing their own invite link — no code path
    here ever accepts a plaintext password for anyone but the user setting
    their own. Deactivation is a status flip; the row and its history are
    never deleted (§2.1.2)."""

    __tablename__ = "users"

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisations.id"))
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String, default=None)
    invite_status: Mapped[InviteStatus] = mapped_column(
        Enum(InviteStatus, name="invite_status"), default=InviteStatus.PENDING
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), default=None)

    mfa_secret: Mapped[str | None] = mapped_column(String, default=None)
    mfa_enrolled: Mapped[bool] = mapped_column(Boolean, default=False)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
