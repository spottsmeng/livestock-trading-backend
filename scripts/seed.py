"""Bootstrap seed for local dev: the three organisations (§8) and one demo
account per role, so Phase 0's demo ("log in as each role") has something
to log in as. This is a trusted, local-only script with direct DB access —
it does NOT go through the invite/accept-invite flow, and that's
deliberate: it also solves the chicken-and-egg problem of who invites the
very first OWNER, since normally only an existing OWNER can invite anyone.

Run with: uv run python -m scripts.seed
"""

import asyncio

from core.db import async_session_factory
from core.security import generate_totp_secret, hash_password, totp_provisioning_uri
from models.enums import InviteStatus, OrgKind, Role
from models.organisation import Organisation
from models.user import User
from models.user_role import UserRole
from repositories import organisations as org_repo
from repositories import users as user_repo

DEV_PASSWORD = "ChangeMe123!Dev"  # noqa: S105 — local dev seed only, never used outside this script


async def _get_or_create_org(session, kind: OrgKind, name: str) -> Organisation:
    org = await org_repo.get_by_kind(session, kind)
    if org is not None:
        return org
    org = Organisation(name=name, kind=kind)
    session.add(org)
    await session.flush()
    return org


async def _seed_user(session, *, org: Organisation, email: str, role: Role, with_mfa: bool) -> None:
    existing = await user_repo.get_by_email(session, email)
    if existing is not None:
        print(f"  {role.value}: {email} (already exists, skipped)")
        return

    user = User(
        org_id=org.id,
        email=email.lower(),
        password_hash=hash_password(DEV_PASSWORD),
        invite_status=InviteStatus.ACTIVE,
    )
    if with_mfa:
        secret = generate_totp_secret()
        user.mfa_secret = secret
        user.mfa_enrolled = True
    session.add(user)
    await session.flush()
    session.add(UserRole(user_id=user.id, role=role, assigned_by=None))

    print(f"  {role.value}: {email} / {DEV_PASSWORD}")
    if with_mfa:
        print(f"    TOTP secret: {secret}  (or scan: {totp_provisioning_uri(secret, email)})")


async def main() -> None:
    async with async_session_factory() as session:
        everhealth = await _get_or_create_org(session, OrgKind.EVERHEALTH, "Everhealth (Livestock Trading Co.)")
        # Modeled per §8/§2 for organisation-level data isolation even
        # though neither gets user accounts: the Abattoir never logs in
        # (§2.1.1), and BUYER_CO exists so buyer.org_id is never the same
        # tenant as Everhealth's — External Buyer Co. accounts still live
        # under Everhealth's org in v1 (§9.1 invite has no org selector
        # yet), but the row is here so the isolation model is real, not
        # aspirational, the moment a second tenant is needed.
        await _get_or_create_org(session, OrgKind.ABATTOIR, "Abattoir")
        await _get_or_create_org(session, OrgKind.BUYER_CO, "External Buyer Co.")

        print("Seeded demo accounts (local dev only):")
        await _seed_user(session, org=everhealth, email="bobby@example.com", role=Role.OWNER, with_mfa=False)
        await _seed_user(session, org=everhealth, email="bing@example.com", role=Role.ACCOUNTANT, with_mfa=False)
        await _seed_user(session, org=everhealth, email="buyer@example.com", role=Role.BUYER, with_mfa=False)

        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
