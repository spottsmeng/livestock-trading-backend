"""Web Push (VAPID) sending — §10's second of three redundant delivery
channels, the one that fires even when the PWA is closed. `pywebpush` is
MPL-2.0/FOSS; it never routes through a proprietary SDK — only the
browser's own push service endpoint (already opaque, supplied by the
subscription itself) is contacted over plain HTTPS.
"""

import json
import logging
from dataclasses import dataclass

from pywebpush import WebPushException, webpush

from core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PushSubscriptionInfo:
    endpoint: str
    p256dh: str
    auth: str


class PushSendResult:
    """`gone` is True when the browser's push service reports the
    subscription no longer exists (404/410) — the caller
    (services/delivery_service.py) uses this to prune it, per §10's
    requirement that a stale endpoint isn't retried forever."""

    def __init__(self, *, ok: bool, gone: bool = False) -> None:
        self.ok = ok
        self.gone = gone


def send_push(subscription: PushSubscriptionInfo, payload: dict) -> PushSendResult:
    if not settings.vapid_private_key:
        # No real VAPID key configured (local dev without one generated
        # yet) — fail soft rather than raise, since WS + polling remain
        # functional delivery channels regardless (§10's redundancy is the
        # whole point).
        logger.info("Push skipped (no VAPID key configured): %s", subscription.endpoint)
        return PushSendResult(ok=False)

    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": f"mailto:{settings.vapid_claim_email}"},
        )
        return PushSendResult(ok=True)
    except WebPushException as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code in (404, 410):
            return PushSendResult(ok=False, gone=True)
        logger.warning("Push send failed for %s: %s", subscription.endpoint, exc)
        return PushSendResult(ok=False)
