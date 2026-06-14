"""Read-only administration overview (design/15 §21 — lightweight admin UI).

Aggregates counts and recent activity for an organization so the admin UI and
the admin JSON endpoint share one query path. Read-only: it never mutates state.
"""

from __future__ import annotations

from beagle.service.db import Connection


class AdminService:
    """Builds a read-only overview for one organization."""

    def overview(self, conn: Connection, organization_id: str) -> dict:
        return {
            "organization_id": organization_id,
            "counts": self._counts(conn, organization_id),
            "repositories": self._repositories(conn, organization_id),
            "recent_audit": self._recent_audit(conn, organization_id),
        }

    def _counts(self, conn: Connection, org: str) -> dict:
        return {
            "users": self._count(conn, "users", org),
            "repositories": self._count(conn, "repositories", org),
            "active_tokens": self._scalar(
                conn,
                "SELECT COUNT(*) AS n FROM jwt_tokens WHERE organization_id = ? AND revoked = 0",
                org,
            ),
            "sessions": self._count(conn, "mcp_sessions", org),
        }

    def _repositories(self, conn: Connection, org: str) -> list[dict]:
        rows = conn.fetch_all(
            "SELECT id, slug, name, ingestion_state FROM repositories"
            " WHERE organization_id = ? ORDER BY slug",
            (org,),
        )
        for row in rows:
            row["snapshots"] = self._scalar(
                conn,
                "SELECT COUNT(*) AS n FROM index_snapshots WHERE repository_id = ?",
                row["id"],
            )
            row["commits"] = self._scalar(
                conn,
                "SELECT COUNT(*) AS n FROM git_commits WHERE repository_id = ?",
                row["id"],
            )
        return rows

    def _recent_audit(self, conn: Connection, org: str) -> list[dict]:
        return conn.fetch_all(
            "SELECT timestamp, action, user_id, repository_id FROM audit_events"
            " WHERE organization_id = ? ORDER BY timestamp DESC LIMIT 20",
            (org,),
        )

    def _count(self, conn: Connection, table: str, org: str) -> int:
        return self._scalar(
            conn, f"SELECT COUNT(*) AS n FROM {table} WHERE organization_id = ?", org
        )

    @staticmethod
    def _scalar(conn: Connection, sql: str, param: str) -> int:
        row = conn.fetch_one(sql, (param,))
        return int(row["n"]) if row else 0
