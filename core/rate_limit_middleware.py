"""§14 — "100/min general, 1000/min on buyer sync endpoints." The login
limiter (5/min) stays exactly where Phase 0 put it, as its own dependency
in api/v1/auth.py — this middleware explicitly skips that route rather than
double-limiting it under a different bucket.

Bucketed by (authenticated user_id, else client IP) so one buyer's device
can't exhaust another's allowance, and by path prefix: every /api/v1/buyer/*
route gets the higher buyer-sync ceiling (§12.7's offline queue flush can
legitimately burst many entries at once on reconnect), everything else under
/api/v1/* gets the general ceiling. Reuses core.rate_limit's fixed-window
primitive — the same one services/auth_service.check_login_rate_limit calls.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.deps import redis_dep
from core import rate_limit
from core.config import settings
from core.errors import RateLimited
from services.auth_service import decode_access_token

_EXEMPT_PATHS = {"/api/v1/auth/login", "/api/v1/health"}
_BUYER_PREFIX = "/api/v1/buyer"
_LIMITED_PREFIX = "/api/v1"


def _bucket_key(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        try:
            payload = decode_access_token(auth_header[7:])
            return f"user:{payload['sub']}"
        except Exception:  # noqa: BLE001 — an invalid/expired token just falls back to IP scoping
            pass
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    return f"ip:{ip}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith(_LIMITED_PREFIX) or path in _EXEMPT_PATHS:
            return await call_next(request)

        is_buyer_sync = path.startswith(_BUYER_PREFIX)
        limit = settings.buyer_sync_rate_limit_per_minute if is_buyer_sync else settings.general_rate_limit_per_minute
        bucket = "buyer" if is_buyer_sync else "general"
        redis_key = f"ratelimit:{bucket}:{_bucket_key(request)}"

        # Resolved via the FastAPI dependency-override table (not
        # core.redis.get_redis() directly) so tests' per-test redis_client
        # fixture (tests/conftest.py) — which overrides redis_dep to avoid
        # sharing one Redis client's connection pool across pytest-asyncio's
        # function-scoped event loops — takes effect here too, the same way
        # it already does for every route's own Depends(redis_dep).
        redis = request.app.dependency_overrides.get(redis_dep, redis_dep)()
        try:
            await rate_limit.enforce(redis, key=redis_key, limit=limit, window_seconds=60)
        except RateLimited as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            )
        return await call_next(request)
