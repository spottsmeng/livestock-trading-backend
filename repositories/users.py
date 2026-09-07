import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.enums import InviteStatus, Role
from models.user import User
from models.user_role import UserRole


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_role(db: AsyncSession, user_id: uuid.UUID) -> UserRole | None:
    result = await db.execute(select(UserRole).where(UserRole.user_id == user_id))
    return result.scalar_one_or_none()


async def list_users(
    db: AsyncSession, *, role: Role | None = None, is_active: bool | None = None
) -> list[tuple[User, UserRole]]:
    stmt = select(User, UserRole).join(UserRole, UserRole.user_id == User.id)
    if role is not None:
        stmt = stmt.where(UserRole.role == role)
    if is_active is not None:
        if is_active:
            stmt = stmt.where(User.invite_status != InviteStatus.DEACTIVATED)
        else:
            stmt = stmt.where(User.invite_status == InviteStatus.DEACTIVATED)
    result = await db.execute(stmt.order_by(User.created_at))
    return list(result.all())


async def count_active_owners(db: AsyncSession, *, excluding_user_id: uuid.UUID | None = None) -> int:
    """The last-active-OWNER guard (§2.1.2) reads through this — never
    trust a cached count, always ask the database at decision time."""
    stmt = (
        select(func.count())
        .select_from(User)
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role == Role.OWNER, User.invite_status != InviteStatus.DEACTIVATED)
    )
    if excluding_user_id is not None:
        stmt = stmt.where(User.id != excluding_user_id)
    result = await db.execute(stmt)
    return result.scalar_one()


async def create_pending_user(
    db: AsyncSession, *, org_id: uuid.UUID, email: str, role: Role, invited_by: uuid.UUID | None
) -> User:
    user = User(org_id=org_id, email=email.lower(), invite_status=InviteStatus.PENDING, invited_by=invited_by)
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role=role, assigned_by=invited_by))
    return user
