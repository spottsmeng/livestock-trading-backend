from typing import Any


class AppError(Exception):
    """Raise this anywhere in services/routes for a domain-level failure.
    A single exception handler in main.py turns it into §9's envelope:
    { "error": { "code", "message", "details" } }."""

    def __init__(self, code: str, message: str, status_code: int = 400, details: Any = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class InvalidCredentials(AppError):
    def __init__(self) -> None:
        super().__init__("INVALID_CREDENTIALS", "Incorrect email or password.", status_code=401)


class MfaRequired(AppError):
    def __init__(self) -> None:
        super().__init__("MFA_REQUIRED", "A valid TOTP code is required.", status_code=401)


class MfaInvalid(AppError):
    def __init__(self) -> None:
        super().__init__("MFA_INVALID", "The TOTP code is incorrect or expired.", status_code=401)


class AccountNotActive(AppError):
    def __init__(self, status: str) -> None:
        super().__init__("ACCOUNT_NOT_ACTIVE", f"Account is {status}, not active.", status_code=403)


class RateLimited(AppError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            "RATE_LIMITED",
            "Too many attempts. Try again shortly.",
            status_code=429,
            details={"retry_after_seconds": retry_after_seconds},
        )


class InvalidToken(AppError):
    def __init__(self, message: str = "Invalid or expired token.") -> None:
        super().__init__("INVALID_TOKEN", message, status_code=401)


class TokenReused(AppError):
    def __init__(self) -> None:
        super().__init__(
            "REFRESH_TOKEN_REUSED",
            "This session was revoked because a refresh token was reused. Please log in again.",
            status_code=401,
        )


class Forbidden(AppError):
    def __init__(self, message: str = "You do not have permission to do this.") -> None:
        super().__init__("FORBIDDEN", message, status_code=403)


class NotFound(AppError):
    def __init__(self, entity: str) -> None:
        super().__init__("NOT_FOUND", f"{entity} not found.", status_code=404)


class Conflict(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, status_code=409)


class LastOwnerGuard(AppError):
    def __init__(self) -> None:
        super().__init__(
            "LAST_OWNER_GUARD",
            "Cannot deactivate the platform's last remaining active OWNER.",
            status_code=409,
        )


class PasswordPolicyViolation(AppError):
    def __init__(self, violations: list[str]) -> None:
        super().__init__(
            "PASSWORD_POLICY_VIOLATION",
            "Password does not meet the minimum policy.",
            status_code=422,
            details={"violations": violations},
        )


class BreachedPassword(AppError):
    def __init__(self) -> None:
        super().__init__(
            "BREACHED_PASSWORD",
            "This password has appeared in a known data breach. Choose a different one.",
            status_code=422,
        )


class PreviewExpired(AppError):
    def __init__(self) -> None:
        super().__init__(
            "PREVIEW_EXPIRED",
            "This upload preview has expired or was not found. Please re-upload the file.",
            status_code=410,
        )


class SnapshotNotCalculated(AppError):
    def __init__(self) -> None:
        super().__init__(
            "SNAPSHOT_NOT_CALCULATED",
            "This snapshot has not been calculated yet.",
            status_code=409,
        )


class PublicationBlocked(AppError):
    def __init__(self, blocked_line_ids: list[str]) -> None:
        super().__init__(
            "PUBLICATION_BLOCKED",
            "One or more active lines have a BLOCK issue — publication is refused (§5.7).",
            status_code=409,
            details={"blocked_order_line_ids": blocked_line_ids},
        )


class IssuesNotAcknowledged(AppError):
    def __init__(self, issue_ids: list[str]) -> None:
        super().__init__(
            "ISSUES_NOT_ACKNOWLEDGED",
            "Every WARN/CORRECTION issue on an active line must be acknowledged before publishing.",
            status_code=409,
            details={"unacknowledged_issue_ids": issue_ids},
        )


class NothingToPublish(AppError):
    def __init__(self) -> None:
        super().__init__(
            "NOTHING_TO_PUBLISH",
            "No active line in this snapshot has a computed DNBP to publish.",
            status_code=409,
        )


class TicketInvalid(AppError):
    def __init__(self) -> None:
        super().__init__(
            "TICKET_INVALID", "This connection ticket is invalid, expired, or already used.", status_code=401
        )
