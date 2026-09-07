import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.v1 import api_router
from core.config import settings
from core.errors import AppError

logging.basicConfig(level=logging.INFO, format="%(levelname)-5.5s [%(name)s] %(message)s")

app = FastAPI(title="Livestock Trade Management API")

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
