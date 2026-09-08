import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.push_subscription import PushSubscription


async def upsert(
    db: AsyncSession, *, user_id: uuid.UUID, endpoint: str, p256dh: str, auth: str, ua: str | None
) -> PushSubscription:
    result = await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.user_id = user_id
        existing.p256dh = p256dh
        existing.auth = auth
        existing.ua = ua
        existing.last_seen_at = datetime.now(UTC)
        await db.flush()
        return existing

    subscription = PushSubscription(
        user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth, ua=ua, last_seen_at=datetime.now(UTC)
    )
    db.add(subscription)
    await db.flush()
    return subscription


async def list_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[PushSubscription]:
    result = await db.execute(select(PushSubscription).where(PushSubscription.user_id == user_id))
    return list(result.scalars().all())


async def list_for_users(db: AsyncSession, user_ids: list[uuid.UUID]) -> list[PushSubscription]:
    result = await db.execute(select(PushSubscription).where(PushSubscription.user_id.in_(user_ids)))
    return list(result.scalars().all())


async def delete_by_endpoint(db: AsyncSession, endpoint: str) -> None:
    """Called when pywebpush reports a subscription is gone (410/404) —
    a stale endpoint must not be retried forever."""
    result = await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    existing = result.scalar_one_or_none()
    if existing is not None:
        await db.delete(existing)
        await db.flush()
