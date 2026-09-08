import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import redis_dep
from core.config import settings
from core.db import Base, get_db
from core.security import generate_totp_secret, hash_password
from main import app
from models.enums import InviteStatus, OrgKind, Role
from models.organisation import Organisation
from models.user import User
from models.user_role import UserRole

DEV_PASSWORD = "TestPassword123!"  # noqa: S105 — fixture-only, never a real credential

# Truncate order matters: children before parents (FK constraints).
_TABLES_IN_DELETE_ORDER = [
    "validation_issues",
    "correction_requests",
    "order_workings",
    "order_lines",
    "order_snapshots",
    "audit_log",
    "refresh_tokens",
    "user_roles",
    "users",
    "organisations",
]


@pytest.fixture(scope="session", autouse=True)
def _force_mfa_enforcement():
    """§14's MFA gate (core/config.py's mfa_enforcement_enabled) defaults
    on but a developer's local .env may turn it off for their own
    convenience during this dev/test/demo phase. The test suite must never
    inherit that: tests like test_auth_flow.py's
    test_owner_login_without_totp_is_rejected exist specifically to prove
    the gate works, so they always run against it forced on, regardless of
    whatever's currently convenient to develop against."""
    original = settings.mfa_enforcement_enabled
    settings.mfa_enforcement_enabled = True
    yield
    settings.mfa_enforcement_enabled = original


def _test_database_url() -> str:
    """Never run tests against settings.database_url directly — that's
    whatever a developer's local Postgres happens to be pointed at (e.g.
    a dev DB seeded via scripts/seed.py), and colliding with real dev data
    is exactly the kind of flaky, environment-dependent failure a test
    suite must not have. Tests get their own <name>_test database instead,
    created on demand."""
    base_url, _, db_name = settings.database_url.rpartition("/")
    return f"{base_url}/{db_name}_test"


@pytest.fixture(scope="session", autouse=True)
async def _test_database_schema():
    """Session-scoped: create the test database if it doesn't exist yet,
    then create every table from the SQLAlchemy models directly. This
    intentionally does NOT go through Alembic — migration correctness
    (including the enum-type downgrade fix) is validated separately by
    actually running alembic upgrade/downgrade, not by the test suite."""
    admin_engine = create_async_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    test_db_name = _test_database_url().rsplit("/", 1)[-1]
    async with admin_engine.connect() as conn:
        exists = await conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": test_db_name})
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{test_db_name}"'))
    await admin_engine.dispose()

    schema_engine = create_async_engine(_test_database_url())
    async with schema_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await schema_engine.dispose()
    yield


@pytest.fixture
async def db():
    """A fresh engine per test, not the process-lifetime singleton in
    core/db.py. That singleton is correct for the real app (one event loop
    for its whole life) but wrong across pytest-asyncio's function-scoped
    loops — a pooled connection from one test's loop breaks when reused
    under a later test's (different) loop. This also becomes the engine
    the app itself uses for the duration of the test, via the dependency
    override below, so test-inserted data and app-driven queries share one
    consistent, this-test-only connection pool."""
    engine = create_async_engine(_test_database_url(), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    async with session_factory() as session:
        yield session

    async with session_factory() as session:
        for table in _TABLES_IN_DELETE_ORDER:
            await session.execute(text(f"DELETE FROM {table}"))
        await session.commit()

    del app.dependency_overrides[get_db]
    await engine.dispose()


@pytest.fixture
async def redis_client():
    """Same reasoning as `db` above, applied to core/redis.py's
    @lru_cache'd client."""
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    await client.flushdb()

    app.dependency_overrides[redis_dep] = lambda: client

    yield client

    await client.flushdb()
    del app.dependency_overrides[redis_dep]
    await client.aclose()


@pytest.fixture(autouse=True)
def _wire_overrides(db, redis_client):
    """Every test gets both overrides active without asking for them by
    name — asking for `db`/`redis_client` directly is still fine when a
    test needs to touch them."""
    yield


@pytest.fixture
async def everhealth_org(db: AsyncSession) -> Organisation:
    org = Organisation(name="Everhealth (Livestock Trading Co.)", kind=OrgKind.EVERHEALTH)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def make_active_user(
    db: AsyncSession, *, org: Organisation, email: str, role: Role, with_mfa: bool = False
) -> tuple[User, str | None]:
    """Test helper — creates an ACTIVE user directly (bypassing invite),
    returning (user, mfa_secret). Mirrors scripts/seed.py's bootstrap
    approach, kept separate since production code must never take this
    shortcut outside a trusted local script."""
    user = User(
        org_id=org.id, email=email.lower(), password_hash=hash_password(DEV_PASSWORD), invite_status=InviteStatus.ACTIVE
    )
    secret = None
    if with_mfa:
        secret = generate_totp_secret()
        user.mfa_secret = secret
        user.mfa_enrolled = True
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role=role, assigned_by=None))
    await db.commit()
    await db.refresh(user)
    return user, secret
