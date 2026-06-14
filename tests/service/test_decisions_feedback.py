from __future__ import annotations

import pytest

from beagle.service import decision_roles
from beagle.service.decisions import DecisionStore
from beagle.service.errors import ValidationError
from beagle.service.feedback_store import FeedbackStore


@pytest.fixture
def decisions():
    return DecisionStore()


@pytest.fixture
def feedback():
    return FeedbackStore()


@pytest.fixture
def repo_and_user(db, identity):
    with db.connect() as conn:
        org = identity.create_organization(conn, "frappe", "Frappe")
        user = identity.create_user(conn, org.id, "tanmoy", "T", "t@e.com")
        conn.execute(
            "INSERT INTO repositories(id, organization_id, slug, name, remote_url,"
            " default_branch, storage_path, ingestion_state, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("repo_1", org.id, "press", "Press", None, "main", "/x", "registered", "2026"),
        )
    return "repo_1", user.id


def test_decision_records_author_as_confirmed_proposer(db, decisions, repo_and_user):
    repo_id, user_id = repo_and_user
    with db.connect() as conn:
        episode = decisions.create_episode(conn, repo_id, "Auth rework", "", user_id)
        decision = decisions.record_decision(
            conn, episode.id, repo_id, "Use JWT", user_id, rationale="simple"
        )
        detail = decisions.get_decision(conn, decision.id)
    actors = detail["actors"]
    assert len(actors) == 1
    assert actors[0]["role"] == decision_roles.PROPOSER
    assert actors[0]["user_id"] == user_id
    assert actors[0]["confirmation_state"] == decision_roles.CONFIRMED


def test_mentioned_actor_is_inferred_until_confirmed(db, decisions, repo_and_user):
    repo_id, user_id = repo_and_user
    with db.connect() as conn:
        episode = decisions.create_episode(conn, repo_id, "E", "", user_id)
        decision = decisions.record_decision(conn, episode.id, repo_id, "Do X", user_id)
        actor = decisions.add_actor(
            conn, decision.id, decision_roles.APPROVER, external_name="Alice"
        )
        assert actor.confirmation_state == decision_roles.INFERRED
        decisions.confirm_actor(conn, actor.id)
        detail = decisions.get_decision(conn, decision.id)
    approver = [a for a in detail["actors"] if a["role"] == decision_roles.APPROVER][0]
    assert approver["external_name"] == "Alice"
    assert approver["confirmation_state"] == decision_roles.CONFIRMED


def test_unknown_role_rejected(db, decisions, repo_and_user):
    repo_id, user_id = repo_and_user
    with db.connect() as conn:
        episode = decisions.create_episode(conn, repo_id, "E", "", user_id)
        decision = decisions.record_decision(conn, episode.id, repo_id, "X", user_id)
        with pytest.raises(ValidationError):
            decisions.add_actor(conn, decision.id, "boss", user_id=user_id)
        with pytest.raises(ValidationError):
            decisions.add_actor(conn, decision.id, decision_roles.REVIEWER)  # no identity


def test_decision_history_by_entity(db, decisions, repo_and_user):
    repo_id, user_id = repo_and_user
    with db.connect() as conn:
        episode = decisions.create_episode(conn, repo_id, "E", "", user_id)
        d1 = decisions.record_decision(conn, episode.id, repo_id, "touches Site", user_id)
        decisions.record_decision(conn, episode.id, repo_id, "unrelated", user_id)
        decisions.link_entity(conn, d1.id, repo_id, "python://press/site.py#Site")
        by_entity = decisions.list_decisions(conn, repo_id, "python://press/site.py#Site")
        all_decisions = decisions.list_decisions(conn, repo_id)
    assert len(all_decisions) == 2
    assert len(by_entity) == 1
    assert by_entity[0]["id"] == d1.id


def test_feedback_lifecycle(db, feedback, repo_and_user):
    repo_id, user_id = repo_and_user
    with db.connect() as conn:
        item = feedback.record(conn, repo_id, "rename this", user_id, entity_id="e1")
        assert item.status == "received"
        feedback.set_status(conn, item.id, "accepted")
        feedback.set_status(conn, item.id, "implemented")
        with pytest.raises(ValidationError):
            feedback.set_status(conn, item.id, "bogus")
        history = feedback.history(conn, repo_id, entity_id="e1")
    assert history[0].status == "implemented"


def test_session_summary_is_redacted(db, identity, sessions, repo_and_user):
    repo_id, user_id = repo_and_user
    with db.connect() as conn:
        org_id = identity.get_user(conn, user_id).organization_id
        session = sessions.open_session(conn, user_id, org_id, repo_id)
        sessions.store_summary(
            conn, session.id, "token is ghp_0123456789012345678901234567890123 secret"
        )
        summaries = sessions.get_summaries(conn, session.id)
    assert "ghp_0123456789" not in summaries[0]["summary"]
    assert "[REDACTED]" in summaries[0]["summary"]
