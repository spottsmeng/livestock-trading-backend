from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.errors import (
    AccountNotActive,
    InvalidCredentials,
    InvalidToken,
    MfaInvalid,
    MfaRequired,
    RateLimited,
    TokenReused,
)
from core.security import (
    create_access_token,
    decode_token,
    generate_refresh_token,
    hash_refresh_token,
    new_token_family,
    verify_password,
    verify_totp,
)
from models.enums import InviteStatus, Role
from models.user import User
from repositories import refresh_tokens as refresh_token_repo
from repositories import users as user_repo


async def check_login_rate_limit(redis: Redis, *, key: str) -> None:
    """Fixed-window limiter, 5/min per email+IP (§14). Cheap and enough for
    a login endpoint — this isn't the buyer-sync-scale limiter."""
    redis_key = f"ratelimit:login:{key}"
    count = await redis.incr(redis_key)
    if count == 1:
        await redis.expire(redis_key, 60)
    if count > settings.login_rate_limit_per_minute:
        ttl = await redis.ttl(redis_key)
        raise RateLimited(retry_after_seconds=max(ttl, 1))


async def authenticate(db: AsyncSession, *, email: str, password: str, totp_code: str | None) -> tuple[User, Role]:
    user = await user_repo.get_by_email(db, email)
    # Constant-shape failure: an unknown email and a wrong password both
    # raise the same InvalidCredentials — never reveal which one it was.
    if user is None or user.password_hash is None or not verify_password(password, user.password_hash):
        raise InvalidCredentials()

    if user.invite_status != InviteStatus.ACTIVE:
        raise AccountNotActive(user.invite_status.value)

    role_row = await user_repo.get_role(db, user.id)
    role = role_row.role  # type: ignore[union-attr]

    if role in (Role.OWNER, Role.ACCOUNTANT):
        if not user.mfa_enrolled:
            # Enrollment happens right after accept-invite; a user who
            # skipped it can't log in until it's done (§14).
            raise MfaRequired()
        if not totp_code:
            raise MfaRequired()
        if not verify_totp(user.mfa_secret, totp_code):  # type: ignore[arg-type]
            raise MfaInvalid()

    user.last_login_at = datetime.now(UTC)
    return user, role


async def issue_token_pair(
    db: AsyncSession, *, user: User, role: Role, device_info: str | None = None
) -> tuple[str, str]:
    access_token = create_access_token(user_id=str(user.id), role=role.value, org_id=str(user.org_id))

    raw_refresh = generate_refresh_token()
    ttl_days = settings.jwt_refresh_ttl_days_buyer if role == Role.BUYER else settings.jwt_refresh_ttl_days
    await refresh_token_repo.create(
        db,
        user_id=user.id,
        token_family=new_token_family(),
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
        device_info=device_info,
    )
    return access_token, raw_refresh


async def rotate_refresh_token(db: AsyncSession, *, raw_refresh_token: str) -> tuple[str, str]:
    token_hash = hash_refresh_token(raw_refresh_token)
    stored = await refresh_token_repo.get_by_hash(db, token_hash)
    if stored is None:
        raise InvalidToken()

    now = datetime.now(UTC)
    if stored.revoked_at is not None:
        # This exact token was already rotated (or the family was already
        # revoked) and is being presented again — reuse. Kill the family.
        # Commit BEFORE raising: the caller's request ends in an error and
        # never reaches its own db.commit(), so without this the
        # revocation would silently roll back when the session closes —
        # the exact opposite of what this branch exists to guarantee.
        await refresh_token_repo.revoke_family(db, token_family=stored.token_family, revoked_at=now)
        await db.commit()
        raise TokenReused()

    if stored.expires_at.replace(tzinfo=UTC) < now:
        raise InvalidToken("Refresh token expired.")

    user = await user_repo.get_by_id(db, stored.user_id)
    if user is None or user.invite_status != InviteStatus.ACTIVE:
        raise InvalidToken()
    role_row = await user_repo.get_role(db, user.id)
    role = role_row.role  # type: ignore[union-attr]

    access_token = create_access_token(user_id=str(user.id), role=role.value, org_id=str(user.org_id))

    new_raw_refresh = generate_refresh_token()
    ttl_days = settings.jwt_refresh_ttl_days_buyer if role == Role.BUYER else settings.jwt_refresh_ttl_days
    new_hash = hash_refresh_token(new_raw_refresh)
    await refresh_token_repo.create(
        db,
        user_id=user.id,
        token_family=stored.token_family,
        token_hash=new_hash,
        expires_at=now + timedelta(days=ttl_days),
        device_info=stored.device_info,
    )
    await refresh_token_repo.mark_replaced(db, stored, new_hash=new_hash, revoked_at=now)
    return access_token, new_raw_refresh


async def logout(db: AsyncSession, *, raw_refresh_token: str) -> None:
    token_hash = hash_refresh_token(raw_refresh_token)
    stored = await refresh_token_repo.get_by_hash(db, token_hash)
    if stored is not None and stored.revoked_at is None:
        await refresh_token_repo.revoke_family(db, token_family=stored.token_family, revoked_at=datetime.now(UTC))


def decode_access_token(token: str) -> dict:
    try:
        payload = decode_token(token)
    except Exception as exc:  # jwt.PyJWTError and subclasses
        raise InvalidToken() from exc
    if payload.get("type") != "access":
        raise InvalidToken()
    return payload
