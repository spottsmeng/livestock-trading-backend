"""§9.9/§10 — fan-out and delivery-state tracking for a publication. Three
redundant channels: WebSocket (ws/channels.py's `publish_event`, instant
while foregrounded), Web Push (core/push.py, fires even when closed — the
primary alerting channel), and polling (nothing extra needed here — it's
just GET /buyer/dnbp/current, called on a timer by the PWA).

"Delivered" and "acknowledged" are deliberately the same client-reported
event in this system: the buyer PWA calls POST /buyer/dnbp/ack the moment
it renders a publication, whichever channel got it there first (WS push,
a tapped Web Push notification, or a poll) — there is no separate
"delivered but not yet seen" state to track beyond that single call,
since nothing server-side can otherwise know a WS publish or push send
actually reached a screen a human looked at.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.push import PushSubscriptionInfo, send_push
from models.dnbp_publication import DnbpPublication, DnbpPublicationLine
from models.enums import DeliveryChannel, Role
from repositories import publication_deliveries as deliveries_repo
from repositories import push_subscriptions as push_subscriptions_repo
from repositories import users as users_repo
from services import escalation
from ws import channels


def buyer_safe_payload(publication: DnbpPublication, lines: list[DnbpPublicationLine]) -> dict:
    """The exact shape sent over WS and Web Push, and returned from
    GET /buyer/dnbp/current — buyer-safe by construction, since it is
    built only from DnbpPublicationLine, which carries no price/customer/
    margin column at all (§2.2)."""
    return {
        "publication_id": str(publication.id),
        "published_at": publication.published_at.isoformat(),
        "effective_from": publication.effective_from.isoformat(),
        "engine_version": publication.engine_version,
        "species": [
            {
                "species": line.species,
                "dnbp_per_kg": _round_down_2dp(line.dnbp_per_kg),
                "target_heads": str(line.target_heads) if line.target_heads is not None else None,
                "weight_band": (
                    {"min": str(line.target_weight_kg_min), "max": str(line.target_weight_kg_max)}
                    if line.target_weight_kg_min is not None
                    else None
                ),
            }
            for line in lines
        ],
    }


def _round_down_2dp(value: Decimal) -> str:
    # §5.5 — the buyer never sees a rounded-up ceiling; that would
    # authorise an overpay.
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_FLOOR))


async def fan_out(
    db: AsyncSession, redis: Redis, *, publication: DnbpPublication, lines: list[DnbpPublicationLine]
) -> None:
    payload = buyer_safe_payload(publication, lines)

    # Web Push — the primary alerting channel (§10), fires even closed.
    buyers = await users_repo.list_users(db, role=Role.BUYER, is_active=True)
    for user, _role in buyers:
        subscriptions = await push_subscriptions_repo.list_for_user(db, user.id)
        if not subscriptions:
            continue
        species_summary = " · ".join(f"{s['species']} ${s['dnbp_per_kg']}/kg" for s in payload["species"][:3])
        push_body = {
            "title": "New Do Not Buy Price",
            "body": f"{species_summary} · Tap to open",
            "publication_id": str(publication.id),
        }
        for sub in subscriptions:
            result = send_push(PushSubscriptionInfo(endpoint=sub.endpoint, p256dh=sub.p256dh, auth=sub.auth), push_body)
            if result.gone:
                await push_subscriptions_repo.delete_by_endpoint(db, sub.endpoint)

    # WebSocket — instant while foregrounded (§10); every currently
    # connected buyer socket is subscribed to this channel (ws/routes.py).
    await channels.publish_event(redis, channels.buyer_channel(publication.org_id), "dnbp.published", payload)

    # Console sees the publish immediately too (§11.5's post-publish tracker).
    await channels.publish_event(
        redis,
        channels.console_channel(publication.org_id),
        "dnbp.published",
        {"publication_id": str(publication.id), "buyer_count": len(buyers)},
    )


async def acknowledge(db: AsyncSession, redis: Redis, *, publication: DnbpPublication, buyer_id: uuid.UUID) -> None:
    delivery = await deliveries_repo.get_or_create(db, publication_id=publication.id, buyer_id=buyer_id)
    await deliveries_repo.mark_delivered(db, delivery, channel=DeliveryChannel.WS)
    await deliveries_repo.mark_acknowledged(db, delivery)

    await channels.publish_event(
        redis,
        channels.console_channel(publication.org_id),
        "delivery.updated",
        {
            "publication_id": str(publication.id),
            "buyer_id": str(buyer_id),
            "acknowledged_at": delivery.acknowledged_at.isoformat(),
        },
    )


async def delivery_states(db: AsyncSession, publication: DnbpPublication) -> list[dict]:
    """§11.5's post-publish tracker / §10's "Delivered ✓ 14:03 / Not yet
    seen ⚠" — computed on demand rather than pushed by a background job
    (see services/escalation.py's module docstring), which also means an
    overdue-and-not-yet-escalated buyer gets escalated exactly when someone
    is actually looking at this state, not silently in the background."""
    buyers = await users_repo.list_users(db, role=Role.BUYER, is_active=True)
    deadline = publication.published_at + timedelta(minutes=settings.delivery_escalation_minutes)
    now = datetime.now(UTC)

    states = []
    for user, _role in buyers:
        delivery = await deliveries_repo.get_or_create(db, publication_id=publication.id, buyer_id=user.id)
        is_overdue = delivery.acknowledged_at is None and now > deadline
        await escalation.maybe_escalate(db, delivery, is_overdue=is_overdue)
        states.append(
            {
                "buyer_id": str(user.id),
                "buyer_email": user.email,
                "delivered_at": delivery.delivered_at.isoformat() if delivery.delivered_at else None,
                "acknowledged_at": delivery.acknowledged_at.isoformat() if delivery.acknowledged_at else None,
                "channel": delivery.channel.value if delivery.channel else None,
                "is_overdue": is_overdue,
                "escalated_at": delivery.escalated_at.isoformat() if delivery.escalated_at else None,
            }
        )
    return states
