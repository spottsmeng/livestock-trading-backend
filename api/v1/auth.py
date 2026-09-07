from fastapi import APIRouter, Cookie, Depends, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUser, client_ip, get_current_user, redis_dep
from core.config import settings
from core.db import get_db
from core.errors import InvalidToken, NotFound, PasswordPolicyViolation
from core.security import hash_password, password_policy_violations, verify_password
from repositories import users as user_repo
from schemas.auth import (
    AcceptInviteRequest,
    AcceptInviteResponse,
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
    TokenPair,
)
from services import auth_service, user_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"


def _set_refresh_cookie(response: Response, raw_refresh_token: str) -> None:
    # httpOnly + Secure + SameSite=Strict per §14. Never exposed in a JSON
    # body — the cookie is the only place a refresh token ever appears
    # outside the database (as a hash).
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api/v1/auth",
    )


@router.post("/login", response_model=TokenPair)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(redis_dep),
    ip: str = Depends(client_ip),
) -> TokenPair:
    await auth_service.check_login_rate_limit(redis, key=f"{body.email.lower()}:{ip}")
    user, role = await auth_service.authenticate(
        db, email=body.email, password=body.password, totp_code=body.totp_code
    )
    access_token, raw_refresh = await auth_service.issue_token_pair(db, user=user, role=role)
    await db.commit()
    _set_refresh_cookie(response, raw_refresh)
    return TokenPair(access_token=access_token)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> TokenPair:
    if refresh_token is None:
        raise InvalidToken("No refresh token presented.")
    access_token, new_raw_refresh = await auth_service.rotate_refresh_token(db, raw_refresh_token=refresh_token)
    await db.commit()
    _set_refresh_cookie(response, new_raw_refresh)
    return TokenPair(access_token=access_token)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> None:
    if refresh_token is not None:
        await auth_service.logout(db, raw_refresh_token=refresh_token)
        await db.commit()
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/v1/auth")


@router.get("/me", response_model=MeResponse)
async def me(current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> MeResponse:
    user = await user_repo.get_by_id(db, current.user_id)
    if user is None:
        raise NotFound("User")
    return MeResponse(
        id=user.id, email=user.email, role=current.role, org_id=user.org_id, mfa_enrolled=user.mfa_enrolled
    )


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    user = await user_repo.get_by_id(db, current.user_id)
    if user is None or user.password_hash is None or not verify_password(body.current_password, user.password_hash):
        raise InvalidToken("Current password is incorrect.")
    violations = password_policy_violations(body.new_password)
    if violations:
        raise PasswordPolicyViolation(violations)
    user.password_hash = hash_password(body.new_password)
    await db.commit()


@router.post("/accept-invite", response_model=AcceptInviteResponse)
async def accept_invite(
    body: AcceptInviteRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> AcceptInviteResponse:
    user, role, provisioning_uri = await user_service.accept_invite(
        db, invite_token=body.invite_token, password=body.password
    )
    access_token, raw_refresh = await auth_service.issue_token_pair(db, user=user, role=role)
    await db.commit()
    _set_refresh_cookie(response, raw_refresh)
    return AcceptInviteResponse(
        access_token=access_token,
        mfa_required=provisioning_uri is not None,
        totp_provisioning_uri=provisioning_uri,
    )


@router.post("/mfa/confirm", status_code=204)
async def confirm_mfa(
    code: str,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Not in the PRD's literal §9.1 list — added because §14 requires
    TOTP *enrollment* for OWNER/ACCOUNTANT, and enrollment needs a step
    that verifies the user actually captured the secret before it's
    trusted for login."""
    user = await user_repo.get_by_id(db, current.user_id)
    if user is None:
        raise NotFound("User")
    await user_service.confirm_mfa_enrollment(db, user=user, code=code)
    await db.commit()
