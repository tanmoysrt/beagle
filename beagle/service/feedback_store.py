"""Feedback memory (design/15 §18).

Records review feedback and tracks its lifecycle. Feedback is not promoted into
a permanent rule automatically — that requires explicit confirmation, repetition,
or encoding in tests. This store only preserves the comment, its target, and its
status transitions.
"""

from __future__ import annotations

from beagle.service import decision_roles, ids
from beagle.service.clock import now_iso
from beagle.service.db import Connection
from beagle.service.errors import NotFound
from beagle.service.models import Feedback


class FeedbackStore:
    """Persists feedback items and their state transitions."""

    def record(
        self, conn: Connection, repository_id: str, comment: str, author_user_id: str,
        episode_id: str | None = None, revision: str | None = None,
        entity_id: str | None = None, rationale: str = "",
    ) -> Feedback:
        item = Feedback(
            ids._new("fb"), repository_id, episode_id, comment, author_user_id,
            revision, entity_id, "received", rationale, now_iso(),
        )
        conn.execute(
            "INSERT INTO feedback(id, repository_id, episode_id, comment, author_user_id,"
            " revision, entity_id, status, rationale, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item.id, repository_id, episode_id, comment, author_user_id, revision,
             entity_id, "received", rationale, item.created_at),
        )
        return item

    def set_status(self, conn: Connection, feedback_id: str, status: str) -> None:
        decision_roles.validate_feedback_state(status)
        if not conn.fetch_one("SELECT id FROM feedback WHERE id = ?", (feedback_id,)):
            raise NotFound(f"feedback not found: {feedback_id}")
        conn.execute("UPDATE feedback SET status = ? WHERE id = ?", (status, feedback_id))

    def get(self, conn: Connection, feedback_id: str) -> Feedback:
        row = conn.fetch_one("SELECT * FROM feedback WHERE id = ?", (feedback_id,))
        if not row:
            raise NotFound(f"feedback not found: {feedback_id}")
        return Feedback(**row)

    def history(
        self, conn: Connection, repository_id: str, entity_id: str | None = None,
        limit: int = 50,
    ) -> list[Feedback]:
        if entity_id:
            rows = conn.fetch_all(
                "SELECT * FROM feedback WHERE repository_id = ? AND entity_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (repository_id, entity_id, limit),
            )
        else:
            rows = conn.fetch_all(
                "SELECT * FROM feedback WHERE repository_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (repository_id, limit),
            )
        return [Feedback(**row) for row in rows]
