"""Persistence for temporal memory (design/13 Phase B/G).

Owns every read and write of the ``temporal_*`` tables and nothing else. It
serializes the records in :mod:`beagle.temporal.models` to rows and back. No
git access, no diff parsing, no ranking — the service layer composes those.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

from beagle.database.connection import Database
from beagle.temporal.models import (
    Alternative, ChangeEpisode, ChangeSet, CommitRecord, Decision,
    EntityChange, FollowUp, Session,
)


def _loads(value: Optional[str]) -> dict:
    return json.loads(value) if value else {}


class TemporalRepository:
    def __init__(self, db: Database):
        self.db = db
        self.conn = db.conn

    # --- episodes ----------------------------------------------------------

    def save_episode(self, ep: ChangeEpisode) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO temporal_episodes(id, title, status, "
                "created_at, updated_at, base_commit, head_commit, branch, summary, "
                "problem, goal, outcome, confidence, confirmation, provenance_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ep.id, ep.title, ep.status, ep.created_at, ep.updated_at,
                 ep.base_commit, ep.head_commit, ep.branch, ep.summary, ep.problem,
                 ep.goal, ep.outcome, ep.confidence, ep.confirmation,
                 json.dumps(ep.provenance) if ep.provenance else None),
            )

    def get_episode(self, episode_id: str) -> Optional[ChangeEpisode]:
        row = self.conn.execute(
            "SELECT * FROM temporal_episodes WHERE id = ?", (episode_id,)
        ).fetchone()
        return _episode(row) if row else None

    def list_episodes(self, status: Optional[str] = None) -> list[ChangeEpisode]:
        sql, params = "SELECT * FROM temporal_episodes", []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY updated_at DESC"
        return [_episode(r) for r in self.conn.execute(sql, params).fetchall()]

    # --- decisions / alternatives / follow-ups -----------------------------

    def save_decision(self, d: Decision) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO temporal_decisions(id, episode_id, statement, "
                "rationale, status, confidence, created_at, superseded_by, confirmation, "
                "provenance_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (d.id, d.episode_id, d.statement, d.rationale, d.status, d.confidence,
                 d.created_at, d.superseded_by, d.confirmation,
                 json.dumps(d.provenance) if d.provenance else None),
            )

    def decisions_for(self, episode_id: str) -> list[Decision]:
        rows = self.conn.execute(
            "SELECT * FROM temporal_decisions WHERE episode_id = ? ORDER BY created_at",
            (episode_id,),
        ).fetchall()
        return [_decision(r) for r in rows]

    def save_alternative(self, a: Alternative) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO temporal_alternatives(id, episode_id, "
                "description, status, rejection_reason, provenance_json) "
                "VALUES (?,?,?,?,?,?)",
                (a.id, a.episode_id, a.description, a.status, a.rejection_reason,
                 json.dumps(a.provenance) if a.provenance else None),
            )

    def alternatives_for(self, episode_id: str) -> list[Alternative]:
        rows = self.conn.execute(
            "SELECT * FROM temporal_alternatives WHERE episode_id = ?", (episode_id,)
        ).fetchall()
        return [_alternative(r) for r in rows]

    def save_followup(self, f: FollowUp) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO temporal_followups(id, episode_id, description, "
                "status, priority, related_entities) VALUES (?,?,?,?,?,?)",
                (f.id, f.episode_id, f.description, f.status, f.priority,
                 json.dumps(f.related_entities)),
            )

    def followups_for(self, episode_id: str) -> list[FollowUp]:
        rows = self.conn.execute(
            "SELECT * FROM temporal_followups WHERE episode_id = ?", (episode_id,)
        ).fetchall()
        return [_followup(r) for r in rows]

    # --- commits / entity changes / changesets -----------------------------

    def save_commit(self, c: CommitRecord) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO temporal_commits(commit_sha, episode_id, "
                "parent_shas, message, author, timestamp, patch_id, match_confidence) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (c.commit_sha, c.episode_id, json.dumps(c.parent_shas), c.message,
                 c.author, c.timestamp, c.patch_id, c.match_confidence),
            )

    def commits_for(self, episode_id: str) -> list[CommitRecord]:
        rows = self.conn.execute(
            "SELECT * FROM temporal_commits WHERE episode_id = ? ORDER BY timestamp",
            (episode_id,),
        ).fetchall()
        return [_commit(r) for r in rows]

    def save_entity_change(self, c: EntityChange) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO temporal_entity_changes(episode_id, commit_sha, "
                "entity_before, entity_after, change_type, path_before, path_after, "
                "diff_ranges_json, confidence) VALUES (?,?,?,?,?,?,?,?,?)",
                (c.episode_id, c.commit_sha, c.entity_before, c.entity_after,
                 c.change_type, c.path_before, c.path_after,
                 json.dumps(c.diff_ranges), c.confidence),
            )

    def changes_for_entity(self, entity_id: str) -> list[EntityChange]:
        rows = self.conn.execute(
            "SELECT * FROM temporal_entity_changes WHERE entity_after = ? "
            "OR entity_before = ? ORDER BY id",
            (entity_id, entity_id),
        ).fetchall()
        return [_entity_change(r) for r in rows]

    def changes_for_episode(self, episode_id: str) -> list[EntityChange]:
        rows = self.conn.execute(
            "SELECT * FROM temporal_entity_changes WHERE episode_id = ? ORDER BY id",
            (episode_id,),
        ).fetchall()
        return [_entity_change(r) for r in rows]

    def episodes_for_entity(self, entity_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT episode_id FROM temporal_entity_changes "
            "WHERE (entity_after = ? OR entity_before = ?) AND episode_id IS NOT NULL",
            (entity_id, entity_id),
        ).fetchall()
        return [r["episode_id"] for r in rows]

    def save_changeset(self, c: ChangeSet) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO temporal_changesets(id, episode_id, base_commit, "
                "head_commit, patch_id, entity_fingerprint, summary) VALUES (?,?,?,?,?,?,?)",
                (c.id, c.episode_id, c.base_commit, c.head_commit, c.patch_id,
                 c.entity_fingerprint, c.summary),
            )

    def find_changeset_by_patch(self, patch_id: str) -> Optional[ChangeSet]:
        row = self.conn.execute(
            "SELECT * FROM temporal_changesets WHERE patch_id = ?", (patch_id,)
        ).fetchone()
        return _changeset(row) if row else None

    def find_changeset_by_fingerprint(self, fingerprint: str) -> Optional[ChangeSet]:
        row = self.conn.execute(
            "SELECT * FROM temporal_changesets WHERE entity_fingerprint = ?", (fingerprint,)
        ).fetchone()
        return _changeset(row) if row else None

    # --- sessions ----------------------------------------------------------

    def save_session(self, s: Session) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO temporal_sessions(id, episode_id, tool, "
                "started_at, ended_at, working_directory, start_commit, end_commit, "
                "transcript_path, transcript_hash, summary, redaction_status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (s.id, s.episode_id, s.tool, s.started_at, s.ended_at,
                 s.working_directory, s.start_commit, s.end_commit, s.transcript_path,
                 s.transcript_hash, s.summary, s.redaction_status),
            )


# --- row mappers -------------------------------------------------------------

def _episode(row: sqlite3.Row) -> ChangeEpisode:
    return ChangeEpisode(
        id=row["id"], title=row["title"], status=row["status"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        base_commit=row["base_commit"], head_commit=row["head_commit"],
        branch=row["branch"], summary=row["summary"], problem=row["problem"],
        goal=row["goal"], outcome=row["outcome"], confidence=row["confidence"],
        confirmation=row["confirmation"], provenance=_loads(row["provenance_json"]),
    )


def _decision(row: sqlite3.Row) -> Decision:
    return Decision(
        id=row["id"], episode_id=row["episode_id"], statement=row["statement"],
        rationale=row["rationale"], status=row["status"], confidence=row["confidence"],
        created_at=row["created_at"], superseded_by=row["superseded_by"],
        confirmation=row["confirmation"], provenance=_loads(row["provenance_json"]),
    )


def _alternative(row: sqlite3.Row) -> Alternative:
    return Alternative(
        id=row["id"], episode_id=row["episode_id"], description=row["description"],
        status=row["status"], rejection_reason=row["rejection_reason"],
        provenance=_loads(row["provenance_json"]),
    )


def _followup(row: sqlite3.Row) -> FollowUp:
    return FollowUp(
        id=row["id"], episode_id=row["episode_id"], description=row["description"],
        status=row["status"], priority=row["priority"],
        related_entities=json.loads(row["related_entities"]) if row["related_entities"] else [],
    )


def _commit(row: sqlite3.Row) -> CommitRecord:
    return CommitRecord(
        commit_sha=row["commit_sha"], episode_id=row["episode_id"],
        parent_shas=json.loads(row["parent_shas"]) if row["parent_shas"] else [],
        message=row["message"], author=row["author"], timestamp=row["timestamp"],
        patch_id=row["patch_id"], match_confidence=row["match_confidence"],
    )


def _entity_change(row: sqlite3.Row) -> EntityChange:
    return EntityChange(
        change_type=row["change_type"], entity_before=row["entity_before"],
        entity_after=row["entity_after"], path_before=row["path_before"],
        path_after=row["path_after"],
        diff_ranges=[tuple(r) for r in (json.loads(row["diff_ranges_json"]) or [])],
        confidence=row["confidence"], episode_id=row["episode_id"],
        commit_sha=row["commit_sha"], id=row["id"],
    )


def _changeset(row: sqlite3.Row) -> ChangeSet:
    return ChangeSet(
        id=row["id"], base_commit=row["base_commit"], head_commit=row["head_commit"],
        patch_id=row["patch_id"], entity_fingerprint=row["entity_fingerprint"],
        summary=row["summary"], episode_id=row["episode_id"],
    )
