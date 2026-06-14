from __future__ import annotations

from pathlib import Path

import pytest

from beagle.service.audit import AuditLog
from beagle.service.config import ServiceConfig
from beagle.service.db import Database
from beagle.service.identity import IdentityStore
from beagle.service.jwt_service import JwtService
from beagle.service.sessions import SessionStore


@pytest.fixture
def config(tmp_path: Path) -> ServiceConfig:
    return ServiceConfig(
        database_url=f"sqlite:///{tmp_path / 'service.db'}",
        repo_storage_root=tmp_path / "repositories",
        jwt_secret="test-secret-do-not-use-in-prod-0123456789",
        default_token_ttl_seconds=3600,
    )


@pytest.fixture
def db(config: ServiceConfig) -> Database:
    database = Database(config.database_url)
    database.migrate()
    return database


@pytest.fixture
def identity() -> IdentityStore:
    return IdentityStore()


@pytest.fixture
def sessions() -> SessionStore:
    return SessionStore()


@pytest.fixture
def audit() -> AuditLog:
    return AuditLog()


@pytest.fixture
def jwt_service(config: ServiceConfig, identity: IdentityStore) -> JwtService:
    return JwtService(config, identity)
