from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.v1 import api_router
from core.config import settings
from core.correlation import correlation_id_middleware
from core.errors import AppError
from core.logging_config import configure_logging
from core.rate_limit_middleware import RateLimitMiddleware
from core.security_headers import security_headers_middleware

configure_logging()

# §16 — "Sentry on both tiers," client-SDK-only, disabled unless a DSN is
# configured (see core/config.py's sentry_dsn comment and
# [[foss-only-software-stack]]). Import is local to this guard so the
# dependency has zero effect on a deployment that never sets a DSN.
if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(dsn=settings.sentry_dsn, send_default_pii=False)

app = FastAPI(title="Livestock Trade Management API")

# Middleware order (Starlette wraps outside-in in REVERSE add order — the
# last one added here ends up outermost): RateLimit and SecurityHeaders are
# added first (innermost of the four), then CORS, then Correlation last so
# it's outermost — every request gets a correlation id in its logging
# context before anything else runs, and every response (including a 429
# from the rate limiter) carries the X-Request-Id header on the way out.
app.add_middleware(RateLimitMiddleware)
app.middleware("http")(security_headers_middleware)

# allow_credentials=True (the refresh cookie) requires explicit origins —
# the fetch spec rejects "*" combined with credentials, so this must stay
# a real allowlist, not a wildcard, however tempting that is in dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(correlation_id_middleware)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Keeps every error response on one envelope shape (§9), including
    # Pydantic's own 422s, not just the ones this codebase raises itself.
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": "Invalid request.", "details": exc.errors()}},
    )


app.include_router(api_router, prefix="/api/v1")
