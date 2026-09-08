"""domain/engine is required to have zero I/O (§17.1), and its golden-vector
suite is meant to be "the highest-value test in the codebase" (§17.3) —
runnable in complete isolation, with no Postgres/Redis/docker-compose. The
parent tests/conftest.py wires up exactly that DB/Redis infrastructure via
three autouse fixtures for the rest of the suite; redefine all three here
as no-ops so pytest resolves this nearer conftest's version for every test
under tests/engine/, without touching the parent suite at all.

Phase 5 found this directory was actually only two-thirds isolated:
`_seed_reference_data` (Phase 3b) is also autouse and depends on `db`, and
was never given a matching override here — every test under tests/engine/
was silently opening a real Postgres connection despite none of them
taking a `db`/`client` fixture themselves (confirmed: grepped, zero hits).
This stayed invisible locally because the `livestock_test` database this
needs has quietly existed in the persisted local docker-compose Postgres
volume since Phase 1 — CI's Postgres service container starts empty every
run, and the *other* two no-ops here mean nothing ever creates it, so this
whole directory failed in CI (`database "livestock_test" does not exist`)
the moment a fresh checkout actually got far enough to run it.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _test_database_schema():
    yield


@pytest.fixture(autouse=True)
def _wire_overrides():
    yield


@pytest.fixture(autouse=True)
def _seed_reference_data():
    yield
