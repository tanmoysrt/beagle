"""Password login for the admin UI (env-supplied password).

The admin UI authenticates with a single shared password from
``BEAGLE_ADMIN_PASSWORD``. On success the service mints a normal JWT (all
permissions, all repositories) for a built-in ``admin`` user, so every
downstream check reuses the existing JWT path — there is no second auth system.
"""

from __future__ import annotations

import hmac

from beagle.service import permissions
from beagle.service.config import ServiceConfig
from beagle.service.db import Connection
from beagle.service.errors import AuthenticationError, ServiceError
from beagle.service.identity import IdentityStore
from beagle.service.jwt_service import JwtService

_ADMIN_USERNAME = "admin"
_ADMIN_TTL_SECONDS = 12 * 3600


class AdminAuth:
    """Verifies the admin password and issues an admin session token."""

    def __init__(self, config: ServiceConfig, identity: IdentityStore, jwt: JwtService):
        self._config = config
        self._identity = identity
        self._jwt = jwt

    @property
    def enabled(self) -> bool:
        return bool(self._config.admin_password)

    def login(self, conn: Connection, password: str) -> str:
        """Return an admin JWT if the password matches; raise otherwise."""
        if not self.enabled:
            raise ServiceError("admin UI is disabled; set BEAGLE_ADMIN_PASSWORD")
        if not hmac.compare_digest(password or "", self._config.admin_password):
            raise AuthenticationError("invalid admin password")
        user = self._ensure_admin_user(conn)
        token, _ = self._jwt.mint(
            conn, user.id, [permissions.ALL_REPOSITORIES],
            sorted(permissions.ALL_PERMISSIONS), _ADMIN_TTL_SECONDS, label="admin-ui",
        )
        return token

    def _ensure_admin_user(self, conn: Connection):
        org = self._identity.default_organization(conn)
        try:
            return self._identity.resolve_user(conn, _ADMIN_USERNAME)
        except Exception:
            return self._identity.create_user(
                conn, org.id, _ADMIN_USERNAME, "Administrator", "admin@local"
            )
