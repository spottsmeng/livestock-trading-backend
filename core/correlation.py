"""§16 — "structured JSON logs with correlation ids." One id per request:
honours an inbound `X-Request-Id` if the caller (or a load balancer) already
set one, else generates a fresh uuid4. Stored in a ContextVar so
core.logging_config's filter can stamp it onto every log record emitted
while handling this request, without threading it through every function
signature by hand; echoed back as a response header so a caller can
correlate their own logs against ours.
"""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.requests import Request
from starlette.responses import Response

_REQUEST_ID_HEADER = "X-Request-Id"

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")

_logger = logging.getLogger("app.request")

CallNext = Callable[[Request], Awaitable[Response]]


async def correlation_id_middleware(request: Request, call_next: CallNext) -> Response:
    incoming = request.headers.get(_REQUEST_ID_HEADER)
    correlation_id = incoming if incoming else str(uuid.uuid4())
    token = correlation_id_var.set(correlation_id)
    started_at = time.monotonic()
    try:
        response = await call_next(request)

        # uvicorn's own access logger ("uvicorn.access") is configured with
        # propagate=False and its own plain-text handler (uvicorn.config
        # .LOGGING_CONFIG), so it never reaches core.logging_config's JSON
        # formatter regardless of when that's configured — this explicit,
        # structured request log is what actually satisfies §16's
        # "structured JSON logs with correlation ids" for the request/
        # response lifecycle itself. Logged INSIDE the try, before the
        # ContextVar is reset in `finally` below — the filter reads
        # correlation_id_var at emission time, so logging after the reset
        # would stamp every request log with "-".
        duration_ms = round((time.monotonic() - started_at) * 1000, 2)
        _logger.info(
            "request completed",
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
    finally:
        correlation_id_var.reset(token)
    response.headers[_REQUEST_ID_HEADER] = correlation_id
    return response
