import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import TimestampedBase


class RefreshToken(TimestampedBase):
    """§14. Only a SHA-256 hash of the token is ever stored. token_family
    ties every token descended from one login together — reuse of an
    already-rotated token revokes the whole family, not just that token.
    BUYER rows get a long device_info-tagged lifetime (90d rolling);
    OWNER/ACCOUNTANT rows get the standard 30d."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    token_family: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    device_info: Mapped[str | None] = mapped_column(String, default=None)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    replaced_by_hash: Mapped[str | None] = mapped_column(String, default=None)
