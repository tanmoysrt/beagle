"""Index snapshot manifest persistence (design/15 §8).

A snapshot manifest records that a commit's tree has been indexed into an
immutable artifact, with counts and the indexer version for provenance. The
artifact itself (a self-contained index) lives on the object store; this row is
the catalog entry, keyed by repository + commit so shared commits are reused.
"""

from __future__ import annotations

from beagle.service import ids
from beagle.service.clock import now_iso
from beagle.service.db import Connection
from beagle.service.errors import NotFound
from beagle.service.models import IndexSnapshot


class SnapshotStore:
    """CRUD for index snapshot manifests."""

    def find(
        self, conn: Connection, repository_id: str, commit_sha: str
    ) -> IndexSnapshot | None:
        row = conn.fetch_one(
            "SELECT * FROM index_snapshots WHERE repository_id = ? AND commit_sha = ?",
            (repository_id, commit_sha),
        )
        return IndexSnapshot(**row) if row else None

    def get(self, conn: Connection, repository_id: str, commit_sha: str) -> IndexSnapshot:
        snapshot = self.find(conn, repository_id, commit_sha)
        if not snapshot:
            raise NotFound(f"snapshot not found: {commit_sha}")
        return snapshot

    def create_pending(
        self, conn: Connection, repository_id: str, commit_sha: str, tree_sha: str,
        indexer_version: str, artifact_path: str,
    ) -> IndexSnapshot:
        snapshot = IndexSnapshot(
            id=ids._new("snap"),
            repository_id=repository_id,
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            indexer_version=indexer_version,
            status="indexing",
            file_count=None,
            entity_count=None,
            observation_count=None,
            edge_count=None,
            artifact_path=artifact_path,
            created_at=now_iso(),
        )
        conn.execute(
            "INSERT INTO index_snapshots(id, repository_id, commit_sha, tree_sha,"
            " indexer_version, status, artifact_path, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot.id, repository_id, commit_sha, tree_sha, indexer_version,
                snapshot.status, artifact_path, snapshot.created_at,
            ),
        )
        return snapshot

    def mark_ready(
        self, conn: Connection, snapshot_id: str, counts: dict[str, int]
    ) -> None:
        conn.execute(
            "UPDATE index_snapshots SET status = 'ready', file_count = ?,"
            " entity_count = ?, observation_count = ?, edge_count = ? WHERE id = ?",
            (
                counts.get("files"), counts.get("entities"),
                counts.get("observations"), counts.get("edges"), snapshot_id,
            ),
        )

    def delete(self, conn: Connection, repository_id: str, commit_sha: str) -> None:
        conn.execute(
            "DELETE FROM index_snapshots WHERE repository_id = ? AND commit_sha = ?",
            (repository_id, commit_sha),
        )

    def mark_failed(self, conn: Connection, snapshot_id: str) -> None:
        conn.execute(
            "UPDATE index_snapshots SET status = 'failed' WHERE id = ?", (snapshot_id,)
        )

    def list_for_repository(
        self, conn: Connection, repository_id: str
    ) -> list[IndexSnapshot]:
        rows = conn.fetch_all(
            "SELECT * FROM index_snapshots WHERE repository_id = ?"
            " ORDER BY created_at DESC",
            (repository_id,),
        )
        return [IndexSnapshot(**row) for row in rows]
