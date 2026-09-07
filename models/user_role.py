import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import TimestampedBase
from models.enums import Role


class UserRole(TimestampedBase):
    """§8, §2.1.2. One active role per user account — WHO holds a role is
    ordinary, unbounded data (any number of accounts may hold OWNER,
    ACCOUNTANT or BUYER); the three role *shapes* are the only fixed part.
    Kept as its own table (rather than a column on users) so a role change
    is a clean, auditable event via PATCH /users/{id}/role."""

    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True, index=True
    )
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"))
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), default=None)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
