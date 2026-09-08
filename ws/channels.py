"""Redis pub/sub channel naming + event publishing for §9.9's two audiences.

Each `/ws/buyer` or `/ws/console` connection subscribes directly to its own
Redis channel for the life of the socket (ws/routes.py) — there is no
separate in-process connection registry to keep in sync, so this stays
correct even if the API ever runs as more than one process (Railway can
scale it horizontally without this breaking).
"""

import json
import uuid
from typing import Any

from redis.asyncio import Redis


def buyer_channel(org_id: uuid.UUID) -> str:
    return f"ws:buyer:{org_id}"


def console_channel(org_id: uuid.UUID) -> str:
    return f"ws:console:{org_id}"


async def publish_event(redis: Redis, channel: str, event: str, data: dict[str, Any]) -> None:
    await redis.publish(channel, json.dumps({"event": event, "data": data}))
