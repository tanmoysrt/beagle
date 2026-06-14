"""Audit logging (design/15 §23).

Records who did what: synced a repository, queried source, minted or revoked a
token, opened a session. Detail is stored as redacted JSON — never raw request
parameters that may contain secrets.
"""

from __future__ import annotations

import json

from beagle.service import ids
from beagle.service.clock import now_iso
from beagle.service.db import Connection
from beagle.service.models import AuditEvent


class AuditLog:
    """Append-only record of security-relevant actions."""

    def record(
        self,
        conn: Connection,
        action: str,
        user_id: str | None = None,
        organization_id: str | None = None,
        repository_id: str | None = None,
        request_id: str | None = None,
        detail: dict | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            id=ids.audit_id(),
            timestamp=now_iso(),
            user_id=user_id,
            organization_id=organization_id,
            repository_id=repository_id,
            action=action,
            request_id=request_id,
            detail=detail or {},
        )
        conn.execute(
            "INSERT INTO audit_events(id, timestamp, user_id, organization_id,"
            " repository_id, action, request_id, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.id,
                event.timestamp,
                event.user_id,
                event.organization_id,
                event.repository_id,
                event.action,
                event.request_id,
                json.dumps(event.detail),
            ),
        )
        return event

    def list_for_user(self, conn: Connection, user_id: str, limit: int = 100) -> list[AuditEvent]:
        rows = conn.fetch_all(
            "SELECT * FROM audit_events WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit),
        )
        return [_event_from_row(row) for row in rows]


def _event_from_row(row: dict) -> AuditEvent:
    return AuditEvent(
        id=row["id"],
        timestamp=row["timestamp"],
        user_id=row["user_id"],
        organization_id=row["organization_id"],
        repository_id=row["repository_id"],
        action=row["action"],
        request_id=row["request_id"],
        detail=json.loads(row["detail"]),
    )
