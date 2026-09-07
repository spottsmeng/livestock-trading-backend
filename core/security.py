import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from core.config import settings

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12


# ---------------------------------------------------------------------------
# Passwords — Argon2id, minimum length, breached-password check (§14).
# Never call anything in this module with a plaintext password you intend
# to log or persist anywhere but hash_password's return value.
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def password_policy_violations(password: str) -> list[str]:
    violations = []
    if len(password) < MIN_PASSWORD_LENGTH:
        violations.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return violations


async def is_breached_password(password: str) -> bool:
    """Have I Been Pwned k-anonymity range API. No API key, free, and the
    full password never leaves this process — only a 5-char SHA-1 prefix
    does. Skippable in CI/tests via DISABLE_BREACHED_PASSWORD_CHECK.
    """
    if settings.disable_breached_password_check:
        return False
    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()  # noqa: S324 — HIBP protocol, not for storage
    prefix, suffix = sha1[:5], sha1[5:]
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            resp = await client.get(f"https://api.pwnedpasswords.com/range/{prefix}")
            resp.raise_for_status()
        except httpx.HTTPError:
            # Fail open: an HIBP outage must never block a legitimate login/invite.
            return False
    for line in resp.text.splitlines():
        candidate_suffix, _count = line.split(":")
        if candidate_suffix == suffix:
            return True
    return False


# ---------------------------------------------------------------------------
# JWT access tokens — short-lived, role/org carried in the claims so every
# route's require_role() check never has to hit the DB (§14).
# ---------------------------------------------------------------------------


def create_access_token(*, user_id: str, role: str, org_id: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "org_id": org_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# ---------------------------------------------------------------------------
# Refresh tokens — opaque random values; only a SHA-256 hash is ever stored,
# so a stolen DB dump can't be replayed as a live session. Rotation, reuse
# detection and per-family revocation live in services/auth_service.py.
# ---------------------------------------------------------------------------


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def new_token_family() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# TOTP MFA — required at enrollment for OWNER/ACCOUNTANT only (§14).
# ---------------------------------------------------------------------------


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, email: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name="Livestock Trade Management")


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.totp.TOTP(secret).verify(code, valid_window=1)


# ---------------------------------------------------------------------------
# Invite tokens — short-lived, single-purpose JWTs. Possession of the link
# is the only credential; the user still sets their own password on accept.
# ---------------------------------------------------------------------------


def create_invite_token(*, user_id: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "type": "invite",
        "iat": now,
        "exp": now + timedelta(hours=settings.invite_ttl_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_invite_token(token: str) -> str:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "invite":
        raise jwt.InvalidTokenError("Not an invite token")
    return payload["sub"]
