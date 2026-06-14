"""Decision and change-episode memory (design/15 §16).

Records decisions made through authenticated sessions and the roles people
played. The authenticated user who records a decision is attached as a confirmed
proposer; any other named participant is stored as inferred attribution until
explicitly confirmed. Affected entities are linked so history can be retrieved
per entity. Commit authorship is never treated as decision ownership.
"""

from __future__ import annotations

from beagle.service import decision_roles, ids
from beagle.service.clock import now_iso
from beagle.service.db import Connection
from beagle.service.errors import NotFound, ValidationError
from beagle.service.models import ChangeEpisode, Decision, DecisionActor


class DecisionStore:
    """Persists change episodes, decisions, actors, and affected entities."""

    def create_episode(
        self, conn: Connection, repository_id: str, title: str, summary: str, created_by: str
    ) -> ChangeEpisode:
        episode = ChangeEpisode(
            ids._new("epi"), repository_id, title, summary, "open", created_by, now_iso()
        )
        conn.execute(
            "INSERT INTO change_episodes(id, repository_id, title, summary, status,"
            " created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (episode.id, repository_id, title, summary, "open", created_by, episode.created_at),
        )
        return episode

    def get_episode(self, conn: Connection, episode_id: str) -> ChangeEpisode:
        row = conn.fetch_one("SELECT * FROM change_episodes WHERE id = ?", (episode_id,))
        if not row:
            raise NotFound(f"episode not found: {episode_id}")
        return ChangeEpisode(**row)

    def record_decision(
        self, conn: Connection, episode_id: str, repository_id: str, decision: str,
        created_by: str, problem: str = "", goal: str = "", rationale: str = "",
    ) -> Decision:
        self.get_episode(conn, episode_id)
        record = Decision(
            ids._new("dec"), episode_id, repository_id, problem, goal, decision,
            rationale, "open", created_by, now_iso(),
        )
        conn.execute(
            "INSERT INTO decisions(id, episode_id, repository_id, problem, goal,"
            " decision, rationale, status, created_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record.id, episode_id, repository_id, problem, goal, decision, rationale,
             "open", created_by, record.created_at),
        )
        # The authenticated author is a confirmed proposer (design §16, §17).
        self.add_actor(
            conn, record.id, decision_roles.PROPOSER, user_id=created_by,
            evidence="authenticated session", confirmation_state=decision_roles.CONFIRMED,
        )
        return record

    def add_actor(
        self, conn: Connection, decision_id: str, role: str, user_id: str | None = None,
        external_name: str | None = None, confidence: float = 1.0, evidence: str = "",
        confirmation_state: str = decision_roles.INFERRED,
    ) -> DecisionActor:
        decision_roles.validate_role(role)
        decision_roles.validate_confirmation(confirmation_state)
        if not user_id and not external_name:
            raise ValidationError("actor needs a user_id or an external_name")
        actor = DecisionActor(
            ids._new("act"), decision_id, user_id, external_name, role,
            confidence, evidence, confirmation_state,
        )
        conn.execute(
            "INSERT INTO decision_actors(id, decision_id, user_id, external_name, role,"
            " confidence, evidence, confirmation_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (actor.id, decision_id, user_id, external_name, role, confidence,
             evidence, confirmation_state),
        )
        return actor

    def confirm_actor(
        self, conn: Connection, actor_id: str, state: str = decision_roles.CONFIRMED
    ) -> None:
        decision_roles.validate_confirmation(state)
        if not conn.fetch_one("SELECT id FROM decision_actors WHERE id = ?", (actor_id,)):
            raise NotFound(f"actor not found: {actor_id}")
        conn.execute(
            "UPDATE decision_actors SET confirmation_state = ? WHERE id = ?",
            (state, actor_id),
        )

    def link_entity(
        self, conn: Connection, decision_id: str, repository_id: str, entity_id: str
    ) -> None:
        if conn.fetch_one(
            "SELECT decision_id FROM decision_entities WHERE decision_id = ? AND entity_id = ?",
            (decision_id, entity_id),
        ):
            return
        conn.execute(
            "INSERT INTO decision_entities(decision_id, repository_id, entity_id)"
            " VALUES (?, ?, ?)",
            (decision_id, repository_id, entity_id),
        )

    def set_status(self, conn: Connection, decision_id: str, status: str) -> None:
        if status not in decision_roles.DECISION_STATUSES:
            raise ValidationError(f"unknown decision status: {status}")
        if not conn.fetch_one("SELECT id FROM decisions WHERE id = ?", (decision_id,)):
            raise NotFound(f"decision not found: {decision_id}")
        conn.execute("UPDATE decisions SET status = ? WHERE id = ?", (status, decision_id))

    def get_decision(self, conn: Connection, decision_id: str) -> dict:
        row = conn.fetch_one("SELECT * FROM decisions WHERE id = ?", (decision_id,))
        if not row:
            raise NotFound(f"decision not found: {decision_id}")
        row["actors"] = conn.fetch_all(
            "SELECT * FROM decision_actors WHERE decision_id = ?", (decision_id,)
        )
        row["entities"] = [
            r["entity_id"]
            for r in conn.fetch_all(
                "SELECT entity_id FROM decision_entities WHERE decision_id = ?", (decision_id,)
            )
        ]
        return row

    def list_decisions(
        self, conn: Connection, repository_id: str, entity_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        if entity_id:
            rows = conn.fetch_all(
                "SELECT d.* FROM decisions d JOIN decision_entities e"
                " ON e.decision_id = d.id WHERE d.repository_id = ? AND e.entity_id = ?"
                " ORDER BY d.created_at DESC LIMIT ?",
                (repository_id, entity_id, limit),
            )
        else:
            rows = conn.fetch_all(
                "SELECT * FROM decisions WHERE repository_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (repository_id, limit),
            )
        for row in rows:
            row["actors"] = conn.fetch_all(
                "SELECT role, user_id, external_name, confirmation_state FROM decision_actors"
                " WHERE decision_id = ?", (row["id"],)
            )
        return rows
