"""Request authentication for the JSON API.

A FastAPI dependency turns the ``Authorization: Bearer`` header into a validated
:class:`AuthenticatedIdentity`. Every write route depends on it, so the design's
rule — reject unauthenticated writes — holds structurally.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import Request

from beagle.service.container import ServiceContainer
from beagle.service.errors import AuthenticationError
from beagle.service.jwt_service import AuthenticatedIdentity


def container_of(request: Request) -> ServiceContainer:
    return request.app.state.container


def request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or uuid4().hex


def authenticate(request: Request) -> AuthenticatedIdentity:
    """Validate the bearer token; raise :class:`AuthenticationError` if absent."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("missing bearer token")
    container = container_of(request)
    with container.database.connect() as conn:
        return container.jwt.validate(conn, token.strip())
