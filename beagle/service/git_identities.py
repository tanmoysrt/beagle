"""Git identity harvesting and user mapping (design/15 §5, Phase G).

Identities are anchored on email, never on display-name similarity. They are
harvested from indexed commit metadata — authors, committers, and co-author /
review trailers — and may be mapped to a verified user by matching email, by an
administrator, or by an explicit user claim. Unmatched historical authors stay
unclaimed. Commit roles (author, committer, co-author) are evidence here and are
kept distinct from decision roles (Phase H).
"""

from __future__ import annotations

import re

from beagle.service.db import Connection
from beagle.service.errors import NotFound
from beagle.service.models import GitIdentity

_TRAILER_KEYS = ("Co-authored-by", "Signed-off-by", "Reviewed-by", "Acked-by")
_NAME_EMAIL = re.compile(r"^(.*?)\s*<([^>]+)>\s*$")


class GitIdentityStore:
    """Persists and maps Git identities for an organization."""

    def harvest(self, conn: Connection, organization_id: str) -> int:
        """Recompute identities from indexed commits. Idempotent; preserves mappings."""
        identities = self._collect(conn, organization_id)
        for email, info in identities.items():
            self._upsert(conn, organization_id, email, info)
        return len(identities)

    def _collect(self, conn: Connection, organization_id: str) -> dict[str, dict]:
        collected: dict[str, dict] = {}
        self._add_authors(conn, organization_id, collected)
        self._add_committers(conn, organization_id, collected)
        self._add_trailers(conn, organization_id, collected)
        return collected

    def _add_authors(self, conn: Connection, org_id: str, into: dict) -> None:
        rows = conn.fetch_all(
            "SELECT author_email AS email, MAX(author_name) AS name,"
            " MIN(author_time) AS first_seen, MAX(author_time) AS last_seen,"
            " COUNT(*) AS cnt FROM git_commits c JOIN repositories r"
            " ON c.repository_id = r.id WHERE r.organization_id = ?"
            " GROUP BY author_email",
            (org_id,),
        )
        for row in rows:
            into[row["email"]] = {
                "name": row["name"], "first_seen": row["first_seen"],
                "last_seen": row["last_seen"], "commit_count": row["cnt"],
            }

    def _add_committers(self, conn: Connection, org_id: str, into: dict) -> None:
        rows = conn.fetch_all(
            "SELECT committer_email AS email, MAX(committer_name) AS name,"
            " MIN(commit_time) AS first_seen, MAX(commit_time) AS last_seen"
            " FROM git_commits c JOIN repositories r ON c.repository_id = r.id"
            " WHERE r.organization_id = ? GROUP BY committer_email",
            (org_id,),
        )
        for row in rows:
            self._merge(into, row["email"], row["name"], row["first_seen"], row["last_seen"])

    def _add_trailers(self, conn: Connection, org_id: str, into: dict) -> None:
        placeholders = ", ".join("?" for _ in _TRAILER_KEYS)
        rows = conn.fetch_all(
            "SELECT t.trailer_value AS value, c.author_time AS t"
            " FROM git_commit_trailers t JOIN git_commits c"
            " ON c.repository_id = t.repository_id AND c.sha = t.sha"
            " JOIN repositories r ON r.id = t.repository_id"
            f" WHERE r.organization_id = ? AND t.trailer_key IN ({placeholders})",
            (org_id, *_TRAILER_KEYS),
        )
        for row in rows:
            parsed = _NAME_EMAIL.match(row["value"])
            if parsed:
                self._merge(into, parsed.group(2), parsed.group(1).strip(), row["t"], row["t"])

    @staticmethod
    def _merge(into: dict, email: str, name: str, first_seen: int, last_seen: int) -> None:
        if email in into:
            current = into[email]
            current["first_seen"] = min(current["first_seen"], first_seen)
            current["last_seen"] = max(current["last_seen"], last_seen)
        else:
            into[email] = {
                "name": name, "first_seen": first_seen,
                "last_seen": last_seen, "commit_count": 0,
            }

    def _upsert(self, conn: Connection, org_id: str, email: str, info: dict) -> None:
        existing = conn.fetch_one(
            "SELECT email FROM git_identities WHERE organization_id = ? AND email = ?",
            (org_id, email),
        )
        if existing:
            conn.execute(
                "UPDATE git_identities SET name = ?, first_seen = ?, last_seen = ?,"
                " commit_count = ? WHERE organization_id = ? AND email = ?",
                (info["name"], info["first_seen"], info["last_seen"],
                 info["commit_count"], org_id, email),
            )
        else:
            conn.execute(
                "INSERT INTO git_identities(organization_id, email, name,"
                " verified_user_id, verification_method, first_seen, last_seen,"
                " commit_count) VALUES (?, ?, ?, NULL, NULL, ?, ?, ?)",
                (org_id, email, info["name"], info["first_seen"],
                 info["last_seen"], info["commit_count"]),
            )

    def auto_map_by_email(self, conn: Connection, organization_id: str) -> int:
        """Map unclaimed identities to users whose verified email matches."""
        users = conn.fetch_all(
            "SELECT id, email FROM users WHERE organization_id = ?", (organization_id,)
        )
        mapped = 0
        for user in users:
            result = conn.fetch_all(
                "SELECT email FROM git_identities WHERE organization_id = ?"
                " AND email = ? AND verified_user_id IS NULL",
                (organization_id, user["email"]),
            )
            if result:
                self._set_mapping(conn, organization_id, user["email"], user["id"], "email")
                mapped += 1
        return mapped

    def map_identity(
        self, conn: Connection, organization_id: str, email: str, user_id: str, method: str
    ) -> GitIdentity:
        self.get(conn, organization_id, email)
        self._set_mapping(conn, organization_id, email, user_id, method)
        return self.get(conn, organization_id, email)

    def _set_mapping(
        self, conn: Connection, org_id: str, email: str, user_id: str, method: str
    ) -> None:
        conn.execute(
            "UPDATE git_identities SET verified_user_id = ?, verification_method = ?"
            " WHERE organization_id = ? AND email = ?",
            (user_id, method, org_id, email),
        )

    def get(self, conn: Connection, organization_id: str, email: str) -> GitIdentity:
        row = conn.fetch_one(
            "SELECT * FROM git_identities WHERE organization_id = ? AND email = ?",
            (organization_id, email),
        )
        if not row:
            raise NotFound(f"git identity not found: {email}")
        return GitIdentity(**row)

    def list_identities(self, conn: Connection, organization_id: str) -> list[GitIdentity]:
        rows = conn.fetch_all(
            "SELECT * FROM git_identities WHERE organization_id = ?"
            " ORDER BY commit_count DESC, email",
            (organization_id,),
        )
        return [GitIdentity(**row) for row in rows]

    def list_for_user(
        self, conn: Connection, organization_id: str, user_id: str
    ) -> list[GitIdentity]:
        rows = conn.fetch_all(
            "SELECT * FROM git_identities WHERE organization_id = ?"
            " AND verified_user_id = ? ORDER BY email",
            (organization_id, user_id),
        )
        return [GitIdentity(**row) for row in rows]
