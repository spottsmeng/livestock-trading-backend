"""Ingestion parser tests need no Postgres/Redis (domain/ingestion has no
I/O beyond the file bytes handed to it) — same reasoning, and same
no-op-override trick, as tests/engine/conftest.py."""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _test_database_schema():
    yield


@pytest.fixture(autouse=True)
def _wire_overrides():
    yield
