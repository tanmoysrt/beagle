from __future__ import annotations

from beagle.service.permissions import (
    PermissionDenied,
    require_permission,
    require_repository,
    SOURCE_READ,
    REPO_SYNC,
)

import pytest


def _org_user(db, identity):
    with db.connect() as conn:
        org = identity.create_organization(conn, "frappe", "Frappe")
        user = identity.create_user(conn, org.id, "tanmoy", "T", "t@example.com")
        return org, user


def test_session_lifecycle(db, identity, sessions):
    org, user = _org_user(db, identity)
    with db.connect() as conn:
        session = sessions.open_session(
            conn, user.id, org.id, None, client_name="claude-code", initial_revision="abc"
        )
    with db.connect() as conn:
        sessions.update_revision(conn, session.id, "def")
        sessions.close_session(conn, session.id)
        reloaded = sessions.get_session(conn, session.id)
    assert reloaded.current_revision == "def"
    assert reloaded.ended_at is not None


def test_audit_record_and_list(db, identity, audit):
    org, user = _org_user(db, identity)
    with db.connect() as conn:
        audit.record(conn, "token.mint", user_id=user.id, organization_id=org.id)
        audit.record(conn, "repo.register", user_id=user.id, organization_id=org.id)
    with db.connect() as conn:
        events = audit.list_for_user(conn, user.id)
    assert {e.action for e in events} == {"token.mint", "repo.register"}


def test_permission_checks():
    require_permission([SOURCE_READ, REPO_SYNC], SOURCE_READ)
    with pytest.raises(PermissionDenied):
        require_permission([SOURCE_READ], REPO_SYNC)
    require_repository(["press", "frappe"], "press")
    with pytest.raises(PermissionDenied):
        require_repository(["press"], "frappe")
    # The "*" wildcard authorizes any repository (full-access/local token).
    require_repository(["*"], "anything")
