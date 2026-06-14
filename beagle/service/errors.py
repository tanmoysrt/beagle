"""Service error hierarchy.

Each error carries an HTTP status so the API layer can translate uniformly
without sprinkling status codes through business logic.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for all service errors."""

    status_code = 500
    code = "service_error"


class ValidationError(ServiceError):
    status_code = 400
    code = "validation_error"


class AuthenticationError(ServiceError):
    """The caller could not be authenticated (bad/expired/revoked token)."""

    status_code = 401
    code = "authentication_error"


class PermissionDenied(ServiceError):
    """Authenticated, but lacking the required permission or repository scope."""

    status_code = 403
    code = "permission_denied"


class NotFound(ServiceError):
    status_code = 404
    code = "not_found"


class Conflict(ServiceError):
    status_code = 409
    code = "conflict"
