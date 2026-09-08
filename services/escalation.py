"""§10 — "if unacknowledged after 15 minutes, alert the publisher and offer
an SMS/WhatsApp fallback (integration deferred, but design the hook now)."

This is deliberately the whole hook: no worker, no cron, no outbound SMS/
WhatsApp API call. It is invoked lazily, from services/delivery_service.py,
whenever a publication's delivery state is fetched (i.e. whenever Bing or
Bobby actually looks at the console) — cheap to build now, and correct
enough for v1's scale (~3 buyers), while a real scheduled job or SMS
integration is a scoped later addition, not a rewrite of this call site.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from models.dnbp_publication import DnbpPublicationDelivery
from services import audit_service


async def notify_escalation(db: AsyncSession, *, publication_id: uuid.UUID, buyer_id: uuid.UUID) -> None:
    await audit_service.write(
        db,
        actor_id=None,  # system-detected, not a user action
        action="delivery.escalated",
        entity="dnbp_publication_delivery",
        entity_id=None,
        after={
            "publication_id": str(publication_id),
            "buyer_id": str(buyer_id),
            "note": "Unacknowledged after the configured threshold — SMS/WhatsApp integration not yet built (§10).",
        },
    )


async def maybe_escalate(db: AsyncSession, delivery: DnbpPublicationDelivery, *, is_overdue: bool) -> None:
    if is_overdue and delivery.escalated_at is None:
        delivery.escalated_at = datetime.now(UTC)
        await notify_escalation(db, publication_id=delivery.publication_id, buyer_id=delivery.buyer_id)
        await db.flush()
