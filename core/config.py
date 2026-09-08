from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://livestock:livestock@localhost:5432/livestock"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 30
    jwt_refresh_ttl_days_buyer: int = 90

    invite_ttl_hours: int = 72

    login_rate_limit_per_minute: int = 5
    # §14 — "100/min general" on everything else under /api/v1, and a
    # higher ceiling on the buyer-sync endpoints (§12.7's offline queue can
    # legitimately burst many entries at once on reconnect). Both share
    # core/rate_limit.py's fixed-window primitive with the login limiter.
    general_rate_limit_per_minute: int = 100
    buyer_sync_rate_limit_per_minute: int = 1000

    # Comma-separated. Must be explicit origins (not "*") because
    # allow_credentials=True is required for the refresh cookie — the
    # fetch spec forbids combining a wildcard origin with credentials.
    cors_allowed_origins: str = "http://localhost:3000"

    # §14 requires the refresh cookie to be Secure — but a Secure cookie is
    # silently NEVER sent back by a browser (or httpx) over plain HTTP,
    # which is exactly how this runs locally (no TLS) and in CI. Default
    # True (the safe, spec-correct choice for the real Vercel/Railway
    # deployment); local dev's .env sets this False so refresh/logout
    # actually work before HTTPS exists anywhere in the stack.
    cookie_secure: bool = True

    disable_breached_password_check: bool = False

    # §14 requires TOTP for OWNER/ACCOUNTANT at login — defaults True (the
    # spec-correct, secure choice) so an environment that forgets to set
    # anything still enforces it; this is the one setting where the failure
    # mode of "forgot to configure it" must land on the safe side. Local
    # dev/test/demo's .env sets this False to skip entering a code on every
    # login while the product is still being built out — flip it back to
    # true (or just remove the line) before a real deployment. Enrollment
    # (the QR-code step in accept-invite) is untouched by this flag either
    # way — only the login-time check is gated, so re-enabling this later
    # needs no re-enrollment.
    mfa_enforcement_enabled: bool = True

    # Phase 2 — original-file retention (§7.2 pt 9, §8). "local" is the
    # documented local-dev/CI stand-in (backend/.docker-data/objects/,
    # already gitignored); "s3" is the real answer for the Railway
    # deployment, which has no native blob storage — point it at any
    # S3-compatible bucket (Cloudflare R2, Backblaze B2, self-hosted MinIO,
    # or AWS S3 itself) via boto3, which is Apache-2.0/FOSS regardless of
    # which of those the bucket actually is.
    object_storage_backend: str = "local"
    object_storage_local_dir: str = ".docker-data/objects"
    object_storage_bucket: str = "livestock-order-snapshots"
    object_storage_endpoint_url: str | None = None
    object_storage_region: str = "auto"
    object_storage_access_key_id: str = ""
    object_storage_secret_access_key: str = ""

    # Phase 2 — where EverhealthConfig loads its seed values from (§6).
    # Defaults to backend/fixtures/reference-data-seed.json (vendored —
    # see backend/fixtures/README.md for why); override only for a
    # genuinely different seed source (e.g. a test fixture), which is why
    # this stays a setting rather than a hardcoded path in
    # domain/engine/config.py itself.
    reference_data_seed_path: str | None = None

    # Ephemeral parse-preview cache TTL (§7.3's upload -> preview -> commit
    # flow) — long enough for Bing to review a preview before confirming.
    upload_preview_ttl_seconds: int = 1800

    # Phase 3 — Web Push (VAPID, §10). pywebpush is MPL-2.0/FOSS regardless
    # of which browser push service (Chrome/FCM, Firefox, Apple) the
    # subscription's own endpoint points at — no proprietary SDK involved.
    # Generate a real pair with `uv run python -m scripts.generate_vapid_keys`
    # before a real deployment; these defaults are dev-only placeholders and
    # produce a working (self-consistent) key pair, just not a secret one.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_claim_email: str = "admin@example.com"

    # Phase 3 — WS ticket auth (§9.9). Native WebSocket can't carry a
    # bearer header, so a short-lived, single-use ticket (issued via an
    # authenticated REST call) stands in for it. Short enough that a leaked
    # ticket (e.g. in a browser history/log) is useless almost immediately.
    ws_ticket_ttl_seconds: int = 30

    # Phase 3 — §10's "alert the publisher if unacknowledged after 15
    # minutes" escalation threshold. Computed on demand (no worker/cron
    # introduced this phase — see services/escalation.py), so this is read
    # wherever a publication's delivery state is fetched.
    delivery_escalation_minutes: int = 15

    # Phase 5 — §16 "Sentry on both tiers." Empty disables the SDK entirely
    # (main.py only calls sentry_sdk.init if this is set) — see
    # [[foss-only-software-stack]]: sentry.io's hosted SaaS is proprietary
    # and out of scope for what's *deployed*. sentry-sdk itself is an
    # MIT-licensed client SDK, fine regardless of what it talks to. Point
    # this at a self-hosted, FOSS-licensed target in production — self-
    # hosted Sentry (FSL, free to self-host) or GlitchTip (AGPL) — never at
    # sentry.io.
    sentry_dsn: str = ""


settings = Settings()
