"""Coordinates reading and persisting commit metadata (design/15 §9, §10 Tier 0).

Indexing is incremental: only commits not already stored are read into the
database, so repeated syncs never duplicate history. This is the metadata tier —
it does not parse or graph trees (that is Phase D).
"""

from __future__ import annotations

from beagle.service.commit_store import CommitStore
from beagle.service.db import Connection
from beagle.service.errors import NotFound
from beagle.service.git.commit_reader import CommitReader
from beagle.service.git.mirror import GitMirror


class CommitIndexer:
    """Reads reachable commits from the mirror and stores new ones."""

    def __init__(self, reader: CommitReader, store: CommitStore, mirror: GitMirror):
        self._reader = reader
        self._store = store
        self._mirror = mirror

    def count(self, conn: Connection, repository_id: str) -> int:
        return self._store.count(conn, repository_id)

    def index(self, conn: Connection, repository_id: str) -> int:
        path = self._mirror.path_for(repository_id)
        if not path.exists():
            raise NotFound(f"repository mirror not found: {repository_id}")
        parsed = self._reader.read(path)
        existing = self._store.existing_shas(conn, repository_id)
        new_commits = [commit for commit in parsed if commit.sha not in existing]
        return self._store.insert_commits(conn, repository_id, new_commits)
