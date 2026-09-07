import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import (
    BreachedPassword,
    Conflict,
    InvalidToken,
    LastOwnerGuard,
    MfaInvalid,
    NotFound,
    PasswordPolicyViolation,
)
from core.security import (
    decode_invite_token,
    generate_totp_secret,
    hash_password,
    is_breached_password,
    password_policy_violations,
    totp_provisioning_uri,
    verify_totp,
)
from models.enums import InviteStatus, Role
from models.user import User
from repositories import refresh_tokens as refresh_token_repo
from repositories import users as user_repo
from services import audit_service


async def _enforce_password_policy(password: str) -> None:
    violations = password_policy_violations(password)
    if violations:
        raise PasswordPolicyViolation(violations)
    if await is_breached_password(password):
        raise BreachedPassword()


async def accept_invite(db: AsyncSession, *, invite_token: str, password: str) -> tuple[User, Role, str | None]:
    """Returns (user, role, totp_provisioning_uri). The URI is only present
    for OWNER/ACCOUNTANT — MFA enrollment is mandatory for them (§14) and
    the client should render it as a QR code immediately. The caller (the
    accept-invite route) logs the user in right after this returns, since
    otherwise an OWNER/ACCOUNTANT could never reach /auth/mfa/confirm —
    the normal login path refuses them until MFA is enrolled."""
    try:
        user_id = decode_invite_token(invite_token)
    except Exception as exc:
        raise InvalidToken("Invite link is invalid or has expired.") from exc

    user = await user_repo.get_by_id(db, uuid.UUID(user_id))
    if user is None:
        raise NotFound("User")
    if user.invite_status != InviteStatus.PENDING:
        raise Conflict("INVITE_ALREADY_USED", "This invite has already been used.")

    await _enforce_password_policy(password)

    role_row = await user_repo.get_role(db, user.id)
    role = role_row.role  # type: ignore[union-attr]

    user.password_hash = hash_password(password)
    user.invite_status = InviteStatus.ACTIVE

    provisioning_uri = None
    if role in (Role.OWNER, Role.ACCOUNTANT):
        secret = generate_totp_secret()
        user.mfa_secret = secret
        user.mfa_enrolled = False  # set True once they verify a code, not just receive the secret
        provisioning_uri = totp_provisioning_uri(secret, user.email)

    await audit_service.write(
        db, actor_id=user.id, action="user.accepted_invite", entity="user", entity_id=user.id
    )
    return user, role, provisioning_uri


async def confirm_mfa_enrollment(db: AsyncSession, *, user: User, code: str) -> None:
    if not user.mfa_secret or not verify_totp(user.mfa_secret, code):
        raise MfaInvalid()
    user.mfa_enrolled = True
    await audit_service.write(db, actor_id=user.id, action="user.mfa_enrolled", entity="user", entity_id=user.id)


async def change_role(db: AsyncSession, *, target_user_id: uuid.UUID, new_role: Role, actor_id: uuid.UUID) -> User:
    user = await user_repo.get_by_id(db, target_user_id)
    if user is None:
        raise NotFound("User")
    role_row = await user_repo.get_role(db, target_user_id)
    if role_row is None:
        raise NotFound("User role")

    old_role = role_row.role
    if old_role == Role.OWNER and new_role != Role.OWNER:
        remaining = await user_repo.count_active_owners(db, excluding_user_id=target_user_id)
        if remaining < 1:
            raise LastOwnerGuard()

    role_row.role = new_role
    role_row.assigned_by = actor_id
    role_row.assigned_at = datetime.now(UTC)

    await audit_service.write(
        db,
        actor_id=actor_id,
        action="user.role_changed",
        entity="user",
        entity_id=target_user_id,
        before={"role": old_role.value},
        after={"role": new_role.value},
    )
    return user


async def deactivate(db: AsyncSession, *, target_user_id: uuid.UUID, actor_id: uuid.UUID) -> User:
    user = await user_repo.get_by_id(db, target_user_id)
    if user is None:
        raise NotFound("User")
    role_row = await user_repo.get_role(db, target_user_id)

    if role_row is not None and role_row.role == Role.OWNER:
        remaining = await user_repo.count_active_owners(db, excluding_user_id=target_user_id)
        if remaining < 1:
            raise LastOwnerGuard()

    before_status = user.invite_status.value
    user.invite_status = InviteStatus.DEACTIVATED
    await refresh_token_repo.revoke_all_for_user(db, user_id=user.id, revoked_at=datetime.now(UTC))

    await audit_service.write(
        db,
        actor_id=actor_id,
        action="user.deactivated",
        entity="user",
        entity_id=target_user_id,
        before={"invite_status": before_status},
        after={"invite_status": InviteStatus.DEACTIVATED.value},
    )
    return user


async def reactivate(db: AsyncSession, *, target_user_id: uuid.UUID, actor_id: uuid.UUID) -> User:
    user = await user_repo.get_by_id(db, target_user_id)
    if user is None:
        raise NotFound("User")
    if user.invite_status != InviteStatus.DEACTIVATED:
        raise Conflict("NOT_DEACTIVATED", "User is not currently deactivated.")

    before_status = user.invite_status.value
    user.invite_status = InviteStatus.ACTIVE

    await audit_service.write(
        db,
        actor_id=actor_id,
        action="user.reactivated",
        entity="user",
        entity_id=target_user_id,
        before={"invite_status": before_status},
        after={"invite_status": InviteStatus.ACTIVE.value},
    )
    return user
