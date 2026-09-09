from __future__ import annotations

from typing import Any


class SalesforceAPIError(Exception):
    """Base exception for all Salesforce errors.

    Explicit attributes make later retry classifier and DLQ storage simple:
      ``status_code`` -> HTTP status (None for transport errors)
      ``error_code`` -> short alphanumeric class, e.g. INVALID_CLIENT, INVALID_SESSION_ID
      ``retryable`` -> direct hint to the future retry classifier (None means "use classifier")
      ``response_payload`` -> dict/list returned by Salesforce for structured introspection
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        retryable: bool | None = None,
        response_payload: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.retryable = retryable
        self.response_payload = response_payload or {}

    def __str__(self) -> str:  # pragma: no cover - trivial
        parts = [self.message]
        if self.status_code is not None:
            parts.append(f"status_code={self.status_code}")
        if self.error_code:
            parts.append(f"error_code={self.error_code}")
        if self.retryable is not None:
            parts.append(f"retryable={self.retryable}")
        return " | ".join(parts)


class SalesforceInvalidCredentialsError(SalesforceAPIError):
    """Token grant failed because credentials are wrong / expired / revoked."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message,
            status_code=kwargs.pop("status_code", 401),
            error_code=kwargs.pop("error_code", "INVALID_CREDENTIALS"),
            retryable=False,
            **kwargs,
        )


class SalesforceAuthenticationError(SalesforceAPIError):
    """Auth endpoint returned an error not classified as invalid credentials."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message,
            status_code=kwargs.pop("status_code", 400),
            error_code=kwargs.pop("error_code", "AUTH_ERROR"),
            retryable=kwargs.pop("retryable", None),
            **kwargs,
        )


class SalesforceUnauthorizedError(SalesforceAPIError):
    """401 / INVALID_SESSION_ID etc. from API calls (not the token grant)."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message,
            status_code=kwargs.pop("status_code", 401),
            error_code=kwargs.pop("error_code", "UNAUTHORIZED"),
            retryable=False,
            **kwargs,
        )


class SalesforceForbiddenError(SalesforceAPIError):
    """403: authenticated but insufficient permissions / connected app blocked."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message,
            status_code=kwargs.pop("status_code", 403),
            error_code=kwargs.pop("error_code", "FORBIDDEN"),
            retryable=False,
            **kwargs,
        )


class SalesforceInvalidRequestError(SalesforceAPIError):
    """400: malformed SOQL, bad request body, invalid enum, etc."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message,
            status_code=kwargs.pop("status_code", 400),
            error_code=kwargs.pop("error_code", "INVALID_REQUEST"),
            retryable=False,
            **kwargs,
        )


class SalesforceNotFoundError(SalesforceAPIError):
    """404: invalid job id, deleted object, wrong instance url."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message,
            status_code=kwargs.pop("status_code", 404),
            error_code=kwargs.pop("error_code", "NOT_FOUND"),
            retryable=False,
            **kwargs,
        )


class SalesforceServerError(SalesforceAPIError):
    """5xx: transient on Salesforce side, eligible for retry."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message,
            status_code=kwargs.pop("status_code", None),
            error_code=kwargs.pop("error_code", "SERVER_ERROR"),
            retryable=True,
            **kwargs,
        )


class SalesforceTimeoutError(SalesforceAPIError):
    """ConnectTimeout / ReadTimeout / general transport timeout / network blip."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message,
            status_code=kwargs.pop("status_code", None),
            error_code=kwargs.pop("error_code", "TIMEOUT"),
            retryable=True,
            **kwargs,
        )


def classify_http_error(status_code: int, payload: dict[str, Any] | list[Any] | None, message: str) -> SalesforceAPIError:
    """Map a Salesforce HTTP status + payload onto a structured exception.

    Uses Salesforce's standard ``[].errorCode`` list payload shape plus HTTP
    status.  Does not log anything; callers are responsible for scrubbing logs.
    """
    error_code: str | None = None
    if isinstance(payload, list) and len(payload) >= 1 and isinstance(payload[0], dict):
        error_code = payload[0].get("errorCode") or payload[0].get("code")
    elif isinstance(payload, dict):
        error_code = (
            payload.get("errorCode")
            or payload.get("code")
            or payload.get("error")
        )

    if 500 <= status_code < 600:
        return SalesforceServerError(message, status_code=status_code, error_code=error_code, response_payload=payload or {})
    if status_code == 404:
        return SalesforceNotFoundError(message, error_code=error_code, response_payload=payload or {})
    if status_code == 403:
        return SalesforceForbiddenError(message, error_code=error_code, response_payload=payload or {})
    if status_code == 401:
        if error_code == "INVALID_SESSION_ID":
            return SalesforceUnauthorizedError(message, error_code=error_code, response_payload=payload or {})
        return SalesforceUnauthorizedError(message, error_code=error_code, response_payload=payload or {})
    if status_code == 400:
        return SalesforceInvalidRequestError(message, error_code=error_code, response_payload=payload or {})
    if status_code == 429:
        return SalesforceServerError(
            message,
            status_code=429,
            error_code=error_code or "TOO_MANY_REQUESTS",
            response_payload=payload or {},
        )
    return SalesforceAPIError(
        message,
        status_code=status_code,
        error_code=error_code or f"HTTP_{status_code}",
        retryable=None,
        response_payload=payload or {},
    )
