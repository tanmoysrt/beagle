"""JWT minting and validation (design/15 §3).

The service is the sole minter: it signs short-lived HS256 tokens whose claims
carry the subject, organization, repository scopes, and permissions. Clients
never mint their own trusted token. Validation follows the design's ordered
checks: signature, expiry, revocation, user, organization.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt

from beagle.service import ids
from beagle.service.clock import epoch_seconds
from beagle.service.config import ServiceConfig
from beagle.service.db import Connection
from beagle.service.errors import AuthenticationError, NotFound
from beagle.service.identity import IdentityStore
from beagle.service.models import JwtTokenRecord
from beagle.service.permissions import validate_permissions

_ALGORITHM = "HS256"


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """The validated caller behind a single request."""

    user_id: str
    organization_id: str
    repositories: list[str]
    permissions: list[str]
    jti: str


class JwtService:
    """Mints and validates signed tokens against persisted token records."""

    def __init__(self, config: ServiceConfig, identity: IdentityStore):
        self._config = config
        self._identity = identity

    def mint(
        self,
        conn: Connection,
        user_id: str,
        repositories: list[str],
        permissions: list[str],
        ttl_seconds: int | None = None,
        label: str = "",
    ) -> tuple[str, JwtTokenRecord]:
        """Sign a token for an existing user and persist its revocation record."""
        user = self._identity.get_user(conn, user_id)
        if user.disabled:
            raise AuthenticationError(f"user is disabled: {user_id}")
        permissions = validate_permissions(permissions)
        issued_at = epoch_seconds()
        expires_at = issued_at + (ttl_seconds or self._config.default_token_ttl_seconds)
        jti = ids.token_id()
        token = jwt.encode(
            {
                "sub": user_id,
                "org": user.organization_id,
                "repos": repositories,
                "permissions": permissions,
                "iat": issued_at,
                "exp": expires_at,
                "jti": jti,
                "iss": self._config.jwt_issuer,
            },
            self._config.jwt_secret,
            algorithm=_ALGORITHM,
        )
        record = JwtTokenRecord(
            jti=jti,
            user_id=user_id,
            organization_id=user.organization_id,
            repositories=repositories,
            permissions=permissions,
            issued_at=issued_at,
            expires_at=expires_at,
            revoked=False,
            label=label,
        )
        self._identity.record_token(conn, record)
        return token, record

    def validate(self, conn: Connection, token: str) -> AuthenticatedIdentity:
        """Run the design's ordered validation and return the caller identity."""
        claims = self._decode(token)
        self._check_not_revoked(conn, claims["jti"])
        self._check_user(conn, claims["sub"], claims["org"])
        return AuthenticatedIdentity(
            user_id=claims["sub"],
            organization_id=claims["org"],
            repositories=list(claims.get("repos", [])),
            permissions=list(claims.get("permissions", [])),
            jti=claims["jti"],
        )

    def _decode(self, token: str) -> dict:
        try:
            return jwt.decode(
                token,
                self._config.jwt_secret,
                algorithms=[_ALGORITHM],
                issuer=self._config.jwt_issuer,
                options={"require": ["exp", "iat", "sub", "jti", "org"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("token expired") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError(f"invalid token: {exc}") from exc

    def _check_not_revoked(self, conn: Connection, jti: str) -> None:
        record = self._identity.get_token(conn, jti)
        if record is None:
            raise AuthenticationError("unknown token id")
        if record.revoked:
            raise AuthenticationError("token revoked")

    def _check_user(self, conn: Connection, user_id: str, organization_id: str) -> None:
        try:
            user = self._identity.get_user(conn, user_id)
        except NotFound as exc:
            raise AuthenticationError("unknown user") from exc
        if user.disabled:
            raise AuthenticationError("user disabled")
        if user.organization_id != organization_id:
            raise AuthenticationError("organization mismatch")
