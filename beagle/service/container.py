"""Composition root for the service.

Builds and holds the single instance of each store and service. Both the HTTP
API and the admin CLI construct a container so they share identical wiring and
configuration. Stores are stateless; the only shared mutable resource is the
database, which hands out a fresh connection per operation.
"""

from __future__ import annotations

from beagle.service.audit import AuditLog
from beagle.service.commit_indexer import CommitIndexer
from beagle.service.commit_store import CommitStore
from beagle.service.config import ServiceConfig
from beagle.service.db import Database
from beagle.service.git.commit_reader import CommitReader
from beagle.service.git.mirror import GitMirror
from beagle.service.git.smart_http import SmartHttpHandler
from beagle.service.git_identities import GitIdentityStore
from beagle.service.identity import IdentityStore
from beagle.service.jwt_service import JwtService
from beagle.service.repositories import RepositoryStore
from beagle.service.repository_service import RepositoryService
from beagle.service.revision_indexer import RevisionIndexer
from beagle.service.sessions import SessionStore
from beagle.service.snapshot_store import SnapshotStore


class ServiceContainer:
    """Holds every store and service for one configuration."""

    def __init__(self, config: ServiceConfig):
        self.config = config
        self.database = Database(config.database_url)
        self.identity = IdentityStore()
        self.repositories = RepositoryStore()
        self.sessions = SessionStore()
        self.audit = AuditLog()
        self.jwt = JwtService(config, self.identity)
        self.mirror = GitMirror(config)
        self.commits = CommitStore()
        self.commit_indexer = CommitIndexer(CommitReader(config), self.commits, self.mirror)
        self.git_identities = GitIdentityStore()
        self.snapshots = SnapshotStore()
        self.revision_indexer = RevisionIndexer(
            config, self.database, self.mirror, self.snapshots
        )
        self.repository_service = RepositoryService(
            self.repositories, self.mirror, self.commit_indexer, self.git_identities
        )
        self.smart_http = SmartHttpHandler(
            config, self.database, self.jwt, self.repositories
        )

    def setup(self) -> "ServiceContainer":
        """Run migrations and ensure the repository storage root exists."""
        self.config.repo_storage_root.mkdir(parents=True, exist_ok=True)
        self.database.migrate()
        return self
