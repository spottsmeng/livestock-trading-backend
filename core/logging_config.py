"""§16 — "structured JSON logs with correlation ids." Replaces main.py's
plain-text `logging.basicConfig` format string. Stdlib `logging` +
`json.dumps` only — no new dependency for something this small.
"""

import json
import logging
from datetime import UTC, datetime

from core.correlation import correlation_id_var

_RESERVED = frozenset(logging.LogRecord(None, 0, "", 0, "", (), None).__dict__.keys()) | {
    "message",
    "taskName",
    "correlation_id",  # stamped separately at top level by CorrelationIdFilter below
}


class CorrelationIdFilter(logging.Filter):
    """Stamps the current request's correlation id (core.correlation's
    ContextVar) onto every log record — "-" outside a request context (e.g.
    startup logs), never a missing field."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        if extras:
            payload["extra"] = extras
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(CorrelationIdFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
