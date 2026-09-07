from fastapi.routing import APIRoute, _IncludedRouter

from api.deps import get_current_user
from main import app
from models.enums import Role

# Non-negotiable #3 (phase00-instructions.txt): every route declares its
# required role(s) explicitly; nothing is reachable by omission. This test
# doesn't trust that review caught every route — it inspects the actual
# dependant tree FastAPI built and fails if a NEW route is ever added
# without an auth dependency.
#
# FastAPI 0.141.1 changed include_router's internals: a sub-router is
# wrapped in a lazy _IncludedRouter instead of being flattened into
# app.routes with the prefix baked into .path — app.routes alone no
# longer surfaces the real endpoints. Walking .original_router recursively
# is what actually finds them; discovered by running this, not assumed.
#
# These are the only routes allowed to skip authentication, each for a
# specific, reviewed reason (paths are relative to their own router, since
# that's what this FastAPI version's route tree actually exposes):
#   - the credential-issuing routes themselves (you can't require a token
#     to get a token)
#   - /auth/refresh and /auth/logout, which authenticate via the httpOnly
#     refresh cookie instead of a bearer token
#   - /health, which must be reachable by Docker/CI health checks
_INTENTIONALLY_PUBLIC_PATHS = {
    "/auth/login",
    "/auth/refresh",
    "/auth/logout",
    "/auth/accept-invite",
    "/health",
}


def _all_api_routes() -> list[APIRoute]:
    found: list[APIRoute] = []

    def _walk(router) -> None:
        for r in getattr(router, "routes", []):
            if isinstance(r, APIRoute):
                found.append(r)
            elif isinstance(r, _IncludedRouter):
                _walk(r.original_router)

    _walk(app.router)
    return found


def _dependant_requires_current_user(dependant) -> bool:
    if dependant.call is get_current_user:
        return True
    return any(_dependant_requires_current_user(sub) for sub in dependant.dependencies)


def _dependant_requires_owner_only(dependant) -> bool:
    # require_role's inner closure captures allowed_roles in its cell
    # vars — reach in rather than re-deriving the role set.
    if dependant.call is not None and dependant.call.__name__ == "_dependency":
        closure = dependant.call.__closure__ or ()
        return any(cell.cell_contents == (Role.OWNER,) for cell in closure)
    return any(_dependant_requires_owner_only(sub) for sub in dependant.dependencies)


def test_every_route_except_the_reviewed_public_ones_requires_auth():
    api_routes = _all_api_routes()
    assert len(api_routes) > 5, "sanity check: routes should be registered by the time this test runs"

    unprotected = [
        r.path
        for r in api_routes
        if r.path not in _INTENTIONALLY_PUBLIC_PATHS and not _dependant_requires_current_user(r.dependant)
    ]
    assert unprotected == [], f"Routes reachable with no auth dependency: {unprotected}"


def test_every_users_route_is_owner_only():
    """§9.1a is narrower than the general RBAC rule: the whole /users
    surface is OWNER-only, not OWNER-or-ACCOUNTANT."""
    users_routes = [r for r in _all_api_routes() if r.path.startswith("/users")]
    assert len(users_routes) >= 6

    not_owner_only = [r.path for r in users_routes if not _dependant_requires_owner_only(r.dependant)]
    assert not_owner_only == [], f"/users routes not gated to OWNER only: {not_owner_only}"
