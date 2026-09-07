import pyotp
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import create_invite_token
from models.enums import Role
from models.organisation import Organisation
from repositories import users as user_repo
from tests.conftest import DEV_PASSWORD, make_active_user


async def _owner_token(client, db: AsyncSession, org: Organisation) -> str:
    _user, secret = await make_active_user(db, org=org, email="owner@test.com", role=Role.OWNER, with_mfa=True)
    code = pyotp.TOTP(secret).now()
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "owner@test.com", "password": DEV_PASSWORD, "totp_code": code}
    )
    return resp.json()["access_token"]


async def test_full_invite_accept_mfa_login_lifecycle(client, db: AsyncSession, everhealth_org: Organisation):
    token = await _owner_token(client, db, everhealth_org)

    invite_resp = await client.post(
        "/api/v1/users/invite",
        json={"email": "newbing@test.com", "role": "ACCOUNTANT"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert invite_resp.status_code == 201
    assert invite_resp.json()["invite_status"] == "PENDING"

    # In production the invite token is emailed; Phase 0 has no mailer yet
    # (deliberately, see phase00-instructions.txt) so services/invite_
    # service.py logs it — here we reach into the DB directly instead of
    # scraping logs, which is the point of the token being deterministic
    # from the user id.
    invited_user = await user_repo.get_by_email(db, "newbing@test.com")
    invite_token = create_invite_token(user_id=str(invited_user.id))

    accept_resp = await client.post(
        "/api/v1/auth/accept-invite", json={"invite_token": invite_token, "password": "NewPassword123!"}
    )
    assert accept_resp.status_code == 200
    body = accept_resp.json()
    assert body["mfa_required"] is True
    secret = body["totp_provisioning_uri"].split("secret=")[1].split("&")[0]

    # Can't log in the normal way yet — MFA isn't confirmed.
    blocked = await client.post(
        "/api/v1/auth/login",
        json={"email": "newbing@test.com", "password": "NewPassword123!", "totp_code": pyotp.TOTP(secret).now()},
    )
    assert blocked.status_code == 401
    assert blocked.json()["error"]["code"] == "MFA_REQUIRED"

    confirm_resp = await client.post(
        f"/api/v1/auth/mfa/confirm?code={pyotp.TOTP(secret).now()}",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert confirm_resp.status_code == 204

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "newbing@test.com", "password": "NewPassword123!", "totp_code": pyotp.TOTP(secret).now()},
    )
    assert login_resp.status_code == 200


async def test_inviting_a_duplicate_email_is_rejected(client, db: AsyncSession, everhealth_org: Organisation):
    token = await _owner_token(client, db, everhealth_org)
    await client.post(
        "/api/v1/users/invite",
        json={"email": "dupe@test.com", "role": "BUYER"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.post(
        "/api/v1/users/invite",
        json={"email": "dupe@test.com", "role": "BUYER"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"


async def test_accountant_cannot_invite_users(client, db: AsyncSession, everhealth_org: Organisation):
    """§9.1a is OWNER-only, deliberately narrower than the DNBP-model
    routes that both OWNER and ACCOUNTANT share."""
    _user, secret = await make_active_user(
        db, org=everhealth_org, email="bing@test.com", role=Role.ACCOUNTANT, with_mfa=True
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "bing@test.com", "password": DEV_PASSWORD, "totp_code": pyotp.TOTP(secret).now()},
    )
    token = login.json()["access_token"]

    resp = await client.post(
        "/api/v1/users/invite",
        json={"email": "someone@test.com", "role": "BUYER"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
