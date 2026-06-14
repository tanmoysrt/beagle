"""End-to-end: a real ``git clone`` over the authenticated Smart-HTTP server.

Proves the full transport path — live ASGI server, JWT auth, authorization, and
``git http-backend`` — fetches objects without re-uploading source.
"""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from beagle.service.api.app import create_app
from beagle.service import permissions

# Never let git open an interactive or GUI credential prompt during tests: a 401
# would otherwise hang the suite waiting on an askpass dialog.
_NOPROMPT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "true",
    "SSH_ASKPASS": "true",
    "GCM_INTERACTIVE": "never",
}
_NOPROMPT_FLAGS = ["-c", "credential.helper=", "-c", "credential.interactive=false"]


def _git_net(args, **kwargs):
    """Run a git command that may hit the network, with prompting disabled."""
    return subprocess.run(
        ["git", *_NOPROMPT_FLAGS, *args],
        env=_NOPROMPT_ENV, capture_output=True, text=True, **kwargs
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _make_upstream(path: Path) -> None:
    path.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "U", "GIT_AUTHOR_EMAIL": "u@e.com",
           "GIT_COMMITTER_NAME": "U", "GIT_COMMITTER_EMAIL": "u@e.com"}
    run = lambda *a: subprocess.run(["git", *a], cwd=path, env=env, check=True,
                                    capture_output=True, text=True)
    run("init", "--quiet", "-b", "main")
    (path / "README.md").write_text("hello beagle\n")
    run("add", "README.md")
    run("commit", "--quiet", "-m", "c1")


@pytest.fixture
def live_server(config, tmp_path):
    _make_upstream(tmp_path / "upstream")
    app = create_app(config)
    container = app.state.container
    with container.database.connect() as conn:
        org = container.identity.create_organization(conn, "frappe", "Frappe")
        user = container.identity.create_user(conn, org.id, "tanmoy", "T", "t@e.com")
        repo = container.repository_service.register(
            conn, org.id, "press", "Press", str(tmp_path / "upstream")
        )
        container.repository_service.sync(conn, repo.id)
        token, _ = container.jwt.mint(
            conn, user.id, ["press"], [permissions.SOURCE_READ], 3600
        )
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "server failed to start"
    try:
        yield port, repo.id, token
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_git_fetch_over_http(live_server, tmp_path):
    # The bridge fetches the canonical Beagle ref explicitly (it lives under
    # refs/beagle/upstream/*, not refs/heads/*), then reads the object content.
    port, repo_id, token = live_server
    url = f"http://127.0.0.1:{port}/git/{repo_id}.git"
    local = tmp_path / "local"
    local.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=local, check=True)
    fetched = _git_net(
        ["-c", f"http.extraHeader=Authorization: Bearer {token}",
         "fetch", "--quiet", url, "refs/beagle/upstream/heads/main"],
        cwd=local,
    )
    assert fetched.returncode == 0, fetched.stderr
    shown = subprocess.run(
        ["git", "show", "FETCH_HEAD:README.md"],
        cwd=local, capture_output=True, text=True,
    )
    assert shown.stdout == "hello beagle\n"


def test_git_clone_without_token_fails(live_server, tmp_path):
    port, repo_id, _ = live_server
    url = f"http://127.0.0.1:{port}/git/{repo_id}.git"
    result = _git_net(["clone", "--quiet", url, str(tmp_path / "clone2")])
    assert result.returncode != 0
    assert "clone2" not in os.listdir(tmp_path) or not (tmp_path / "clone2" / ".git").exists()
