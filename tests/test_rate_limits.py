"""§14 — "100/min general, 1000/min on buyer sync endpoints" (Phase 5, on
top of the pre-existing 5/min login limiter — test_auth_flow.py's own
test_login_rate_limited_after_five_attempts). Same "real test hitting the
limit" discipline: loops a real request through the real middleware until
it actually 429s, rather than asserting the config value alone.

Limits are lowered via monkeypatch so the test doesn't need hundreds/
thousands of real requests to prove the ceiling works — core.rate_limit_
middleware reads core.config.settings at request time (never cached), so
this takes effect immediately.
"""

from core.config import settings


async def test_general_rate_limit_refuses_past_the_configured_ceiling(client, monkeypatch):
    monkeypatch.setattr(settings, "general_rate_limit_per_minute", 3)

    for _ in range(3):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401  # no bearer token — reaches the route, just unauthenticated

    limited = await client.get("/api/v1/auth/me")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


async def test_buyer_sync_rate_limit_uses_its_own_higher_ceiling(client, monkeypatch):
    """The buyer-sync bucket is independent of the general one — set the
    general limit very low and confirm a /buyer/* route still gets its own
    (higher, separately-configured) ceiling rather than inheriting the
    general one."""
    monkeypatch.setattr(settings, "general_rate_limit_per_minute", 1)
    monkeypatch.setattr(settings, "buyer_sync_rate_limit_per_minute", 3)

    for _ in range(3):
        resp = await client.get("/api/v1/buyer/dnbp/current")
        assert resp.status_code == 401  # no bearer token — reaches the route, just unauthenticated

    limited = await client.get("/api/v1/buyer/dnbp/current")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


async def test_login_route_is_exempt_from_the_general_limiter(client, db, monkeypatch, everhealth_org):
    """/auth/login keeps its own 5/min limiter (test_auth_flow.py) —
    confirm the general middleware doesn't ALSO count against it, which
    would make the two limiters interfere and lower the effective ceiling
    below the documented 5/min."""
    from models.enums import Role
    from tests.conftest import DEV_PASSWORD, make_active_user

    monkeypatch.setattr(settings, "general_rate_limit_per_minute", 1)
    await make_active_user(db, org=everhealth_org, email="examptlogin@test.com", role=Role.BUYER)

    for _ in range(3):
        resp = await client.post(
            "/api/v1/auth/login", json={"email": "examptlogin@test.com", "password": DEV_PASSWORD}
        )
        assert resp.status_code == 200
