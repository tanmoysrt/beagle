from __future__ import annotations

import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from beagle.bridge.client import ServiceClient
from beagle.bridge.mcp_server import build_server
from beagle.service import permissions
from beagle.service.api.app import create_app


def _make_upstream(path):
    path.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "U", "GIT_AUTHOR_EMAIL": "u@e.com",
           "GIT_COMMITTER_NAME": "U", "GIT_COMMITTER_EMAIL": "u@e.com"}
    run = lambda *a: subprocess.run(["git", *a], cwd=path, env=env, check=True, capture_output=True)
    run("init", "--quiet", "-b", "main")
    (path / "f.py").write_text("def widget():\n    return 1\n")
    run("add", "f.py")
    run("commit", "-qm", "c1")


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


def _mint(app, user_id, repos, perms):
    with app.state.container.database.connect() as conn:
        token, _ = app.state.container.jwt.mint(conn, user_id, repos, perms, 3600)
    return token


def test_admin_overview_requires_admin(client, app, user_id):
    token = _mint(app, user_id, [], [permissions.SOURCE_READ])
    assert client.get("/v1/admin/overview", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_admin_overview_counts(client, app, user_id, tmp_path):
    _make_upstream(tmp_path / "up")
    token = _mint(app, user_id, ["press"],
                  [permissions.ADMIN_IDENTITY, permissions.REPO_REGISTER, permissions.REPO_SYNC])
    repo_id = client.post("/v1/repositories",
                          json={"slug": "press", "name": "Press", "remote_url": str(tmp_path / "up")},
                          headers={"Authorization": f"Bearer {token}"}).json()["repository"]["id"]
    client.post(f"/v1/repositories/{repo_id}/sync", headers={"Authorization": f"Bearer {token}"})

    overview = client.get("/v1/admin/overview",
                          headers={"Authorization": f"Bearer {token}"}).json()["overview"]
    assert overview["counts"]["repositories"] == 1
    assert overview["counts"]["users"] == 1
    assert overview["repositories"][0]["slug"] == "press"
    assert overview["repositories"][0]["commits"] >= 1


def test_admin_page_served(client):
    page = client.get("/admin")
    assert page.status_code == 200
    assert "beagle" in page.text
    assert "/v1/admin/overview" in page.text


def test_mcp_server_exposes_read_only_tools(app, user_id):
    # The MCP server forwards to the service via a TestClient-backed ServiceClient.
    token = _mint(app, user_id, ["press"], [permissions.SOURCE_READ])
    client = TestClient(app)

    class _Forwarding(ServiceClient):
        def _request(self, method, path, body=None):
            response = client.request(
                method, path, json=body, headers={"Authorization": f"Bearer {token}"}
            )
            response.raise_for_status()
            return response.json()

    server = build_server(_Forwarding("http://test", token))
    import asyncio
    tool_names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"current_user", "commit_history", "compare_revisions",
            "revision_search", "decision_history", "dependency_resolutions"} <= tool_names
