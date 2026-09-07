"""domain/engine is required to have zero I/O (§17.1), and its golden-vector
suite is meant to be "the highest-value test in the codebase" (§17.3) —
runnable in complete isolation, with no Postgres/Redis/docker-compose. The
parent tests/conftest.py wires up exactly that DB/Redis infrastructure via
two autouse fixtures for the rest of the (Phase 0) suite; redefine both
here as no-ops so pytest resolves this nearer conftest's version for every
test under tests/engine/, without touching the parent suite at all.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _test_database_schema():
    yield


@pytest.fixture(autouse=True)
def _wire_overrides():
    yield
