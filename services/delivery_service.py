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
from repositories import publications as publications_repo
from repositories import push_subscriptions as push_subscriptions_repo
from repositories import users as users_repo
from services import buying_progress_service, escalation
from ws import channels


async def buyer_safe_payload(db: AsyncSession, publication: DnbpPublication, lines: list[DnbpPublicationLine]) -> dict:
    """The exact shape sent over WS and Web Push, and returned from
    GET /buyer/dnbp/current — buyer-safe by construction, since it is
    built only from DnbpPublicationLine, which carries no price/customer/
    margin column at all (§2.2).

    `heads_bought` (see services/buying_progress_service.py) is the one
    field here that isn't a plain column read — async because it queries
    buy_entries live. Kept in this same payload builder, not bolted on
    separately, so the buyer and the Trading Console's
    GET /publications/current/progress can never see numbers that drift
    apart (both call compute_species_progress)."""
    progress_by_species = {
        p.species: p for p in await buying_progress_service.compute_species_progress(db, publication.org_id, publication, lines)
    }
    return {
        "publication_id": str(publication.id),
        "published_at": publication.published_at.isoformat(),
        "effective_from": publication.effective_from.isoformat(),
        "engine_version": publication.engine_version,
        "species": [
            {
                "species": line.species,
                "dnbp_per_kg": _round_down_2dp(line.dnbp_per_kg),
                # Rounded the same way as dnbp_per_kg — this must match
                # what the buyer's screen actually showed last time, so a
                # client-side delta (current - previous) reproduces exactly
                # the "▲ +0.12" the buyer would compute in their head.
                "previous_dnbp_per_kg": (
                    _round_down_2dp(line.previous_dnbp_per_kg) if line.previous_dnbp_per_kg is not None else None
                ),
                "target_heads": str(line.target_heads) if line.target_heads is not None else None,
                "heads_bought": (
                    str(progress_by_species[line.species].heads_bought) if line.species in progress_by_species else "0"
                ),
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
    db: AsyncSession,
    redis: Redis,
    *,
    publication: DnbpPublication,
    lines: list[DnbpPublicationLine],
    buyer_notified: bool,
) -> None:
    payload = await buyer_safe_payload(db, publication, lines)

    # Web Push — the primary ALERTING channel (§10), fires even closed. Only
    # for a publication that actually changes something the buyer needs to
    # act on (services/publication_service.py's _prices_changed) — an
    # interruptive push on a same-price republish would train the buyer to
    # tap "New Do Not Buy Price" away unread, which is exactly wrong on the
    # day it's a real change.
    buyers = await users_repo.list_users(db, role=Role.BUYER, is_active=True)
    if buyer_notified:
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
                result = send_push(
                    PushSubscriptionInfo(endpoint=sub.endpoint, p256dh=sub.p256dh, auth=sub.auth), push_body
                )
                if result.gone:
                    await push_subscriptions_repo.delete_by_endpoint(db, sub.endpoint)

    # WebSocket/poll — always fires, regardless of buyer_notified. This is
    # passive status sync (GET /buyer/dnbp/current's "updated X min ago"),
    # not an interruption, so an unchanged-price day still silently keeps
    # that timestamp honest instead of letting it look stale.
    await channels.publish_event(redis, channels.buyer_channel(publication.org_id), "dnbp.published", payload)

    # Console sees the publish immediately too (§11.5's post-publish
    # tracker) — including whether this one actually notified anyone, so
    # the publisher isn't left guessing what today's click did.
    await channels.publish_event(
        redis,
        channels.console_channel(publication.org_id),
        "dnbp.published",
        {"publication_id": str(publication.id), "buyer_count": len(buyers), "buyer_notified": buyer_notified},
    )


async def push_buying_progress(db: AsyncSession, redis: Redis, *, org_id: uuid.UUID, species: set[str]) -> None:
    """Fired after a buy_entry write (api/v1/buyer.py's create_entry and
    bulk_sync_entries, after their db.commit()) — the real-time half of the
    live buying-progress counter (see services/buying_progress_service.py
    and domain/buyer/buying_progress.py for the "why" and the reset rule).
    Pushes to both channels.buyer_channel and channels.console_channel so
    the buyer's own screen and the Trading Console update within the same
    instant, off the exact same computation, no polling required.

    A no-op when nothing is currently published — there's no target to
    measure progress against yet, so nothing to push."""
    publication = await publications_repo.get_current_for_org(db, org_id)
    if publication is None or not species:
        return
    lines = await publications_repo.list_lines(db, publication.id)
    progress = await buying_progress_service.compute_species_progress(
        db, org_id, publication, lines, species_filter=species
    )
    if not progress:
        return
    payload = {
        "publication_id": str(publication.id),
        "species": [
            {
                "species": p.species,
                "target_heads": str(p.target_heads) if p.target_heads is not None else None,
                "heads_bought": str(p.heads_bought),
            }
            for p in progress
        ],
    }
    await channels.publish_event(redis, channels.buyer_channel(org_id), "buying.progress_updated", payload)
    await channels.publish_event(redis, channels.console_channel(org_id), "buying.progress_updated", payload)


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
