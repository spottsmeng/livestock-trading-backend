import hashlib

import httpx
import pytest

from core.security import is_breached_password, password_policy_violations


def test_short_password_is_rejected():
    assert password_policy_violations("Sh0rt!") != []


def test_twelve_char_password_passes_length_check():
    assert password_policy_violations("LongEnough12") == []


async def test_breach_check_flags_a_known_breached_password(monkeypatch):
    """§14: checked against a breached-password list. Simulates the HIBP
    k-anonymity response without hitting the real network."""
    monkeypatch.setattr("core.config.settings.disable_breached_password_check", False)

    password = "password123"
    sha1 = hashlib.sha1(password.encode()).hexdigest().upper()  # noqa: S324
    suffix = sha1[5:]

    class FakeResponse:
        text = f"{suffix}:3730471\nAAAA0000:1\n"

        def raise_for_status(self):
            pass

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: FakeClient())

    assert await is_breached_password(password) is True


async def test_breach_check_fails_open_on_network_error(monkeypatch):
    """An HIBP outage must never block a legitimate login/invite (§14's
    intent is user protection, not availability risk)."""
    monkeypatch.setattr("core.config.settings.disable_breached_password_check", False)

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: FailingClient())

    assert await is_breached_password("whatever-password-123") is False


@pytest.mark.asyncio
async def test_breach_check_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr("core.config.settings.disable_breached_password_check", True)
    assert await is_breached_password("password123") is False
