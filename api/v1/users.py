import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUser, require_role
from core.db import get_db
from core.errors import Conflict, NotFound
from models.audit_log import AuditLog
from models.enums import OrgKind, Role
from repositories import organisations as org_repo
from repositories import users as user_repo
from schemas.users import AuditEntryResponse, InviteUserRequest, RoleChangeRequest, UserResponse
from services import invite_service, user_service

router = APIRouter(prefix="/users", tags=["users"])

# Every route in this file is OWNER-only per §9.1a/§2.1.2 — Bobby is the
# only one who manages accounts. This is a deliberate, narrower gate than
# require_role(OWNER, ACCOUNTANT); do not widen it without re-reading §9.1a.
_owner_only = require_role(Role.OWNER)


def _to_response(user, role: Role) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        role=role,
        org_id=user.org_id,
        invite_status=user.invite_status,
        mfa_enrolled=user.mfa_enrolled,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.post("/invite", response_model=UserResponse, status_code=201)
async def invite(
    body: InviteUserRequest,
    current: CurrentUser = Depends(_owner_only),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    existing = await user_repo.get_by_email(db, body.email)
    if existing is not None:
        raise Conflict("EMAIL_ALREADY_EXISTS", "A user with this email already exists.")

    # v1 has one organisation on the Livestock Trading Co. side; every
    # invited user (OWNER, ACCOUNTANT, or BUYER) belongs to it. External
    # buyers are still "hired by Bobby" (§2.1), not a separate org tenant.
    org = await org_repo.get_by_kind(db, OrgKind.EVERHEALTH)
    if org is None:
        raise NotFound("Organisation")

    user, _invite_token = await invite_service.invite_user(
        db, org_id=org.id, email=body.email, role=body.role, invited_by=current.user_id
    )
    await db.commit()
    return _to_response(user, body.role)


@router.get("", response_model=list[UserResponse])
async def list_all(
    role: Role | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    current: CurrentUser = Depends(_owner_only),
    db: AsyncSession = Depends(get_db),
) -> list[UserResponse]:
    rows = await user_repo.list_users(db, role=role, is_active=is_active)
    return [_to_response(user, user_role.role) for user, user_role in rows]


@router.get("/{user_id}", response_model=UserResponse)
async def get_one(
    user_id: uuid.UUID, current: CurrentUser = Depends(_owner_only), db: AsyncSession = Depends(get_db)
) -> UserResponse:
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        raise NotFound("User")
    role_row = await user_repo.get_role(db, user_id)
    if role_row is None:
        raise NotFound("User role")
    return _to_response(user, role_row.role)


@router.patch("/{user_id}/role", response_model=UserResponse)
async def change_role(
    user_id: uuid.UUID,
    body: RoleChangeRequest,
    current: CurrentUser = Depends(_owner_only),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    user = await user_service.change_role(db, target_user_id=user_id, new_role=body.role, actor_id=current.user_id)
    await db.commit()
    return _to_response(user, body.role)


@router.post("/{user_id}/deactivate", response_model=UserResponse)
async def deactivate(
    user_id: uuid.UUID, current: CurrentUser = Depends(_owner_only), db: AsyncSession = Depends(get_db)
) -> UserResponse:
    user = await user_service.deactivate(db, target_user_id=user_id, actor_id=current.user_id)
    await db.commit()
    role_row = await user_repo.get_role(db, user_id)
    return _to_response(user, role_row.role)  # type: ignore[union-attr]


@router.post("/{user_id}/reactivate", response_model=UserResponse)
async def reactivate(
    user_id: uuid.UUID, current: CurrentUser = Depends(_owner_only), db: AsyncSession = Depends(get_db)
) -> UserResponse:
    user = await user_service.reactivate(db, target_user_id=user_id, actor_id=current.user_id)
    await db.commit()
    role_row = await user_repo.get_role(db, user_id)
    return _to_response(user, role_row.role)  # type: ignore[union-attr]


@router.get("/{user_id}/audit", response_model=list[AuditEntryResponse])
async def audit(
    user_id: uuid.UUID, current: CurrentUser = Depends(_owner_only), db: AsyncSession = Depends(get_db)
) -> list[AuditEntryResponse]:
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.entity == "user", AuditLog.entity_id == user_id)
        .order_by(AuditLog.at.desc())
    )
    return list(result.scalars().all())
