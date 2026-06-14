"""Stable, prefixed identifiers for service records.

Every primary key is an application-generated string so the schema stays
portable across SQLite and PostgreSQL (no SERIAL / IDENTITY differences) and so
IDs read clearly in logs and JWT claims.
"""

from __future__ import annotations

from uuid import uuid4


def _new(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def organization_id() -> str:
    return _new("org")


def user_id() -> str:
    return _new("user")


def token_id() -> str:
    """A JWT ``jti``; also the primary key of its revocation record."""
    return _new("token")


def repository_id() -> str:
    return _new("repo")


def access_id() -> str:
    return _new("access")


def session_id() -> str:
    return _new("sess")


def audit_id() -> str:
    return _new("audit")
