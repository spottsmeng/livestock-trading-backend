import pyotp
from sqlalchemy.ext.asyncio import AsyncSession

from models.enums import Role
from models.organisation import Organisation
from tests.conftest import DEV_PASSWORD, make_active_user


async def test_buyer_logs_in_without_mfa(client, db: AsyncSession, everhealth_org: Organisation):
    await make_active_user(db, org=everhealth_org, email="buyer@test.com", role=Role.BUYER)
    resp = await client.post("/api/v1/auth/login", json={"email": "buyer@test.com", "password": DEV_PASSWORD})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_owner_login_without_totp_is_rejected(client, db: AsyncSession, everhealth_org: Organisation):
    await make_active_user(db, org=everhealth_org, email="owner@test.com", role=Role.OWNER, with_mfa=True)
    resp = await client.post("/api/v1/auth/login", json={"email": "owner@test.com", "password": DEV_PASSWORD})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "MFA_REQUIRED"


async def test_owner_login_with_wrong_totp_is_rejected(client, db: AsyncSession, everhealth_org: Organisation):
    await make_active_user(db, org=everhealth_org, email="owner2@test.com", role=Role.OWNER, with_mfa=True)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner2@test.com", "password": DEV_PASSWORD, "totp_code": "000000"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "MFA_INVALID"


async def test_owner_login_with_correct_totp_succeeds(client, db: AsyncSession, everhealth_org: Organisation):
    user, secret = await make_active_user(
        db, org=everhealth_org, email="owner3@test.com", role=Role.OWNER, with_mfa=True
    )
    code = pyotp.TOTP(secret).now()
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "owner3@test.com", "password": DEV_PASSWORD, "totp_code": code}
    )
    assert resp.status_code == 200


async def test_unknown_email_and_wrong_password_return_the_same_error(
    client, db: AsyncSession, everhealth_org: Organisation
):
    """Never let a login response reveal whether the account exists."""
    await make_active_user(db, org=everhealth_org, email="known@test.com", role=Role.BUYER)

    unknown = await client.post("/api/v1/auth/login", json={"email": "nobody@test.com", "password": "whatever123"})
    wrong_pw = await client.post("/api/v1/auth/login", json={"email": "known@test.com", "password": "wrongpassword"})

    assert unknown.status_code == wrong_pw.status_code == 401
    assert unknown.json()["error"]["code"] == wrong_pw.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_rate_limited_after_five_attempts(client, db: AsyncSession, everhealth_org: Organisation):
    await make_active_user(db, org=everhealth_org, email="ratelimited@test.com", role=Role.BUYER)
    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/login", json={"email": "ratelimited@test.com", "password": "wrongpassword"}
        )
        assert resp.status_code == 401
    sixth = await client.post(
        "/api/v1/auth/login", json={"email": "ratelimited@test.com", "password": "wrongpassword"}
    )
    assert sixth.status_code == 429
    assert sixth.json()["error"]["code"] == "RATE_LIMITED"


async def test_refresh_rotation_and_reuse_detection(client, db: AsyncSession, everhealth_org: Organisation):
    await make_active_user(db, org=everhealth_org, email="rotator@test.com", role=Role.BUYER)
    login = await client.post("/api/v1/auth/login", json={"email": "rotator@test.com", "password": DEV_PASSWORD})
    assert login.status_code == 200
    old_cookie = client.cookies.get("refresh_token")

    first_refresh = await client.post("/api/v1/auth/refresh")
    assert first_refresh.status_code == 200

    # Replay the OLD (already-rotated) cookie — must be detected as reuse.
    client.cookies.set("refresh_token", old_cookie)
    reused = await client.post("/api/v1/auth/refresh")
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"

    # And the family is now fully dead — even the token that WAS valid a
    # moment ago no longer works.
    new_cookie = first_refresh.cookies.get("refresh_token")
    client.cookies.set("refresh_token", new_cookie)
    dead = await client.post("/api/v1/auth/refresh")
    assert dead.status_code == 401


async def test_me_requires_a_bearer_token(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_deny_by_default_owner_route_rejects_buyer(client, db: AsyncSession, everhealth_org: Organisation):
    await make_active_user(db, org=everhealth_org, email="buyer2@test.com", role=Role.BUYER)
    login = await client.post("/api/v1/auth/login", json={"email": "buyer2@test.com", "password": DEV_PASSWORD})
    token = login.json()["access_token"]

    resp = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"
