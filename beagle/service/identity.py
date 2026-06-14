"""Identity persistence: organizations, users, token records, repo access.

This store owns the rows; JWT crypto lives in :mod:`beagle.service.jwt_service`
and reads token records through here to check revocation. Every method takes a
:class:`~beagle.service.db.Connection` so callers control the transaction.
"""

from __future__ import annotations

import json

from beagle.service import ids
from beagle.service.clock import now_iso
from beagle.service.db import Connection
from beagle.service.errors import Conflict, NotFound
from beagle.service.models import (
    JwtTokenRecord,
    Organization,
    RepositoryAccess,
    User,
)


class IdentityStore:
    """CRUD for organizations, users, repository access, and token records."""

    # -- organizations --------------------------------------------------
    def create_organization(self, conn: Connection, slug: str, name: str) -> Organization:
        if conn.fetch_one("SELECT id FROM organizations WHERE slug = ?", (slug,)):
            raise Conflict(f"organization slug already exists: {slug}")
        org = Organization(ids.organization_id(), slug, name, now_iso())
        conn.execute(
            "INSERT INTO organizations(id, slug, name, created_at) VALUES (?, ?, ?, ?)",
            (org.id, org.slug, org.name, org.created_at),
        )
        return org

    def get_organization(self, conn: Connection, organization_id: str) -> Organization:
        row = conn.fetch_one("SELECT * FROM organizations WHERE id = ?", (organization_id,))
        if not row:
            raise NotFound(f"organization not found: {organization_id}")
        return Organization(**row)

    def find_organization_by_slug(self, conn: Connection, slug: str) -> Organization | None:
        row = conn.fetch_one("SELECT * FROM organizations WHERE slug = ?", (slug,))
        return Organization(**row) if row else None

    # -- users ----------------------------------------------------------
    def create_user(
        self,
        conn: Connection,
        organization_id: str,
        username: str,
        display_name: str,
        email: str,
    ) -> User:
        self.get_organization(conn, organization_id)
        if conn.fetch_one(
            "SELECT id FROM users WHERE organization_id = ? AND username = ?",
            (organization_id, username),
        ):
            raise Conflict(f"username already exists in organization: {username}")
        user = User(
            ids.user_id(), organization_id, username, display_name, email, False, now_iso()
        )
        conn.execute(
            "INSERT INTO users(id, organization_id, username, display_name, email,"
            " disabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user.id, organization_id, username, display_name, email, 0, user.created_at),
        )
        return user

    def get_user(self, conn: Connection, user_id: str) -> User:
        row = conn.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
        if not row:
            raise NotFound(f"user not found: {user_id}")
        return _user_from_row(row)

    # -- repository access ----------------------------------------------
    def grant_access(
        self,
        conn: Connection,
        user_id: str,
        repository_id: str,
        permissions: list[str],
    ) -> RepositoryAccess:
        self.get_user(conn, user_id)
        existing = conn.fetch_one(
            "SELECT id FROM repository_access WHERE user_id = ? AND repository_id = ?",
            (user_id, repository_id),
        )
        granted_at = now_iso()
        if existing:
            conn.execute(
                "UPDATE repository_access SET permissions = ?, granted_at = ? WHERE id = ?",
                (json.dumps(permissions), granted_at, existing["id"]),
            )
            access_id = existing["id"]
        else:
            access_id = ids.access_id()
            conn.execute(
                "INSERT INTO repository_access(id, user_id, repository_id, permissions,"
                " granted_at) VALUES (?, ?, ?, ?, ?)",
                (access_id, user_id, repository_id, json.dumps(permissions), granted_at),
            )
        return RepositoryAccess(access_id, user_id, repository_id, permissions, granted_at)

    def list_access(self, conn: Connection, user_id: str) -> list[RepositoryAccess]:
        rows = conn.fetch_all(
            "SELECT * FROM repository_access WHERE user_id = ?", (user_id,)
        )
        return [_access_from_row(row) for row in rows]

    # -- token records --------------------------------------------------
    def record_token(self, conn: Connection, record: JwtTokenRecord) -> None:
        conn.execute(
            "INSERT INTO jwt_tokens(jti, user_id, organization_id, repositories,"
            " permissions, issued_at, expires_at, revoked, revoked_at, label)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.jti,
                record.user_id,
                record.organization_id,
                json.dumps(record.repositories),
                json.dumps(record.permissions),
                record.issued_at,
                record.expires_at,
                1 if record.revoked else 0,
                record.revoked_at,
                record.label,
            ),
        )

    def get_token(self, conn: Connection, jti: str) -> JwtTokenRecord | None:
        row = conn.fetch_one("SELECT * FROM jwt_tokens WHERE jti = ?", (jti,))
        return _token_from_row(row) if row else None

    def revoke_token(self, conn: Connection, jti: str) -> None:
        if not conn.fetch_one("SELECT jti FROM jwt_tokens WHERE jti = ?", (jti,)):
            raise NotFound(f"token not found: {jti}")
        conn.execute(
            "UPDATE jwt_tokens SET revoked = 1, revoked_at = ? WHERE jti = ?",
            (now_iso(), jti),
        )

    def list_tokens(self, conn: Connection, user_id: str) -> list[JwtTokenRecord]:
        rows = conn.fetch_all("SELECT * FROM jwt_tokens WHERE user_id = ?", (user_id,))
        return [_token_from_row(row) for row in rows]


def _user_from_row(row: dict) -> User:
    return User(
        id=row["id"],
        organization_id=row["organization_id"],
        username=row["username"],
        display_name=row["display_name"],
        email=row["email"],
        disabled=bool(row["disabled"]),
        created_at=row["created_at"],
    )


def _access_from_row(row: dict) -> RepositoryAccess:
    return RepositoryAccess(
        id=row["id"],
        user_id=row["user_id"],
        repository_id=row["repository_id"],
        permissions=json.loads(row["permissions"]),
        granted_at=row["granted_at"],
    )


def _token_from_row(row: dict) -> JwtTokenRecord:
    return JwtTokenRecord(
        jti=row["jti"],
        user_id=row["user_id"],
        organization_id=row["organization_id"],
        repositories=json.loads(row["repositories"]),
        permissions=json.loads(row["permissions"]),
        issued_at=row["issued_at"],
        expires_at=row["expires_at"],
        revoked=bool(row["revoked"]),
        revoked_at=row["revoked_at"],
        label=row["label"],
    )
