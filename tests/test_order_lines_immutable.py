"""§19 acceptance criteria: "the application database role holds no
UPDATE/DELETE grant on order_lines, and the guard trigger fires in a
test." Non-negotiable #1.

This can only be verified by actually running the Alembic migration —
tests/conftest.py's standard `db` fixture builds its schema straight from
SQLAlchemy metadata (`Base.metadata.create_all`), which has no concept of
a REVOKE or a trigger (see that fixture's own docstring). This test uses a
dedicated, migration-built database instead, mirroring how the first
migration's enum-drop fix is "validated separately by actually running
alembic upgrade/downgrade, not by the test suite."
"""

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import settings

BACKEND_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_TEST_DB_NAME = "livestock_migration_test"


def _migration_test_db_url() -> str:
    base_url, _, _ = settings.database_url.rpartition("/")
    return f"{base_url}/{MIGRATION_TEST_DB_NAME}"


@pytest.fixture(scope="module")
async def migration_test_db_url():
    """Module-scoped: the expensive part (create the database, run the
    real Alembic CLI against it in a subprocess) happens once. Yields only
    the URL — each test builds its own engine against it (see `db_engine`
    below), since an asyncpg connection pool is tied to the event loop it
    was created on and pytest-asyncio gives each test function its own."""
    admin_engine = create_async_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_TEST_DB_NAME}"'))
        await conn.execute(text(f'CREATE DATABASE "{MIGRATION_TEST_DB_NAME}"'))
    await admin_engine.dispose()

    # alembic/env.py itself calls asyncio.run(...), which cannot nest inside
    # pytest-asyncio's already-running loop — run the real CLI in a
    # subprocess instead, exactly as a developer would.
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env={**os.environ, "DATABASE_URL": _migration_test_db_url()},
        check=True,
        capture_output=True,
    )

    yield _migration_test_db_url()

    admin_engine = create_async_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_TEST_DB_NAME}"'))
    await admin_engine.dispose()


@pytest.fixture
async def db_engine(migration_test_db_url):
    engine = create_async_engine(migration_test_db_url)
    yield engine
    await engine.dispose()


async def _seed_line(conn, *, lifecycle: str, contract_no: str) -> uuid.UUID:
    suffix = uuid.uuid4().hex[:8]
    org_name = f"Test Org {suffix}"
    await conn.execute(
        text("INSERT INTO organisations (id, name, kind) VALUES (gen_random_uuid(), :name, 'EVERHEALTH')"),
        {"name": org_name},
    )
    org_id = (
        await conn.execute(text("SELECT id FROM organisations WHERE name = :n"), {"n": org_name})
    ).scalar()
    email = f"immutable-test-{suffix}@x.com"
    await conn.execute(
        text(
            "INSERT INTO users (id, org_id, email, invite_status, mfa_enrolled) "
            "VALUES (gen_random_uuid(), :org, :email, 'ACTIVE', false)"
        ),
        {"org": org_id, "email": email},
    )
    user_id = (await conn.execute(text("SELECT id FROM users WHERE email = :email"), {"email": email})).scalar()
    sha = f"sha-{suffix}"
    await conn.execute(
        text(
            "INSERT INTO order_snapshots (id, org_id, uploaded_by, source_filename, source_sha256, "
            "object_storage_key, detected_layout, abattoir_reference_tables, parser_version, status) "
            "VALUES (gen_random_uuid(), :org, :u, 'f.xlsx', :sha, 'key', '{}', '{}', 'v1', 'PARSED')"
        ),
        {"org": org_id, "u": user_id, "sha": sha},
    )
    snapshot_id = (
        await conn.execute(text("SELECT id FROM order_snapshots WHERE source_sha256 = :sha"), {"sha": sha})
    ).scalar()
    await conn.execute(
        text(
            "INSERT INTO order_lines (id, snapshot_id, line_no, lifecycle, contract_no, value_sources) "
            "VALUES (gen_random_uuid(), :s, 1, :lifecycle, :contract_no, '{}')"
        ),
        {"s": snapshot_id, "lifecycle": lifecycle, "contract_no": f"{contract_no}-{suffix}"},
    )
    return (
        await conn.execute(
            text("SELECT id FROM order_lines WHERE contract_no = :c"), {"c": f"{contract_no}-{suffix}"}
        )
    ).scalar()


async def _cleanup(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE order_lines DISABLE TRIGGER order_lines_no_mutation"))
        await conn.execute(text("DELETE FROM order_workings"))
        await conn.execute(text("DELETE FROM order_lines"))
        await conn.execute(text("ALTER TABLE order_lines ENABLE TRIGGER order_lines_no_mutation"))
        await conn.execute(text("DELETE FROM order_snapshots"))
        await conn.execute(text("DELETE FROM users"))
        await conn.execute(text("DELETE FROM organisations"))


async def test_update_on_order_lines_is_rejected(db_engine):
    async with db_engine.begin() as conn:
        line_id = await _seed_line(conn, lifecycle="ACTIVE", contract_no="C1")

    with pytest.raises(Exception, match="order_lines is immutable"):
        async with db_engine.begin() as conn:
            await conn.execute(text("UPDATE order_lines SET contract_no = 'C2' WHERE id = :id"), {"id": line_id})

    await _cleanup(db_engine)


async def test_delete_on_order_lines_is_rejected(db_engine):
    async with db_engine.begin() as conn:
        line_id = await _seed_line(conn, lifecycle="ACTIVE", contract_no="C1")

    with pytest.raises(Exception, match="order_lines is immutable"):
        async with db_engine.begin() as conn:
            await conn.execute(text("DELETE FROM order_lines WHERE id = :id"), {"id": line_id})

    await _cleanup(db_engine)


async def test_order_workings_rejected_for_loaded_line(db_engine):
    async with db_engine.begin() as conn:
        loaded_line_id = await _seed_line(conn, lifecycle="LOADED", contract_no="C2")

    with pytest.raises(Exception, match="may only be created for an ACTIVE order_line"):
        async with db_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO order_workings (id, order_line_id, engine_version, ref_data_version, "
                    "bing_dnbp_inputs, supporting_analysis_complete) "
                    "VALUES (gen_random_uuid(), :l, 'v1', 'v1', '{}', false)"
                ),
                {"l": loaded_line_id},
            )

    await _cleanup(db_engine)
