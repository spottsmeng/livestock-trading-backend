import uuid
from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis

from core.errors import Forbidden, InvalidToken
from core.redis import get_redis
from models.enums import Role
from services.auth_service import decode_access_token

_bearer = HTTPBearer(auto_error=False)


class CurrentUser:
    """Everything a route needs from the token, without a DB round trip.
    §14: authorization is deny-by-default and resolved via a dependency —
    this is that dependency's output type."""

    def __init__(self, user_id: uuid.UUID, role: Role, org_id: uuid.UUID) -> None:
        self.user_id = user_id
        self.role = role
        self.org_id = org_id


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if credentials is None:
        raise InvalidToken("Missing bearer token.")
    payload = decode_access_token(credentials.credentials)
    return CurrentUser(
        user_id=uuid.UUID(payload["sub"]),
        role=Role(payload["role"]),
        org_id=uuid.UUID(payload["org_id"]),
    )


def require_role(*allowed_roles: Role) -> Callable:
    """Every route that isn't intentionally public depends on this. There
    is no route in this codebase that skips declaring its required roles —
    that's the deny-by-default guarantee non-negotiable #3 asks for, and
    tests/test_rbac_deny_by_default.py checks it by introspecting routes."""

    async def _dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise Forbidden()
        return current_user

    return _dependency


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def redis_dep() -> Redis:
    return get_redis()
