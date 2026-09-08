import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.dnbp_publication import DnbpPublicationDelivery
from models.enums import DeliveryChannel


async def get_or_create(db: AsyncSession, *, publication_id: uuid.UUID, buyer_id: uuid.UUID) -> DnbpPublicationDelivery:
    result = await db.execute(
        select(DnbpPublicationDelivery).where(
            DnbpPublicationDelivery.publication_id == publication_id, DnbpPublicationDelivery.buyer_id == buyer_id
        )
    )
    delivery = result.scalar_one_or_none()
    if delivery is None:
        delivery = DnbpPublicationDelivery(publication_id=publication_id, buyer_id=buyer_id)
        db.add(delivery)
        await db.flush()
    return delivery


async def list_for_publication(db: AsyncSession, publication_id: uuid.UUID) -> list[DnbpPublicationDelivery]:
    result = await db.execute(
        select(DnbpPublicationDelivery).where(DnbpPublicationDelivery.publication_id == publication_id)
    )
    return list(result.scalars().all())


async def mark_delivered(db: AsyncSession, delivery: DnbpPublicationDelivery, *, channel: DeliveryChannel) -> None:
    """First delivery wins the recorded channel and timestamp — a later
    channel also reaching the buyer (e.g. push arriving after WS already
    did) doesn't overwrite the earlier one; only acknowledgement matters
    for §10's "Delivered ✓" state from here on."""
    if delivery.delivered_at is None:
        delivery.delivered_at = datetime.now(UTC)
        delivery.channel = channel
    await db.flush()


async def mark_acknowledged(db: AsyncSession, delivery: DnbpPublicationDelivery) -> None:
    if delivery.acknowledged_at is None:
        delivery.acknowledged_at = delivery.delivered_at or delivery.created_at
    await db.flush()
