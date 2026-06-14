"""Coordinates repository records with their bare Git mirrors (design/15 §6, §7).

Registration is explicit (design §23: no silent source upload). Synchronization
fetches upstream history into the canonical namespace and refreshes tracked-ref
state. Keeps DB persistence (:class:`RepositoryStore`) and Git file operations
(:class:`GitMirror`) on separate objects, tied together only here.
"""

from __future__ import annotations

from dataclasses import dataclass

from beagle.service.commit_indexer import CommitIndexer
from beagle.service.db import Connection
from beagle.service.git import refs as ref_ns
from beagle.service.git.mirror import GitMirror, RefEntry
from beagle.service.git_identities import GitIdentityStore
from beagle.service.models import Repository
from beagle.service.repositories import RepositoryStore


@dataclass
class SyncResult:
    repository_id: str
    ref_count: int
    ingestion_state: str
    commit_count: int = 0


class RepositoryService:
    """Registers and synchronizes repositories."""

    def __init__(
        self,
        store: RepositoryStore,
        mirror: GitMirror,
        commit_indexer: CommitIndexer,
        identities: GitIdentityStore,
    ):
        self._store = store
        self._mirror = mirror
        self._commit_indexer = commit_indexer
        self._identities = identities

    def register(
        self,
        conn: Connection,
        organization_id: str,
        slug: str,
        name: str,
        remote_url: str | None,
        default_branch: str = "main",
    ) -> Repository:
        repo = self._store.create(
            conn, organization_id, slug, name, remote_url, default_branch, storage_path=""
        )
        path = self._mirror.init_bare(repo.id)
        conn.execute(
            "UPDATE repositories SET storage_path = ? WHERE id = ?",
            (str(path), repo.id),
        )
        repo.storage_path = str(path)
        if remote_url:
            self._mirror.set_upstream(repo.id, remote_url)
        return repo

    def sync(self, conn: Connection, repository_id: str) -> SyncResult:
        repo = self._store.get(conn, repository_id)
        if repo.remote_url:
            self._store.set_ingestion_state(conn, repository_id, "syncing")
            self._mirror.fetch_upstream(repository_id)
        entries = self._mirror.list_refs(repository_id)
        self._persist_refs(conn, repository_id, entries)
        new_commits = self._commit_indexer.index(conn, repository_id)
        self._identities.harvest(conn, repo.organization_id)
        self._identities.auto_map_by_email(conn, repo.organization_id)
        self._store.set_ingestion_state(conn, repository_id, "synced")
        return SyncResult(repository_id, len(entries), "synced", new_commits)

    def status(self, conn: Connection, repository_id: str) -> SyncResult:
        repo = self._store.get(conn, repository_id)
        refs = self._store.list_refs(conn, repository_id)
        commits = self._commit_indexer.count(conn, repository_id)
        return SyncResult(repository_id, len(refs), repo.ingestion_state, commits)

    def _persist_refs(
        self, conn: Connection, repository_id: str, entries: list[RefEntry]
    ) -> None:
        rows = [
            (ref_ns.classify_namespace(entry.ref_name), entry.ref_name, entry.commit_sha)
            for entry in entries
        ]
        self._store.replace_refs(conn, repository_id, rows)
