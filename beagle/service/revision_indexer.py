"""Per-commit source indexing into immutable snapshots (design/15 §8).

For a commit, the indexer materializes its tree (tracked files only, no checkout
of repository code execution), runs the existing local index engine over it, and
records an immutable snapshot keyed by repository + commit. Snapshots are reused
across branches that share the commit and survive force-pushes.

This object owns its database transactions because indexing spans three steps
(reserve manifest, do heavy work, mark ready) that must not share one
transaction with the heavy subprocess work between them.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from beagle import __version__ as INDEXER_VERSION
from beagle.database import Database as EngineDatabase
from beagle.database.repository import Repository as EngineRepository
from beagle.service.config import ServiceConfig
from beagle.service.db import Database
from beagle.service.errors import NotFound, ServiceError
from beagle.service.git.mirror import GitMirror
from beagle.service.models import IndexSnapshot
from beagle.service.snapshot_store import SnapshotStore
from beagle.workspace import Workspace


class RevisionIndexer:
    """Indexes commit trees into reusable snapshots."""

    def __init__(
        self,
        config: ServiceConfig,
        database: Database,
        mirror: GitMirror,
        store: SnapshotStore,
    ):
        self._config = config
        self._db = database
        self._mirror = mirror
        self._store = store

    def index_revision(self, repository_id: str, revision: str) -> IndexSnapshot:
        sha = self._mirror.resolve(repository_id, revision)
        if not sha:
            raise NotFound(f"revision not found: {revision}")
        snapshot = self._reserve(repository_id, sha)
        if snapshot.status == "ready":
            return snapshot
        return self._run_index(repository_id, snapshot)

    def index_history(
        self, repository_id: str, revision: str, limit: int = 50
    ) -> list[IndexSnapshot]:
        """Index commits reachable from ``revision`` parent-first, reusing snapshots."""
        shas = self._mirror.rev_list(repository_id, revision, limit)
        return [self.index_revision(repository_id, sha) for sha in shas]

    def _reserve(self, repository_id: str, sha: str) -> IndexSnapshot:
        with self._db.connect() as conn:
            existing = self._store.find(conn, repository_id, sha)
            if existing and existing.status == "ready":
                return existing
            if existing:
                return existing
            tree_sha = self._mirror.tree_sha(repository_id, sha) or ""
            return self._store.create_pending(
                conn, repository_id, sha, tree_sha, INDEXER_VERSION,
                str(self._artifact_path(repository_id, sha)),
            )

    def _run_index(self, repository_id: str, snapshot: IndexSnapshot) -> IndexSnapshot:
        artifact = Path(snapshot.artifact_path)
        artifact.parent.mkdir(parents=True, exist_ok=True)
        try:
            counts = self._materialize_and_index(repository_id, snapshot.commit_sha, artifact)
        except Exception:
            artifact.unlink(missing_ok=True)
            with self._db.connect() as conn:
                self._store.mark_failed(conn, snapshot.id)
            raise
        with self._db.connect() as conn:
            self._store.mark_ready(conn, snapshot.id, counts)
            return self._store.get(conn, repository_id, snapshot.commit_sha)

    def _materialize_and_index(
        self, repository_id: str, sha: str, artifact: Path
    ) -> dict[str, int]:
        artifact.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="beagle-tree-") as tree_dir:
            self._mirror.export_tree(repository_id, sha, Path(tree_dir))
            workspace = Workspace(Path(tree_dir), db_path=artifact)
            try:
                workspace.index(force=True)
                return workspace.repo.counts()
            finally:
                workspace.close()

    def _artifact_path(self, repository_id: str, sha: str) -> Path:
        return self._config.repo_storage_root / "snapshots" / repository_id / f"{sha}.db"


def read_snapshot_counts(artifact_path: str) -> dict[str, int]:
    database = EngineDatabase(Path(artifact_path))
    try:
        return EngineRepository(database).counts()
    finally:
        database.close()


def search_snapshot_entities(
    artifact_path: str, name: str, limit: int = 20
) -> list[dict]:
    """Search a snapshot's entities by name. Results are revision-scoped."""
    database = EngineDatabase(Path(artifact_path))
    try:
        entities = EngineRepository(database).find_entities_by_name(name, limit)
        return [
            {"id": e.id, "name": e.name, "kind": e.kind, "file": e.owner_file,
             "start_line": e.source_range.start_line, "end_line": e.source_range.end_line}
            for e in entities
        ]
    finally:
        database.close()
