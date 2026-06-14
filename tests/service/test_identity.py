from __future__ import annotations

import pytest

from beagle.service.errors import Conflict, NotFound
from beagle.service.permissions import SOURCE_READ, REPO_SYNC


def test_create_org_and_user(db, identity):
    with db.connect() as conn:
        org = identity.create_organization(conn, "frappe", "Frappe")
        user = identity.create_user(conn, org.id, "tanmoy", "Tanmoy", "t@example.com")
        assert user.organization_id == org.id
        assert identity.get_user(conn, user.id).username == "tanmoy"


def test_duplicate_org_slug_rejected(db, identity):
    with db.connect() as conn:
        identity.create_organization(conn, "frappe", "Frappe")
        with pytest.raises(Conflict):
            identity.create_organization(conn, "frappe", "Other")


def test_duplicate_username_rejected(db, identity):
    with db.connect() as conn:
        org = identity.create_organization(conn, "frappe", "Frappe")
        identity.create_user(conn, org.id, "tanmoy", "T", "t@example.com")
        with pytest.raises(Conflict):
            identity.create_user(conn, org.id, "tanmoy", "T2", "t2@example.com")


def _insert_repo(conn, org_id, repo_id="repo_1"):
    conn.execute(
        "INSERT INTO repositories(id, organization_id, slug, name, remote_url,"
        " default_branch, storage_path, ingestion_state, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (repo_id, org_id, "press", "Press", None, "main", "/tmp/x", "registered", "2026"),
    )


def test_grant_access_is_upsert(db, identity):
    with db.connect() as conn:
        org = identity.create_organization(conn, "frappe", "Frappe")
        user = identity.create_user(conn, org.id, "tanmoy", "T", "t@example.com")
        _insert_repo(conn, org.id)
        identity.grant_access(conn, user.id, "repo_1", [SOURCE_READ])
        identity.grant_access(conn, user.id, "repo_1", [SOURCE_READ, REPO_SYNC])
        access = identity.list_access(conn, user.id)
        assert len(access) == 1
        assert access[0].permissions == [SOURCE_READ, REPO_SYNC]


def test_get_unknown_user_raises(db, identity):
    with db.connect() as conn:
        with pytest.raises(NotFound):
            identity.get_user(conn, "user_missing")
