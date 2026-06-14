"""MCP session records (design/15 §4).

Every Claude Code connection opens a session tied to the authenticated user, so
later attribution of decisions and feedback rests on the JWT subject rather than
on Git authorship.
"""

from __future__ import annotations

from beagle.service import ids
from beagle.service.clock import now_iso
from beagle.service.db import Connection
from beagle.service.errors import NotFound
from beagle.service.models import McpSession
from beagle.temporal.redact import redact


class SessionStore:
    """Opens, updates, and closes MCP sessions."""

    def open_session(
        self,
        conn: Connection,
        user_id: str,
        organization_id: str,
        repository_id: str | None,
        client_name: str = "",
        client_version: str = "",
        privacy_mode: str = "summary",
        initial_revision: str | None = None,
    ) -> McpSession:
        session = McpSession(
            id=ids.session_id(),
            user_id=user_id,
            organization_id=organization_id,
            repository_id=repository_id,
            client_name=client_name,
            client_version=client_version,
            privacy_mode=privacy_mode,
            initial_revision=initial_revision,
            current_revision=initial_revision,
            workspace_id=None,
            started_at=now_iso(),
            ended_at=None,
        )
        conn.execute(
            "INSERT INTO mcp_sessions(id, user_id, organization_id, repository_id,"
            " client_name, client_version, privacy_mode, initial_revision,"
            " current_revision, workspace_id, started_at, ended_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session.id,
                session.user_id,
                session.organization_id,
                session.repository_id,
                session.client_name,
                session.client_version,
                session.privacy_mode,
                session.initial_revision,
                session.current_revision,
                session.workspace_id,
                session.started_at,
                session.ended_at,
            ),
        )
        return session

    def get_session(self, conn: Connection, session_id: str) -> McpSession:
        row = conn.fetch_one("SELECT * FROM mcp_sessions WHERE id = ?", (session_id,))
        if not row:
            raise NotFound(f"session not found: {session_id}")
        return McpSession(**row)

    def update_revision(
        self, conn: Connection, session_id: str, current_revision: str
    ) -> None:
        self.get_session(conn, session_id)
        conn.execute(
            "UPDATE mcp_sessions SET current_revision = ? WHERE id = ?",
            (current_revision, session_id),
        )

    def close_session(self, conn: Connection, session_id: str) -> None:
        self.get_session(conn, session_id)
        conn.execute(
            "UPDATE mcp_sessions SET ended_at = ? WHERE id = ?",
            (now_iso(), session_id),
        )

    def store_summary(
        self, conn: Connection, session_id: str, summary: str,
        problem: str = "", decision: str = "",
    ) -> str:
        """Store a redacted session summary; the raw transcript stays local (§17)."""
        self.get_session(conn, session_id)
        summary_id = ids._new("sum")
        conn.execute(
            "INSERT INTO session_summaries(id, session_id, problem, decision, summary,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (summary_id, session_id, redact(problem), redact(decision),
             redact(summary), now_iso()),
        )
        return summary_id

    def get_summaries(self, conn: Connection, session_id: str) -> list[dict]:
        return conn.fetch_all(
            "SELECT * FROM session_summaries WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        )
