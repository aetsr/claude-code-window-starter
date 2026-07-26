from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    UNSUPPORTED_OS = "UNSUPPORTED_OS"
    UNSUPPORTED_ARCH = "UNSUPPORTED_ARCH"
    CLAUDE_NOT_FOUND = "CLAUDE_NOT_FOUND"
    CLAUDE_NOT_AUTHENTICATED = "CLAUDE_NOT_AUTHENTICATED"
    CLAUDE_SESSION_EXPIRED = "CLAUDE_SESSION_EXPIRED"
    CLAUDE_SESSION_UNAVAILABLE = "CLAUDE_SESSION_UNAVAILABLE"
    CLAUDE_USAGE_UNAVAILABLE = "CLAUDE_USAGE_UNAVAILABLE"
    API_KEY_DETECTED = "API_KEY_DETECTED"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    DNS_FAILURE = "DNS_FAILURE"
    TIMEOUT = "TIMEOUT"
    RATE_OR_USAGE_LIMIT = "RATE_OR_USAGE_LIMIT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    NONZERO_EXIT = "NONZERO_EXIT"
    CONFIG_INVALID = "CONFIG_INVALID"
    LOCK_UNAVAILABLE = "LOCK_UNAVAILABLE"
    ALREADY_RUNNING = "ALREADY_RUNNING"
    ALREADY_RAN_TODAY = "ALREADY_RAN_TODAY"
    WINDOW_NOT_DUE = "WINDOW_NOT_DUE"
    DISK_SPACE_LOW = "DISK_SPACE_LOW"
    STATE_WRITE_FAILED = "STATE_WRITE_FAILED"
    TELEGRAM_TOKEN_MISSING = "TELEGRAM_TOKEN_MISSING"  # noqa: S105
    TELEGRAM_UNAUTHORIZED = "TELEGRAM_UNAUTHORIZED"
    TELEGRAM_RATE_LIMITED = "TELEGRAM_RATE_LIMITED"
    TELEGRAM_API_ERROR = "TELEGRAM_API_ERROR"
    TELEGRAM_SERVICE_FAILED = "TELEGRAM_SERVICE_FAILED"
    TELEGRAM_PAIRING_FAILED = "TELEGRAM_PAIRING_FAILED"
    LAUNCHD_FAILED = "LAUNCHD_FAILED"
    RELEASE_PREPARATION_FAILED = "RELEASE_PREPARATION_FAILED"
    HEALTH_CHECK_FAILED = "HEALTH_CHECK_FAILED"
    SYMLINK_SWITCH_FAILED = "SYMLINK_SWITCH_FAILED"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    NO_HEALTHY_PREVIOUS_RELEASE = "NO_HEALTHY_PREVIOUS_RELEASE"
    INVALID_RELEASE = "INVALID_RELEASE"


ERROR_MESSAGES: dict[ErrorCode, str] = {
    code: code.value.replace("_", " ").title() for code in ErrorCode
}
ERROR_MESSAGES.update(
    {
        ErrorCode.API_KEY_DETECTED: "A disallowed API or provider credential was detected.",
        ErrorCode.CLAUDE_NOT_AUTHENTICATED: "Claude subscription authentication is unavailable.",
        ErrorCode.ALREADY_RAN_TODAY: "The automatic request already ran for this local date.",
        ErrorCode.WINDOW_NOT_DUE: "The current five-hour window has already been started.",
        ErrorCode.NETWORK_UNAVAILABLE: (
            "The internet connection is unavailable; the work is pending."
        ),
    }
)


@dataclass(slots=True)
class AppError(Exception):
    code: ErrorCode
    message: str = ""
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.message:
            self.message = ERROR_MESSAGES[self.code]
        Exception.__init__(self, self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, "details": self.details or {}}
