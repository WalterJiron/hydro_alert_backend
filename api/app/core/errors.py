"""Application-level exceptions shared by HTTP and background processes."""

from __future__ import annotations


class ApplicationError(Exception):
    """Base error with a stable machine-readable code and HTTP mapping."""

    code = "application_error"
    status_code = 500
    headers: dict[str, str] | None = None

    def __init__(self, message: str | None = None) -> None:
        self.message = message or "Unexpected application error"
        super().__init__(self.message)


class ConfigurationError(ApplicationError):
    code = "configuration_error"


class ResourceNotFoundError(ApplicationError):
    code = "not_found"
    status_code = 404

    def __init__(self, resource: str, identifier: object) -> None:
        super().__init__(f"{resource} '{identifier}' was not found")


class InvalidQueryError(ApplicationError):
    code = "invalid_query"
    status_code = 422


class PersistenceError(ApplicationError):
    code = "database_error"
    status_code = 503


class ScrapingError(ApplicationError):
    code = "scraping_error"
    status_code = 502


class IneterUnavailableError(ScrapingError):
    code = "ineter_unavailable"


class IneterResponseTooLargeError(ScrapingError):
    code = "ineter_response_too_large"


class InvalidSeismicEventError(ApplicationError):
    code = "invalid_seismic_event"
    status_code = 422


class SyncLockUnavailableError(ApplicationError):
    """Raised when another instance already owns the synchronization lock."""

    code = "sync_already_running"
    status_code = 409


class InvalidRegistrationError(ApplicationError):
    code = "invalid_registration"
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)


class EmailAlreadyRegisteredError(ApplicationError):
    code = "email_already_registered"
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Email is already registered.")


class CedulaAlreadyRegisteredError(ApplicationError):
    code = "cedula_already_registered"
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Cédula is already registered.")


class InvalidCredentialsError(ApplicationError):
    code = "invalid_credentials"
    status_code = 401

    def __init__(self) -> None:
        super().__init__("Invalid email or password.")


class InvalidLoginError(ApplicationError):
    code = "invalid_login"
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidTokenError(ApplicationError):
    code = "invalid_token"
    status_code = 401

    def __init__(self, message: str = "Invalid or missing token.") -> None:
        super().__init__(message)


class RateLimitExceededError(ApplicationError):
    code = "rate_limited"
    status_code = 429

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            "Rate limit exceeded. Please try again in a few seconds."
        )
        self.retry_after_seconds = retry_after_seconds
        self.headers = {"Retry-After": str(retry_after_seconds)}


class ForbiddenError(ApplicationError):
    code = "forbidden"
    status_code = 403

    def __init__(self, message: str = "You do not have permission to perform this action.") -> None:
        super().__init__(message)


class InvalidReportError(ApplicationError):
    code = "invalid_report"
    status_code = 422

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ReportPhotoTooLargeError(ApplicationError):
    code = "photo_too_large"
    status_code = 413

    def __init__(self, max_bytes: int) -> None:
        super().__init__(
            f"Photo exceeds maximum size of {max_bytes // 1_048_576} MB."
        )


class UnsupportedPhotoError(ApplicationError):
    code = "unsupported_photo"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Photo must be JPG, JPEG, PNG, or WebP.")
