from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from beagle.bridge.client import ServiceClient
from beagle.bridge.local_repo import LocalRepository
from beagle.bridge.session import BridgeSession
from beagle.bridge.token_store import TokenStore
from beagle.service import permissions
from beagle.service.api.app import create_app


def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "dev@e.com",
           "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "dev@e.com",
           "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True)


# --- token store ----------------------------------------------------------

def test_token_store_file(tmp_path, monkeypatch):
    monkeypatch.delenv("BEAGLE_TOKEN", raising=False)
    store = TokenStore(path=tmp_path / "token")
    assert store.get() is None
    store.set("abc.def.ghi")
    assert store.get() == "abc.def.ghi"
    assert (tmp_path / "token").stat().st_mode & 0o777 == 0o600


def test_token_store_env_takes_precedence(tmp_path, monkeypatch):
    store = TokenStore(path=tmp_path / "token")
    store.set("file-token")
    monkeypatch.setenv("BEAGLE_TOKEN", "env-token")
    assert store.get() == "env-token"


# --- local repo -----------------------------------------------------------

@pytest.fixture
def working_repo(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    _git(root, "init", "--quiet", "-b", "main")
    (root / "a.py").write_text("x = 1\n")
    _git(root, "add", "a.py")
    _git(root, "commit", "--quiet", "-m", "c1")
    return root


def test_local_repo_state(working_repo):
    local = LocalRepository(working_repo)
    assert len(local.head_sha()) == 40
    assert local.branch() == "main"
    assert not local.is_dirty()
    (working_repo / "a.py").write_text("x = 2\n")
    assert local.is_dirty()
    assert "x = 2" in local.dirty_patch()
    assert len(local.dirty_fingerprint()) == 64


# --- end-to-end sync over a live server -----------------------------------

def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live(config, working_repo):
    app = create_app(config)
    container = app.state.container
    with container.database.connect() as conn:
        org = container.identity.create_organization(conn, "frappe", "Frappe")
        user = container.identity.create_user(conn, org.id, "dev", "Dev", "dev@e.com")
        repo = container.repository_service.register(conn, org.id, "app", "App", None)
        token, _ = container.jwt.mint(
            conn, user.id, ["app"],
            [permissions.SOURCE_READ, permissions.REPO_SYNC], 3600,
        )
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}", token, repo.id, container
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_bridge_pushes_missing_commit_then_indexes(live, working_repo):
    url, token, repo_id, container = live
    session = BridgeSession(ServiceClient(url, token), LocalRepository(working_repo))

    assert session.connect()["user"]["username"] == "dev"

    first = session.ensure_head_synced("app")
    assert first.pushed is True   # commit was missing, so it was pushed
    assert first.indexed is True  # and indexed
    assert container.mirror.has_commit(repo_id, first.head)

    # Second sync uploads nothing — the commit and snapshot already exist.
    second = session.ensure_head_synced("app")
    assert second.pushed is False
    assert second.indexed is False


def test_bridge_local_only_uploads_nothing(live, working_repo):
    url, token, repo_id, container = live
    session = BridgeSession(ServiceClient(url, token), LocalRepository(working_repo))
    outcome = session.ensure_head_synced("app", local_only=True)
    assert outcome.local_only is True
    assert outcome.pushed is False and outcome.indexed is False
    assert not container.mirror.has_commit(repo_id, outcome.head)


def test_bridge_uploads_dirty_overlay(live, working_repo):
    url, token, repo_id, container = live
    # WORKSPACE_CREATE is needed to create an overlay; re-mint with the scope.
    with container.database.connect() as conn:
        user_id = conn.fetch_one("SELECT id FROM users WHERE username='dev'")["id"]
        token2, _ = container.jwt.mint(
            conn, user_id, ["app"],
            [permissions.SOURCE_READ, permissions.REPO_SYNC, permissions.WORKSPACE_CREATE],
            3600,
        )
    # Make the tree dirty.
    (working_repo / "a.py").write_text("x = 99\n")
    session = BridgeSession(ServiceClient(url, token2), LocalRepository(working_repo))
    outcome = session.ensure_head_synced("app", upload_dirty=True)
    assert outcome.dirty is True
    assert outcome.workspace_id is not None
    with container.database.connect() as conn:
        overlay = container.workspaces.get(conn, outcome.workspace_id)
    assert overlay.snapshot_id is not None
