from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from beagle.service.api.app import create_app
from beagle.service import permissions


def _make_upstream(path: Path) -> None:
    path.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "U", "GIT_AUTHOR_EMAIL": "u@e.com",
           "GIT_COMMITTER_NAME": "U", "GIT_COMMITTER_EMAIL": "u@e.com"}
    run = lambda *a: subprocess.run(["git", *a], cwd=path, env=env, check=True,
                                    capture_output=True, text=True)
    run("init", "--quiet", "-b", "main")
    (path / "f.txt").write_text("x\n")
    run("add", "f.txt")
    run("commit", "--quiet", "-m", "c1")


@pytest.fixture
def app(config):
    return create_app(config)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def user_id(app):
    container = app.state.container
    with container.database.connect() as conn:
        org = container.identity.create_organization(conn, "frappe", "Frappe")
        user = container.identity.create_user(conn, org.id, "tanmoy", "T", "t@e.com")
    return user.id


def _mint(app, user_id, repos, perms, ttl=3600):
    container = app.state.container
    with container.database.connect() as conn:
        token, _ = container.jwt.mint(conn, user_id, repos, perms, ttl)
    return token


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_unauthenticated_write_rejected(client):
    response = client.post("/v1/repositories", json={"slug": "press", "name": "Press"})
    assert response.status_code == 401


def test_me_returns_identity(client, app, user_id):
    token = _mint(app, user_id, ["press"], [permissions.SOURCE_READ])
    response = client.get("/v1/me", headers=_auth(token))
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == "tanmoy"
    assert body["repositories"] == ["press"]


def test_register_requires_permission(client, app, user_id):
    token = _mint(app, user_id, [], [permissions.SOURCE_READ])
    response = client.post(
        "/v1/repositories", json={"slug": "press", "name": "Press"}, headers=_auth(token)
    )
    assert response.status_code == 403


def test_register_and_sync(client, app, user_id, tmp_path):
    _make_upstream(tmp_path / "upstream")
    token = _mint(
        app, user_id, ["press"],
        [permissions.REPO_REGISTER, permissions.REPO_SYNC],
    )
    registered = client.post(
        "/v1/repositories",
        json={"slug": "press", "name": "Press", "remote_url": str(tmp_path / "upstream")},
        headers=_auth(token),
    )
    assert registered.status_code == 200
    repo_id = registered.json()["repository"]["id"]

    synced = client.post(f"/v1/repositories/{repo_id}/sync", headers=_auth(token))
    assert synced.status_code == 200
    assert synced.json()["index_status"]["ref_count"] >= 1

    # Audit trail recorded both actions.
    with app.state.container.database.connect() as conn:
        events = app.state.container.audit.list_for_user(conn, user_id)
    assert {"repo.register", "repo.sync"} <= {e.action for e in events}


def test_session_open_and_end(client, app, user_id):
    token = _mint(app, user_id, ["press"], [permissions.SOURCE_READ])
    opened = client.post("/v1/sessions", json={"client_name": "claude-code"}, headers=_auth(token))
    assert opened.status_code == 200
    session_id = opened.json()["session"]["id"]
    ended = client.post(f"/v1/sessions/{session_id}/end", headers=_auth(token))
    assert ended.json()["ended"] is True


def test_git_info_refs_through_handler(client, app, user_id, tmp_path):
    """The Smart-HTTP handler proxies a real git-upload-pack advertisement."""
    _make_upstream(tmp_path / "upstream")
    token = _mint(
        app, user_id, ["press"],
        [permissions.REPO_REGISTER, permissions.REPO_SYNC, permissions.SOURCE_READ],
    )
    repo_id = client.post(
        "/v1/repositories",
        json={"slug": "press", "name": "Press", "remote_url": str(tmp_path / "upstream")},
        headers=_auth(token),
    ).json()["repository"]["id"]
    client.post(f"/v1/repositories/{repo_id}/sync", headers=_auth(token))

    handler = app.state.container.smart_http
    response = handler.handle(
        "GET", repo_id, "info/refs", "service=git-upload-pack",
        {"authorization": f"Bearer {token}"}, b"",
    )
    assert response.status_code == 200
    assert b"git-upload-pack" in response.body

    denied = handler.handle(
        "GET", repo_id, "info/refs", "service=git-upload-pack", {}, b""
    )
    assert denied.status_code == 401
