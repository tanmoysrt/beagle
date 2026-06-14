"""Coordinates workspace overlays with their indexed snapshots (design/15 §15).

Creating or updating an overlay indexes the base tree plus the patch into a
private artifact, so queries against a workspace see the user's local changes
layered on the base commit. Keeps metadata persistence (:class:`WorkspaceStore`)
and indexing (:class:`RevisionIndexer`) on separate objects.
"""

from __future__ import annotations

from pathlib import Path

from beagle.service.config import ServiceConfig
from beagle.service.db import Database
from beagle.service.models import WorkspaceOverlay
from beagle.service.revision_indexer import RevisionIndexer
from beagle.service.snapshot_store import SnapshotStore
from beagle.service.workspaces import WorkspaceStore


class WorkspaceService:
    """Creates, updates, and indexes workspace overlays."""

    def __init__(
        self, config: ServiceConfig, database: Database, store: WorkspaceStore,
        indexer: RevisionIndexer, snapshots: SnapshotStore,
    ):
        self._config = config
        self._db = database
        self._store = store
        self._indexer = indexer
        self._snapshots = snapshots

    def create(
        self, user_id: str, repository_id: str, base_commit: str, patch: str,
        dirty_tree_hash: str = "",
    ) -> WorkspaceOverlay:
        with self._db.connect() as conn:
            overlay = self._store.create(
                conn, user_id, repository_id, base_commit, patch, dirty_tree_hash
            )
        self._index_overlay(repository_id, overlay)
        with self._db.connect() as conn:
            return self._store.get(conn, overlay.id)

    def update(self, workspace_id: str, patch: str, dirty_tree_hash: str = "") -> WorkspaceOverlay:
        with self._db.connect() as conn:
            overlay = self._store.update_patch(conn, workspace_id, patch, dirty_tree_hash)
        self._index_overlay(overlay.repository_id, overlay)
        with self._db.connect() as conn:
            return self._store.get(conn, workspace_id)

    def _index_overlay(self, repository_id: str, overlay: WorkspaceOverlay) -> None:
        artifact = self._artifact_path(overlay.id)
        patch = self._store.read_patch(overlay)
        counts = self._indexer.index_overlay(
            repository_id, overlay.base_commit, patch, artifact
        )
        synthetic_commit = f"workspace:{overlay.id}"
        with self._db.connect() as conn:
            self._snapshots.delete(conn, repository_id, synthetic_commit)
            snapshot = self._snapshots.create_pending(
                conn, repository_id, synthetic_commit, "", "overlay", str(artifact)
            )
            self._snapshots.mark_ready(conn, snapshot.id, counts)
            self._store.set_snapshot(conn, overlay.id, snapshot.id)

    def artifact_path(self, workspace_id: str) -> Path:
        return self._artifact_path(workspace_id)

    def _artifact_path(self, workspace_id: str) -> Path:
        return self._config.repo_storage_root / "workspaces" / f"{workspace_id}.db"
