"""Service configuration.

A single immutable object carries every deployment knob: where the database
lives, where bare repositories are stored, and the JWT signing secret. Tests
construct it directly; deployments use :meth:`ServiceConfig.from_env`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TOKEN_TTL_SECONDS = 24 * 3600
DEFAULT_ISSUER = "beagle"


@dataclass(frozen=True)
class ServiceConfig:
    """Immutable deployment configuration for the shared service."""

    database_url: str
    repo_storage_root: Path
    jwt_secret: str
    jwt_issuer: str = DEFAULT_ISSUER
    default_token_ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS
    git_binary: str = "git"
    # Password for the admin web UI. When unset, the UI login is disabled.
    admin_password: str | None = None

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        secret = os.environ.get("BEAGLE_SERVICE_SECRET")
        if not secret:
            raise RuntimeError("BEAGLE_SERVICE_SECRET is required to run the service")
        return cls(
            database_url=os.environ.get(
                "BEAGLE_DATABASE_URL", "sqlite:///beagle-service.db"
            ),
            repo_storage_root=Path(
                os.environ.get("BEAGLE_REPO_ROOT", "./beagle-repositories")
            ).resolve(),
            jwt_secret=secret,
            jwt_issuer=os.environ.get("BEAGLE_JWT_ISSUER", DEFAULT_ISSUER),
            default_token_ttl_seconds=int(
                os.environ.get("BEAGLE_TOKEN_TTL", DEFAULT_TOKEN_TTL_SECONDS)
            ),
            git_binary=os.environ.get("BEAGLE_GIT_BINARY", "git"),
            admin_password=os.environ.get("BEAGLE_ADMIN_PASSWORD") or None,
        )
