"""§14's rate limits: 5/min login (Phase 0, already built against this same
Redis instance), 100/min general, 1000/min buyer-sync (Phase 5). One fixed-
window limiter primitive, reused by all three rather than duplicated per
call site — `services/auth_service.check_login_rate_limit` and
`api/v1/middleware.py`'s general/buyer-sync middleware both call this.
"""

from redis.asyncio import Redis

from core.errors import RateLimited


async def enforce(redis: Redis, *, key: str, limit: int, window_seconds: int) -> None:
    """Fixed-window counter: increments `key`, sets a TTL on first increment
    within the window, and raises RateLimited once the count exceeds `limit`.
    Cheap and sufficient at this scale (§16: ~20 users, ~500 buy entries/day)
    — a sliding-window/token-bucket scheme would be more precise at a window
    boundary but isn't warranted here."""
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    if count > limit:
        ttl = await redis.ttl(key)
        raise RateLimited(retry_after_seconds=max(ttl, 1))
