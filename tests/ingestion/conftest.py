"""Ingestion parser tests need no Postgres/Redis (domain/ingestion has no
I/O beyond the file bytes handed to it) — same reasoning, and same
no-op-override trick, as tests/engine/conftest.py.

Phase 5: this directory had the same gap tests/engine/conftest.py's own
docstring now documents in detail — `_seed_reference_data` (Phase 3b,
autouse, depends on `db`) was never overridden here either, so every test
in this directory was silently opening a real Postgres connection. See
tests/engine/conftest.py for the full story; the fix is identical."""

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
