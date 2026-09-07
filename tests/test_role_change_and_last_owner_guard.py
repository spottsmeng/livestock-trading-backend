import pyotp
from sqlalchemy.ext.asyncio import AsyncSession

from models.enums import Role
from models.organisation import Organisation
from tests.conftest import DEV_PASSWORD, make_active_user


async def _login(client, email: str, secret: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEV_PASSWORD, "totp_code": pyotp.TOTP(secret).now()}
    )
    return resp.json()["access_token"]


async def test_cannot_deactivate_the_last_active_owner(client, db: AsyncSession, everhealth_org: Organisation):
    owner, secret = await make_active_user(
        db, org=everhealth_org, email="solo@test.com", role=Role.OWNER, with_mfa=True
    )
    token = await _login(client, "solo@test.com", secret)

    resp = await client.post(f"/api/v1/users/{owner.id}/deactivate", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "LAST_OWNER_GUARD"


async def test_cannot_demote_the_last_active_owner(client, db: AsyncSession, everhealth_org: Organisation):
    owner, secret = await make_active_user(
        db, org=everhealth_org, email="solo2@test.com", role=Role.OWNER, with_mfa=True
    )
    token = await _login(client, "solo2@test.com", secret)

    resp = await client.patch(
        f"/api/v1/users/{owner.id}/role", json={"role": "ACCOUNTANT"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "LAST_OWNER_GUARD"


async def test_can_deactivate_an_owner_when_a_second_owner_exists(
    client, db: AsyncSession, everhealth_org: Organisation
):
    owner_a, secret_a = await make_active_user(
        db, org=everhealth_org, email="ownera@test.com", role=Role.OWNER, with_mfa=True
    )
    owner_b, _secret_b = await make_active_user(
        db, org=everhealth_org, email="ownerb@test.com", role=Role.OWNER, with_mfa=True
    )
    token = await _login(client, "ownera@test.com", secret_a)

    resp = await client.post(f"/api/v1/users/{owner_b.id}/deactivate", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["invite_status"] == "DEACTIVATED"


async def test_deactivation_revokes_sessions_but_keeps_the_row(
    client, db: AsyncSession, everhealth_org: Organisation
):
    owner_a, secret_a = await make_active_user(
        db, org=everhealth_org, email="ownerc@test.com", role=Role.OWNER, with_mfa=True
    )
    target, secret_target = await make_active_user(db, org=everhealth_org, email="target@test.com", role=Role.BUYER)

    admin_token = await _login(client, "ownerc@test.com", secret_a)
    target_login = await client.post(
        "/api/v1/auth/login", json={"email": "target@test.com", "password": DEV_PASSWORD}
    )
    assert target_login.status_code == 200
    target_refresh_cookie = target_login.cookies.get("refresh_token")

    resp = await client.post(
        f"/api/v1/users/{target.id}/deactivate", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200

    # The row survives (history is financial record, never deleted, §2.1.2)...
    audit = await client.get(f"/api/v1/users/{target.id}/audit", headers={"Authorization": f"Bearer {admin_token}"})
    assert any(entry["action"] == "user.deactivated" for entry in audit.json())

    # ...but the session is dead immediately.
    client.cookies.set("refresh_token", target_refresh_cookie)
    refresh_resp = await client.post("/api/v1/auth/refresh")
    assert refresh_resp.status_code == 401
