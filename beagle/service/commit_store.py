"""Commit metadata persistence, history, and message search (design/15 §9).

Stores the full message body, author/committer identities (kept separate),
parents, trailers, and diff statistics. Search is a portable case-insensitive
scan over subjects, bodies, identities, and trailers so commit history is
queryable before any source tree is indexed (Tier 0).
"""

from __future__ import annotations

from beagle.service.clock import now_iso
from beagle.service.db import Connection
from beagle.service.errors import NotFound
from beagle.service.git.commit_reader import ParsedCommit


class CommitStore:
    """Persists and queries indexed commit metadata."""

    def count(self, conn: Connection, repository_id: str) -> int:
        row = conn.fetch_one(
            "SELECT COUNT(*) AS n FROM git_commits WHERE repository_id = ?",
            (repository_id,),
        )
        return int(row["n"]) if row else 0

    def existing_shas(self, conn: Connection, repository_id: str) -> set[str]:
        rows = conn.fetch_all(
            "SELECT sha FROM git_commits WHERE repository_id = ?", (repository_id,)
        )
        return {row["sha"] for row in rows}

    def insert_commits(
        self, conn: Connection, repository_id: str, commits: list[ParsedCommit]
    ) -> int:
        indexed_at = now_iso()
        for commit in commits:
            self._insert_commit(conn, repository_id, commit, indexed_at)
            self._insert_parents(conn, repository_id, commit)
            self._insert_trailers(conn, repository_id, commit)
        return len(commits)

    def _insert_commit(
        self, conn: Connection, repository_id: str, commit: ParsedCommit, indexed_at: str
    ) -> None:
        conn.execute(
            "INSERT INTO git_commits(repository_id, sha, tree_sha, subject, body,"
            " author_name, author_email, author_time, author_tz, committer_name,"
            " committer_email, commit_time, committer_tz, signature_status, is_merge,"
            " files_changed, insertions, deletions, indexed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                repository_id, commit.sha, commit.tree_sha, commit.subject, commit.body,
                commit.author_name, commit.author_email, commit.author_time, commit.author_tz,
                commit.committer_name, commit.committer_email, commit.commit_time,
                commit.committer_tz, commit.signature_status, 1 if commit.is_merge else 0,
                commit.files_changed, commit.insertions, commit.deletions, indexed_at,
            ),
        )

    def _insert_parents(
        self, conn: Connection, repository_id: str, commit: ParsedCommit
    ) -> None:
        for position, parent_sha in enumerate(commit.parents):
            conn.execute(
                "INSERT INTO git_commit_parents(repository_id, child_sha, parent_sha,"
                " position) VALUES (?, ?, ?, ?)",
                (repository_id, commit.sha, parent_sha, position),
            )

    def _insert_trailers(
        self, conn: Connection, repository_id: str, commit: ParsedCommit
    ) -> None:
        for position, (key, value) in enumerate(commit.trailers):
            conn.execute(
                "INSERT INTO git_commit_trailers(repository_id, sha, position,"
                " trailer_key, trailer_value) VALUES (?, ?, ?, ?, ?)",
                (repository_id, commit.sha, position, key, value),
            )

    def history(
        self, conn: Connection, repository_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        return conn.fetch_all(
            "SELECT * FROM git_commits WHERE repository_id = ?"
            " ORDER BY commit_time DESC, sha DESC LIMIT ? OFFSET ?",
            (repository_id, limit, offset),
        )

    def search(
        self, conn: Connection, repository_id: str, query: str, limit: int = 20
    ) -> list[dict]:
        like = f"%{query.lower()}%"
        return conn.fetch_all(
            "SELECT * FROM git_commits WHERE repository_id = ? AND ("
            " lower(subject) LIKE ? OR lower(body) LIKE ?"
            " OR lower(author_name) LIKE ? OR lower(author_email) LIKE ?"
            " OR lower(committer_name) LIKE ?"
            " OR EXISTS (SELECT 1 FROM git_commit_trailers t"
            "   WHERE t.repository_id = git_commits.repository_id AND t.sha = git_commits.sha"
            "   AND lower(t.trailer_value) LIKE ?))"
            " ORDER BY commit_time DESC, sha DESC LIMIT ?",
            (repository_id, like, like, like, like, like, like, limit),
        )

    def find_one(self, conn: Connection, repository_id: str, sha: str) -> dict | None:
        return conn.fetch_one(
            "SELECT * FROM git_commits WHERE repository_id = ? AND sha = ?",
            (repository_id, sha),
        )

    def get_commit(self, conn: Connection, repository_id: str, sha: str) -> dict:
        row = conn.fetch_one(
            "SELECT * FROM git_commits WHERE repository_id = ? AND sha = ?",
            (repository_id, sha),
        )
        if not row:
            raise NotFound(f"commit not indexed: {sha}")
        row["parents"] = [
            p["parent_sha"]
            for p in conn.fetch_all(
                "SELECT parent_sha FROM git_commit_parents WHERE repository_id = ?"
                " AND child_sha = ? ORDER BY position",
                (repository_id, sha),
            )
        ]
        row["trailers"] = [
            {"key": t["trailer_key"], "value": t["trailer_value"]}
            for t in conn.fetch_all(
                "SELECT trailer_key, trailer_value FROM git_commit_trailers"
                " WHERE repository_id = ? AND sha = ? ORDER BY position",
                (repository_id, sha),
            )
        ]
        return row
