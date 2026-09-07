import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.refresh_token import RefreshToken


async def create(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    token_family: uuid.UUID,
    token_hash: str,
    expires_at: datetime,
    device_info: str | None = None,
) -> RefreshToken:
    token = RefreshToken(
        user_id=user_id,
        token_family=token_family,
        token_hash=token_hash,
        expires_at=expires_at,
        device_info=device_info,
    )
    db.add(token)
    await db.flush()
    return token


async def get_by_hash(db: AsyncSession, token_hash: str) -> RefreshToken | None:
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    return result.scalar_one_or_none()


async def mark_replaced(db: AsyncSession, token: RefreshToken, *, new_hash: str, revoked_at: datetime) -> None:
    token.replaced_by_hash = new_hash
    token.revoked_at = revoked_at


async def revoke_family(db: AsyncSession, *, token_family: uuid.UUID, revoked_at: datetime) -> None:
    """Reuse of an already-rotated refresh token revokes the WHOLE family
    (§14) — this is the call that does it."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_family == token_family, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=revoked_at)
    )


async def revoke_all_for_user(db: AsyncSession, *, user_id: uuid.UUID, revoked_at: datetime) -> None:
    """Used on deactivation (§2.1.2) — revokes every session immediately."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=revoked_at)
    )
