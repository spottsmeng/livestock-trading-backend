"""§9.9 — WebSocket ticket auth. Native `WebSocket` (browser API) can't
attach a bearer header the way `fetch` can, so a normal authenticated REST
call (`POST /ws/ticket`, any role, gated by the ordinary `require_role`
dependency like everything else) issues a short-lived, single-use ticket
that the WS handshake carries as a query param instead.

Redis's GETDEL makes "single-use" atomic: two concurrent connect attempts
with the same ticket can never both succeed, and a consumed or expired
ticket leaves nothing behind to replay.
"""

import json
import secrets
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

from core.config import settings
from core.errors import TicketInvalid
from models.enums import Role

_TICKET_KEY_PREFIX = "ws-ticket:"


@dataclass(frozen=True, slots=True)
class TicketPayload:
    user_id: uuid.UUID
    role: Role
    org_id: uuid.UUID


async def issue_ticket(redis: Redis, *, user_id: uuid.UUID, role: Role, org_id: uuid.UUID) -> str:
    ticket = secrets.token_urlsafe(32)
    payload = json.dumps({"user_id": str(user_id), "role": role.value, "org_id": str(org_id)})
    await redis.set(f"{_TICKET_KEY_PREFIX}{ticket}", payload, ex=settings.ws_ticket_ttl_seconds)
    return ticket


async def consume_ticket(redis: Redis, ticket: str) -> TicketPayload:
    raw = await redis.getdel(f"{_TICKET_KEY_PREFIX}{ticket}")
    if raw is None:
        raise TicketInvalid()
    data = json.loads(raw)
    return TicketPayload(user_id=uuid.UUID(data["user_id"]), role=Role(data["role"]), org_id=uuid.UUID(data["org_id"]))
