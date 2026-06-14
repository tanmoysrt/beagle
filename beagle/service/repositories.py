"""Repository record persistence and tracked-ref mirror state.

This store owns the ``repositories`` and ``git_refs`` rows. Bare-repo file
operations live in :class:`beagle.service.git.mirror.GitMirror`; the two are
coordinated by :class:`beagle.service.repository_service.RepositoryService`.
"""

from __future__ import annotations

from beagle.service import ids
from beagle.service.clock import now_iso
from beagle.service.db import Connection
from beagle.service.errors import Conflict, NotFound
from beagle.service.models import GitRef, Repository


class RepositoryStore:
    """CRUD for repository records and their tracked Git refs."""

    def create(
        self,
        conn: Connection,
        organization_id: str,
        slug: str,
        name: str,
        remote_url: str | None,
        default_branch: str,
        storage_path: str,
    ) -> Repository:
        if conn.fetch_one(
            "SELECT id FROM repositories WHERE organization_id = ? AND slug = ?",
            (organization_id, slug),
        ):
            raise Conflict(f"repository slug already exists: {slug}")
        repo = Repository(
            id=ids.repository_id(),
            organization_id=organization_id,
            slug=slug,
            name=name,
            remote_url=remote_url,
            default_branch=default_branch,
            storage_path=storage_path,
            ingestion_state="registered",
            created_at=now_iso(),
        )
        conn.execute(
            "INSERT INTO repositories(id, organization_id, slug, name, remote_url,"
            " default_branch, storage_path, ingestion_state, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                repo.id,
                repo.organization_id,
                repo.slug,
                repo.name,
                repo.remote_url,
                repo.default_branch,
                repo.storage_path,
                repo.ingestion_state,
                repo.created_at,
            ),
        )
        return repo

    def get(self, conn: Connection, repository_id: str) -> Repository:
        row = conn.fetch_one("SELECT * FROM repositories WHERE id = ?", (repository_id,))
        if not row:
            raise NotFound(f"repository not found: {repository_id}")
        return Repository(**row)

    def find_by_slug(
        self, conn: Connection, organization_id: str, slug: str
    ) -> Repository | None:
        row = conn.fetch_one(
            "SELECT * FROM repositories WHERE organization_id = ? AND slug = ?",
            (organization_id, slug),
        )
        return Repository(**row) if row else None

    def list_for_org(self, conn: Connection, organization_id: str) -> list[Repository]:
        rows = conn.fetch_all(
            "SELECT * FROM repositories WHERE organization_id = ? ORDER BY slug",
            (organization_id,),
        )
        return [Repository(**row) for row in rows]

    def set_ingestion_state(
        self, conn: Connection, repository_id: str, state: str
    ) -> None:
        self.get(conn, repository_id)
        conn.execute(
            "UPDATE repositories SET ingestion_state = ? WHERE id = ?",
            (state, repository_id),
        )

    def replace_refs(
        self, conn: Connection, repository_id: str, refs: list[tuple[str, str, str]]
    ) -> None:
        """Replace tracked refs for a repository. ``refs`` is (namespace, name, sha)."""
        conn.execute("DELETE FROM git_refs WHERE repository_id = ?", (repository_id,))
        updated_at = now_iso()
        for namespace, ref_name, commit_sha in refs:
            conn.execute(
                "INSERT INTO git_refs(repository_id, namespace, ref_name, commit_sha,"
                " updated_at) VALUES (?, ?, ?, ?, ?)",
                (repository_id, namespace, ref_name, commit_sha, updated_at),
            )

    def list_refs(self, conn: Connection, repository_id: str) -> list[GitRef]:
        rows = conn.fetch_all(
            "SELECT * FROM git_refs WHERE repository_id = ? ORDER BY ref_name",
            (repository_id,),
        )
        return [GitRef(**row) for row in rows]
