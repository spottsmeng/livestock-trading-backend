"""§14 — "HTTPS only, HSTS, strict CSP, no inline scripts." The backend
only ever serves JSON (no HTML it renders itself), so its CSP is a
belt-and-braces default-deny — it matters mainly for any response a browser
might ever render directly (e.g. an error page from a proxy, a downloaded
export). The frontend's own next.config.ts headers() carries the CSP that
actually governs the rendered app; the two are kept in sync deliberately
(see that file's own comment) rather than the frontend relying on this one.
"""

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

_CSP = "; ".join(
    [
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
    ]
)


CallNext = Callable[[Request], Awaitable[Response]]


async def security_headers_middleware(request: Request, call_next: CallNext) -> Response:
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = _CSP
    return response
