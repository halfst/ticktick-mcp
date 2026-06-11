"""Typed error hierarchy for the v2 client (DESIGN.md §4).

Client methods either return a typed result or raise one of these. They never
return ``None``-on-error and never let a raw ``httpx`` exception escape the
``client/`` package. No exception message ever contains a secret.
"""

from __future__ import annotations

__all__ = ["TickTickError", "AuthError", "APIError", "PayloadError"]


class TickTickError(Exception):
    """Base class for every error this client raises."""


class AuthError(TickTickError):
    """Login failed, credentials were rejected, or a login challenge blocked sign-in.

    The message is human-actionable (e.g. "log in via the web client from this IP,
    then retry") and never includes the password.
    """


class APIError(TickTickError):
    """A non-2xx HTTP response that is not auth-related.

    Carries the HTTP status code and any server-provided message (secrets stripped).
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PayloadError(TickTickError):
    """A 2xx response whose body did not match the expected shape.

    Usually means the undocumented v2 API drifted (a field was renamed or removed).
    """
