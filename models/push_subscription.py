import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import TimestampedBase


class PushSubscription(TimestampedBase):
    """§8, §10 — a browser's Web Push (VAPID) subscription, one row per
    device a user has installed the PWA on. `endpoint` is unique per
    device/browser; `p256dh`/`auth` are the subscription's own encryption
    keys, opaque to us, handed straight to pywebpush (core/push.py)."""

    __tablename__ = "push_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String, unique=True)
    p256dh: Mapped[str] = mapped_column(String)
    auth: Mapped[str] = mapped_column(String)
    ua: Mapped[str | None] = mapped_column(String, default=None)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
