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


settings = Settings()
