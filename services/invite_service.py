import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.security import create_invite_token
from models.enums import Role
from models.user import User
from repositories import users as user_repo
from services import audit_service

logger = logging.getLogger("invite")


async def invite_user(
    db: AsyncSession, *, org_id: uuid.UUID, email: str, role: Role, invited_by: uuid.UUID
) -> tuple[User, str]:
    user = await user_repo.create_pending_user(db, org_id=org_id, email=email, role=role, invited_by=invited_by)
    invite_token = create_invite_token(user_id=str(user.id))

    # No email infra exists yet (out of scope for Phase 0 — see
    # phase00-instructions.txt). This is the seam a real mailer plugs into
    # later; for now the link is logged so it's usable in local dev.
    send_invite_email(email=user.email, invite_token=invite_token)

    await audit_service.write(
        db,
        actor_id=invited_by,
        action="user.invited",
        entity="user",
        entity_id=user.id,
        after={"email": user.email, "role": role.value},
    )
    return user, invite_token


def send_invite_email(*, email: str, invite_token: str) -> None:
    link = f"/accept-invite?token={invite_token}"
    logger.info("Invite link for %s: %s", email, link)
