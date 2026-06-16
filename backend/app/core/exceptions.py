"""Custom application exceptions."""

from typing import Any, Optional


class AppException(Exception):
    def __init__(self, message: str, code: str = "app_error", details: Optional[Any] = None) -> None:
        self.message = message
        self.code = code
        self.details = details
        super().__init__(message)


class NotFoundError(AppException):
    def __init__(self, message: str = "Resource not found", details: Optional[Any] = None) -> None:
        super().__init__(message, code="not_found", details=details)


class ForbiddenError(AppException):
    def __init__(self, message: str = "Forbidden", details: Optional[Any] = None) -> None:
        super().__init__(message, code="forbidden", details=details)


class ValidationError(AppException):
    def __init__(self, message: str = "Validation failed", details: Optional[Any] = None) -> None:
        super().__init__(message, code="validation_error", details=details)
